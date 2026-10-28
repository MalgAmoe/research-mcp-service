"""Bounded search with a killable per-call worker; no shared personal-service state."""
from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import sys
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
from research_gateway.errors import GatewayError
from research_gateway.models import SearchWebRequest
from research_gateway.services import search_web


class SearchOptions(SearchWebRequest):
    query: str = Field(min_length=1, max_length=2000)
    language: str | None = Field(default=None, max_length=32, pattern=r'^[A-Za-z]{2,8}([-_][A-Za-z0-9]{2,8})*$')
    include_domains: list[str] = Field(default_factory=list, max_length=10)
    exclude_domains: list[str] = Field(default_factory=list, max_length=10)
    provider: Literal['auto', 'searxng', 'ddgs'] = 'auto'

    @field_validator('include_domains', 'exclude_domains')
    @classmethod
    def domains(cls, values):
        normalized = []
        for value in values:
            value = value.strip().lower().rstrip('.').encode('idna').decode('ascii')
            if len(value) > 253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value):
                raise ValueError('Use domain names only, without schemes, paths, ports or wildcards')
            if any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-') for label in value.split('.')):
                raise ValueError('Invalid domain name')
            if value not in normalized:
                normalized.append(value)
        return normalized


def bounded_result(result: dict, requested_limit: int) -> dict:
    reasons = set()
    retained = []
    for item in result['results']:
        if len(item['url']) > 8192 or urlparse(item['url']).scheme not in {'http', 'https'}:
            reasons.add('unsupported_or_oversized_url'); continue
        for name, limit in [('title', 500), ('snippet', 4000)]:
            if item.get(name) and len(item[name]) > limit:
                item[name] = item[name][:limit]
                reasons.add(name)
        item['engines'] = [engine[:100] for engine in item.get('engines', [])[:8]]
        retained.append(item)
    result['results'] = retained
    for section in [result, *result.get('attempts', [])]:
        section['engine_failures'] = [[str(part)[:200] for part in failure[:3]]
                                     for failure in section.get('engine_failures', [])[:16]]
    result['requested_limit'] = requested_limit
    result['truncation'] = sorted(reasons)
    while len(json.dumps(result, ensure_ascii=False).encode()) > 500_000 and result['results']:
        result['results'].pop()
        reasons.add('response_byte_limit')
        result['truncation'] = sorted(reasons)
    result['returned_count'] = len(result['results'])
    if not result['results'] and result['status'] == 'ok':
        result['status'] = 'no_results'
    return result


async def execute_search(req: SearchOptions) -> dict:
    try:
        response = await search_web(req, provider=req.provider)
        result = bounded_result(response.model_dump(mode='json'), req.limit)
        result['warnings'] = []
        if response.provider == 'ddgs':
            result['warnings'].append('DDGS per-result engine provenance is unavailable; engines is empty.')
            if req.language:
                result['warnings'].append('DDGS uses the configured region; the requested language is not independently enforced.')
        return result
    except GatewayError as exc:
        return {'query': req.query, 'results': [], 'provider': None, 'status': 'unavailable',
                'error_code': exc.code, 'attempts': exc.context.get('attempts', []),
                'engine_failures': [], 'requested_limit': req.limit, 'returned_count': 0, 'truncation': []}


async def search_backend(query: str, limit: int, freshness: str, **options) -> dict:
    req = SearchOptions(query=query, limit=limit, freshness=freshness, **options)
    # The existing DDGS library uses blocking thread workers. Killing a dedicated
    # process on timeout/cancellation avoids leaking threads or freeing capacity
    # while the underlying provider call is still running.
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'research_mcp_service.search',
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
    )
    try:
        output, _ = await process.communicate(req.model_dump_json().encode())
        if process.returncode != 0:
            raise RuntimeError('Search worker failed')
        return json.loads(output)
    finally:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


if __name__ == '__main__':
    # Requests travel over stdin, never process arguments/logs. No browser or data
    # store is contacted by this path; provider URLs are administrator-configured.
    request = SearchOptions.model_validate_json(sys.stdin.buffer.read(65536))
    print(json.dumps(asyncio.run(execute_search(request)), ensure_ascii=False))
