import contextlib
import io
import json
import unittest
from starlette.testclient import TestClient
from research_mcp_service.server import create_app

LEGACY = 'legacy-offline-token-' + 'a' * 32
NAMED = 'named-offline-token-' + 'b' * 32


class RequestAuthTests(unittest.TestCase):
    def test_named_legacy_and_rejected_requests(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), TestClient(create_app(LEGACY, client_tokens={'test-client': NAMED}), base_url='http://127.0.0.1:8766') as client:
            for token in (LEGACY, NAMED, 'wrong'):
                response = client.post('/mcp', headers={'Authorization': 'Bearer ' + token,
                    'Accept': 'application/json, text/event-stream'}, json={
                    'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'health', 'arguments': {}}})
                self.assertEqual(response.status_code, 401 if token == 'wrong' else 200)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r['client'] for r in records], ['legacy', 'test-client', 'unauthenticated'])
        self.assertEqual(records[1]['tool'], 'health')
        self.assertEqual(records[1]['outcome'], 'ok')
        self.assertTrue(all(r['duration_ms'] >= 0 for r in records))
        self.assertNotIn(LEGACY, output.getvalue())
        self.assertNotIn(NAMED, output.getvalue())

    def test_validation(self):
        for tokens in ({'legacy': NAMED}, {'bad label': NAMED}, {'test': LEGACY}, {'test': 'short'}):
            with self.assertRaises(ValueError):
                create_app(LEGACY, client_tokens=tokens)

    def test_tool_error_is_logged_without_arguments(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), TestClient(create_app(LEGACY), base_url='http://127.0.0.1:8766') as client:
            client.post('/mcp', headers={'Authorization': 'Bearer ' + LEGACY,
                'Accept': 'application/json, text/event-stream'}, json={
                'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': 'missing', 'arguments': {'secret': 'do-not-log-me'}}})
        record = json.loads(output.getvalue().strip())
        self.assertEqual(record['outcome'], 'error')
        self.assertNotIn('do-not-log-me', output.getvalue())
