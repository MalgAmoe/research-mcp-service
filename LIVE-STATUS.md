# Private development deployment

## Prepared clarity release — not deployed

Source changes passed 108 offline tests; live processes/images have not been restarted:

- MCP/control/worker health captures a source SHA-256 once at module import. It hashes packaged Python sources and the controller when present, not credentials/configuration. This identifies a startup source snapshot, not a dependency/image digest; components may differ. No dynamic Git HEAD lookup.
- `web_document(include_headings=true, heading_offset=0)` returns 100 ATX heading entries per index page with cleaned-Markdown character offsets. The heading index and targeted lookup share one parser; no extraction or stored data changes.
- Screenshot size/capture failure returns the preceding observation plus a safe warning. This does not guarantee recovery from a crashed browser or whole-worker deadline.
- Preview removes synthetic subscribed_at and declares preview=true/subscription_changed=false; it does not falsely claim an already-subscribed feed is unsubscribed.
- Compact output retains boolean artifact availability fields.
- Unsupported conversion format, conversion exception, HTTP timeout and worker deadline now have distinct codes. Unknown causes remain generic; HTTP 403 is not automatically described as a CAPTCHA/block.

Deployment requires coordinated control/worker rebuild and MCP restart, followed by live checks. Worker recreation expires interactive sessions. No wait-for-condition/history/PDF-link features are included in this release.

## Targeted retrieval and safe errors

Live endpoint now exposes 31 tools, including `web_document_find(doc_id, heading=... OR query=..., occurrence=1, max_chars=12000)`. Case-insensitive literal phrase lookup and ATX Markdown heading substring lookup return bounded cached passages with absolute offsets; fenced code headings are ignored. Heading results stop at the next same/higher-level heading, including subsections. No extraction engine or stored original changes. Setext headings and semantic search are not implemented; the existing 2 MiB backend response ceiling still applies.

Worker → gateway → MCP now preserves allowlisted failure codes and upstream HTTP 4xx/5xx status without forwarding exception text or internal addresses. Verified live: heading and repeated-phrase lookup in Python documentation; an HTTP 403 probe returned `Website returned an unsuccessful HTTP status. Upstream HTTP 403. [fetch_bad_status]`. Offline suite: 98 tests. Failures without known HTTP status still cannot report one; full per-attempt error reporting is not claimed.

## Output update

Live MCP startup now uses text-only results (native browser images preserved), without a second structured JSON copy. Batch/research/recent-document tools request metadata only and return compact excerpts even when an older client passes include_markdown=true. Single reads/conversions return at most 12,000 Markdown characters; web_document supports offset/max_chars (maximum 30,000) and explicit continuation metadata. Embedded image data is omitted from presented Markdown, not from cached originals. Offsets refer to that cleaned Markdown.

Verified through the live endpoint: a standard-mode Python documentation batch produced 903 text bytes, no structured copy; cached text retrieval produced two bounded, successive passages; browser_sessions likewise had one representation. Offline suite: 94 tests. This is not a reproduction of the user's 36,000-token multi-source batch.

Remaining: broader failure classification and backend-side pagination for documents exceeding the existing 2 MiB transport ceiling. The current passage implementation fetches the cached document before slicing; it does not yet remove that ceiling. No claims of complete boilerplate removal or client-specific token accounting.


The existing authenticated MCP endpoint `http://100.69.41.80:8766/mcp` now advertises 31 tools. Reconnect the Mac client/new conversation to refresh its tool list. Same client token; no client credential change.

Verified through the actual MCP endpoint: tool listing, web_read with Markdown, rss_preview, browser_open and browser_close_all. Prior worker checks cover four reader modes, PDF conversion, interaction, private subresources, public WSS, and cancellation. This is not a public or multi-user production deployment. Inline artifacts remain limited to 256 KiB.

Independent control service: `research-mcp-dev-control-1`, authenticated using `.env.control` / `.secrets/gateway-token`, internal storage network only, read-only worker RPC socket. No browser execution or Internet network on the storage gateway. The unused all-in-one engine profile and Dockerfile have been removed.

Docker does not publish ports for this internal-only network here. The host MCP process currently reaches the inspected control IP `http://172.21.0.4:8000`, stored in `.env.mcp` as MCP_GATEWAY_URL. **After recreating the control container, inspect its address and update that setting before restarting MCP.** Stable discovery remains follow-up work.

Build/start control:

```sh
docker compose --env-file .env.runtime -f docker-compose.yml -f compose.workers.yml -f compose.control.yml --profile workers build control
docker compose --env-file .env.runtime -f docker-compose.yml -f compose.workers.yml -f compose.control.yml --profile workers up -d --wait control
```

MCP remains a development background process, not a boot service. PID/log: `.state/mcp.pid`, `.state/mcp.log`. Startup: `uv run --locked --env-file .env.mcp python -m research_mcp_service.server`.

Research orchestration searches in the MCP process using its existing search backend, then calls isolated batch fetching; the legacy gateway `/research` and direct search routes remain blocked. Gateway transport bounds and worker limits remain in force. End-to-end verification of every tool and gateway-layer disconnect propagation remain follow-up work; do not claim comprehensive coverage from the four live smoke calls.

Repository cleanup checkpoint: `57ad401` preserves the tested pre-cleanup runtime. Cleanup removed the unused all-in-one Dockerfile/engine services, unimplemented job lookup route/models/storage access, unused Store protocol and imports; README/DESIGN now describe the current runtime rather than historical implementation stages. Retention, tests, explicit smoke checks and private operational evidence remain. Cleanup was verified offline without restarting live services; running images still contain the preceding source until a coordinated rebuild. Personal gateway services and all stored data were not changed.
