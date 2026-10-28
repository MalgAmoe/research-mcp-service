"""Private-worker HTTP proxy over a Unix socket; public IPv4, ports 80/443 only.

Workers must have network_mode=none and reach this proxy through a loopback-to-Unix
bridge. URL validation alone is not the isolation boundary. No request URL logging.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
from pathlib import Path
import socket
from urllib.parse import urlsplit

HEADER_LIMIT = 16384
CONNECTION_LIMIT = 64
TRANSFER_LIMIT = 32 * 1024 * 1024


class Denied(ValueError):
    pass


def public_ipv4(value: str) -> bool:
    try:
        address = ipaddress.IPv4Address(value)
        special = (ipaddress.IPv4Network('192.0.0.0/24'), ipaddress.IPv4Network('192.88.99.0/24'),
                   ipaddress.IPv4Network('168.63.129.16/32'))  # Azure platform virtual IP
        return (address.is_global and not address.is_multicast and not address.is_reserved
                and not any(address in network for network in special))
    except ValueError:
        return False


def authority(value: str):
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise Denied('Invalid port') from None
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.fragment or any(ord(c) <= 32 or ord(c) == 127 for c in value)):
        raise Denied('Invalid destination')
    # Reject IPv6 and alternative numeric forms rather than applying an incomplete
    # policy to IPv4-mapped/NAT64/6to4 addresses. DNS uses only A records below.
    if ':' in parsed.hostname:
        raise Denied('IPv6 is not supported')
    return parsed, port


async def resolve_public(host: str, port: int) -> str:
    if port not in {80, 443}:
        raise Denied('Port is not allowed')
    records = await asyncio.get_running_loop().getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(item[4][0] for item in records))
    if not addresses or any(not public_ipv4(address) for address in addresses):
        raise Denied('Destination is not public')
    return addresses[0]


def parse_request(header: bytes):
    lines = header.decode('iso-8859-1').split('\r\n')
    method, target, version = lines[0].split(' ')
    if version not in {'HTTP/1.0', 'HTTP/1.1'}:
        raise Denied('Unsupported protocol')
    if method == 'CONNECT':
        parsed, port = authority('http://' + target)
        if port is None or parsed.path or parsed.query:
            raise Denied('Invalid tunnel destination')
        return parsed.hostname, port, None
    if method not in {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'}:
        raise Denied('Unsupported method')
    parsed, port = authority(target)
    if parsed.scheme != 'http':
        raise Denied('HTTP requests require absolute HTTP URLs; use CONNECT for TLS')
    port = 80 if port is None else port
    path = (parsed.path or '/') + ('?' + parsed.query if parsed.query else '')
    fields = []
    upgrade = False
    for line in lines[1:]:
        if not line:
            continue
        if line[0].isspace() or ':' not in line:
            raise Denied('Invalid header')
        name, value = line.split(':', 1)
        if not name or any(c not in "!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in name):
            raise Denied('Invalid header name')
        if any(ord(c) < 32 and c != '\t' or ord(c) == 127 for c in value):
            raise Denied('Invalid header value')
        if name.lower() in {'host', 'proxy-authorization', 'proxy-connection', 'connection'}:
            continue
        if name.lower() == 'upgrade':
            upgrade = True
        fields.append(line)
    # Fix the upstream authority and close ordinary connections after one response.
    # Any pipelined bytes still reach ONLY this same pinned public IP/port.
    host_header = parsed.hostname + (f':{port}' if port != 80 else '')
    fields += [f'Host: {host_header}', 'Connection: ' + ('Upgrade' if upgrade else 'close')]
    forwarded = f'{method} {path} {version}\r\n' + '\r\n'.join(fields) + '\r\n\r\n'
    return parsed.hostname, port, forwarded.encode('iso-8859-1')


async def copy_stream(reader, writer):
    transferred = 0
    while chunk := await asyncio.wait_for(reader.read(65536), timeout=30):
        transferred += len(chunk)
        if transferred > TRANSFER_LIMIT:
            raise Denied('Transfer limit')
        writer.write(chunk)
        await writer.drain()


class Proxy:
    def __init__(self):
        self.active = 0

    async def handle(self, reader, writer):
        if self.active >= CONNECTION_LIMIT:
            writer.write(b'HTTP/1.1 503 Busy\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            await writer.drain()
            writer.close()
            return
        self.active += 1
        remote = None
        relays = []
        started = False
        try:
            async with asyncio.timeout(120):
                header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), timeout=10)
                if len(header) > HEADER_LIMIT:
                    raise Denied('Header limit')
                host, port, request = parse_request(header)
                ip = await asyncio.wait_for(resolve_public(host, port), timeout=10)
                # Dial the validated numeric address, NEVER resolve the hostname again.
                upstream, remote = await asyncio.wait_for(
                    asyncio.open_connection(ip, port, family=socket.AF_INET), timeout=10)
                if request is None:
                    writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                    await writer.drain()
                else:
                    remote.write(request)
                    await remote.drain()
                started = True
                relays = [asyncio.create_task(copy_stream(reader, remote)),
                          asyncio.create_task(copy_stream(upstream, writer))]
                await asyncio.wait(relays, return_when=asyncio.FIRST_COMPLETED)
        except (Denied, ValueError, UnicodeError):
            if not started:
                writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            if not started:
                writer.write(b'HTTP/1.1 502 Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        finally:
            for task in relays:
                task.cancel()
            await asyncio.gather(*relays, return_exceptions=True)
            if remote:
                remote.close()
            try:
                await asyncio.wait_for(writer.drain(), timeout=1)
            except (OSError, TimeoutError):
                pass
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=1)
            except (OSError, TimeoutError):
                writer.transport.abort()
            self.active -= 1


async def main():
    path = Path(os.environ.get('EGRESS_SOCKET', '/egress/proxy.sock'))
    if path.exists():
        if not path.is_socket():
            raise RuntimeError('Refusing to replace a non-socket file')
        path.unlink()
    server = await asyncio.start_unix_server(Proxy().handle, path=str(path), limit=HEADER_LIMIT)
    path.chmod(0o600)
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
