"""Scratch lifetime regression checks without launching networked browsers."""
import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from research_mcp_service.browser_process import BrowserProcess
from research_mcp_service.temporary import temporary_environment
from research_mcp_service.worker_server import run_job


class ScratchTests(unittest.IsolatedAsyncioTestCase):
    def controller(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/browser_controller.py'
        spec = importlib.util.spec_from_file_location('scratch_controller', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    async def test_job_inherits_owned_tmp_and_removes_profiles(self):
        roots = []

        async def launch(*args, **kwargs):
            root = Path(kwargs['env']['TMPDIR'])
            roots.append(root)
            self.assertEqual(str(root), kwargs['cwd'])
            (root / 'playwright-profile').mkdir()
            (root / 'result.json').write_text('{"result": {"ok": true}}')
            process = AsyncMock()
            process.returncode = 0
            process.pid = 12345
            return process

        with patch('research_mcp_service.worker_server.asyncio.create_subprocess_exec', side_effect=launch), \
             patch('research_mcp_service.worker_server.os.killpg'):
            self.assertEqual(await run_job({'action': 'read'}), {'result': {'ok': True}})
        self.assertFalse(roots[0].exists())

    async def test_controller_stop_waits_before_removing_scratch(self):
        controller = BrowserProcess()
        controller.scratch = tempfile.TemporaryDirectory(prefix='scratch-test-')
        root = Path(controller.scratch.name)
        (root / 'profile').mkdir()
        process = AsyncMock()
        process.pid = 12345
        async def wait():
            self.assertTrue(root.exists())
        process.wait.side_effect = wait
        controller.process = process
        with patch('research_mcp_service.browser_process.os.killpg'):
            await controller.stop()
        self.assertFalse(root.exists())
        await controller.stop()

    async def test_session_close_removes_only_its_scratch(self):
        controller = self.controller()
        with tempfile.TemporaryDirectory() as parent:
            with temporary_environment(parent):
                async def opened(params):
                    root = Path(tempfile.gettempdir())
                    (root / 'profile').mkdir()
                    session = controller.BrowserSession('s', 'standard', None,
                                                       type('Manager', (), {'__aexit__': AsyncMock()})())
                    controller.sessions['s'] = session
                    return {'session_id': 's'}
                with patch.object(controller, '_open_session', side_effect=opened):
                    await controller.open_session({})
                root = Path(controller.sessions['s'].scratch)
                self.assertEqual(root.parent, Path(parent))
                self.assertTrue((root / 'profile').exists())
                await controller.close_session({'session_id': 's'})
                self.assertFalse(root.exists())
                self.assertTrue(Path(parent).exists())

    async def test_environment_restored_on_cancellation(self):
        previous = os.environ.get('TMPDIR')
        cached = tempfile.tempdir
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(asyncio.CancelledError):
                with temporary_environment(root):
                    self.assertEqual(tempfile.gettempdir(), root)
                    raise asyncio.CancelledError()
        self.assertEqual(os.environ.get('TMPDIR'), previous)
        self.assertEqual(tempfile.tempdir, cached)
