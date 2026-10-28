# Private development deployment

## Deployed release 283b6f2 — no deletion or scheduling enabled

Control/worker source layers and host MCP were updated after matching dependency manifest/lock hashes against the prior images. Rollback images end in pre-283b6f2. This deployment retains its internal TCP control connection; it was not migrated to the fresh-server socket overlay or a boot service.

119 offline tests pass. All live probes passed: 34 tools, search → acquisition, page storage/retrieval, heading lookup, artifact/RSS-preview fields, Chromium navigation and text/element waits, screenshot-limit fallback, unsupported-format errors and 58 NASA PDF links. Deployed retention completed a dry run (55 documents, 5 RSS entries, 110 artifacts / 17,471,745 bytes; zero eligible deletions). The host guard refused running control, and the deployed container refused unguarded apply before storage access. No destructive apply, pin change or automatic cleanup was performed. Probe browser sessions were closed.

Logs: .state/deploy-283b6f2.log, .state/check-283b6f2.log, .state/tests-deploy-283b6f2.log. Current source snapshots:
- MCP/worker: sha256:4dd49625eb19f45cb51a3ba89938a044aa8e3f384513cc07691999f44989b464
- Control: sha256:b30c27a23c9b6928b4d3bbfe139ad6f22893552b5598015889db26be9fd63b11

### Retention integration

scripts/retention.py runs the existing retention engine inside a temporary control-image process against this project's storage. It supports development and fresh-server Compose layouts and strips shell project/config overrides. Dry run remains the default; pin operations are explicit. Apply requires an updated control image plus --writers-stopped, refuses absent/non-exited control, and rechecks stopped state after acquiring the maintenance lock. Apply failure after deletion begins retains the lock for explicit recovery; successful completion releases it. No automatic service stopping/restarting or unlocking is added.

119 offline tests pass, including current-state refusal, one-off-container handling, both layouts, locked handshake refusal/success and failure-lock retention. A live read-only control check correctly refused the running service. The host launcher successfully ran the unchanged inventory code in the existing image: 55 documents, 5 RSS entries, 110 objects / 17,471,745 artifact bytes and 1,816,088 Redis used-memory bytes; zero deletion candidates at 30/90 days. Logs: .state/retention-dry-run.log and .state/tests-retention-host.log. These preparation checks did not delete data, change pins or restart services. The apply protocol is now deployed; its refusal checks were exercised live, but destructive execution against real data was not.

## Fresh-server workflow — available, not adopted by this deployment

INSTALL.md and scripts/setup_server.py provide fresh configuration, instance-scoped image builds/startup, foreground MCP execution, status and optional user-systemd unit generation. Initialization refuses existing configuration; there is no automatic install/enable, migration, cleanup or credential rotation. compose.server.yml uses a private host Unix socket for control, retaining internal storage and network-none execution. The old TCP path remains supported for the current deployment.

The initial workflow passed 111 offline tests. Fresh-directory Compose configurations validate; an ephemeral non-root/network-none Docker probe verified authenticated host-to-container Unix socket access. Those preparation checks did not alter existing services. A separate-server cold build and boot-cycle remains unverified. scripts/check_install.py supplies authenticated checks and an optional public-fetch/browser probe without model calls.

## Deployed description clarifications

Removed the undeployed UUID-per-acquisition change, its tests, and the expanded capabilities module/wiring. Cache implementation and capabilities output match deployed fd40a6b again. Document IDs are cache handles, not archives; refresh can replace cached content.

Retained brief workflow, reading/conversion, extraction-limit, browser timing/lifecycle/keyboard and RSS-side-effect descriptions. RSS force_refresh remains a compatibility no-op. No new storage policy is introduced. These descriptions are now deployed; no cache migration or data deletion was performed.

## Previous deployment fd40a6b

