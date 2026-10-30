# Research MCP Service

Research service with **34 MCP tools** for search, page reading, document conversion, cached evidence, RSS and interactive Chromium/Camoufox browsing. Streamable HTTP with bearer authentication over loopback/Tailscale or HTTPS. **One owner per independent deployment**; clients sharing a token share its cache and browser pool. No OAuth or shared-application multi-user tenancy.

- [LIVE-STATUS.md](LIVE-STATUS.md): current deployment, commands, verified behavior and known limitations.
- [INSTALL.md](INSTALL.md): image-only Compose installation, verified image digests, startup and maintenance.
- [HTTPS.md](HTTPS.md): optional public TLS and separate endpoint paths.
- [DESIGN.md](DESIGN.md): runtime boundaries and remaining security work.
- [ORIGIN.md](ORIGIN.md): MIT source attribution. This checkout is independent of the original personal gateway; no shared code mounts, credentials or data.

## Runtime

| Component | Source / deployment |
| --- | --- |
| MCP frontend, control and one-time credential setup | Shared app image built from `Dockerfile.control`, separate containers/permissions |
| Chromium/Camoufox and document execution | Worker image built from `Dockerfile.worker`, network-none |
| Restricted web-access proxy | Egress image built from `Dockerfile.egress` |
| Dedicated search | Pinned upstream SearXNG image |
| Private metadata and artifacts | Pinned upstream Redis and SeaweedFS images |

**`compose.deploy.yml` is the default deployment entry point.** `scripts/setup_server.py` initializes private configuration and operates the stack using published images from `malgamoe/mcps`; no host application virtualenv or application systemd unit is needed. Only MCP publishes a port. Browsers receive no storage credentials or storage-network access; no application has Docker access.

Follow [INSTALL.md](INSTALL.md) for a fresh administrator-owned deployment. The VPS uses this layout. The existing local installation still uses the older host-runtime layout described in LIVE-STATUS.md; do not initialize over it.

## Tools and behavior

Usual workflow: **search → fetch selected sources → retrieve saved passages**; use interactive browsing when needed. Successful calls do not certify extraction completeness or fidelity.

- Search: explicit SearXNG/DDGS provider, automatic fallback, domains, page, freshness and language; optional diagnostics. Upstream pagination may overlap; language/freshness are not guarantees and missing publication dates are not inferred from snippets.
- Reading: `light` HTTP/Trafilatura; `standard` Chromium/structured Markdown; `browser` Chromium or Camoufox; `auto` fallback. Stealth requires `strategy=browser` and `browser_profile=stealth`; it does not guarantee access past blocking.
- Documents: PDF, DOCX, PPTX, TXT, Markdown and HTML text conversion; saved originals and extracted text. Text extraction is not complete document/layout understanding.
- Retrieval: bounded cached passages, continuation offsets, an optional heading index, and `web_document_find` by literal phrase or ATX Markdown heading. Original evidence remains unchanged.
- Batch/research: compact source summaries and separate failures. Full text is retrieved separately, even if an older client requests full Markdown in a batch.
- RSS: preview, subscribe/list, fetch, cached entries and read-state updates. Unsubscribe is not implemented.
- Browser: open/observe/navigate/click/type/press/scroll/wait/text/find/close/list, bounded text/element waits, explicit back/forward, and native image screenshots with observation-preserving failure warnings. Four ephemeral sessions per owner worker; failures/restarts can expire them.

Live MCP uses one text representation, not duplicate text/structured JSON. Documents default to 12,000-character passages, at most 30,000 per retrieval. Backend JSON is limited to 2 MiB; passage lookup currently retrieves the whole cached document before slicing, so this ceiling still applies. Inline artifacts are limited to 256 KiB; screenshots to 1 MiB. Batches accept 15 URLs and a concurrency argument of 1–10; actual isolated fetch execution has two slots. These are limits, not throughput promises.

Document IDs are cache handles, not archival guarantees: refreshing may replace cached content. URL lookup selects the last saved document; page cache reuse depends on strategy/profile.

## Development and operations

```sh
uv sync --locked --no-dev
.venv/bin/python -m unittest discover -s tests -q
```

Offline tests exercise the production text-only MCP format, search → batch research orchestration, extraction/presentation regressions, storage maintenance and runtime safety boundaries. Tests include protocol calls, subprocesses and local Unix sockets, but do not start the storage stack or real browsers. Explicit live checks are under `scripts/check_*.py`; some open/close browser sessions and fetch public sources. Run them only in a coordinated test window, not during someone else's investigation.

The published images passed two-owner deployment, browser, isolation and reboot checks in a disposable Ubuntu VM, followed by a clean VPS installation. See LIVE-STATUS.md for exact verification and limits; these checks are not a production soak.

Clients use their configured MCP URL and `Authorization: Bearer <token>` in protected client settings. Reconnect after schema changes. `health` checks MCP connectivity, not backend health. Never copy credentials between independent deployments.

### Legacy local compatibility

The older Compose overlays, `scripts/init_{mcp,search,storage}.py` and their compatibility tests remain while the existing local host-runtime installation is still in use. They are **not the fresh-install workflow**. Its commands and active PID/log locations are confined to LIVE-STATUS.md. Removing that machinery requires a separately coordinated local migration; repository cleanup must not break the running service.

Preserve `.env*`, `.secrets/`, `.state/` evidence and Docker data volumes. Never print secrets or use `docker compose down -v` as cleanup. Manual cache retention is available through `python3 scripts/retention.py` (read-only dry run by default); see INSTALL.md for pinning, stopped-writer checks and failure recovery. No automatic retention is enabled. Do not restart workers while users are testing without coordinating the interruption.

## License

[MIT](LICENSE). Third-party dependencies retain their own licenses.
