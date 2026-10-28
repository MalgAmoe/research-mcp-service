import unittest
import httpx
from mcp.server.mcpserver.exceptions import ToolError
from research_mcp_service.passages import locate
from research_mcp_service.gateway import GatewayClient
from research_mcp_service.error_details import safe_error


class PassageTests(unittest.TestCase):
    def test_section_includes_children_not_next_peer(self):
        text = 'cookies\n# Paper\n## Results\nEvidence\n### Table\nData\n## References\nSources'
        match, count = locate(text, heading='results')
        self.assertEqual(count, 1)
        self.assertEqual(text[match['start']:match['end']], '## Results\nEvidence\n### Table\nData\n')

    def test_fenced_headings_ignored_and_repeated_phrase_offsets(self):
        text = '```python\n# Results\n```\n## Results\nA Test and a TEST'
        match, count = locate(text, heading='results')
        self.assertEqual(count, 1)
        match, count = locate(text, query='test', occurrence=2)
        self.assertEqual(count, 2)
        self.assertEqual(text[match['match_offset']:], 'TEST')
        self.assertEqual(locate(text, query='absent'), (None, 0))

    def test_error_fields_allowlisted(self):
        result = safe_error({'code': 'fetch_bad_status', 'http_status': 403, 'message': 'secret', 'cause': 'secret'})
        self.assertEqual(result['http_status'], 403)
        self.assertNotIn('secret', str(result))


class ErrorTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_safe_upstream_status_survives_gateway_response(self):
        client = GatewayClient('http://backend', transport=httpx.MockTransport(lambda request:
            httpx.Response(502, json={'detail': {'code': 'fetch_bad_status', 'http_status': 403, 'message': 'secret'}})))
        with self.assertRaises(ToolError) as exc:
            await client('POST', '/read_url')
        self.assertIn('403', str(exc.exception))
        self.assertNotIn('secret', str(exc.exception))
