import base64
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from research_gateway import services
from research_gateway.document_io import prepare_document
from research_gateway.errors import GatewayError
from research_gateway.models import ConvertDocumentRequest, ReadUrlRequest
from research_mcp_service.worker_client import WorkerClient
from research_mcp_service.worker_io import download


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_reader_uses_worker_without_host_rendering(self):
        backend = SimpleNamespace(run=AsyncMock(return_value={'title': 'Title', 'markdown': 'Text',
            'method': 'playwright+markdownify', 'strategy_used': 'standard', 'attempts': [], 'raw_html': '<p>Text</p>'}))
        with patch.object(services, 'settings', SimpleNamespace(worker_socket='/rpc/worker.sock')), \
             patch('research_mcp_service.worker_client.get_worker', return_value=backend), \
             patch.object(services, '_extract_with_playwright', new=AsyncMock()) as render:
            result = await services._read_with_strategy(ReadUrlRequest(url='https://example.org/'))
            self.assertEqual(result[1], 'Text')
            self.assertEqual(backend.run.call_args.args[0], 'read')
            render.assert_not_awaited()
            backend.run.side_effect = GatewayError('worker_unavailable', 'Unavailable')
            with self.assertRaises(GatewayError):
                await services._read_with_strategy(ReadUrlRequest(url='https://example.org/'))
            render.assert_not_awaited()

    async def test_document_conversion_uses_worker_bytes_and_text(self):
        backend = SimpleNamespace(run=AsyncMock(return_value={'original_base64': base64.b64encode(b'original').decode(),
            'content_type': 'application/pdf', 'suffix': '.pdf', 'markdown': '## Page 1\nContent'}))
        with patch('research_gateway.document_io.settings', SimpleNamespace(worker_socket='/rpc/worker.sock')), \
             patch('research_mcp_service.worker_client.get_worker', return_value=backend), \
             patch.object(services, '_convert_document_content', new=AsyncMock()) as convert:
            result = await prepare_document(ConvertDocumentRequest(url='https://example.org/report.pdf'))
            self.assertEqual(result, (b'original', 'application/pdf', '.pdf', '## Page 1\nContent', {}))
            convert.assert_not_awaited()
            with self.assertRaises(GatewayError):
                await prepare_document(ConvertDocumentRequest(url='https://example.org/report.pdf', strategy='structured'))
            self.assertEqual(backend.run.await_count, 1)

    async def test_rss_worker_serialization_preserves_ids_and_dates(self):
        xml = '<rss version="2.0"><channel><title>Feed</title><item><title>Entry</title><link>https://example.org/item</link><pubDate>Tue, 27 Oct 2026 10:00:00 GMT</pubDate></item></channel></rss>'
        url = 'https://example.org/feed'
        original = services._parse_rss_feed(xml, url)
        serialized = json.loads(json.dumps(original, default=str))
        backend = SimpleNamespace(run=AsyncMock(return_value=serialized))
        with patch.object(services, 'settings', SimpleNamespace(worker_socket='/rpc/worker.sock')), \
             patch('research_mcp_service.worker_client.get_worker', return_value=backend):
            result = await services.rss_preview(url)
        item = original['entries'][0]
        self.assertEqual(result.entries[0].entry_id, services._entry_id(url, item['link'], item['title'], item['published_at']))
        self.assertEqual(result.entries[0].published_at, item['published_at'])
        backend.run.assert_awaited_once_with('feed', {'feed_url': url})


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_errors_are_sanitized_and_no_redirect_is_followed(self):
        for response in [httpx.Response(302, headers={'location': 'http://private/'}),
                         httpx.Response(200, json={'error': {'code': 'read_failed', 'message': 'private-secret'}})]:
            seen = []
            def handler(request):
                seen.append(request)
                return response
            worker = WorkerClient('/rpc/worker.sock', transport=httpx.MockTransport(handler))
            with self.assertRaises(GatewayError) as exc:
                await worker.run('read', {'url': 'https://example.org/'})
            self.assertNotIn('private-secret', str(exc.exception))
            self.assertEqual(len(seen), 1)

    async def test_worker_success(self):
        worker = WorkerClient('/rpc/worker.sock', transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={'result': {'markdown': 'read'}})))
        self.assertEqual(await worker.run('read', {}), {'markdown': 'read'})

    async def test_download_uses_fixed_proxy_and_bounds_body(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'oversized')))
        with patch('research_mcp_service.worker_io.settings', SimpleNamespace(fetch_proxy='http://127.0.0.1:3128')), \
             patch('research_mcp_service.worker_io.httpx.AsyncClient', return_value=client) as factory:
            with self.assertRaises(GatewayError) as exc:
                await download('https://example.org/', max_bytes=2)
            self.assertEqual(exc.exception.code, 'download_too_large')
            self.assertEqual(factory.call_args.kwargs['proxy'], 'http://127.0.0.1:3128')
            self.assertFalse(factory.call_args.kwargs['trust_env'])

    async def test_http_failures_remain_gateway_errors_for_auto_fallback(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403)))
        with patch('research_mcp_service.worker_io.settings', SimpleNamespace(fetch_proxy='http://127.0.0.1:3128')), \
             patch('research_mcp_service.worker_io.httpx.AsyncClient', return_value=client):
            with self.assertRaises(GatewayError) as exc:
                await download('https://example.org/')
            self.assertEqual(exc.exception.code, 'fetch_bad_status')
