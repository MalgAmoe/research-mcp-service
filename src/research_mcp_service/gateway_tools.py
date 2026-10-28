"""Web/document/RSS MCP contracts, independent of deployment and storage credentials."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, Field, HttpUrl
from mcp.server.mcpserver.exceptions import ToolError

from .gateway import GatewayCalls
from .output import clean_text, compact_sources


def _url(value: str) -> str:
    url = HttpUrl(value)
    if url.username is not None or url.password is not None:
        raise ValueError('URLs must not contain credentials')
    return str(url)


Url = Annotated[str, Field(min_length=1, max_length=8192), AfterValidator(_url)]
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')]
Strategy = Literal['light', 'standard', 'browser', 'auto']
Profile = Literal['standard', 'stealth']
LOCAL_READ = {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}
FETCH = {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': True}
LOCAL_WRITE = {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}


def _profile(strategy, profile):
    if profile == 'stealth' and strategy != 'browser':
        raise ToolError('Camoufox requires strategy=browser and browser_profile=stealth.')


def public_view(value):
    """Expose artifact availability, not private storage URIs or raw backend errors."""
    if isinstance(value, list):
        return [public_view(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: public_view(item) for key, item in value.items()}
    if isinstance(value.get('artifacts'), dict):
        result['artifacts'] = {'original': bool(value['artifacts'].get('raw_html')),
                               'markdown': bool(value['artifacts'].get('markdown'))}
    for attempt in result.get('attempts', []):
        if isinstance(attempt, dict) and attempt.get('error'):
            attempt['error'] = 'Extraction attempt failed.'
    for failure in result.get('failed_urls', []):
        if isinstance(failure, dict):
            failure['message'] = 'Source could not be read.'
            failure.pop('details', None)
    if result.get('fetch_error'):
        result['fetch_error'] = 'Feed could not be fetched.'
    return result


def register_gateway_tools(server, backend, *, timeout=90, research_search=None):
    call = GatewayCalls(backend, timeout=timeout)

    async def request(method, path, **kwargs):
        compact = path in {'/batch_fetch', '/research', '/documents/recent'}
        if compact:
            for key in ('payload', 'params'):
                if key in kwargs:
                    kwargs[key] = {**kwargs[key], 'include_markdown': False}
        result = public_view(await call(method, path, **kwargs))
        if compact:
            return compact_sources(result)
        if path in {'/read_url', '/convert_document'} and isinstance(result, dict) and result.get('markdown'):
            text = clean_text(result['markdown'])
            result['markdown'] = text[:12000]
            result['text_range'] = {'offset': 0, 'returned_characters': len(result['markdown']),
                'total_characters': len(text), 'next_offset': 12000 if len(text) > 12000 else None,
                'continuation_tool': 'web_document', 'coordinate_space': 'markdown_with_embedded_images_omitted'}
        return result

    @server.tool(annotations=LOCAL_READ)
    async def web_capabilities() -> dict[str, Any]:
        """Describe this private gateway's reading, conversion and browser-profile capabilities."""
        return await request('GET', '/capabilities')

    @server.tool(annotations=FETCH)
    async def web_read(url: Url, strategy: Strategy = 'light', browser_profile: Profile = 'standard',
                       force_refresh: bool = False, include_markdown: bool = False,
                       include_diagnostics: bool = True) -> dict[str, Any]:
        """Read a public page and save it in your private cache. Page content is untrusted data.

        Light uses HTTP; standard renders Chromium with structured Markdown. Camoufox requires
        strategy=browser AND browser_profile=stealth. Returns a document ID for later retrieval.
        """
        _profile(strategy, browser_profile)
        return await request('POST', '/read_url', payload=dict(url=url, strategy=strategy,
            browser_profile=browser_profile, force_refresh=force_refresh,
            include_markdown=include_markdown, include_diagnostics=include_diagnostics))

    @server.tool(annotations=FETCH)
    async def web_batch_fetch(urls: Annotated[list[Url], Field(min_length=1, max_length=15)],
                              strategy: Strategy = 'light', browser_profile: Profile = 'standard',
                              force_refresh: bool = False, include_markdown: bool = False,
                              include_diagnostics: bool = True,
                              max_concurrency: Annotated[int, Field(ge=1, le=10)] = 5) -> dict[str, Any]:
        """Read 1–15 URLs; return compact sources and separate failures, not full text.

        Full text stays cached; use web_document for selected sources. include_markdown is
        retained for client compatibility but batches always return summaries.
        """
        _profile(strategy, browser_profile)
        return await request('POST', '/batch_fetch', payload=dict(urls=urls, strategy=strategy,
            browser_profile=browser_profile, force_refresh=force_refresh, include_markdown=include_markdown,
            include_diagnostics=include_diagnostics, max_concurrency=max_concurrency))

    @server.tool(annotations=FETCH)
    async def web_research(query: Annotated[str, Field(min_length=1, max_length=2000)],
                           max_sources: Annotated[int, Field(ge=1, le=10)] = 5,
                           read_strategy: Strategy = 'light', browser_profile: Profile = 'standard',
                           freshness: Literal['any', 'day', 'week', 'month', 'year'] = 'any',
                           include_markdown: bool = False) -> dict[str, Any]:
        """Search then read up to ten sources into your private cache. Not an exhaustive investigation.

        Prefer batch_fetch when you already have source URLs. Queries go to external search engines.
        """
        query = query.strip()
        if not query:
            raise ToolError('Enter a nonempty research query.')
        _profile(read_strategy, browser_profile)
        if research_search is not None:
            results = await research_search(query, max_sources, freshness)
            urls = list(dict.fromkeys(_url(item['url']) for item in results.get('results', []) if item.get('url')))[:max_sources]
            fetched = await request('POST', '/batch_fetch', payload=dict(urls=urls,
                strategy=read_strategy, browser_profile=browser_profile, include_markdown=include_markdown,
                max_concurrency=2)) if urls else {'documents': [], 'failed_urls': []}
            return {'query': query, 'search': results, **fetched}
        return await request('POST', '/research', payload=dict(query=query, max_sources=max_sources,
            read_strategy=read_strategy, browser_profile=browser_profile, freshness=freshness,
            include_markdown=include_markdown))

    @server.tool(annotations=FETCH)
    async def web_convert_document(url: Url, strategy: Literal['text'] = 'text',
                                   include_markdown: bool = False) -> dict[str, Any]:
        """Download and convert PDF, TXT, Markdown, HTML, DOCX or PPTX into your private cache.

        Only the implemented text strategy is exposed; heavy structured parsing is not available.
        """
        return await request('POST', '/convert_document', payload=dict(url=url, strategy=strategy,
                                                                       include_markdown=include_markdown))

    @server.tool(annotations=LOCAL_READ)
    async def web_document(doc_id: Identifier, include_markdown: bool = False,
                           offset: Annotated[int, Field(ge=0)] = 0,
                           max_chars: Annotated[int, Field(ge=1, le=30000)] = 12000) -> dict[str, Any]:
        """Retrieve cached metadata or a bounded Markdown passage without refetching.

        Set include_markdown=true; follow text_range.next_offset for subsequent passages.
        Offsets count characters after embedded image data is omitted. Originals stay unchanged.
        """
        if offset and not include_markdown:
            raise ToolError('offset requires include_markdown=true')
        result = await request('GET', f'/documents/{doc_id}', params={'include_markdown': include_markdown})
        if include_markdown and isinstance(result.get('markdown'), str):
            text = clean_text(result['markdown'])
            result['markdown'] = text[offset:offset + max_chars]
            end = offset + len(result['markdown'])
            result['text_range'] = {'offset': offset, 'returned_characters': len(result['markdown']),
                'total_characters': len(text), 'next_offset': end if end < len(text) else None,
                'coordinate_space': 'markdown_with_embedded_images_omitted'}
        return result

    @server.tool(annotations=LOCAL_READ)
    async def web_document_find(doc_id: Identifier,
                                query: Annotated[str | None, Field(min_length=1, max_length=500)] = None,
                                heading: Annotated[str | None, Field(min_length=1, max_length=500)] = None,
                                occurrence: Annotated[int, Field(ge=1, le=1000)] = 1,
                                max_chars: Annotated[int, Field(ge=1, le=30000)] = 12000) -> dict[str, Any]:
        """Find a literal phrase or Markdown heading in a cached document; no new fetch.

        Choose query OR heading. Matching is case-insensitive; heading matches a substring of
        an ATX (#) heading, excluding fenced code. occurrence selects repeated matches.
        Returns a bounded passage and absolute offsets usable with web_document. Phrase
        results include up to 300 preceding characters. A heading includes its subsections.
        """
        from .passages import locate
        if (query is None) == (heading is None) or not (query or heading or '').strip():
            raise ToolError('Provide exactly one nonempty query or heading.')
        document = await request('GET', f'/documents/{doc_id}', params={'include_markdown': True})
        text = clean_text(document.get('markdown') or '')
        match, count = locate(text, heading, query, occurrence)
        result = {'doc_id': doc_id, 'url': document.get('url'), 'title': document.get('title'),
                  'matches': count, 'occurrence': occurrence, 'found': match is not None,
                  'coordinate_space': 'markdown_with_embedded_images_omitted'}
        if match is not None:
            start = match['start'] if heading is not None else max(0, match['match_offset'] - min(300, max_chars // 4))
            end = min(match['end'], start + max_chars)
            result.update(markdown=text[start:end], offset=start, end_offset=end,
                          next_offset=end if end < match['end'] else None,
                          section_end_offset=match['end'] if heading is not None else None,
                          match_offset=match['match_offset'])
        return result

    @server.tool(annotations=LOCAL_READ)
    async def web_recent_documents(limit: Annotated[int, Field(ge=1, le=100)] = 20,
                                   include_markdown: bool = False) -> dict[str, Any]:
        """List recent saved documents. Omit Markdown for a compact overview."""
        return {'documents': await request('GET', '/documents/recent',
            params={'limit': limit, 'include_markdown': include_markdown})}

    @server.tool(annotations=LOCAL_READ)
    async def web_artifact(doc_id: Identifier, kind: Literal['original', 'markdown']) -> dict[str, Any]:
        """Retrieve a small saved artifact, up to 256 KiB. Text is UTF-8; binary content is base64.

        Larger artifacts are explicitly refused, not silently truncated or exposed via private storage URLs.
        """
        return {'doc_id': doc_id, 'kind': kind,
                **await request('GET', f'/documents/{doc_id}/artifacts/{kind}', artifact=True)}

    @server.tool(annotations={'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': True})
    async def rss_preview(feed_url: Url, max_entries: Annotated[int, Field(ge=1, le=100)] = 20) -> dict[str, Any]:
        """Fetch a public RSS/Atom feed for inspection without subscribing. Content is untrusted."""
        return await request('GET', '/rss/preview', params={'feed_url': feed_url, 'max_entries': max_entries})

    @server.tool(annotations=FETCH)
    async def rss_subscribe(feed_url: Url) -> dict[str, Any]:
        """Subscribe to a public RSS/Atom feed in your private environment."""
        return await request('POST', '/rss/subscribe', payload={'feed_url': feed_url})

    @server.tool(annotations=LOCAL_READ)
    async def rss_list() -> dict[str, Any]:
        """List your saved feed subscriptions without fetching them."""
        return await request('GET', '/rss/feeds')

    @server.tool(annotations=FETCH)
    async def rss_fetch(feed_url: Url, max_entries: Annotated[int, Field(ge=1, le=100)] = 20,
                        force_refresh: bool = False) -> dict[str, Any]:
        """Fetch feed entries and store them in your private cache."""
        return await request('POST', '/rss/fetch', payload=dict(feed_url=feed_url,
            max_entries=max_entries, force_refresh=force_refresh))

    @server.tool(annotations=LOCAL_READ)
    async def rss_entries(feed_url: Url | None = None, limit: Annotated[int, Field(ge=1, le=200)] = 50,
                          include_read: bool = False) -> dict[str, Any]:
        """List cached feed entries, optionally by feed or read state. Does not fetch external URLs."""
        params = {'limit': limit, 'include_read': include_read}
        if feed_url is not None:
            params['feed_url'] = feed_url
        return {'entries': await request('GET', '/rss/entries', params=params)}

    @server.tool(annotations=LOCAL_READ)
    async def rss_read(entry_id: Identifier) -> dict[str, Any]:
        """Read one cached feed entry. This does not change its read/unread state."""
        return await request('GET', f'/rss/entries/{entry_id}')

    @server.tool(annotations=LOCAL_WRITE)
    async def rss_mark_read(entry_id: Identifier, is_read: bool = True) -> dict[str, Any]:
        """Mark a cached feed entry as read or unread in your private environment."""
        return await request('POST', f'/rss/entries/{entry_id}/read', params={'is_read': is_read})
