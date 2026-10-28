import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from research_gateway.errors import GatewayError
from research_gateway.models import SearchResult, SearchWebRequest, SearchWebResponse
from research_gateway.services import search_web, _build_search_query, _search_domain_allowed
from research_mcp_service.search import SearchOptions, search_backend


class FilterTests(unittest.TestCase):
    def test_news_is_not_supported(self):
        with self.assertRaises(ValueError):
            SearchOptions(query='test', category='news')

    def test_normalized_domain_alternatives_and_subdomains(self):
        req = SearchOptions(query='test', include_domains=[' Example.COM. ', 'python.org'],
                            exclude_domains=['private.example.com'])
        self.assertEqual(req.include_domains, ['example.com', 'python.org'])
        self.assertEqual(_build_search_query(req), 'test (site:example.com OR site:python.org) -site:private.example.com')
        for host in ['example.com', 'www.example.com', 'docs.python.org']:
            self.assertTrue(_search_domain_allowed(host, req))
        for host in ['evil-example.com', 'example.com.evil.test', 'private.example.com', 'sub.private.example.com']:
            self.assertFalse(_search_domain_allowed(host, req))

    def test_invalid_domains_rejected(self):
        for host in ['https://example.com', 'example.com/path', 'example.com:443', '*.example.com', 'x OR y', 'a..b']:
            with self.assertRaises(ValueError):
                SearchOptions(query='test', include_domains=[host])


class RoutingEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_keeps_primary_error(self):
        response = SearchWebResponse(query='test', provider='ddgs', results=[
            SearchResult(title='test', url='https://example.com/', rank=1)])
        with patch('research_gateway.services._search_searxng', new=AsyncMock(side_effect=GatewayError('search_failed', 'private detail'))), \
             patch('research_gateway.services._search_ddgs', new=AsyncMock(return_value=response)):
            result = await search_web(SearchWebRequest(query='test'), provider='auto')
        self.assertEqual([attempt.provider for attempt in result.attempts], ['searxng', 'ddgs'])
        self.assertEqual(result.attempts[0].error_code, 'search_failed')
        self.assertNotIn('private detail', result.model_dump_json())

    async def test_degraded_results_do_not_trigger_fallback(self):
        response = SearchWebResponse(query='test', status='degraded', engine_failures=[['ddg', 'CAPTCHA']],
            results=[SearchResult(title='test', url='https://example.com/', rank=1)])
        with patch('research_gateway.services._search_searxng', new=AsyncMock(return_value=response)), \
             patch('research_gateway.services._search_ddgs', new=AsyncMock()) as fallback:
            result = await search_web(SearchWebRequest(query='test'), provider='auto')
        fallback.assert_not_awaited()
        self.assertEqual(result.attempts[0].engine_failures, [['ddg', 'CAPTCHA']])

    async def test_explicit_ddgs_skips_primary(self):
        response = SearchWebResponse(query='test', provider='ddgs', results=[], status='no_results')
        with patch('research_gateway.services._search_searxng', new=AsyncMock()) as primary, \
             patch('research_gateway.services._search_ddgs', new=AsyncMock(return_value=response)):
            result = await search_web(SearchWebRequest(query='test'), provider='ddgs')
        primary.assert_not_awaited()
        self.assertEqual([a.provider for a in result.attempts], ['ddgs'])

    async def test_cancellation_kills_and_reaps_worker(self):
        spawned = []
        ready = asyncio.Event()
        real_spawn = asyncio.create_subprocess_exec
        async def sleeper(*args, **kwargs):
            process = await real_spawn(sys.executable, '-c', 'import time; time.sleep(60)', **kwargs)
            spawned.append(process)
            ready.set()
            return process
        with patch('research_mcp_service.search.asyncio.create_subprocess_exec', new=sleeper):
            task = asyncio.create_task(search_backend('test', 1, 'any'))
            await asyncio.wait_for(ready.wait(), 5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
        self.assertIsNotNone(spawned[0].returncode)
        self.assertLess(spawned[0].returncode, 0)
