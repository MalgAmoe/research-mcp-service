"""Offline contract checks; no services or external requests required."""
import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from research_gateway.errors import GatewayError
from research_gateway.main import app
from research_gateway.models import PublicReadRequest, SearchWebRequest
from research_gateway.services import _is_public_address, _resolve_public_host


class ContractTests(unittest.TestCase):
    def test_documented_routes_exist(self):
        paths = app.openapi()["paths"]
        for path in ("/search_web", "/safe_read_url", "/batch_fetch", "/read_url",
                     "/rss/preview", "/health/dependencies"):
            with self.subTest(path=path):
                self.assertIn(path, paths)

    def test_search_defaults(self):
        request = SearchWebRequest(query="Python")
        self.assertEqual(request.category, "general")
        self.assertEqual(request.page, 1)

    def test_request_limits(self):
        for fields in ({"query": ""}, {"query": "x", "page": 0},
                       {"query": "x", "limit": 51}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                SearchWebRequest(**fields)
        with self.assertRaises(ValidationError):
            PublicReadRequest(url="https://example.com", max_chars=50001)

    def test_nonpublic_addresses_rejected(self):
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1",
                        "fc00::1", "not-an-address"):
            with self.subTest(address=address):
                self.assertFalse(_is_public_address(address))
        self.assertTrue(_is_public_address("8.8.8.8"))


class ResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_mixed_dns_answers_rejected(self):
        answers = [(2, 1, 6, "", (address, 443))
                   for address in ("8.8.8.8", "127.0.0.1")]
        with patch("asyncio.base_events.BaseEventLoop.getaddrinfo",
                   new=AsyncMock(return_value=answers)):
            with self.assertRaises(GatewayError):
                await _resolve_public_host("example.com", 443)


if __name__ == "__main__":
    unittest.main()
