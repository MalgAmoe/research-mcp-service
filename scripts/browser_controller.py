#!/usr/bin/env python3
"""JSONL browser controller for the Pi browser extension.

This is intentionally separate from the research gateway. It keeps short-lived
interactive browser sessions in this subprocess and returns compact observations
for agent control.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrowserSession:
    session_id: str
    profile: str
    browser: Any
    page: Any
    context: Any | None = None
    playwright: Any | None = None
    browser_manager: Any | None = None
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    console: list[dict[str, Any]] = field(default_factory=list)
    failed_requests: list[dict[str, Any]] = field(default_factory=list)
    request_count: int = 0
    response_count: int = 0
    main_status: int | None = None


sessions: dict[str, BrowserSession] = {}
MAX_SESSIONS = max(1, int(os.getenv("PI_BROWSER_MAX_SESSIONS", "8")))
IDLE_TIMEOUT_SECONDS = max(60, int(os.getenv("PI_BROWSER_IDLE_TIMEOUT_SECONDS", "1800")))


def _get_session(session_id: str) -> BrowserSession:
    session = sessions[session_id]
    session.last_used_at = time.time()
    return session


OBSERVE_JS = r"""
() => {
  function visible(el) {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }
  function roleOf(el) {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button') return 'button';
    if (tag === 'input') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      if (type === 'submit' || type === 'button') return 'button';
      return 'textbox';
    }
    if (tag === 'textarea') return 'textbox';
    if (tag === 'select') return 'combobox';
    if (/^h[1-6]$/.test(tag)) return 'heading';
    if (tag === 'form') return 'form';
    if (tag === 'img') return 'img';
    return tag;
  }
  function nameOf(el) {
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const text = labelledBy.split(/\s+/).map(id => document.getElementById(id)?.innerText || '').join(' ').trim();
      if (text) return text;
    }
    const aria = el.getAttribute('aria-label');
    if (aria) return aria.trim();
    const title = el.getAttribute('title');
    const alt = el.getAttribute('alt');
    const value = el.value;
    const text = el.innerText || el.textContent || '';
    return String(aria || title || alt || value || text || '').replace(/\s+/g, ' ').trim().slice(0, 220);
  }
  function isInteresting(el) {
    const tag = el.tagName.toLowerCase();
    return ['a','button','input','textarea','select','summary','form'].includes(tag) ||
      /^h[1-6]$/.test(tag) || el.getAttribute('role') || el.onclick || el.getAttribute('tabindex');
  }
  const nodes = [];
  let n = 1;
  for (const el of Array.from(document.querySelectorAll('body *'))) {
    if (!visible(el) || !isInteresting(el)) continue;
    let ref = el.getAttribute('data-pi-ref');
    if (!ref) {
      ref = 'e' + n++;
      el.setAttribute('data-pi-ref', ref);
    }
    const role = roleOf(el);
    const name = nameOf(el);
    const attrs = [];
    if (el.disabled) attrs.push('disabled');
    if (el.checked) attrs.push('checked');
    if (el.getAttribute('aria-expanded')) attrs.push('expanded=' + el.getAttribute('aria-expanded'));
    if (el.href) attrs.push('url=' + el.href);
    nodes.push({ ref, role, name, attrs, tag: el.tagName.toLowerCase() });
    if (nodes.length >= 120) break;
  }
  const visibleText = (document.body?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 5000);
  return { visibleText, nodes };
}
"""


async def _setup_page_events(session: BrowserSession) -> None:
    page = session.page

    def on_console(msg: Any) -> None:
        if len(session.console) < 100:
            session.console.append({"type": msg.type, "text": msg.text[:1000]})

    def on_request(_request: Any) -> None:
        session.request_count += 1

    def on_response(response: Any) -> None:
        session.response_count += 1
        try:
            if response.request.resource_type == "document" and session.main_status is None:
                session.main_status = response.status
        except Exception:
            pass

    def on_request_failed(request: Any) -> None:
        if len(session.failed_requests) < 50:
            failure = request.failure or {}
            session.failed_requests.append({
                "url": request.url,
                "method": request.method,
                "resource_type": request.resource_type,
                "error": failure.get("errorText") if isinstance(failure, dict) else str(failure),
            })

    page.on("console", on_console)
    page.on("request", on_request)
    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)


async def _maybe_block_resources(context: Any, block_resources: bool) -> None:
    if not block_resources:
        return

    async def route_handler(route: Any) -> None:
        if route.request.resource_type in {"image", "media", "font"}:
            await route.abort()
        else:
            await route.continue_()

    await context.route("**/*", route_handler)


async def open_session(params: dict[str, Any]) -> dict[str, Any]:
    await expire_idle_sessions()
    if len(sessions) >= MAX_SESSIONS:
        oldest = min(sessions.values(), key=lambda item: item.last_used_at)
        await close_session({"session_id": oldest.session_id, "reason": "session_limit"})

    url = params["url"]
    profile = params.get("profile", "standard")
    headless = params.get("headless", True)
    block_resources = params.get("block_resources", False)
    viewport = params.get("viewport") or {"width": 1365, "height": 900}
    locale = params.get("locale")
    timezone = params.get("timezone")

    session_id = "br_" + uuid.uuid4().hex[:12]

    if profile == "standard":
        from playwright.async_api import async_playwright  # type: ignore

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=headless)
        context_kwargs: dict[str, Any] = {"viewport": viewport}
        if locale:
            context_kwargs["locale"] = locale
        if timezone:
            context_kwargs["timezone_id"] = timezone
        context = await browser.new_context(**context_kwargs)
        await _maybe_block_resources(context, block_resources)
        page = await context.new_page()
        session = BrowserSession(session_id=session_id, profile=profile, browser=browser, context=context, page=page, playwright=pw)
    elif profile == "stealth":
        from camoufox.async_api import AsyncCamoufox  # type: ignore

        humanize = params.get("humanize", True)
        manager = AsyncCamoufox(
            headless=headless,
            humanize=humanize,
            block_webrtc=True,
            block_images=block_resources,
            locale=locale,
        )
        browser = await manager.__aenter__()
        page = await browser.new_page(viewport=viewport)
        session = BrowserSession(
            session_id=session_id,
            profile=profile,
            browser=browser,
            page=page,
            browser_manager=manager,
        )
    else:
        raise ValueError(f"unknown profile: {profile}")

    sessions[session_id] = session
    try:
        await _setup_page_events(session)
        response = await page.goto(url, wait_until=params.get("wait_until", "domcontentloaded"), timeout=params.get("timeout_ms", 30000))
        if response is not None:
            session.main_status = response.status
        wait_ms = int(params.get("wait_ms", 500))
        if wait_ms > 0:
            await page.wait_for_timeout(wait_ms)
        return await observe_session({"session_id": session_id, "include_screenshot": params.get("include_screenshot", False)})
    except BaseException:
        await close_session({"session_id": session_id, "reason": "open_failed"})
        raise


async def observe_session(params: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(params["session_id"])
    page = session.page
    observed = await page.evaluate(OBSERVE_JS)
    screenshot_b64 = None
    if params.get("include_screenshot", False):
        png = await page.screenshot(full_page=bool(params.get("full_page", False)))
        screenshot_b64 = base64.b64encode(png).decode("ascii")
    return {
        "session_id": session.session_id,
        "profile": session.profile,
        "url": page.url,
        "title": await page.title(),
        "visible_text": observed.get("visibleText", ""),
        "snapshot": observed.get("nodes", []),
        "screenshot_base64": screenshot_b64,
        "diagnostics": {
            "main_status": session.main_status,
            "request_count": session.request_count,
            "response_count": session.response_count,
            "failed_request_count": len(session.failed_requests),
            "console_error_count": sum(1 for m in session.console if m.get("type") == "error"),
        },
    }


async def _element_by_ref(page: Any, ref: str) -> Any:
    locator = page.locator(f'[data-pi-ref="{ref}"]')
    count = await locator.count()
    if count == 0:
        raise ValueError(f"ref not found: {ref}; call browser_observe first")
    return locator.first


async def goto_session(params: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(params["session_id"])
    response = await session.page.goto(
        params["url"],
        wait_until=params.get("wait_until", "domcontentloaded"),
        timeout=params.get("timeout_ms", 30000),
    )
    if response is not None:
        session.main_status = response.status
    wait_ms = int(params.get("wait_ms", 500))
    if wait_ms > 0:
        await session.page.wait_for_timeout(wait_ms)
    return await observe_session({"session_id": session.session_id, "include_screenshot": params.get("include_screenshot", False)})


async def click_session(params: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(params["session_id"])
    locator = await _element_by_ref(session.page, params["ref"])
    await locator.click(timeout=params.get("timeout_ms", 10000))
    await session.page.wait_for_timeout(int(params.get("wait_ms", 500)))
    return await observe_session({"session_id": session.session_id, "include_screenshot": params.get("include_screenshot", False)})


async def type_session(params: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(params["session_id"])
    locator = await _element_by_ref(session.page, params["ref"])
    if params.get("clear", True):
        await locator.fill("")
        await locator.fill(params["text"])
    else:
        await locator.type(params["text"])
    await session.page.wait_for_timeout(int(params.get("wait_ms", 200)))
    return await observe_session({"session_id": session.session_id, "include_screenshot": params.get("include_screenshot", False)})


async def press_session(params: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(params["session_id"])
    await session.page.keyboard.press(params["key"])
    await session.page.wait_for_timeout(int(params.get("wait_ms", 500)))
    return await observe_session({"session_id": session.session_id, "include_screenshot": params.get("include_screenshot", False)})


async def scroll_session(params: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(params["session_id"])
    amount = int(params.get("amount", 700))
    direction = params.get("direction", "down")
    dy = amount if direction == "down" else -amount
    dx = amount if direction == "right" else -amount if direction == "left" else 0
    if direction in {"up", "down"}:
        dx = 0
    await session.page.mouse.wheel(dx, dy)
    await session.page.wait_for_timeout(int(params.get("wait_ms", 500)))
    return await observe_session({"session_id": session.session_id, "include_screenshot": params.get("include_screenshot", False)})


async def wait_session(params: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(params["session_id"])
    await session.page.wait_for_timeout(int(params.get("ms", 1000)))
    return await observe_session({"session_id": session.session_id, "include_screenshot": params.get("include_screenshot", False)})


async def text_session(params: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(params["session_id"])
    max_chars = int(params.get("max_chars", 50000))
    text = await session.page.evaluate("() => document.body?.innerText || ''")
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    return {
        "session_id": session.session_id,
        "profile": session.profile,
        "url": session.page.url,
        "title": await session.page.title(),
        "text": text,
        "truncated": truncated,
        "text_length": len(text),
    }


async def find_session(params: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(params["session_id"])
    query = str(params["query"])
    case_sensitive = bool(params.get("case_sensitive", False))
    context_chars = int(params.get("context_chars", 250))
    max_results = int(params.get("max_results", 20))
    text = await session.page.evaluate("() => document.body?.innerText || ''")
    haystack = text if case_sensitive else text.lower()
    needle = query if case_sensitive else query.lower()
    results = []
    start = 0
    while len(results) < max_results:
        idx = haystack.find(needle, start)
        if idx == -1:
            break
        a = max(0, idx - context_chars)
        b = min(len(text), idx + len(query) + context_chars)
        results.append({"index": idx, "snippet": text[a:b].replace("\n", " ")})
        start = idx + max(1, len(needle))
    return {
        "session_id": session.session_id,
        "profile": session.profile,
        "url": session.page.url,
        "title": await session.page.title(),
        "query": query,
        "matches": len(results),
        "results": results,
        "text_length": len(text),
    }


async def close_session(params: dict[str, Any]) -> dict[str, Any]:
    session = sessions.pop(params["session_id"], None)
    if not session:
        return {"closed": False, "message": "session not found"}
    try:
        if session.context is not None:
            await session.context.close()
        if session.browser_manager is not None:
            await session.browser_manager.__aexit__(None, None, None)
        else:
            await session.browser.close()
        if session.playwright is not None:
            await session.playwright.stop()
    except Exception as exc:
        return {"closed": False, "error": str(exc)}
    return {"closed": True, "session_id": params["session_id"]}


async def close_all_sessions(_params: dict[str, Any] | None = None) -> dict[str, Any]:
    session_ids = list(sessions)
    results = [await close_session({"session_id": session_id, "reason": "close_all"}) for session_id in session_ids]
    return {"closed": sum(1 for result in results if result.get("closed")), "requested": len(session_ids)}


async def expire_idle_sessions() -> int:
    cutoff = time.time() - IDLE_TIMEOUT_SECONDS
    expired = [session_id for session_id, session in sessions.items() if session.last_used_at < cutoff]
    for session_id in expired:
        await close_session({"session_id": session_id, "reason": "idle_timeout"})
    return len(expired)


async def idle_reaper() -> None:
    while True:
        await asyncio.sleep(min(60, IDLE_TIMEOUT_SECONDS))
        await expire_idle_sessions()


async def list_sessions(_params: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "profile": s.profile,
                "url": s.page.url,
                "age_seconds": int(now - s.created_at),
                "idle_seconds": int(now - s.last_used_at),
            }
            for s in sessions.values()
        ],
        "limits": {"max_sessions": MAX_SESSIONS, "idle_timeout_seconds": IDLE_TIMEOUT_SECONDS},
    }


ACTIONS = {
    "open": open_session,
    "observe": observe_session,
    "goto": goto_session,
    "click": click_session,
    "type": type_session,
    "press": press_session,
    "scroll": scroll_session,
    "wait": wait_session,
    "text": text_session,
    "find": find_session,
    "close": close_session,
    "close_all": close_all_sessions,
    "sessions": list_sessions,
}


async def handle(line: str) -> None:
    request = json.loads(line)
    req_id = request.get("id")
    try:
        action = request.get("action")
        if action not in ACTIONS:
            raise ValueError(f"unknown action: {action}")
        result = await ACTIONS[action](request.get("params") or {})
        response = {"id": req_id, "ok": True, "result": result}
    except Exception as exc:
        response = {"id": req_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(response), flush=True)


async def main() -> None:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    reaper_task = asyncio.create_task(idle_reaper())
    stop_task = asyncio.create_task(stop_event.wait())
    try:
        while not stop_event.is_set():
            read_task = asyncio.create_task(reader.readline())
            done, _ = await asyncio.wait(
                {read_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if stop_task in done:
                read_task.cancel()
                break
            line = read_task.result()
            if not line:
                break
            stripped = line.decode("utf-8", errors="replace").strip()
            if stripped:
                await handle(stripped)
    finally:
        stop_task.cancel()
        reaper_task.cancel()
        await close_all_sessions()


if __name__ == "__main__":
    asyncio.run(main())