Removed obsolete standalone safe-reader/DNS code and direct search/research HTTP routes, their request/response models, the unused render_js option and queued-job status scaffold. Batch responses still report status=done. Removed the direct-HTTP document-conversion fallback and the unimplemented structured strategy placeholder. Production extraction and egress remain intact.

Removed test_contract.py (six tests, covering obsolete route/DNS contracts plus redundant model defaults/validation). Removed the noncompact create_app mode; protocol tests now assert one text representation and no structuredContent. Replaced the legacy research forwarding case with search → unique-URL batch-fetch checks, including empty/error results and missing-search rejection. Retained active security, retention/persistence, extraction and user-feedback regressions. The revised 108-test suite passes offline.

Control/worker source layers and the host MCP process have been updated. Dependency manifest/lock hashes were checked against both prior images before reusing their dependency layers. Rollback image tags end in pre-fd40a6b. No evidence, credentials or volumes were deleted.

Live checks passed: 34 tools, single text representation, search → acquired Python documentation, obsolete-route rejection, heading index, artifact/preview metadata, browser history and condition waits, screenshot-limit observation preservation, unsupported-format errors and 58 NASA PDF annotation links. The first browser-open probe returned browser_reset; no browser processes remained. A separate retry passed the full browser/conversion probe without another service restart. The original failure is preserved in .state/check-fd40a6b.log; its cause is not established.

Deployment/check logs: .state/deploy-fd40a6b.log, .state/check-cleanup-fd40a6b.log, .state/check-fd40a6b-retry.log. Previous source snapshots:
- MCP/worker: sha256:a608d7400499422cbee602aa1be7fa26cb3fc1f89585e44c721ac5abd3da2d40
- Control: sha256:7368f3b1b08a74ad25fef69cdcb14179925d1155948aacc4700ae9cbff15784e

## Previous deployment 5018cf5

Both clarity and navigation/link changes are live. The endpoint advertises 34 tools. Live MCP checks passed: heading index, artifact booleans, preview metadata, back/forward URLs, text/element matching, unmatched-condition timeout retaining observation, oversized screenshot fallback, unsupported-format errors, and the NASA project guide PDF (58 URI/internal link annotations). All 112 offline tests pass. Probe browser session was closed. No storage or feed data was purged.

Deployment reused the prior images' dependency/browser layers after verifying that pyproject.toml and uv.lock hashes matched exactly; only source/controller layers changed. Full source Dockerfiles remain the clean-build path. Rollback images: research-mcp-fetch-worker:pre-5018cf5 and research-mcp-control:pre-5018cf5. Deployment/probe logs: .state/deploy-5018cf5.log and .state/release-5018cf5-check.log.

Captured source snapshots:
- MCP and worker: sha256:537ee44c6620493d4828c71a7b30f6cb73947e8f76cc0e5280d9b83ae8bbfce1
- Control: sha256:86d9d870f2677bf29016740d3b4fde72390f77bcbd0a5c3f9c76b743a58869c8 (does not package the browser controller)

## Navigation/link release behavior

This release includes the clarity changes below plus three additional MCP tools (34 total):

- `browser_wait_for`: literal case-sensitive body text or first CSS-matched visible element, 1–10,000 ms deadline. Reports matched/timed_out with an observation. Existing text can match immediately; it does not prove new results arrived or global page readiness.
- `browser_back` / `browser_forward`: browser history APIs, resulting URL, URL-change flag and navigation outcome. Null browser responses are honestly labelled same_document_or_no_entry; same-document history can also return null. Navigation timeout is distinct from that case.
- Newly converted PDFs include `metadata.extra.pdf_links`: bounded URI annotation destinations and direct internal destination page numbers. Maximum 200 entries and 2,048 URI bytes. Other actions/oversized destinations are counted as omitted; partial/limited/failed states are explicit. No destinations are fetched, and printed/image-based links are not inferred. Annotation failure retains converted text. Existing cached documents are not retroactively rewritten; reconversion is needed to populate this metadata.

