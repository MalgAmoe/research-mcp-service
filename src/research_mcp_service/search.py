"""Search adapter using only this repository's copied engine and fixed SearXNG endpoint.

No URL fetching, storage, browser sessions, or DDGS worker threads are exposed.
"""
from research_gateway.models import SearchWebRequest
from research_gateway.services import _search_searxng


async def search_backend(query: str, limit: int, freshness: str) -> dict:
    response = await _search_searxng(SearchWebRequest(query=query, limit=limit, freshness=freshness))
    result = response.model_dump(mode='json')
    # Bound model-visible untrusted snippets and diagnostics. Do not return
    # truncated URLs as if they were usable links.
    result['results'] = [item for item in result['results'] if len(item['url']) <= 2048]
    for item in result['results']:
        item['title'] = item['title'][:300]
        if item['snippet']:
            item['snippet'] = item['snippet'][:2000]
        item['engines'] = [engine[:100] for engine in (item['engines'] or [])[:8]]
    result['engine_failures'] = [[str(part)[:200] for part in failure[:3]]
                                for failure in result['engine_failures'][:16]]
    return result
