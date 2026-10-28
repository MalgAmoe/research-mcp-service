# Research MCP Service

Private single-user research service: **34 MCP tools** for search, page reading, document conversion, cached evidence, RSS and interactive Chromium/Camoufox browsing. Streamable HTTP with bearer authentication over loopback/Tailscale. **Not a public or multi-user production service.**

- [LIVE-STATUS.md](LIVE-STATUS.md): current deployment, commands, verified behavior and known limitations.
- [INSTALL.md](INSTALL.md): fresh private-server setup, stable Unix control socket and optional boot service.
- [DESIGN.md](DESIGN.md): runtime boundaries and remaining security work.
- [ORIGIN.md](ORIGIN.md): MIT source attribution. This checkout is independent of the original personal gateway; no shared code mounts, credentials or data.

## Runtime

| Component | Source / deployment |
| --- | --- |
| Host MCP process | `src/research_mcp_service/server.py`, `.env.mcp` |
| Dedicated search | `compose.search.yml`, `.env.search`, loopback port 18080 |
| Private Redis/MinIO | `docker-compose.yml`, `.env.runtime` |
| Network-isolated execution and egress proxy | `compose.workers.yml`, `Dockerfile.worker`, `Dockerfile.egress` |
| Authenticated storage/control gateway | `compose.control.yml`, `Dockerfile.control`, `.env.control` |

The base Compose file starts storage only. The old all-in-one gateway/engine profile and its Dockerfile have been removed. Do not recreate that topology: browsers must not receive storage credentials or join the storage network.

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

Offline tests exercise the production text-only MCP format, search → batch research orchestration, extraction/presentation regressions, storage maintenance and runtime safety boundaries. Legacy standalone-route tests and the noncompact app mode are removed. Tests include protocol calls, subprocesses and local Unix sockets, but do not start the storage stack or real browsers. Explicit live checks are under `scripts/check_*.py`; some open/close browser sessions and fetch public sources. Run them only in a coordinated test window, not during someone else's investigation.

For a fresh server, use `scripts/setup_server.py` as described in INSTALL.md; it creates the complete configuration and keeps the control endpoint stable across container recreation. Do not run it over the existing development configuration.

Older component-level configuration helpers: `scripts/init_mcp.py`, `scripts/init_search.py`, `scripts/init_storage.py`. They refuse to overwrite existing configuration. Full runtime setup additionally requires a private random `GATEWAY_TOKEN` in `.env.control` and the matching mode-0600 `.secrets/gateway-token`. Never copy credentials from another service. See LIVE-STATUS for the existing deployment rather than rerunning initialization.

MCP startup:

```sh
uv run --locked --env-file .env.mcp python -m research_mcp_service.server
```

Clients use the configured Tailnet URL and `Authorization: Bearer <token>` in protected client settings. No OAuth/public deployment yet. Reconnect clients after schema changes. `health` checks MCP connectivity, not backend health. The MCP process is manually managed with `.state/mcp.pid` / `.state/mcp.log`, not installed as a boot service.

Preserve `.env*`, `.secrets/`, `.state/` evidence and Docker data volumes. Never print secrets or use `docker compose down -v` as cleanup. Retention code is retained for deliberate administrator maintenance; no automatic retention is enabled. Do not restart workers while users are testing without coordinating the interruption.

## License

[MIT](LICENSE). Third-party dependencies retain their own licenses.
