# Research MCP Service

A new, self-contained project for a hosted research tool service used by a small, approved group, with private environments for each person.

**Status: private single-user authenticated MCP prototype with `health` and opt-in `search`. No multi-user routing, page-reading or browser tools are exposed yet. Do not expose this application publicly.**

## Boundaries

- This repository owns its code. It does not import, mount, symlink, or execute code from the original personal tool project.
- Dependencies are ordinary third-party packages declared in `pyproject.toml` and resolved in `uv.lock`.
- No personal credentials, caches, databases, browser profiles, agent configurations, or Git history were copied.
- The original project and its running services are not part of this deployment.
- Nothing is provisioned or started automatically by cloning/installing this project.

See [DESIGN.md](DESIGN.md) for the security model, first implementation steps, and release gates. See [ORIGIN.md](ORIGIN.md) for the copied source revision and license attribution.

## Included today

- Research engine: search, page reading, document conversion, storage and RSS.
- Chromium/Camoufox interactive controller source, not yet exposed remotely.
- Cache retention/pinning implementation; service-side maintenance orchestration is still to be designed.
- Offline tests for the copied engine and repository isolation boundaries.
- A locked Python environment, Docker build, and a private per-user backend Compose skeleton.

## Private MCP connectivity test

Uses the official Python MCP SDK, pinned to `mcp==2.3.0`, with Streamable HTTP at `/mcp`. No OAuth or extra custom headers are needed for this single-user test.

```bash
uv sync --locked --no-dev
# Use this machine's Tailscale IPv4 address, or leave --host out for loopback.
python3 scripts/init_mcp.py --host 100.x.y.z --port 8766
uv run --locked --env-file .env.mcp python -m research_mcp_service.server
```

Replace `100.x.y.z` with the real address. Setup creates a random token in `.secrets/mcp-token` and private `.env.mcp`; both are Git-ignored and excluded from Docker context. Setup will not overwrite an existing configuration. The endpoint process requires a private token file and refuses wildcard/public-IP binds. It starts in health-only mode unless search is explicitly enabled below. It never starts backend containers itself.

In an MCP client that can directly reach this host over Tailscale:

- Transport: **Streamable HTTP**.
- URL: `http://YOUR_TAILSCALE_IP:8766/mcp`.
- Bearer-token environment variable: `RESEARCH_MCP_TOKEN`.
- Set that variable on the **client machine** to the contents of the server's private token file, via a secure transfer. Supply the raw token, not the `Bearer ` prefix. Do not paste secrets into chat or commit them.
- No extra headers. If the client lacks a bearer-token setting, use `Authorization: Bearer <token>` through its protected configuration instead.

A macOS app launched from Finder may not inherit variables exported in a terminal. Ensure the client process actually receives `RESEARCH_MCP_TOKEN`; exporting it only on the server does not configure the client.

HTTP here relies on Tailscale's encrypted network path; it is not a public HTTPS deployment. Tailscale ACLs must allow the client to reach the selected port. A hosted connector running outside the Tailnet cannot use this private URL merely because its UI is on your Mac.

The `health` tool reports MCP connectivity and whether search is enabled, **not** search-provider health. Missing/invalid tokens receive 401; Host/Origin checks stay enabled; requests are limited to 64 KiB and 32 concurrent connections. Stateless transport avoids shared mutable MCP sessions at this stage. No browser/storage state or user routing is exposed. Run it in the foreground for development, or manage it explicitly with a PID/log; no boot service is installed. Rotate the token by replacing the private file and restarting the process.

## Enable independent web search

Only a dedicated SearXNG container is needed for this stage—no Redis, MinIO, browser worker, or existing personal gateway. The copied search implementation is maintained in this repository. In `auto` mode it uses this project's SearXNG instance first, then DDGS on an error or zero usable results. Usable `degraded` SearXNG results do not trigger fallback.

```bash
python3 scripts/init_search.py
# Starts this project's search-only stack on loopback port 18080.
docker compose --env-file .env.search -f compose.search.yml up -d --wait
```

Add these non-secret settings to the private `.env.mcp`, then restart the MCP process:

```dotenv
MCP_ENABLE_SEARCH=true
SEARXNG_URL=http://127.0.0.1:18080
```

`init_search.py` creates a mode-0600 `.env.search` with a fresh SearXNG secret; it refuses to overwrite an existing file. `--port` can select a different free loopback port; keep `SEARXNG_URL` in sync. The default Compose project name is `research-mcp-search-dev`, with its own network, no persistent volumes, and no reference to another application's services. Do not override its project name to an existing stack. This is a single-user development setup, not automated tenant provisioning.

