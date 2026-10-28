import asyncio
import base64
import unittest
from unittest.mock import AsyncMock

import httpx
from starlette.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

from research_mcp_service.gateway import GatewayClient, GatewayCalls, MAX_ARTIFACT_BYTES, MAX_RESPONSE_BYTES
from research_mcp_service.server import create_app

TOKEN = 'offline-test-token-not-for-deployment-123456'
HEADERS = {'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/json, text/event-stream'}
URL = 'https://example.org/source'
CASES = [
    ('web_capabilities', {}, 'GET', '/capabilities', {}),
    ('web_read', {'url': URL}, 'POST', '/read_url', {'payload': dict(url=URL, strategy='light', browser_profile='standard', force_refresh=False, include_markdown=False, include_diagnostics=True)}),
    ('web_batch_fetch', {'urls': [URL]}, 'POST', '/batch_fetch', {'payload': dict(urls=[URL], strategy='light', browser_profile='standard', force_refresh=False, include_markdown=False, include_diagnostics=True, max_concurrency=5)}),
    ('web_research', {'query': ' research '}, 'POST', '/research', {'payload': dict(query='research', max_sources=5, read_strategy='light', browser_profile='standard', freshness='any', include_markdown=False)}),
    ('web_convert_document', {'url': URL}, 'POST', '/convert_document', {'payload': dict(url=URL, strategy='text', include_markdown=False)}),
    ('web_document_find', {'doc_id': 'doc_123', 'query': 'example'}, 'GET', '/documents/doc_123', {'params': {'include_markdown': True}}),
    ('web_document', {'doc_id': 'doc_123'}, 'GET', '/documents/doc_123', {'params': {'include_markdown': False}}),
    ('web_recent_documents', {}, 'GET', '/documents/recent', {'params': {'limit': 20, 'include_markdown': False}}),
    ('web_artifact', {'doc_id': 'doc_123', 'kind': 'markdown'}, 'GET', '/documents/doc_123/artifacts/markdown', {'artifact': True}),
    ('rss_preview', {'feed_url': URL}, 'GET', '/rss/preview', {'params': {'feed_url': URL, 'max_entries': 20}}),
    ('rss_subscribe', {'feed_url': URL}, 'POST', '/rss/subscribe', {'payload': {'feed_url': URL}}),
    ('rss_list', {}, 'GET', '/rss/feeds', {}),
    ('rss_fetch', {'feed_url': URL}, 'POST', '/rss/fetch', {'payload': {'feed_url': URL, 'max_entries': 20, 'force_refresh': False}}),
    ('rss_entries', {}, 'GET', '/rss/entries', {'params': {'limit': 50, 'include_read': False}}),
    ('rss_read', {'entry_id': 'entry_123'}, 'GET', '/rss/entries/entry_123', {}),
    ('rss_mark_read', {'entry_id': 'entry_123', 'is_read': False}, 'POST', '/rss/entries/entry_123/read', {'params': {'is_read': False}}),
]


def rpc(name, arguments):
    return {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}


