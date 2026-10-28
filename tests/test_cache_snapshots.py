import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from research_gateway import services
from research_gateway.models import ReadUrlRequest, ReadStrategy, ConvertDocumentRequest


class SnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_page_refresh_preserves_full_evidence_and_cache_hits_reuse_id(self):
        documents, blobs, url_index = {}, {}, {}

        async def save(doc):
            documents[doc.doc_id] = doc.model_copy(deep=True)
            url_index[doc.url] = doc.doc_id

        def put(bucket, key, content, *args):
            uri = f's3://{bucket}/{key}'
            blobs[uri] = content
            return uri

        store = SimpleNamespace(save_document=AsyncMock(side_effect=save),
            get_by_url=AsyncMock(side_effect=lambda url: documents.get(url_index.get(url))))
        artifacts = SimpleNamespace(put_text=put, get_text_uri=lambda uri: blobs[uri])
        prefix = 'Shared text ' * 300
        render = AsyncMock(side_effect=[('Title', prefix + ending, 'playwright+markdownify',
             ReadStrategy.standard, [], raw) for ending, raw in [('A', '<p>A</p>'), ('B', '<p>B</p>'), ('B', '<p>B</p>')]])
        with patch.object(services, 'redis_store', store), patch.object(services, 'artifact_store', artifacts), \
             patch.object(services, '_read_with_strategy', render):
            request = ReadUrlRequest(url='https://example.org/page', include_markdown=True)
            first = await services.read_url(request)
            cached = await services.read_url(request)
            self.assertEqual(first.doc_id, cached.doc_id)
            self.assertEqual(first.retrieved_at, cached.retrieved_at)
            self.assertEqual(render.await_count, 1)
            second = await services.read_url(request.model_copy(update={'force_refresh': True}))
            third = await services.read_url(request.model_copy(update={'force_refresh': True}))
            self.assertEqual(len({first.doc_id, second.doc_id, third.doc_id}), 3)
            self.assertEqual(blobs[first.artifacts.markdown], prefix + 'A')
            self.assertEqual(blobs[first.artifacts.raw_html], '<p>A</p>')
            self.assertEqual(blobs[second.artifacts.markdown], prefix + 'B')
            self.assertEqual(url_index[first.url], third.doc_id)
            self.assertEqual(len(documents), 3)

    async def test_conversion_preserves_original_and_changed_extraction_snapshots(self):
        blobs, documents = {}, {}
        def put(bucket, key, content, *args):
            uri = f's3://{bucket}/{key}'; blobs[uri] = content; return uri
        async def save(doc):
            documents[doc.doc_id] = doc.model_copy(deep=True)
        prefix = b'P' * 4096
        prepared = AsyncMock(side_effect=[(data, 'application/pdf', '.pdf', text, {})
            for data, text in [(prefix + b'A', 'first'), (prefix + b'B', 'second'), (prefix + b'B', 'new extraction')]])
        with patch('research_gateway.document_io.prepare_document', prepared), \
             patch.object(services, 'redis_store', SimpleNamespace(save_document=save)), \
             patch.object(services, 'artifact_store', SimpleNamespace(put_bytes=put, put_text=put)):
            for _ in range(3):
                await services.convert_document(ConvertDocumentRequest(url='https://example.org/file.pdf'))
        self.assertEqual(len(documents), 3)
        saved = list(documents.values())
        self.assertEqual(blobs[saved[0].artifacts.raw_html], prefix + b'A')
        self.assertEqual(blobs[saved[1].artifacts.markdown], 'second')
        self.assertEqual(blobs[saved[2].artifacts.markdown], 'new extraction')
