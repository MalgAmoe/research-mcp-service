"""Credential-free, Unix-socket-only supervisor for disposable fetch jobs."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import signal
import socket
import sys
import tempfile

from fastapi import FastAPI, HTTPException, Request
import uvicorn

from .egress_bridge import Bridge
from .browser_process import BrowserProcess, ACTIONS


async def run_job(job):
    with tempfile.TemporaryDirectory(prefix='research-job-') as directory:
        output = Path(directory) / 'result.json'
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-m', 'research_mcp_service.worker_job', str(output),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True, cwd=directory)
        try:
            await process.communicate(json.dumps(job).encode())
            if process.returncode != 0 or not output.exists() or output.is_symlink():
                raise RuntimeError('Worker job failed')
            if output.stat().st_size > 32 * 1024 * 1024:
                raise RuntimeError('Worker result exceeded limit')
            return json.loads(output.read_text())
        finally:
            # Terminate the entire owned group, including any leftover browsers.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


async def disconnected(request):
    # The body has already been consumed. Wait directly for the disconnect event;
    # polling is_disconnected() uses a cancellation scope that can swallow cancel().
    while True:
        message = await request.receive()
        if message['type'] == 'http.disconnect':
            return


async def read_payload(request):
    body = bytearray()
    async for part in request.stream():
        if len(body) + len(part) > 65536:
            raise HTTPException(413, 'Worker request too large')
        body.extend(part)
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(400, 'Invalid worker request') from None


async def complete(request, operation, timeout):
    task = asyncio.create_task(operation)
    watch = asyncio.create_task(disconnected(request))
    try:
        async with asyncio.timeout(timeout):
            done, _ = await asyncio.wait([task, watch], return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                return task.result()
            raise HTTPException(499, 'Caller disconnected')
    except TimeoutError:
        raise HTTPException(504, 'Worker job timed out') from None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, 'Worker job failed') from None
    finally:
        task.cancel(); watch.cancel()
        await asyncio.gather(task, watch, return_exceptions=True)


def create_worker_app(executor=run_job, timeout=75):
    slots = asyncio.Semaphore(2)
    browser = BrowserProcess()

    @asynccontextmanager
    async def lifespan(app):
        bridge = await asyncio.start_server(Bridge().handle, '127.0.0.1', 3128)
        async with bridge:
            try:
                yield
            finally:
                await browser.stop()

    app = FastAPI(lifespan=lifespan)

    @app.get('/health')
    async def health():
        return {'status': 'ok', 'role': 'isolated-fetch-worker'}

    @app.post('/run')
    async def run(request: Request):
        job = await read_payload(request)
        if not isinstance(job.get('action'), str) or job['action'] not in {'read', 'convert', 'feed'} or not isinstance(job.get('request'), dict):
            raise HTTPException(400, 'Invalid worker job')
        if slots.locked():
            raise HTTPException(503, 'Worker busy')
        async with slots:
            return await complete(request, executor(job), timeout)

    @app.post('/browser')
    async def browser_action(request: Request):
        data = await read_payload(request)
        if not isinstance(data.get('action'), str) or data['action'] not in ACTIONS or not isinstance(data.get('params'), dict):
            raise HTTPException(400, 'Invalid browser request')
        return await complete(request, browser.call(data['action'], data['params']), 50)

    return app


def main():
    if {name for _, name in socket.if_nameindex()} != {'lo'}:
        raise SystemExit('Worker refuses to start with a non-loopback network interface')
    if os.environ.get('FETCH_PROXY') != 'http://127.0.0.1:3128':
        raise SystemExit('Worker requires its fixed egress bridge')
    if any(os.environ.get(key) for key in ['MINIO_ACCESS_KEY', 'MINIO_SECRET_KEY', 'REDIS_URL', 'MCP_TOKEN_FILE', 'WORKER_SOCKET']):
        raise SystemExit('Worker must not receive storage/control credentials or endpoints')
    path = Path('/rpc/worker.sock')
    if path.exists():
        if not path.is_socket():
            raise SystemExit('Refusing to replace a non-socket file')
        path.unlink()
    os.umask(0o077)
    uvicorn.run(create_worker_app(), uds=str(path), access_log=False, log_level='warning',
                limit_concurrency=16, timeout_keep_alive=5)


if __name__ == '__main__':
    main()
