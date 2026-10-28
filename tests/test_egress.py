import asyncio
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from research_mcp_service.egress import Denied, Proxy, parse_request, public_ipv4, resolve_public


class PolicyTests(unittest.TestCase):
    def test_nonpublic_and_transition_addresses_are_denied(self):
        for address in ['127.0.0.1', '10.0.0.1', '172.16.0.1', '192.168.1.1', '169.254.169.254',
                        '100.69.41.80', '0.0.0.0', '224.0.0.1', '255.255.255.255', '192.0.2.1',
                        '168.63.129.16', '192.0.0.9', '192.88.99.1',
                        '::1', '::ffff:127.0.0.1', '64:ff9b::7f00:1', '2002:7f00:1::']:
            with self.subTest(address=address):
                self.assertFalse(public_ipv4(address))
        self.assertTrue(public_ipv4('1.1.1.1'))

    def test_authority_is_fixed_and_proxy_credentials_are_removed(self):
        host, port, data = parse_request(b'GET http://example.org/path?q=1 HTTP/1.1\r\nHost: private\r\nProxy-Authorization: secret\r\n\r\n')
        self.assertEqual((host, port), ('example.org', 80))
        self.assertIn(b'GET /path?q=1 HTTP/1.1', data)
        self.assertIn(b'Host: example.org', data)
        self.assertNotIn(b'private', data)
        self.assertNotIn(b'secret', data)

    def test_invalid_targets_and_headers(self):
        for line in [b'CONNECT example.org HTTP/1.1', b'CONNECT [::1]:443 HTTP/1.1',
                     b'GET file:///etc/passwd HTTP/1.1', b'GET http://user:pass@example.org/ HTTP/1.1',
                     b'GET http://example.org/ HTTP/2.0', b'TRACE http://example.org/ HTTP/1.1',
                     b'GET http://example.org/ HTTP/1.1\r\n Folded: x']:
            with self.subTest(line=line), self.assertRaises((ValueError, Denied)):
                parse_request(line + b'\r\n\r\n')
        self.assertEqual(parse_request(b'CONNECT example.org:443 HTTP/1.1\r\n\r\n'), ('example.org', 443, None))


class ResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_resolved_answers_must_be_public(self):
        loop = asyncio.get_running_loop()
        def record(ip):
            return (socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))
        for ips in [[], ['127.0.0.1'], ['1.1.1.1', '10.0.0.1']]:
            with patch.object(loop, 'getaddrinfo', new=AsyncMock(return_value=[record(ip) for ip in ips])):
                with self.assertRaises(Denied):
                    await resolve_public('example.org', 443)
        with patch.object(loop, 'getaddrinfo', new=AsyncMock(return_value=[record('1.1.1.1')])):
            self.assertEqual(await resolve_public('example.org', 443), '1.1.1.1')
        for port in [0, 22, 6379, 9000]:
            with self.assertRaises(Denied):
                await resolve_public('example.org', port)

    async def test_unix_proxy_dials_only_validated_numeric_address(self):
        upstream = asyncio.StreamReader()
        upstream.feed_data(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok')
        upstream.feed_eof()
        remote = Mock()
        remote.drain = AsyncMock()
        proxy = Proxy()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'egress.sock')
            server = await asyncio.start_unix_server(proxy.handle, path=path)
            async with server:
                with patch('research_mcp_service.egress.resolve_public', new=AsyncMock(return_value='1.1.1.1')) as resolver, \
                     patch('research_mcp_service.egress.asyncio.open_connection', new=AsyncMock(return_value=(upstream, remote))) as connect:
                    reader, writer = await asyncio.open_unix_connection(path)
                    writer.write(b'GET http://example.org/ HTTP/1.1\r\nHost: example.org\r\n\r\n')
                    await writer.drain()
                    response = await asyncio.wait_for(reader.read(), timeout=5)
                    writer.close(); await writer.wait_closed()
                    self.assertTrue(response.endswith(b'ok'), response)
                    resolver.assert_awaited_once_with('example.org', 80)
                    connect.assert_awaited_once_with('1.1.1.1', 80, family=socket.AF_INET)
                    await asyncio.sleep(.01)
                    self.assertEqual(proxy.active, 0)

    async def test_denial_never_connects_upstream(self):
        proxy = Proxy()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'egress.sock')
            server = await asyncio.start_unix_server(proxy.handle, path=path)
            async with server:
                with patch('research_mcp_service.egress.resolve_public', new=AsyncMock(side_effect=Denied())), \
                     patch('research_mcp_service.egress.asyncio.open_connection', new=AsyncMock()) as connect:
                    reader, writer = await asyncio.open_unix_connection(path)
                    writer.write(b'CONNECT 169.254.169.254:443 HTTP/1.1\r\n\r\n')
                    await writer.drain()
                    response = await asyncio.wait_for(reader.read(), timeout=5)
                    self.assertIn(b'403 Forbidden', response)
                    connect.assert_not_awaited()
                    writer.close(); await writer.wait_closed()
