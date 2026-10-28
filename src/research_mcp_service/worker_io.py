"""Bounded HTTP download inside the network-none worker, through its egress bridge."""
import httpx

from research_gateway.config import settings
from research_gateway.errors import GatewayError


async def download(url: str, *, max_bytes: int = 20 * 1024 * 1024) -> httpx.Response:
    try:
        return await _download(url, max_bytes=max_bytes)
    except httpx.HTTPStatusError as exc:
        raise GatewayError('fetch_bad_status', 'URL returned an unsuccessful HTTP status',
                           status_code=502, http_status=exc.response.status_code) from None
    except httpx.TimeoutException:
        raise GatewayError('fetch_timeout', 'HTTP fetching exceeded its timeout', status_code=504) from None
    except httpx.HTTPError:
        raise GatewayError('fetch_failed', 'Could not fetch URL through the worker proxy', status_code=502) from None


async def _download(url: str, *, max_bytes: int) -> httpx.Response:
    if settings.fetch_proxy != 'http://127.0.0.1:3128':
        raise RuntimeError('Worker download requires its fixed loopback egress bridge')
    async with httpx.AsyncClient(proxy=settings.fetch_proxy, trust_env=False,
                                follow_redirects=True, max_redirects=5, timeout=30) as client:
        async with client.stream('GET', url, headers={'User-Agent': 'research-mcp-service/0.1',
                                                     'Accept-Encoding': 'identity'}) as response:
            response.raise_for_status()
            if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                raise GatewayError('unsupported_encoding', 'Server ignored the uncompressed download request', status_code=502)
            data = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=65536):
                if len(data) + len(chunk) > max_bytes:
                    raise GatewayError('download_too_large', 'Download exceeds the worker limit', status_code=413)
                data.extend(chunk)
            return httpx.Response(response.status_code, headers=response.headers,
                                  content=bytes(data), request=response.request)
