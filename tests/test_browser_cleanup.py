"""Legacy adapters retain their contracts while sharing action/capture primitives."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, call, patch


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/browser_controller.py'
        spec = importlib.util.spec_from_file_location('cleanup_controller', path)
        self.controller = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.controller
        spec.loader.exec_module(self.controller)
        self.element = SimpleNamespace(fill=AsyncMock(), type=AsyncMock(), click=AsyncMock())
        self.page = SimpleNamespace(
            url='https://example.org/', title=AsyncMock(return_value='Title'),
            evaluate=AsyncMock(return_value={'visibleText': 'Evidence', 'nodes': []}),
            locator=Mock(return_value=SimpleNamespace(count=AsyncMock(return_value=1), first=self.element)),
            wait_for_timeout=AsyncMock(), keyboard=SimpleNamespace(press=AsyncMock()),
            mouse=SimpleNamespace(wheel=AsyncMock()), on=Mock())
        self.manager = SimpleNamespace(__aexit__=AsyncMock())
        self.session = self.controller.BrowserSession('s', 'standard', self.page, self.manager)
        self.controller.sessions['s'] = self.session

    async def test_legacy_clear_fill_and_default_wait(self):
        result = await self.controller.type_session({'session_id': 's', 'ref': 'e1', 'text': 'value'})
        self.assertEqual(self.element.fill.await_args_list, [call(''), call('value', timeout=None)])
        self.element.type.assert_not_awaited()
        self.page.wait_for_timeout.assert_awaited_once_with(200)
        self.assertEqual(result['visible_text'], 'Evidence')

    async def test_legacy_append_is_typing_not_replacement(self):
        await self.controller.type_session({'session_id': 's', 'ref': 'e1', 'text': ' suffix', 'clear': False})
        self.element.type.assert_awaited_once_with(' suffix')
        self.element.fill.assert_not_awaited()

    async def test_legacy_click_keeps_custom_timeout_wait_and_failure(self):
        await self.controller.click_session({'session_id': 's', 'ref': 'e1', 'timeout_ms': 42, 'wait_ms': 7})
        self.element.click.assert_awaited_once_with(timeout=42)
        self.page.wait_for_timeout.assert_awaited_once_with(7)
        self.page.evaluate.reset_mock()
        self.element.click.side_effect = RuntimeError('failed')
        with self.assertRaises(RuntimeError):
            await self.controller.click_session({'session_id': 's', 'ref': 'e1'})
        self.page.evaluate.assert_not_awaited()

    async def test_legacy_press_remains_page_keyboard_not_element_action(self):
        await self.controller.press_session({'session_id': 's', 'key': 'Tab'})
        self.page.keyboard.press.assert_awaited_once_with('Tab')
        self.page.locator.assert_not_called()
        self.page.wait_for_timeout.assert_awaited_once_with(500)

    async def test_legacy_wait_and_scroll_use_shared_primitives(self):
        await self.controller.wait_session({'session_id': 's', 'ms': 10000})
        self.page.wait_for_timeout.assert_awaited_once_with(10000)
        self.page.wait_for_timeout.reset_mock()
        for direction, axes in [('down', (0, 321)), ('up', (0, -321)),
                                ('right', (321, 0)), ('left', (-321, 0))]:
            with self.subTest(direction=direction):
                self.page.mouse.wheel.reset_mock()
                self.page.wait_for_timeout.reset_mock()
                await self.controller.scroll_session({'session_id': 's', 'direction': direction, 'amount': 321, 'wait_ms': 0})
                self.page.mouse.wheel.assert_awaited_once_with(*axes)
                self.page.wait_for_timeout.assert_awaited_once_with(0)

    async def test_close_uses_manager_once_and_removes_session(self):
        result = await self.controller.close_session({'session_id': 's'})
        self.assertTrue(result['closed'])
        self.manager.__aexit__.assert_awaited_once_with(None, None, None)
        self.assertFalse(hasattr(self.session, 'browser'))
        self.assertNotIn('s', self.controller.sessions)
        self.assertFalse((await self.controller.close_session({'session_id': 's'}))['closed'])
        self.manager.__aexit__.assert_awaited_once()

    async def test_close_failure_keeps_failure_receipt_without_stale_handle(self):
        self.manager.__aexit__.side_effect = RuntimeError('manager close failed')
        result = await self.controller.close_session({'session_id': 's'})
        self.assertFalse(result['closed'])
        self.assertNotIn('s', self.controller.sessions)

    async def test_screenshot_paths_share_capture_without_merging_receipts(self):
        image = {'url': self.page.url, 'screenshot_base64': 'image', 'warnings': []}
        with patch.object(self.controller, 'screenshot', new=AsyncMock(return_value=image)) as capture:
            observed = await self.controller.observe_session({'session_id': 's', 'include_screenshot': True})
            standalone = await self.controller.screenshot_session({'session_id': 's', 'selector': 'table'})
        self.assertEqual(observed['visible_text'], 'Evidence')
        self.assertNotIn('visible_text', standalone)
        capture.assert_has_awaits([call(self.page, full_page=False), call(self.page, selector='table')])

    async def test_diagnostics_count_events_without_storing_private_payloads(self):
        await self.controller._setup_page_events(self.session)
        handlers = {args[0]: args[1] for args, _ in self.page.on.call_args_list}
        # Objects intentionally have no text/URL/failure properties to inspect.
        for _ in range(120):
            handlers['console'](SimpleNamespace(type='error'))
            handlers['console'](SimpleNamespace(type='log'))
            handlers['requestfailed'](object())
            handlers['request'](object())
        handlers['response'](SimpleNamespace(request=SimpleNamespace(resource_type='document'), status=200))
        result = await self.controller.observe_session({'session_id': 's'})
        self.assertEqual(result['diagnostics']['console_error_count'], 120)
        self.assertEqual(result['diagnostics']['failed_request_count'], 120)
        self.assertEqual(result['diagnostics']['request_count'], 120)
        self.assertEqual(result['diagnostics']['main_status'], 200)
        self.assertFalse(hasattr(self.session, 'console'))
        self.assertFalse(hasattr(self.session, 'failed_requests'))
