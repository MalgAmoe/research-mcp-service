# Local Scrapling integration

Source branch: `test/scrapling-acquisition`. Local MCP is the 40-tool test deployment; VPS remains on the published 35-tool RSS candidate. The fresh-image candidate `scrapling-20261108-223033-e9c05b2` is published; pins and update instructions are in [INSTALL.md](INSTALL.md). VPS promotion has not occurred. Current image digests: [LIVE-STATUS.md](LIVE-STATUS.md).

## Runtime

- Scrapling 0.5.1 / Patchright 1.64.4 handle standard Chromium sessions and rendered HTML acquisition inside the existing isolated worker.
- Playwright is pinned to 1.62.0 for Camoufox 158.0.1 beta.41 compatibility. Do not upgrade it without real Camoufox route/proxy checks.
- Light HTTP/Trafilatura, structured Markdown, Camoufox, search, document conversion, RSS, storage and restricted egress are retained.
- Existing eN observations, tool contracts, history receipts and lifecycle policies remain our adapters; Scrapling ARIA refs are not exposed.
- Chromium BFCache is disabled (`--disable-back-forward-cache`) so history waits receive the expected lifecycle event. Checks require completed history receipts, not merely changed URLs.
- Individual actions and chains share `perform_action`, preserving their respective waits, timeouts and failure behavior. Legacy append typing, clear-then-fill events and page-level keyboard presses remain intact. Left/right scrolling changes only the horizontal axis; up/down changes only the vertical axis. Session managers own browser shutdown; there is no raw-browser fallback.
- Observation and standalone screenshots share capture. Failed observation screenshots preserve the preceding page evidence. Diagnostics retain counters, not unused console/failure payloads.

## Additional tools

- `browser_extract`: CSS-targeted HTML/text/structured Markdown without navigation; optional open Shadow DOM serialization. Total output <=30,000 characters and <=50 matches. Does not save evidence.
- `browser_network_requests`: completed API/error traffic in standard/Scrapling sessions, with literal URL filtering and pagination.
- `browser_network_response`: saved text passages without replaying requests. No request bodies or credential headers; response bodies may contain sensitive website data. History is ephemeral, not evidence storage.
- `browser_actions`: <=20 steps / <=48 KB serialized input; click/hover/fill/press/check/uncheck/select/drag/scroll/wait, then observation. The whole chain is validated first; partial effects are not rolled back. Inspect `actions.failed_action` before retrying.
- `browser_screenshot`: viewport/full-page/element PNG as a native MCP image, <=1 MiB.

Camoufox supports extraction/actions/screenshots but not network-history tools. No arbitrary JavaScript, host paths, executable/proxy overrides, remote CDP, saved logins, adaptive recovery or crawler jobs are exposed.

## Boundaries and limits

Same non-root, read-only, network-none worker and fixed loopback proxy. Chromium context fixes proxy bypass to `<-loopback>`, blocks service workers and disables downloads; WebRTC proxy enforcement is enabled. Public-only DNS/dial rules remain in unchanged egress. Session caps/idle expiry, serialization, cancellation/reset and output bounds remain in our service. A worker timeout can expire all browser sessions.

Upstream callback exceptions can be swallowed; callers require valid captured page/HTML and fail otherwise. Shadow serialization imports one pinned upstream implementation constant; browser ownership uses public session/fetch/page_setup APIs.

Scrapling retains <=1,000 network entries, <=1 MiB per supported text response and <=20 MiB retained response bytes. These are not total browser-memory or in-flight capture limits. Completed entries can be missing at navigation/closure. Serialized Shadow DOM covers open roots, not iframe traversal. HTML-based extraction is not equivalent to visible `body.innerText`.

## Known client limitations

- `web_read` rejects direct data-file URLs such as `.json`; its current public error can be a generic backend failure rather than an explanation of this restriction. It is not a general JSON API fetcher. JSON responses loaded by browser pages can be inspected with the network-history tools.
- Hermes currently counts application errors, including website 403s, toward a server-wide circuit breaker: three consecutive errors can pause all tools for about 60 seconds, including browser fallback. That pause is client-side, not MCP server rate-limiting. Restarting Hermes clears its volatile state but does not fix the behavior. Avoid blind repeated calls; neither this guard nor the generic error handling has been changed.

## Build and checks

```sh
uv sync --locked --no-dev
.venv/bin/python -m unittest discover -s tests -q
docker build -f Dockerfile.worker -t research-mcp-local:scrapling-worker .
docker build -f Dockerfile.app -t research-mcp-local:scrapling-app .
# Disposable offline fixture: no storage, credentials or egress.
docker run --rm -i --init --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --memory 2g --pids-limit 512 \
  --tmpfs /tmp:size=536870912,mode=1777 \
  research-mcp-local:scrapling-worker python - < scripts/check_scrapling.py
# Live endpoint: opens/closes only its own probe sessions.
.venv/bin/python scripts/check_scrapling_mcp.py --output .state/local-maintenance/mcp.json
# Public-page history readiness in both profiles.
docker compose --env-file .env.runtime -f compose.deploy.yml exec -T fetch-worker \
  python - < scripts/check_browser_history.py
# Real private-navigation/subresource/WebSocket denial checks.
docker compose --env-file .env.runtime -f compose.deploy.yml exec -T fetch-worker \
  python - < scripts/check_browser_egress.py
```

158 host tests pass; the worker suite passes with two Docker-CLI-only skips. The 56-call endpoint suite, offline fixtures, 24 history traversals, proxy/WebSocket checks and cancellation checks pass. Fresh candidate image builds are verified separately as recorded in INSTALL.md. No full fresh Compose installation, sustained soak or actual-host reboot has been verified for this trial.

## Operations and rollback

Current build/test receipts and rollback configuration: `.state/local-maintenance/`. History-fix receipts: `.state/scrapling-cleanup/`. Initial build/deployment receipts and full rollback: `.state/scrapling-local/`.

- `bash .state/local-maintenance/rollback.sh` restores the preceding 40-tool deployment with the history fix intact.
- `bash .state/scrapling-local/rollback.sh` restores the published 35-tool stack.

Preserve `.env*`, `.secrets/` and data volumes. Recreating app/control/worker expires browser sessions; never use `down -v`. Reconnect clients when schemas change.