112 offline tests pass, including a real generated PDF with URI/internal annotations, MCP dispatch, conditional timeout and null-history handling. Real browser/new-image checks also passed through the live endpoint as recorded above.

## Clarity release behavior

The clarity subset initially passed 108 offline tests and is now included in the deployed release:

- MCP/control/worker health captures a source SHA-256 once at module import. It hashes packaged Python sources and the controller when present, not credentials/configuration. This identifies a startup source snapshot, not a dependency/image digest; components may differ. No dynamic Git HEAD lookup.
- `web_document(include_headings=true, heading_offset=0)` returns 100 ATX heading entries per index page with cleaned-Markdown character offsets. The heading index and targeted lookup share one parser; no extraction or stored data changes.
- Screenshot size/capture failure returns the preceding observation plus a safe warning. This does not guarantee recovery from a crashed browser or whole-worker deadline.
- Preview removes synthetic subscribed_at and declares preview=true/subscription_changed=false; it does not falsely claim an already-subscribed feed is unsubscribed.
- Compact output retains boolean artifact availability fields.
- Unsupported conversion format, conversion exception, HTTP timeout and worker deadline now have distinct codes. Unknown causes remain generic; HTTP 403 is not automatically described as a CAPTCHA/block.

Deployment used coordinated control/worker recreation and MCP restart. Worker recreation expires interactive sessions. Wait-for-condition/history/PDF-link features are included in the combined release above.

## Targeted retrieval and safe errors

The endpoint includes `web_document_find(doc_id, heading=... OR query=..., occurrence=1, max_chars=12000)`. Case-insensitive literal phrase lookup and ATX Markdown heading substring lookup return bounded cached passages with absolute offsets; fenced code headings are ignored. Heading results stop at the next same/higher-level heading, including subsections. No extraction engine or stored original changes. Setext headings and semantic search are not implemented; the existing 2 MiB backend response ceiling still applies.

Worker → gateway → MCP now preserves allowlisted failure codes and upstream HTTP 4xx/5xx status without forwarding exception text or internal addresses. Verified live: heading and repeated-phrase lookup in Python documentation; an HTTP 403 probe returned `Website returned an unsuccessful HTTP status. Upstream HTTP 403. [fetch_bad_status]`. Offline suite: 98 tests. Failures without known HTTP status still cannot report one; full per-attempt error reporting is not claimed.

## Output update

Live MCP startup now uses text-only results (native browser images preserved), without a second structured JSON copy. Batch/research/recent-document tools request metadata only and return compact excerpts even when an older client passes include_markdown=true. Single reads/conversions return at most 12,000 Markdown characters; web_document supports offset/max_chars (maximum 30,000) and explicit continuation metadata. Embedded image data is omitted from presented Markdown, not from cached originals. Offsets refer to that cleaned Markdown.

Verified through the live endpoint: a standard-mode Python documentation batch produced 903 text bytes, no structured copy; cached text retrieval produced two bounded, successive passages; browser_sessions likewise had one representation. Offline suite: 94 tests. This is not a reproduction of the user's 36,000-token multi-source batch.

Remaining: broader failure classification and backend-side pagination for documents exceeding the existing 2 MiB transport ceiling. The current passage implementation fetches the cached document before slicing; it does not yet remove that ceiling. No claims of complete boilerplate removal or client-specific token accounting.


The existing authenticated MCP endpoint `http://100.69.41.80:8766/mcp` now advertises 34 tools. Reconnect the Mac client/new conversation to refresh its tool list. Same client token; no client credential change.

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

Repository cleanup checkpoint: `57ad401` preserves the tested pre-cleanup runtime. Cleanup removed the unused all-in-one Dockerfile/engine services, unimplemented job lookup route/models/storage access, unused Store protocol and imports; README/DESIGN now describe the current runtime rather than historical implementation stages. Retention, tests, explicit smoke checks and private operational evidence remain. Cleanup was initially verified offline and is now included in the deployed source layers. Personal gateway services and all stored data were not changed.
