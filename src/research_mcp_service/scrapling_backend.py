"""Pinned Scrapling Chromium acquisition; policy and extraction stay with our worker.

Only public session/fetch/page_setup APIs are used for browser ownership. The
shadow serializer is a pinned upstream implementation detail, covered by live
fixture checks. No caller-supplied proxy, executable, CDP URL or state path.
"""
from __future__ import annotations


async def start_chromium(*, proxy=None, viewport=None, locale=None, timezone=None,
                         record_requests=False):
    from scrapling.fetchers import AsyncStealthySession

    options = {'viewport': viewport or {'width': 1365, 'height': 900},
               'device_scale_factor': 1, 'color_scheme': 'light',
               'service_workers': 'block', 'accept_downloads': False}
    if proxy:
        options['proxy'] = {'server': proxy, 'bypass': '<-loopback>'}
    session = AsyncStealthySession(
        headless=True, max_pages=1, retries=1, block_webrtc=True,
        record_requests=record_requests, google_search=False,
        locale=locale, timezone_id=timezone, additional_args=options,
        # BFCache restores can omit the lifecycle event our history contract awaits.
        extra_flags=['--disable-back-forward-cache'],
    )
    try:
        await session.start()
    except BaseException:
        await session.close()
        raise
    return session


async def render(url, *, proxy=None):
    """Return final HTML, URL, title and status without changing extraction policy."""
    session = await start_chromium(proxy=proxy)
    captured = {}

    async def capture(page):
        try:
            await page.wait_for_load_state('networkidle', timeout=5000)
        except Exception:
            pass
        captured.update(html=await page.content(), url=page.url, title=await page.title())

    try:
        response = await session.fetch(url, timeout=30000, google_search=False,
                                       page_action=capture, solve_cloudflare=False)
        return {**captured, 'status': response.status}
    finally:
        await session.close()


async def page_html(page, *, pierce_shadow=False):
    if pierce_shadow:
        from scrapling.engines.toolbelt.convertor import SHADOW_SNAPSHOT_JS
        return await page.evaluate(SHADOW_SNAPSHOT_JS)
    return await page.content()
