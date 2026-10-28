"""Search routing checks without network requests."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from research_gateway.errors import GatewayError
from research_gateway.models import SearchWebRequest, SearchWebResponse, SearchResult
from research_gateway.services import search_web


class SearchRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, primary, fallback):
        req = SearchWebRequest(query='example')
        with patch('research_gateway.services.settings', SimpleNamespace(search_provider='auto')), \
             patch('research_gateway.services._search_searxng', new=AsyncMock()) as sx, \
             patch('research_gateway.services._search_ddgs', new=AsyncMock()) as ddgs:
            if isinstance(primary, Exception):
                sx.side_effect = primary
            else:
                sx.return_value = primary
            if isinstance(fallback, Exception):
                ddgs.side_effect = fallback
            else:
                ddgs.return_value = fallback
            result = await search_web(req)
            sx.assert_awaited_once_with(req)
            return result, ddgs.await_count

    def response(self, provider, populated=False):
        return SearchWebResponse(query='example', provider=provider, results=[
            SearchResult(title='Example', url='https://example.com', rank=1)
        ] if populated else [], status='ok' if populated else 'no_results')

    async def test_primary_success_skips_fallback(self):
        primary = self.response('searxng', True)
        result, calls = await self.run_case(primary, None)
        self.assertIs(result, primary)
        self.assertEqual(calls, 0)

    async def test_empty_primary_uses_ddgs(self):
        fallback = self.response('ddgs', True)
        result, calls = await self.run_case(self.response('searxng'), fallback)
        self.assertIs(result, fallback)
        self.assertEqual(calls, 1)

    async def test_primary_error_uses_ddgs(self):
        fallback = self.response('ddgs', True)
        result, calls = await self.run_case(GatewayError('search_failed', 'offline'), fallback)
        self.assertIs(result, fallback)
        self.assertEqual(calls, 1)

    async def test_empty_primary_preserved_when_fallback_fails(self):
        primary = self.response('searxng')
        result, _ = await self.run_case(primary, RuntimeError('offline'))
        self.assertIs(result, primary)

    async def test_both_fail_raise_gateway_error(self):
        with self.assertRaises(GatewayError):
            await self.run_case(GatewayError('search_failed', 'offline'), RuntimeError('offline'))
