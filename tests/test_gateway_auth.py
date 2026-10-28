import unittest

import httpx

from research_mcp_service.gateway import GatewayClient


class GatewayAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_sent_only_to_fixed_backend_without_redirects(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(302, headers={'location': 'https://other.example/'})
        client = GatewayClient('http://backend', token='x' * 48,
                               transport=httpx.MockTransport(handler))
        with self.assertRaises(Exception):
            await client('GET', '/health')
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].headers['authorization'], 'Bearer ' + 'x' * 48)
        self.assertEqual(requests[0].url.host, 'backend')

    async def test_invalid_tokens_rejected(self):
        for token in ['', 'short', 'x' * 40 + '\n', 'é' * 40]:
            with self.assertRaises(ValueError):
                GatewayClient('http://backend', token=token)
