"""Control-side client for the private Unix-socket worker. Never falls back to host fetching."""
import asyncio
import json
import re
import time

from .capacity import acquisition_concurrency
from functools import lru_cache

import httpx

from research_gateway.errors import GatewayError


@lru_cache(maxsize=1)
def get_worker(socket_path: str):
    # One client/admission pool per single-event-loop gateway process.
    return WorkerClient(socket_path)


class WorkerClient:
    def __init__(self, socket_path: str, *, transport=None):
        if not socket_path.startswith('/'):
            raise ValueError('Worker socket must be an absolute administrator-configured path')
        self.socket_path = socket_path
        self.transport = transport
        self.slots = asyncio.Semaphore(acquisition_concurrency())

    async def run(self, action, request):
        return await self._exchange('/run', {'action': action, 'request': request}, 80, 32 * 1024 * 1024)

    async def browser(self, action, params):
        return await self._exchange('/browser', {'action': action, 'params': params}, 55, 2 * 1024 * 1024)

    async def _exchange(self, path, payload, timeout, bound):
        started = time.monotonic()
        admitted = None
        outcome = 'cancelled'
        try:
            async with self.slots:
                admitted = time.monotonic()
                result = await self._admitted_exchange(path, payload, timeout, bound)
                error = result.get('error') if isinstance(result, dict) else None
                code = error.get('code') if isinstance(error, dict) else None
                outcome = code if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,64}', code) else ('browser_error' if error else 'ok')
                return result
        except GatewayError as exc:
            outcome = exc.code
            raise
        except Exception:
            outcome = 'internal_error'
            raise
        finally:
            ended = time.monotonic()
            # No URLs, request bodies, credentials or exception text in metrics.
            print(json.dumps({'event': 'worker_operation', 'operation': payload.get('action'),
                              'queue_ms': round(((admitted or ended) - started) * 1000),
                              'duration_ms': round((ended - (admitted or ended)) * 1000),
                              'total_ms': round((ended - started) * 1000),
                              'outcome': outcome}), flush=True)

    async def _admitted_exchange(self, path, payload, timeout, bound):
        # Admission is shared by acquisition and interactive browser operations.
        try:
            return await self._request(path, payload, timeout, bound)
        except GatewayError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise GatewayError('worker_timeout', 'Worker response deadline exceeded', status_code=504) from None
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise GatewayError('worker_unavailable', 'Isolated worker unavailable or timed out', status_code=502) from None

    async def _request(self, path, payload, timeout, bound):
        async with asyncio.timeout(timeout):
            transport = self.transport or httpx.AsyncHTTPTransport(uds=self.socket_path)
            async with httpx.AsyncClient(transport=transport, base_url='http://worker',
                                        trust_env=False, follow_redirects=False, timeout=timeout) as client:
                async with client.stream('POST', path, json=payload) as response:
                    if response.status_code == 503:
                        raise GatewayError('worker_busy', 'Isolated worker is busy; retry shortly', status_code=503)
                    if response.status_code == 504:
                        raise GatewayError('worker_timeout', 'Worker execution exceeded its deadline', status_code=504)
                    if response.status_code != 200:
                        raise GatewayError('worker_unavailable', 'Isolated worker could not complete the request', status_code=502)
                    data = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        if len(data) + len(chunk) > bound:
                            raise GatewayError('worker_result_too_large', 'Worker response exceeds its transfer limit', status_code=502)
                        data.extend(chunk)
                    result = json.loads(data)
                    if not isinstance(result, dict):
                        raise ValueError('Invalid worker response')
                    if path == '/browser':
                        return result
                    if result.get('error'):
                        code = result['error'].get('code', '')
                        if not isinstance(code, str) or not re.fullmatch(r'[a-z_]{1,64}', code):
                            code = 'worker_operation_failed'
                        from .error_details import safe_error
                        safe = safe_error(result['error'])
                        context = {'http_status': safe['http_status']} if 'http_status' in safe else {}
                        raise GatewayError(code, safe.get('message', 'Isolated worker could not complete this operation'), status_code=502, **context)
                    if not isinstance(result.get('result'), dict):
                        raise ValueError('Invalid worker response')
                    return result['result']
