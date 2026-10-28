import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from research_gateway.errors import GatewayError
from research_mcp_service.worker_client import WorkerClient
from research_mcp_service.output import compact_sources
from research_mcp_service.passages import heading_index
from research_mcp_service.gateway_tools import register_gateway_tools
from test_output import Registry


class ClarityTests(unittest.IsolatedAsyncioTestCase):
    def test_artifact_booleans_preserved(self):
        self.assertEqual(compact_sources({'artifacts': {'markdown': True}}), {'artifacts': {'markdown': True}})

    def test_heading_index_fences_and_literal_hash(self):
        text = '```\n# Not heading\n```\n# C#\n## Sub ##\n'
        headings = heading_index(text)
        self.assertEqual([h['title'] for h in headings], ['C#', 'Sub'])
        self.assertEqual(text[headings[0]['offset']:].splitlines()[0], '# C#')

    async def test_index_without_returning_body(self):
        registry = Registry()
        async def backend(*a, **kw): return {'doc_id': 'd', 'markdown': '# Title\nBody'}
        register_gateway_tools(registry, backend)
        result = await registry.functions['web_document']('d', include_headings=True)
        self.assertNotIn('markdown', result)
        self.assertEqual(result['heading_index']['items'][0]['title'], 'Title')

    async def test_preview_does_not_claim_subscription(self):
        registry = Registry()
        async def backend(*a, **kw): return {'feed': {'subscribed_at': 'fake'}}
        register_gateway_tools(registry, backend)
        result = await registry.functions['rss_preview']('https://example.org/feed')
        self.assertNotIn('subscribed_at', result['feed'])
        self.assertFalse(result['subscription_changed'])

    async def test_worker_deadline_distinct_from_unavailable(self):
        worker = WorkerClient('/rpc/worker.sock', transport=httpx.MockTransport(lambda req: httpx.Response(504)))
        with self.assertRaises(GatewayError) as caught:
            await worker.run('read', {})
        self.assertEqual(caught.exception.code, 'worker_timeout')

    async def test_download_timeout_is_not_http_status_failure(self):
        from research_mcp_service.worker_io import download
        with patch('research_mcp_service.worker_io._download', new=AsyncMock(side_effect=httpx.ReadTimeout('private'))):
            with self.assertRaises(GatewayError) as caught:
                await download('https://example.org/')
        self.assertEqual(caught.exception.code, 'fetch_timeout')

    async def test_unsupported_conversion_is_explicit(self):
        from research_mcp_service.worker_job import execute
        response = httpx.Response(200, headers={'content-type': 'application/json'}, content=b'{}',
                                  request=httpx.Request('GET', 'https://example.org/data.json'))
        with patch('research_mcp_service.worker_job.download', new=AsyncMock(return_value=response)):
            with self.assertRaises(GatewayError) as caught:
                await execute({'action': 'convert', 'request': {'url': 'https://example.org/data.json'}})
        self.assertEqual(caught.exception.code, 'unsupported_format')

    def test_build_identifier_has_no_paths_or_configuration(self):
        from research_mcp_service.build_info import SOURCE_SNAPSHOT
        self.assertRegex(SOURCE_SNAPSHOT, r'^sha256:[a-f0-9]{64}$')

    async def test_screenshot_failure_keeps_observation(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/browser_controller.py'
        spec = importlib.util.spec_from_file_location('clarity_controller', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        page = SimpleNamespace(evaluate=AsyncMock(return_value={'visibleText': 'evidence', 'nodes': []}),
            screenshot=AsyncMock(return_value=b'x'*(1024*1024+1)), title=AsyncMock(return_value='Title'), url='https://example.org')
        module.sessions['s'] = module.BrowserSession('s', 'standard', None, page)
        result = await module.observe_session({'session_id': 's', 'include_screenshot': True})
        self.assertEqual(result['visible_text'], 'evidence')
        self.assertEqual(result['warnings'][0]['code'], 'screenshot_limit')
        page.screenshot.side_effect = RuntimeError('private diagnostic')
        result = await module.observe_session({'session_id': 's', 'include_screenshot': True})
        self.assertEqual(result['visible_text'], 'evidence')
        self.assertNotIn('private diagnostic', str(result))
