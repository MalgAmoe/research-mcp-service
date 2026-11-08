"""Bounded browser acquisition features; no arbitrary scripts, paths or proxies."""
from __future__ import annotations

import base64
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class BrowserAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['click', 'hover', 'fill', 'press', 'check', 'uncheck', 'select', 'drag', 'scroll', 'wait']
    ref: str | None = Field(default=None, pattern=r'^e[1-9][0-9]{0,6}$')
    selector: str | None = Field(default=None, min_length=1, max_length=500)
    value: str | None = Field(default=None, max_length=20000)
    destination: str | None = Field(default=None, min_length=1, max_length=500)
    x: int = Field(default=0, ge=-5000, le=5000)
    y: int = Field(default=0, ge=-5000, le=5000)
    ms: int = Field(default=0, ge=0, le=5000)

    @model_validator(mode='after')
    def validate_kind(self):
        if self.kind not in {'wait', 'scroll'} and (self.ref is None) == (self.selector is None):
            raise ValueError('Specify exactly one ref or selector for element actions')
        if self.kind in {'fill', 'press', 'select'} and self.value is None:
            raise ValueError('Action requires value')
        if self.kind == 'press' and len(self.value) > 64:
            raise ValueError('Key exceeds limit')
        if self.kind == 'drag' and self.destination is None:
            raise ValueError('Drag requires destination selector')
        return self


def locator(page, ref=None, selector=None):
    return page.locator(f'[data-pi-ref="{ref}"]' if ref else 'css=' + selector).first


async def perform_action(page, kind, *, target=None, value=None, timeout=5000,
                         x=0, y=0, ms=0, destination=None, clear_first=False):
    """Shared primitives. Exceptions propagate; callers keep their own receipts/waits."""
    if kind == 'wait':
        await page.wait_for_timeout(ms)
    elif kind == 'scroll':
        await page.mouse.wheel(x, y)
    elif kind == 'press' and target is None:
        await page.keyboard.press(value)
    elif kind in {'click', 'hover', 'check', 'uncheck'}:
        await getattr(target, kind)(timeout=timeout)
    elif kind == 'fill':
        if clear_first:  # Preserve the legacy clear-then-fill input event sequence.
            await target.fill('')
        await target.fill(value, timeout=timeout)
    elif kind == 'type':  # Legacy append typing, not exposed as a batch action.
        await target.type(value)
    elif kind == 'press':
        await target.press(value, timeout=timeout)
    elif kind == 'select':
        await target.select_option(label=value, timeout=timeout)
    elif kind == 'drag':
        await target.drag_to(destination, timeout=timeout)
    else:
        raise ValueError('Unsupported browser action')


async def actions(page, raw_actions):
    # Validate the entire chain before producing any side effects.
    if not 1 <= len(raw_actions) <= 20 or len(json.dumps(raw_actions).encode('utf-8')) > 48000:
        raise ValueError('Expected one to twenty actions within 48 KB')
    chain = [BrowserAction.model_validate(a) for a in raw_actions]
    completed = 0
    for action in chain:
        try:
            target = None if action.kind in {'wait', 'scroll'} else locator(page, action.ref, action.selector)
            destination = locator(page, selector=action.destination) if action.kind == 'drag' else None
            await perform_action(page, action.kind, target=target, value=action.value,
                                 x=action.x, y=action.y, ms=action.ms, destination=destination)
            completed += 1
        except Exception:
            return {'completed': completed, 'failed_action': completed + 1,
                    'warning': 'Chain stopped; prior actions may have changed external state. Observe before retrying.'}
    return {'completed': completed, 'failed_action': None}


async def extract(page, *, selector=None, format='markdown', pierce_shadow=False,
                  max_chars=12000, max_matches=20):
    from scrapling import Selector
    from research_mcp_service.scrapling_backend import page_html
    from research_gateway.services import _structured_markdown

    if format not in {'markdown', 'text', 'html'} or not 1 <= max_chars <= 30000 or not 1 <= max_matches <= 50:
        raise ValueError('Invalid extraction limits')
    html = await page_html(page, pierce_shadow=pierce_shadow)
    root = Selector(html, url=page.url)
    selected = root.css(selector) if selector else [root]
    matches = []
    budget = max_chars
    truncated = len(selected) > max_matches
    for node in selected[:max_matches]:
        if isinstance(node, str):
            text = str(node)  # Scrapling ::text / ::attr(...) selection.
        elif format == 'text':
            text = node.get_all_text(separator='\n', strip=True)
        elif format == 'html':
            text = node.get()
        else:
            text = _structured_markdown(node.get(), page.url)
        if len(text) > budget:
            truncated = True
        matches.append(text[:budget])
        budget -= min(len(text), budget)
        if budget <= 0:
            break
    return {'url': page.url, 'format': format, 'selector': selector,
            'pierce_shadow': pierce_shadow, 'match_count': len(selected),
            'matches': matches, 'truncated': truncated or len(matches) < len(selected)}


def network(session):
    if session.profile != 'standard':
        raise ValueError('Network history requires the Scrapling standard profile')
    return session.browser_manager.network


def network_requests(session, *, after_id=0, limit=30, url_contains=None):
    if after_id < 0 or not 1 <= limit <= 100:
        raise ValueError('Invalid network listing limits')
    history = network(session)
    # Literal filter only: no user regex evaluated against the entire history.
    records = history.search(after_id=after_id, include_static=False, limit=None)
    if url_contains:
        records = [r for r in records if url_contains in r.url]
    shown = records[:limit]
    return {'requests': [{'request_id': r.meta['network_id'], 'url': r.url,
                          'method': r.method, 'status': r.status,
                          'resource_type': r.meta.get('resource_type')} for r in shown],
            'has_more': len(records) > limit,
            'next_cursor': shown[-1].meta['network_id'] if shown else max(after_id, history.last_id),
            'dropped_count': history.dropped_count}


def network_response(session, *, request_id, offset=0, max_chars=12000):
    if request_id < 1 or offset < 0 or not 1 <= max_chars <= 30000:
        raise ValueError('Invalid network response limits')
    r = network(session).get(request_id)
    if r is None:
        return {'available': False, 'reason': 'Request missing or evicted from ephemeral history'}
    # Do not expose cookie/authorization headers or request bodies by default.
    text = r.body.decode(r.encoding or 'utf-8', errors='replace') if r.body else ''
    end = offset + max_chars
    return {'available': bool(r.body), 'request_id': request_id, 'url': r.url,
            'status': r.status, 'content_type': r.headers.get('content-type'),
            'text': text[offset:end], 'offset': offset, 'total_chars': len(text),
            'next_offset': end if end < len(text) else None,
            'note': r.meta.get('body_note'), 'ephemeral': True}


async def screenshot(page, *, ref=None, selector=None, full_page=False):
    if ref and selector or full_page and (ref or selector):
        raise ValueError('Choose page or exactly one element target')
    target = locator(page, ref, selector) if ref or selector else page
    options = {'timeout': 10000, 'type': 'png'}
    if target is page:
        options['full_page'] = full_page
    png = await target.screenshot(**options)
    if len(png) > 1024 * 1024:
        return {'url': page.url, 'warnings': [{'code': 'screenshot_limit', 'message': 'Screenshot exceeds 1 MiB'}]}
    return {'url': page.url, 'screenshot_base64': base64.b64encode(png).decode('ascii')}
