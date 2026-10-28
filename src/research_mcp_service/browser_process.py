"""One owner-scoped persistent browser controller, inside the isolated worker."""
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import uuid

ACTIONS = {'open', 'observe', 'goto', 'click', 'type', 'press', 'scroll', 'wait', 'text', 'find',
           'close', 'close_all', 'sessions', 'wait_for', 'history'}


class BrowserProcess:
    def __init__(self):
        self.process = None
        self.lock = asyncio.Lock()

    async def stop(self):
        process, self.process = self.process, None
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()

    async def call(self, action, params):
        if action not in ACTIONS:
            return {'error': {'code': 'invalid_action'}}
        if self.lock.locked():
            return {'error': {'code': 'browser_busy'}}
        async with self.lock:
            try:
                async with asyncio.timeout(45):
                    if self.process is None or self.process.returncode is not None:
                        await self.stop()
                        controller = Path(__file__).resolve().parents[2] / 'scripts/browser_controller.py'
                        self.process = await asyncio.create_subprocess_exec(
                            sys.executable, str(controller), stdin=asyncio.subprocess.PIPE,
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                            limit=2 * 1024 * 1024, start_new_session=True)
                    identity = uuid.uuid4().hex
                    self.process.stdin.write((json.dumps({'id': identity, 'action': action, 'params': params}) + '\n').encode())
                    await self.process.stdin.drain()
                    # Library notices are not protocol messages. Never log or forward them.
                    for _ in range(16):
                        line = await self.process.stdout.readline()
                        if not line or len(line) > 2 * 1024 * 1024:
                            raise RuntimeError('Controller exited or exceeded its output limit')
                        try:
                            response = json.loads(line)
                        except (ValueError, UnicodeError):
                            continue
                        if not isinstance(response, dict) or response.get('id') != identity:
                            continue
                        if response.get('ok'):
                            if not isinstance(response.get('result'), dict):
                                raise RuntimeError('Invalid controller result')
                            return response['result']
                        error = response.get('error', '')
                        if error.startswith('KeyError:'):
                            return {'error': {'code': 'session_not_found'}}
                        if 'Browser session limit reached' in error:
                            return {'error': {'code': 'session_limit'}}
                        if 'Screenshot exceeds' in error:
                            return {'error': {'code': 'screenshot_limit'}}
                        if action == 'open':
                            # Startup can fail before a session is registered. Kill the
                            # complete group rather than leak partially launched browsers.
                            await self.stop()
                            return {'error': {'code': 'browser_reset'}}
                        return {'error': {'code': 'browser_action_failed'}}
                    raise RuntimeError('No matching controller response')
            except asyncio.CancelledError:
                await self.stop()
                raise
            except Exception:
                await self.stop()
                return {'error': {'code': 'browser_reset'}}
