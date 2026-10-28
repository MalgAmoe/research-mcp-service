import json
import unittest
from mcp.types import CallToolResult, TextContent
from research_mcp_service.output import TextOnlyTools, compact_sources
from research_mcp_service.gateway_tools import register_gateway_tools


class Registry:
    def __init__(self): self.functions = {}
    def tool(self, *args, **kwargs):
        def register(fn):
            self.functions[fn.__name__] = fn
            return fn
        return register


class OutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_representation(self):
        registry = Registry()
        @TextOnlyTools(registry).tool()
        async def example() -> dict:
            return {'text': 'once'}
        result = await registry.functions['example']()
        self.assertIsNone(result.structured_content)
        self.assertEqual(json.loads(result.content[0].text), {'text': 'once'})

    async def test_batch_does_not_request_or_return_full_text(self):
        registry = Registry()
        calls = []
        async def backend(method, path, **kwargs):
            calls.append(kwargs)
            return {'sources': [{'doc_id': 'doc1', 'markdown': 'x'*100000, 'excerpt': 'a'*1000}],
                    'failed_urls': [{'url': 'https://example.org/bad', 'code': 'fetch_bad_status'}]}
        register_gateway_tools(registry, backend)
        result = await registry.functions['web_batch_fetch'](['https://example.org/'], include_markdown=True)
        self.assertFalse(calls[0]['payload']['include_markdown'])
        self.assertNotIn('markdown', result['sources'][0])
        self.assertEqual(len(result['sources'][0]['excerpt']), 420)
        self.assertEqual(len(result['failed_urls']), 1)

    async def test_passages_reconstruct_cleaned_text_without_mutating_cache(self):
        registry = Registry()
        original = 'start ![](data:image/png;base64,AAAA) ' + 'abcd'*100
        async def backend(*a, **kw): return {'doc_id': 'doc1', 'markdown': original}
        register_gateway_tools(registry, backend)
        offset = 0
        parts = []
        while offset is not None:
            result = await registry.functions['web_document']('doc1', True, offset, 30)
            parts.append(result['markdown'])
            offset = result['text_range']['next_offset']
        self.assertNotIn('base64,AAAA', ''.join(parts))
        self.assertTrue(''.join(parts).endswith('abcd'*100))
        self.assertIn('base64,AAAA', original)
