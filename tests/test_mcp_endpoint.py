"""In-process HTTP protocol/auth checks: no listening ports or backend services."""
import unittest
from starlette.testclient import TestClient
from research_mcp_service.server import create_app

TOKEN = 'offline-test-token-not-for-deployment-123456'
HEADERS = {'Authorization': 'Bearer ' + TOKEN,
           'Accept': 'application/json, text/event-stream'}


class MCPEndpointTests(unittest.TestCase):
    def client(self):
        return TestClient(create_app(TOKEN), base_url='http://127.0.0.1:8766')

    def test_auth_required_for_all_http_methods(self):
        with self.client() as client:
            for method in ['GET', 'POST', 'DELETE']:
                response = client.request(method, '/mcp')
                self.assertEqual(response.status_code, 401)
            response = client.post('/mcp', headers={**HEADERS, 'Authorization': 'Bearer wrong'})
            self.assertEqual(response.status_code, 401)
            self.assertNotIn(TOKEN, response.text)

    def test_protocol_initialize_list_and_call(self):
        with self.client() as client:
            initialized = client.post('/mcp', headers=HEADERS, json={
                'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                    'protocolVersion': '2025-06-18', 'capabilities': {},
                    'clientInfo': {'name': 'offline-test', 'version': '1'}}})
            self.assertEqual(initialized.status_code, 200, initialized.text)
            self.assertIn('protocolVersion', initialized.json()['result'])
            response = client.post('/mcp', headers=HEADERS,
                json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
            self.assertEqual([tool['name'] for tool in response.json()['result']['tools']], ['health'])
            response = client.post('/mcp', headers=HEADERS, json={
                'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                'params': {'name': 'health', 'arguments': {}}})
            self.assertEqual(response.json()['result']['structuredContent']['status'], 'ok')

    def test_untrusted_host_and_origin_rejected(self):
        with self.client() as client:
            for extra in [{'Host': 'attacker.example'}, {'Origin': 'https://attacker.example'}]:
                response = client.post('/mcp', headers={**HEADERS, **extra}, json={})
                self.assertIn(response.status_code, [403, 421])

    def test_body_limit(self):
        with self.client() as client:
            response = client.post('/mcp', headers=HEADERS, json={'padding': 'x' * 70000})
            self.assertEqual(response.status_code, 413)

    def test_bad_credentials_and_bind_addresses_fail_at_startup(self):
        for token in ['', 'short', 'x' * 33 + '\n']:
            with self.assertRaises(ValueError):
                create_app(token)
        for host in ['0.0.0.0', '8.8.8.8']:
            with self.assertRaises(ValueError):
                create_app(TOKEN, host=host)
