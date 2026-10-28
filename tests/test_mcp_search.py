import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from starlette.testclient import TestClient

from research_gateway.models import SearchResult, SearchWebResponse
from research_mcp_service.search import search_backend, execute_search, SearchOptions
from research_mcp_service.server import create_app

TOKEN = 'offline-test-token-not-for-deployment-123456'
HEADERS = {'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/json, text/event-stream'}
RESULT = {'query': 'test', 'provider': 'searxng', 'status': 'degraded',
          'results': [], 'engine_failures': [['duckduckgo', 'CAPTCHA']]}


def call(arguments=None):
    return {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'search', 'arguments': arguments or {'query': 'test'}}}


class SearchToolTests(unittest.TestCase):
    def test_schema_and_success_hide_routine_diagnostics(self):
        backend = AsyncMock(return_value=RESULT)
        with TestClient(create_app(TOKEN, search_backend=backend), base_url='http://127.0.0.1:8766') as client:
            response = client.post('/mcp', headers=HEADERS, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
            tools = response.json()['result']['tools']
            self.assertEqual({t['name'] for t in tools}, {'health', 'search'})
            schema = next(t for t in tools if t['name'] == 'search')['inputSchema']
            self.assertNotIn('category', schema['properties'])
            response = client.post('/mcp', headers=HEADERS, json=call({'query': ' test ', 'limit': 3}))
            result = response.json()['result']['structuredContent']
            self.assertEqual(result['results'], RESULT['results'])
            self.assertNotIn('status', result)
            self.assertNotIn('diagnostics', result)
        backend.assert_awaited_once_with('test', 3, 'any', category='general', page=1,
            language=None, include_domains=[], exclude_domains=[], provider='auto')

    def test_explicit_diagnostics_are_available_through_mcp(self):
        with TestClient(create_app(TOKEN, search_backend=AsyncMock(return_value=RESULT)), base_url='http://127.0.0.1:8766') as client:
            response = client.post('/mcp', headers=HEADERS, json=call({'query': 'test', 'diagnostics': True}))
            result = response.json()['result']['structuredContent']
            self.assertEqual(result['diagnostics']['status'], 'degraded')
            self.assertEqual(result['diagnostics']['engine_failures'], RESULT['engine_failures'])

    def test_invalid_input_never_reaches_backend(self):
        backend = AsyncMock(return_value=RESULT)
        with TestClient(create_app(TOKEN, search_backend=backend), base_url='http://127.0.0.1:8766') as client:
            for arguments in [{'query': ' '}, {'query': 'x' * 2001}, {'query': 'test', 'limit': 51},
                              {'query': 'test', 'freshness': 'tomorrow'}]:
                data = client.post('/mcp', headers=HEADERS, json=call(arguments)).json()
                self.assertTrue(data['result']['isError'], data)
        backend.assert_not_awaited()

    def test_error_does_not_expose_provider_details(self):
        backend = AsyncMock(side_effect=RuntimeError('private-provider-secret'))
        with TestClient(create_app(TOKEN, search_backend=backend), base_url='http://127.0.0.1:8766') as client:
            response = client.post('/mcp', headers=HEADERS, json=call())
            self.assertTrue(response.json()['result']['isError'])
            self.assertNotIn('private-provider-secret', response.text)

    def test_timeout_releases_slot(self):
        async def slow(*args, **kwargs):
            await asyncio.sleep(1)
        with TestClient(create_app(TOKEN, search_backend=slow, search_timeout=0.01), base_url='http://127.0.0.1:8766') as client:
            for _ in range(3):
                response = client.post('/mcp', headers=HEADERS, json=call())
                self.assertIn('timed out', response.text)
                self.assertTrue(response.json()['result']['isError'])


class SearchAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_slots_and_no_unbounded_queue(self):
        ready = asyncio.Event(); release = asyncio.Event(); count = 0
        async def backend(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                ready.set()
            await release.wait()
            return RESULT
        app = create_app(TOKEN, search_backend=backend)
        async with app.app.router.lifespan_context(app.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8766') as client:
                tasks = [asyncio.create_task(client.post('/mcp', headers=HEADERS, json=call())) for _ in range(2)]
                try:
                    await asyncio.wait_for(ready.wait(), timeout=5)
                    response = await client.post('/mcp', headers=HEADERS, json=call())
                    self.assertTrue(response.json()['result']['isError'])
                    self.assertIn('busy', response.text)
                    self.assertEqual(count, 2)
                finally:
                    release.set()
                    await asyncio.gather(*tasks)

    async def test_adapter_bounds_snippets(self):
        response = SearchWebResponse(query='test', status='degraded', engine_failures=[['ddg', 'CAPTCHA']],
            results=[SearchResult(title='x' * 600, snippet='y' * 5000, url='https://example.org/', rank=1)])
        with patch('research_mcp_service.search.search_web', new=AsyncMock(return_value=response)):
            result = await execute_search(SearchOptions(query='test', limit=1))
        self.assertEqual(len(result['results'][0]['title']), 500)
        self.assertEqual(len(result['results'][0]['snippet']), 4000)
        self.assertEqual(result['truncation'], ['snippet', 'title'])
        self.assertEqual(result['engine_failures'], [['ddg', 'CAPTCHA']])
