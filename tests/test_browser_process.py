import unittest

from research_mcp_service.browser_process import BrowserProcess


class BrowserProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_controller_protocol_without_launching_a_browser(self):
        controller = BrowserProcess()
        try:
            result = await controller.call('sessions', {})
            self.assertEqual(result['sessions'], [])
            self.assertEqual(result['limits']['max_sessions'], 4)
            missing = await controller.call('observe', {'session_id': 'br_' + '0' * 32})
            self.assertEqual(missing['error']['code'], 'session_not_found')
            closed = await controller.call('close_all', {})
            self.assertEqual(closed['closed'], 0)
        finally:
            await controller.stop()
        self.assertIsNone(controller.process)

    async def test_invalid_action_does_not_start_a_process(self):
        controller = BrowserProcess()
        result = await controller.call('execute_shell', {})
        self.assertEqual(result['error']['code'], 'invalid_action')
        self.assertIsNone(controller.process)

    async def test_busy_does_not_queue_an_action(self):
        controller = BrowserProcess()
        async with controller.lock:
            result = await controller.call('sessions', {})
        self.assertEqual(result['error']['code'], 'browser_busy')
        self.assertIsNone(controller.process)