class GatewayToolTests(unittest.TestCase):
    def test_discovery_and_every_tool_route(self):
        backend = AsyncMock(return_value={})
        with TestClient(create_app(TOKEN, gateway_backend=backend), base_url='http://127.0.0.1:8766') as client:
            tools = client.post('/mcp', headers=HEADERS, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).json()['result']['tools']
            self.assertEqual({t['name'] for t in tools}, {'health', *(case[0] for case in CASES)})
            annotations = {t['name']: t['annotations'] for t in tools}
            self.assertFalse(annotations['rss_subscribe']['readOnlyHint'])
            self.assertFalse(annotations['web_read']['readOnlyHint'])
            self.assertTrue(annotations['web_document']['readOnlyHint'])
            for name, args, method, path, kwargs in CASES:
                with self.subTest(tool=name):
                    backend.reset_mock()
                    backend.return_value = [] if name in {'web_recent_documents', 'rss_entries'} else {}
                    response = client.post('/mcp', headers=HEADERS, json=rpc(name, args)).json()['result']
                    self.assertFalse(response.get('isError'), response)
                    backend.assert_awaited_once_with(method, path, **kwargs)

    def test_invalid_inputs_do_not_reach_backend(self):
        backend = AsyncMock(return_value={})
        bad = [('web_read', {'url': 'file:///etc/passwd'}),
               ('web_read', {'url': 'https://user:secret@example.org/'}),
               ('web_read', {'url': URL, 'browser_profile': 'stealth'}),
               ('web_batch_fetch', {'urls': []}), ('web_batch_fetch', {'urls': [URL] * 16}),
               ('web_batch_fetch', {'urls': [URL], 'max_concurrency': 11}),
               ('web_research', {'query': ' '}), ('web_research', {'query': 'x', 'max_sources': 11}),
               ('web_convert_document', {'url': URL, 'strategy': 'structured'}),
               ('web_document', {'doc_id': '../health'}),
               ('web_artifact', {'doc_id': 'doc_123', 'kind': 'credentials'}),
               ('rss_read', {'entry_id': 'x?token=y'}),
               ('rss_entries', {'feed_url': 'ftp://example.org/feed'}),
               ('rss_preview', {'feed_url': URL, 'max_entries': 101})]
        with TestClient(create_app(TOKEN, gateway_backend=backend), base_url='http://127.0.0.1:8766') as client:
            for name, args in bad:
                with self.subTest(tool=name, args=args):
                    response = client.post('/mcp', headers=HEADERS, json=rpc(name, args)).json()['result']
                    self.assertTrue(response['isError'], response)
        backend.assert_not_awaited()

    def test_authentication_still_gates_new_tools(self):
        backend = AsyncMock(return_value={})
        with TestClient(create_app(TOKEN, gateway_backend=backend), base_url='http://127.0.0.1:8766') as client:
            response = client.post('/mcp', json=rpc('rss_subscribe', {'feed_url': URL}))
            self.assertEqual(response.status_code, 401)
        backend.assert_not_awaited()

    def test_storage_uris_and_nested_errors_are_not_returned(self):
        backend = AsyncMock(return_value={'artifacts': {'raw_html': 's3://private-bucket/path', 'markdown': 's3://secret/md'},
            'attempts': [{'error': 'private-password'}],
            'failed_urls': [{'url': URL, 'message': 'private-password', 'details': {'key': 'private-password'}}]})
        with TestClient(create_app(TOKEN, gateway_backend=backend), base_url='http://127.0.0.1:8766') as client:
            response = client.post('/mcp', headers=HEADERS, json=rpc('web_document', {'doc_id': 'doc_123'}))
            self.assertNotIn('private-password', response.text)
            self.assertNotIn('s3://', response.text)
            self.assertEqual(response.json()['result']['structuredContent']['artifacts'], {'original': True, 'markdown': True})

    def test_exceptions_are_sanitized_and_deadlines_release_capacity(self):
        backend = AsyncMock(side_effect=RuntimeError('private-password'))
        with TestClient(create_app(TOKEN, gateway_backend=backend), base_url='http://127.0.0.1:8766') as client:
            response = client.post('/mcp', headers=HEADERS, json=rpc('web_capabilities', {}))
            self.assertTrue(response.json()['result']['isError'])
            self.assertNotIn('private-password', response.text)
        async def slow(*args, **kwargs):
            await asyncio.sleep(1)
        with TestClient(create_app(TOKEN, gateway_backend=slow, gateway_timeout=.01), base_url='http://127.0.0.1:8766') as client:
            for _ in range(3):
                response = client.post('/mcp', headers=HEADERS, json=rpc('web_capabilities', {}))
                self.assertIn('timed out', response.text)


class GatewayTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_json_and_binary_artifacts(self):
        seen = []
        def handler(req):
            seen.append(req)
            return httpx.Response(200, content=b'\x00\xff', headers={'content-type': 'application/pdf'}) if req.url.path.endswith('original') else httpx.Response(200, json={'status': 'ok'})
        client = GatewayClient('http://own-gateway:8000', transport=httpx.MockTransport(handler))
        self.assertEqual(await client('GET', '/capabilities'), {'status': 'ok'})
        result = await client('GET', '/documents/doc_1/artifacts/original', artifact=True)
        self.assertEqual(base64.b64decode(result['content']), b'\x00\xff')
        self.assertEqual(result['encoding'], 'base64')
        self.assertEqual(seen[0].headers['accept-encoding'], 'identity')

    async def test_redirects_errors_and_oversize_are_refused(self):
        for response in [httpx.Response(302, headers={'location': 'http://127.0.0.1:9000/'}),
                         httpx.Response(500, text='private-password'),
                         httpx.Response(200, content=b'a' * (MAX_ARTIFACT_BYTES + 1))]:
            seen = []
            def handler(req):
                seen.append(req)
                return response
            client = GatewayClient('http://own-gateway:8000', transport=httpx.MockTransport(handler))
            with self.assertRaises(ToolError) as error:
                await client('GET', '/documents/doc_1/artifacts/original', artifact=True)
            self.assertNotIn('private-password', str(error.exception))
            self.assertEqual(len(seen), 1)

    async def test_no_unbounded_queue_and_cancellation_releases_slots(self):
        started = asyncio.Event()
        async def backend(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()
        calls = GatewayCalls(backend)
        a = asyncio.create_task(calls('GET', '/capabilities'))
        await started.wait(); started.clear()
        b = asyncio.create_task(calls('GET', '/capabilities'))
        await started.wait()
        try:
            with self.assertRaisesRegex(ToolError, 'busy'):
                await calls('GET', '/capabilities')
        finally:
            a.cancel(); b.cancel()
            await asyncio.gather(a, b, return_exceptions=True)
        calls.backend = AsyncMock(return_value={})
        self.assertEqual(await calls('GET', '/capabilities'), {})

    async def test_oversized_injected_backend_is_also_bounded(self):
        calls = GatewayCalls(AsyncMock(return_value={'text': 'x' * MAX_RESPONSE_BYTES}))
        with self.assertRaisesRegex(ToolError, 'too large'):
            await calls('GET', '/capabilities')
