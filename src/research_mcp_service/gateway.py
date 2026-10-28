"""Bounded client for this deployment's private gateway; no default endpoint.

This is NOT fetch/browser egress enforcement. Never point it at the personal gateway.
Deployment wiring stays disabled until independent workers/storage are ready.
"""
from __future__ import annotations

import asyncio
import base64
import json
from urllib.parse import urlsplit

import httpx
from mcp.server.mcpserver.exceptions import ToolError

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024


class GatewayClient:
    def __init__(self, endpoint: str, *, token: str | None = None, transport=None):
        parsed = urlsplit(endpoint)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
                or parsed.password or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
            raise ValueError('A fixed gateway origin without credentials or path is required')
        if token is not None and (len(token) < 32 or not token.isascii() or any(c.isspace() for c in token)):
            raise ValueError('A strong ASCII backend bearer token without whitespace is required')
        self.endpoint = endpoint.rstrip('/')
        self.transport = transport
        self.headers = {'Accept-Encoding': 'identity'}
        if token is not None:
            self.headers['Authorization'] = 'Bearer ' + token

    async def __call__(self, method: str, path: str, *, payload=None, params=None, artifact=False):
        # Paths originate in fixed tool adapters, never a client-supplied route.
        if not path.startswith('/') or path.startswith('//') or '?' in path or '#' in path:
            raise ValueError('Invalid backend route')
        bound = MAX_ARTIFACT_BYTES if artifact else MAX_RESPONSE_BYTES
        async with httpx.AsyncClient(base_url=self.endpoint, transport=self.transport,
                                    trust_env=False, follow_redirects=False, timeout=90,
                                    headers=self.headers) as client:
            async with client.stream(method, path, json=payload, params=params) as response:
                if response.status_code == 404:
                    raise ToolError('The requested document, artifact or feed entry was not found.')
                if response.status_code == 503:
                    raise ToolError('The research backend is busy or undergoing maintenance. Retry later.')
                if response.status_code >= 300:
                    from .error_details import safe_error
                    error_body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        if len(error_body) + len(chunk) > 16384:
                            break
                        error_body.extend(chunk)
                    try:
                        payload = json.loads(error_body)
                        safe = safe_error(payload.get('detail', payload))
                    except (ValueError, AttributeError, TypeError):
                        safe = {}
                    if safe:
                        message = safe.get('message', 'Website request failed.')
                        if 'http_status' in safe:
                            message += f" Upstream HTTP {safe['http_status']}."
                        if 'code' in safe:
                            message += f" [{safe['code']}]"
                        raise ToolError(message)
                    raise ToolError('The research backend could not complete this request.')
                if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                    raise ToolError('Unexpected compressed backend response.')
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(body) + len(chunk) > bound:
                        raise ToolError('Result exceeds the transfer limit. Request fewer items or omit Markdown; large artifacts are not transferred inline.')
                    body.extend(chunk)
                if artifact:
                    mime = response.headers.get('content-type', 'application/octet-stream').split(';')[0].strip()
                    is_text = mime.startswith('text/') or mime in {'application/json', 'application/xml'}
                    return {'content_type': mime, 'size_bytes': len(body),
                            'encoding': 'utf-8' if is_text else 'base64',
                            'content': bytes(body).decode('utf-8', errors='replace') if is_text
                                       else base64.b64encode(body).decode('ascii')}
                return json.loads(body)


class GatewayCalls:
    """Aggregate admission limits shared by all gateway tools in one owner process."""
    def __init__(self, backend, *, timeout=90, concurrency=2):
        self.backend = backend
        self.timeout = timeout
        self.concurrency = concurrency
        self.slots = asyncio.Semaphore(concurrency)

    async def __call__(self, method, path, **kwargs):
        if self.slots.locked():
            raise ToolError(f'Research tools are busy ({self.concurrency} requests running). Retry shortly.')
        async with self.slots:
            try:
                async with asyncio.timeout(self.timeout):
                    result = await self.backend(method, path, **kwargs)
                    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_RESPONSE_BYTES:
                        raise ToolError('Result is too large. Request fewer items or omit Markdown.')
                    return result
            except ToolError:
                raise
            except TimeoutError:
                raise ToolError('Research request timed out. Backend work may still be finishing; do not immediately repeat state-changing requests.') from None
            except Exception:
                raise ToolError('Research backend unavailable. Ask the administrator to check it.') from None
