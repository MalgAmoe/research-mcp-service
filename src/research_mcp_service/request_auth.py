"""Named bearer credentials and bounded, content-free MCP request accounting."""
from __future__ import annotations

from datetime import datetime, timezone
import hmac
import json
import re
import time

from starlette.responses import JSONResponse


class BearerAuth:
    def __init__(self, app, token: str, client_tokens: dict[str, str] | None = None):
        tokens = {'legacy': token, **(client_tokens or {})}
        if client_tokens and 'legacy' in client_tokens:
            raise ValueError('legacy is reserved for the existing token')
        for label, value in tokens.items():
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', label):
                raise ValueError('Invalid client label')
            if not isinstance(value, str) or len(value) < 32 or not value.isascii() or any(c.isspace() for c in value):
                raise ValueError('MCP bearer token must contain at least 32 non-whitespace ASCII characters')
        if len(set(tokens.values())) != len(tokens):
            raise ValueError('Client tokens must be unique')
        self.app = app
        self.tokens = [(label, value.encode('ascii')) for label, value in tokens.items()]

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        started = time.monotonic()
        timestamp = datetime.now(timezone.utc).isoformat()
        values = [v for k, v in scope['headers'] if k.lower() == b'authorization']
        scheme, _, value = values[0].partition(b' ') if len(values) == 1 else (b'', b'', b'')
        client = None
        for label, expected in self.tokens:
            matches = hmac.compare_digest(value, expected)
            if matches and scheme.lower() == b'bearer':
                client = label
        request = bytearray()
        response = bytearray()
        status = None
        outcome = 'error'
        cap = 65536

        async def receive_logged():
            message = await receive()
            if message['type'] == 'http.request':
                request.extend(message.get('body', b'')[:max(0, cap + 1 - len(request))])
            return message

        async def send_logged(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
            elif message['type'] == 'http.response.body':
                response.extend(message.get('body', b'')[:max(0, cap + 1 - len(response))])
            await send(message)

        def parse(data):
            if len(data) > cap:
                return {}
            try:
                value = json.loads(data)
                return value if isinstance(value, dict) else {}
            except (ValueError, UnicodeDecodeError):
                return {}

        def safe(value):
            return value if isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_./-]{1,80}', value) else None

        try:
            if client is None:
                await JSONResponse({'error': 'unauthorized'}, status_code=401,
                    headers={'WWW-Authenticate': 'Bearer', 'Cache-Control': 'no-store'})(scope, receive, send_logged)
                outcome = 'unauthorized'
            else:
                await self.app(scope, receive_logged, send_logged)
                body = parse(response)
                result = body.get('result')
                failed = 'error' in body or (isinstance(result, dict) and result.get('isError') is True)
                outcome = 'ok' if status is not None and status < 400 and not failed else 'error'
        finally:
            body = parse(request)
            params = body.get('params')
            print(json.dumps({
                'event': 'mcp_request', 'timestamp': timestamp,
                'client': client or 'unauthenticated',
                'http_method': scope['method'], 'method': safe(body.get('method')),
                'tool': safe(params.get('name')) if body.get('method') == 'tools/call' and isinstance(params, dict) else None,
                'duration_ms': round((time.monotonic() - started) * 1000),
                'http_status': status, 'outcome': outcome,
            }), flush=True)
