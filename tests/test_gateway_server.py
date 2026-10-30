import unittest

import httpx
from starlette.responses import JSONResponse

from research_mcp_service.gateway_server import HostedRoutes
from research_mcp_service.server import BearerAuth


class HostedRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_and_disallowed_routes_fail_closed(self):
        async def backend(scope, receive, send):
            await JSONResponse({'ok': True})(scope, receive, send)
        app = BearerAuth(HostedRoutes(backend), 't' * 48)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://backend') as client:
            self.assertEqual((await client.get('/health')).status_code, 401)
            self.assertEqual((await client.get('/health/dependencies')).status_code, 401)
            client.headers['authorization'] = 'Bearer ' + 't' * 48
            for path in ['/research', '/search_web', '/safe_read_url', '/jobs', '/docs']:
                self.assertEqual((await client.post(path)).status_code, 404)
            for path in ['/health', '/health/dependencies', '/read_url', '/browser', '/rss/feeds', '/documents/recent']:
                self.assertEqual((await client.get(path)).status_code, 200)
