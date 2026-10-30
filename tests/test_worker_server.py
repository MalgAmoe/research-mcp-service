import asyncio
import os
import signal
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from research_mcp_service.worker_server import create_worker_app, run_job, main


class WorkerServerTests(unittest.IsolatedAsyncioTestCase):
    def test_worker_refuses_s3_credentials(self):
        for key in ['S3_ACCESS_KEY', 'S3_SECRET_KEY']:
            with self.subTest(key=key), \
                 patch.dict(os.environ, {key: 'test-only', 'FETCH_PROXY': 'http://127.0.0.1:3128'}, clear=True), \
                 patch('research_mcp_service.worker_server.socket.if_nameindex', return_value=[(1, 'lo')]):
                with self.assertRaisesRegex(SystemExit, 'storage/control credentials'):
                    main()

    async def test_validation_and_success(self):
        executor = AsyncMock(return_value={'result': {'markdown': 'read'}})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_worker_app(executor)), base_url='http://worker') as client:
            response = await client.post('/run', json={'action': 'read', 'request': {'url': 'https://example.org/'}})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['result']['markdown'], 'read')
            executor.assert_awaited_once()
            executor.reset_mock()
            for job in [{}, {'action': 'execute_shell', 'request': {}}, {'action': 'read', 'request': 'wrong'}]:
                self.assertEqual((await client.post('/run', json=job)).status_code, 400)
            self.assertEqual((await client.post('/run', content=b'x' * 65537)).status_code, 413)
            executor.assert_not_awaited()

    async def test_deadline_cancels_work_and_releases_capacity(self):
        cancelled = 0
        async def executor(job):
            nonlocal cancelled
            try:
                await asyncio.sleep(10)
            finally:
                cancelled += 1
        app = create_worker_app(executor, timeout=.02)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://worker') as client:
            for _ in range(3):
                response = await client.post('/run', json={'action': 'read', 'request': {}})
                self.assertEqual(response.status_code, 504)
        self.assertEqual(cancelled, 3)

    async def test_errors_do_not_leak_details(self):
        app = create_worker_app(AsyncMock(side_effect=RuntimeError('private-path-or-secret')))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://worker') as client:
            response = await client.post('/run', json={'action': 'read', 'request': {}})
            self.assertEqual(response.status_code, 502)
            self.assertNotIn('private-path-or-secret', response.text)

    async def test_busy_has_no_unbounded_queue(self):
        ready = asyncio.Event(); release = asyncio.Event(); count = 0
        async def executor(job):
            nonlocal count
            count += 1
            if count == 2:
                ready.set()
            await release.wait()
            return {'result': {}}
        app = create_worker_app(executor)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://worker') as client:
            tasks = [asyncio.create_task(client.post('/run', json={'action': 'read', 'request': {}})) for _ in range(2)]
            try:
                await asyncio.wait_for(ready.wait(), 3)
                self.assertEqual((await client.post('/run', json={'action': 'read', 'request': {}})).status_code, 503)
                self.assertEqual(count, 2)
            finally:
                release.set(); await asyncio.gather(*tasks)

    async def test_cancellation_kills_owned_process_group(self):
        started = asyncio.Event()
        async def communicate(data):
            started.set()
            await asyncio.Event().wait()
        process = AsyncMock()
        process.pid = 999999999
        process.communicate.side_effect = communicate
        with patch('research_mcp_service.worker_server.asyncio.create_subprocess_exec', new=AsyncMock(return_value=process)), \
             patch('research_mcp_service.worker_server.os.killpg') as kill:
            task = asyncio.create_task(run_job({'action': 'read', 'request': {}}))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            kill.assert_called_once_with(process.pid, signal.SIGKILL)
            process.wait.assert_awaited_once()
