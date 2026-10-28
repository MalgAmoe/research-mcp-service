import unittest
from unittest.mock import AsyncMock

from starlette.testclient import TestClient

from research_mcp_service.server import create_app
from mcp_helpers import tool_data

TOKEN = 'offline-test-token-not-for-deployment-123456'
HEADERS = {'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/json, text/event-stream'}
SESSION = 'br_123456abcdef'
PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='


def rpc(name, arguments):
    return {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}


class BrowserToolTests(unittest.TestCase):
    def test_all_actions_dispatch_to_one_configured_backend(self):
        backend = AsyncMock(return_value={'session_id': SESSION})
        cases = [
            ('browser_open', {'url': 'https://example.org/'}, 'open'),
            ('browser_observe', {'session_id': SESSION}, 'observe'),
            ('browser_goto', {'session_id': SESSION, 'url': 'https://example.org/'}, 'goto'),
            ('browser_click', {'session_id': SESSION, 'ref': 'e1'}, 'click'),
            ('browser_type', {'session_id': SESSION, 'ref': 'e1', 'text': 'hello'}, 'type'),
            ('browser_press', {'session_id': SESSION, 'key': 'Enter'}, 'press'),
            ('browser_scroll', {'session_id': SESSION, 'direction': 'down'}, 'scroll'),
            ('browser_wait', {'session_id': SESSION}, 'wait'),
            ('browser_wait_for', {'session_id': SESSION, 'text': 'Results'}, 'wait_for'),
            ('browser_back', {'session_id': SESSION}, 'history'),
            ('browser_forward', {'session_id': SESSION}, 'history'),
            ('browser_text', {'session_id': SESSION}, 'text'),
            ('browser_find', {'session_id': SESSION, 'query': 'needle'}, 'find'),
            ('browser_close', {'session_id': SESSION}, 'close'),
            ('browser_close_all', {}, 'close_all'),
            ('browser_sessions', {}, 'sessions'),
        ]
        with TestClient(create_app(TOKEN, browser_backend=backend), base_url='http://127.0.0.1:8766') as client:
            tools = client.post('/mcp', headers=HEADERS, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).json()['result']['tools']
            self.assertEqual({t['name'] for t in tools}, {'health', *(case[0] for case in cases)})
            for name, args, action in cases:
                with self.subTest(tool=name):
                    backend.reset_mock()
                    response = client.post('/mcp', headers=HEADERS, json=rpc(name, args)).json()['result']
                    self.assertFalse(response.get('isError'), response)
                    self.assertEqual(tool_data(response)['session_id'], SESSION)
                    backend.assert_awaited_once()
                    called_action, params = backend.call_args.args
                    self.assertEqual(called_action, action)
                    for key, value in args.items():
                        self.assertEqual(params[key], value)
                    if name == 'browser_open':
                        self.assertTrue(params['headless'])
                        self.assertEqual(params['viewport'], {'width': 1365, 'height': 900})
            by_name = {t['name']: t for t in tools}
            self.assertTrue(by_name['browser_click']['annotations']['destructiveHint'])
            self.assertTrue(by_name['browser_text']['annotations']['readOnlyHint'])
            self.assertNotIn('headless', by_name['browser_open']['inputSchema']['properties'])

    def test_screenshot_is_native_image_and_text_can_be_omitted(self):
        backend = AsyncMock(return_value={'visible_text': 'private page text', 'snapshot': [], 'screenshot_base64': PNG})
        with TestClient(create_app(TOKEN, browser_backend=backend), base_url='http://127.0.0.1:8766') as client:
            result = client.post('/mcp', headers=HEADERS, json=rpc('browser_observe',
                {'session_id': SESSION, 'include_screenshot': True, 'include_text': False})).json()['result']
            self.assertFalse(result.get('isError'), result)
            self.assertNotIn('visible_text', tool_data(result))
            self.assertNotIn('screenshot_base64', tool_data(result))
            self.assertNotIn('private page text', result['content'][0]['text'])
            self.assertEqual(result['content'][1]['type'], 'image')
            self.assertEqual(result['content'][1]['data'], PNG)

    def test_bad_arguments_do_not_reach_worker(self):
        backend = AsyncMock(return_value={})
        bad = [('browser_open', {'url': 'file:///etc/passwd'}),
               ('browser_open', {'url': 'https://example.org/', 'viewport_width': 99999}),
               ('browser_open', {'url': 'https://example.org/', 'profile': 'stealth', 'timezone': 'UTC'}),
               ('browser_observe', {'session_id': '../other-owner'}),
               ('browser_click', {'session_id': SESSION, 'ref': 'e1"] * [x="'}),
               ('browser_wait', {'session_id': SESSION, 'ms': 60000}),
               ('browser_find', {'session_id': SESSION, 'query': ''}),
               ('browser_text', {'session_id': SESSION, 'max_chars': 100001})]
        with TestClient(create_app(TOKEN, browser_backend=backend), base_url='http://127.0.0.1:8766') as client:
            for name, args in bad:
                with self.subTest(tool=name, args=args):
                    result = client.post('/mcp', headers=HEADERS, json=rpc(name, args)).json()['result']
                    self.assertTrue(result['isError'], result)
        backend.assert_not_awaited()

    def test_backend_errors_and_bad_images_are_not_exposed(self):
        backend = AsyncMock()
        with TestClient(create_app(TOKEN, browser_backend=backend), base_url='http://127.0.0.1:8766') as client:
            for value in [{'error': 'private-worker-path'}, {'screenshot_base64': 'private-worker-path'}]:
                backend.return_value = value
                result = client.post('/mcp', headers=HEADERS, json=rpc('browser_observe', {'session_id': SESSION}))
                self.assertTrue(result.json()['result']['isError'])
                self.assertNotIn('private-worker-path', result.text)

    def test_all_groups_coexist_without_replacing_search(self):
        with TestClient(create_app(TOKEN, search_backend=AsyncMock(), gateway_backend=AsyncMock(),
                                  browser_backend=AsyncMock()), base_url='http://127.0.0.1:8766') as client:
            tools = client.post('/mcp', headers=HEADERS, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).json()['result']['tools']
            self.assertEqual(len(tools), 34)
            self.assertEqual(len({t['name'] for t in tools}), 34)
            self.assertIn('search', {t['name'] for t in tools})