Search parameters:

| Parameter | Values |
| --- | --- |
| `query` | 1–2,000 characters |
| `limit` | 1–50; default 5 |
| `freshness` | `any`, `day`, `week`, `month`, `year` |
| `page` | 1–10 |
| `language` | Optional language tag, e.g. `en` or `fr-FR` |
| `include_domains`, `exclude_domains` | Up to 10 plain domains each; normalized and validated |
| `provider` | `auto` (default), `searxng`, or `ddgs` |
| `diagnostics` | `false` (default); set `true` for troubleshooting |

Domain filters match the specified host and its subdomains, not similarly named domains. Multiple included domains are OR alternatives; exclusions take precedence. Filtering is also enforced on returned results. Unlike the original copied implementation, this avoids requiring a result to satisfy several independent `site:` restrictions.

Normal responses show the query, results with sources and returned count. Successful searches are not labelled `degraded`. A short note identifies fallback use, and empty/failed searches have distinct plain-language messages. Material limitations (such as language not being enforced or output being shortened) remain visible.

Set `diagnostics=true` to include a nested `diagnostics` object with provider/status, engine failures and ordered `attempts` history—including a failed primary when fallback succeeds. Per-result engine metadata is also included in this mode. Internal `degraded` status describes partial engine availability, not result quality. DDGS engine provenance is unavailable, so its `engines` arrays are empty rather than claiming configured backends all produced each result.

This is general web search; a news-search mode is deliberately not supported. Freshness, pagination and language depend on upstream support. Pages can overlap or change between calls; there is no cross-page/session deduplication guarantee. Publication dates are returned only when supplied as parseable upstream metadata; dates mentioned in snippets are not assumed to be publication dates. In particular, DDGS uses the configured region (`DDGS_REGION`, default `us-en`); the language parameter is not independently enforced there. Results can be fewer than requested after filtering or upstream limits. There is no relevance reranker or claim of guaranteed search accuracy.

Typical snippets are retained; exceptional titles/snippets are capped at 500/4,000 characters, and the response is bounded to about 500 KB. The returned count and a plain-language note make limits visible by default; diagnostic mode also exposes `truncation` and `requested_limit`. Unsupported or oversized URLs are omitted, never silently shortened into broken links. Returned text is untrusted; queries are sent to external engines, so do not submit secrets. Search does not fetch result pages or save them to storage.

At most two searches execute concurrently in this single MCP process; additional calls receive a retryable busy tool error rather than queueing indefinitely. Each call has a 60-second overall deadline including startup, primary and fallback. Provider calls run in a short-lived process; timeouts and cancellations kill/reap it before releasing capacity, including DDGS's blocking thread workers. This uses Linux process groups and adds small per-call startup overhead. Provider errors are reported without internal URLs or exception details. Restart/reconnect or refresh tools in the client after enabling search. This does not rotate the MCP token or change its URL.

```bash
# Inspect/stop only this project's search backend:
docker compose --env-file .env.search -f compose.search.yml ps
docker compose --env-file .env.search -f compose.search.yml stop
```

The container restarts with Docker (`unless-stopped`); the host MCP development process still has no boot service. Stopping SearXNG while leaving MCP running makes `auto` searches try DDGS; explicit `searxng` searches report unavailable. `health` remains available.

## Local development checks

Python 3.12+ and `uv`:

```bash
uv sync --locked --no-dev
uv run python -m unittest discover -s tests -v
```

These tests include in-process MCP initialization, tool discovery/calls, bearer authentication and HTTP security checks. They do not start Redis, MinIO, SearXNG, browsers, listening sockets, or live model/API calls. Browser binaries are not needed for the offline tests. The Docker build installs Chromium and Camoufox explicitly; do not install extra browsers on the host unless developing the standalone controller.

The full `docker-compose.yml` (distinct from the search-only `compose.search.yml`) describes ONE private user's future backend, not the shared MCP entry point. It publishes no host ports. It requires an administrator-provided tenant ID and unique storage/SearXNG secrets. See `.env.example`; do not reuse credentials from another deployment. The `.env` file is not created by installation.

Different `TENANT_ID` values produce distinct Compose project networks and data volumes when managed from separate tenant configuration directories. Do not override `COMPOSE_PROJECT_NAME` or use `docker compose -p` to point at an existing deployment. Automated provisioning, safe tenant-ID validation, and HTTP access are not implemented yet.

**A separate Compose network is not sufficient protection against malicious URLs or a compromised browser. Network egress enforcement and browser isolation are public-deployment blockers.**

## License

[MIT](LICENSE). Copied notices are retained. Third-party dependencies retain their own licenses.
