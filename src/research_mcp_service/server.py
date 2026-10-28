"""Single-user, private-network Streamable HTTP connectivity prototype."""
from __future__ import annotations

import hmac
import ipaddress
import os
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
import uvicorn


class BearerAuth:
    def __init__(self, app, token: str):
        if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError('MCP bearer token must contain at least 32 non-whitespace ASCII characters')
        self.app = app
        self.expected = token.encode('ascii')

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            values = [value for key, value in scope['headers'] if key.lower() == b'authorization']
            scheme, _, value = values[0].partition(b' ') if len(values) == 1 else (b'', b'', b'')
            if scheme.lower() != b'bearer' or not hmac.compare_digest(value, self.expected):
                response = JSONResponse({'error': 'unauthorized'}, status_code=401,
                    headers={'WWW-Authenticate': 'Bearer', 'Cache-Control': 'no-store'})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(token: str, host: str = '127.0.0.1', port: int = 8766):
    address = ipaddress.IPv4Address(host)
    if not address.is_loopback and address not in ipaddress.IPv4Network('100.64.0.0/10'):
        raise ValueError('Prototype must bind to a loopback or Tailscale IPv4 address')
    if not 1 <= port <= 65535:
        raise ValueError('Invalid port')
    server = MCPServer('Research MCP Service', version='0.1.0',
        instructions='Connectivity prototype. Only health is available; research tools are not connected.')

    @server.tool(annotations={'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False})
    def health() -> dict[str, str]:
        """Check that authenticated MCP tool calls reach this server. Does not check research backends."""
        return {'status': 'ok', 'service': 'research-mcp-service', 'stage': 'connectivity-only'}

    app = server.streamable_http_app(
        stateless_http=True, json_response=True, max_request_body_size=64 * 1024,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[host, f'{host}:{port}'],
            allowed_origins=[f'http://{host}:{port}'],
        ),
    )
    return BearerAuth(app, token)


def main():
    host = os.environ.get('MCP_BIND_HOST', '127.0.0.1')
    port = int(os.environ.get('MCP_PORT', '8766'))
    token_file = os.environ.get('MCP_TOKEN_FILE')
    if not token_file:
        raise SystemExit('Set MCP_TOKEN_FILE to a private token file; no default credential exists')
    path = Path(token_file)
    if path.stat().st_mode & 0o077:
        raise SystemExit('Token file must be private (chmod 600)')
    app = create_app(path.read_text().strip(), host, port)
    uvicorn.run(app, host=host, port=port, access_log=False, log_level='warning',
                proxy_headers=False, limit_concurrency=32, timeout_keep_alive=10)


if __name__ == '__main__':
    main()
