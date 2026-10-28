# Hosted research service: initial design

## Goal and scope

A small approved group connects MCP-compatible clients to an HTTPS endpoint. Each authenticated person owns a private research environment. One person may have several concurrent client sessions. No shared document cache, RSS state, storage credentials, browser profiles or cookies across people.

Start with isolated per-person deployments instead of adding tenant checks to every copied database operation. This is an initial design, not a claim that the current engine is safe for untrusted public requests.

## Proposed topology

```text
MCP client sessions
        |
HTTPS / authentication / admission limits
        |
MCP adapter + identity-to-environment routing
        |
        +-- person A: research engine + Redis + MinIO + SearXNG + browser worker
        +-- person B: research engine + Redis + MinIO + SearXNG + browser worker
```

Use Streamable HTTP for MCP. The initial connectivity prototype uses the official Python SDK `mcp==2.3.0`, checked against its installed API and official SDK documentation. It exposes `health` and opt-in `search`, requires a pre-shared bearer token on every HTTP request and binds only to loopback or a Tailscale IPv4 address. Search uses this project's dedicated SearXNG container with DDGS fallback, retains attempt diagnostics behind opt-in `diagnostics=true` (normal output is results and material notes), has a two-call concurrency limit and 60-second deadline, and does not fetch result pages or access storage. Each search runs in a disposable process so cancellation/timeout can terminate blocking provider threads. The MCP interface supports provider selection, domain filters, pagination, language and freshness for general web queries. News search is intentionally out of scope. Pagination may overlap; publication dates are not inferred from snippet text. This is a single-user test, not the production multi-user authentication design.

References: https://github.com/modelcontextprotocol/python-sdk and https://py.sdk.modelcontextprotocol.io/get-started/ .

For the first implementation, prefer separate MCP processes per environment if that reduces the security-critical routing surface. A shared authenticated ingress may route to them. Regardless of process layout, authenticated server-side identity determines the environment: a client-supplied tenant ID is never authority.

SearXNG is private per person initially. Sharing it later is an explicit resource/privacy tradeoff, not the default. Even with separate instances, a common public egress IP can share upstream rate limits.

## Identity and sessions

- Small administrator-maintained allowlist; no anonymous access or open self-signup.
- Choose an authentication flow supported by the intended MCP clients before implementation. Assess standards-based OAuth and an existing identity provider; do not invent a custom password system.
- Validate issuer, audience, expiry and authorization on every connection/request as appropriate. An MCP session ID is not an authentication credential.
- Different clients belonging to the same person can share that person's research cache.
- Browser profiles/cookies default to per-session isolation. Persistent profiles, if introduced, require explicit user ownership and consent.
- Browser handles must be opaque, unguessable, bound to both user and session, and rejected outside their owner context.
- Reconnect, idle expiry, cancellation, revocation and session cleanup need explicit behavior and tests.

## Security boundaries required before public access

1. TLS and authenticated MCP access; no direct public gateway, Redis, MinIO, console or SearXNG ports.
2. Per-person stores, networks and unique secrets. No host directories or Docker socket accessible to request-serving processes.
3. Enforced egress policy for HTTP fetches AND browser traffic, including redirects, DNS changes, subresources and WebSockets. Deny loopback/private/link-local ranges, other tenants, container/host services and cloud metadata. URL string validation alone is insufficient.
4. A restricted browser worker that cannot reach the storage/control network. The copied gateway currently launches browsers in-process; this must change before public deployment.
5. Appropriate sandbox/runtime and non-root execution. Docker separation alone is not a sufficient promise of safety against hostile browser content.
6. Bounded request size, response size, download size, execution time, queue length, per-user/global concurrency and disk usage. Cancellation must release browser slots and processes.
7. Credential redaction; no tokens, private URLs, page contents or browser cookies in ordinary access logs. Explicit policies for debug logs and administrator access.
8. Authenticated administrative provisioning separate from the public tool service. No client input can choose host mounts, Compose files, project names or storage endpoints.

The copied `safe_read_url` checks are useful defense-in-depth but do not protect every reader or provide browser/network isolation. The existing Docker/browser defaults have not passed a public-service security review.

## Runtime foundation in progress

The default `docker-compose.yml` startup is now **storage only**. Gateway and the old full-stack SearXNG require the explicit `engine` profile and must not be started as a shortcut to exposing the new tools. The existing search-only deployment is unchanged.

```bash
python3 scripts/init_storage.py --tenant-id dev  # refuses an existing .env.runtime
# Own random credentials, own project name research-mcp-dev; no host ports.
docker compose --env-file .env.runtime up -d --wait redis minio
```

Redis and MinIO are running on the `internal: true` storage network with separate named volumes. Actual write/read checks passed; their disposable probe key/bucket were removed. Credentials are in private `.env.runtime`, not copied from any other service.

`compose.workers.yml` adds a separate egress service and a credential-free fetch worker. The intended boundary is stronger than relying on browser proxy flags:

- Worker: `network_mode: none`, non-root UID 10001, read-only image, dropped capabilities, bounded memory/PIDs and writable temporary filesystem. It refuses startup with non-loopback network interfaces or storage/control credentials in its environment.
- Egress: independent network, no storage mounts/credentials. An HTTP/CONNECT proxy listens only on a private Unix socket in an own named volume. The worker mounts that socket volume read-only and runs a loopback-to-Unix bridge for HTTP clients and Chromium/Camoufox.
- Policy: only public IPv4 destinations on ports 80/443. Every new connection resolves and validates all A answers, then dials the selected numeric IP without resolving again. Private, loopback, link-local, Tailnet/CGNAT, special ranges and Azure's platform virtual IP are denied. IPv6 is deliberately unsupported initially.
- Worker RPC: separate Unix socket volume, not a TCP listener; future gateway mount is read-only. The worker receives no Redis/MinIO credentials and has no network route to their network.
- Reads, conversions and feed parsing use disposable child process groups with two admission slots, a 75-second job deadline, body/result bounds, disconnect cancellation and group cleanup. Persistent browser control is supervised separately, with one action at a time, four sessions, 128-bit handles, idle expiry and whole-controller reset after timeout/transport failure. Browser sessions are not silently evicted to make room.

Real-container egress check passed: direct network connections unavailable; ten private/special-address requests explicitly rejected through the proxy; public HTTP and HTTPS worked. The initial example.org probe was blocked by Cloudflare (1010), not our policy; the successful check uses Python documentation. Tests cover mixed DNS answers, numeric-address pinning, invalid targets, cancellation, protocol dispatch and worker routing. Separate live worker checks subsequently passed for light/standard/Chromium/Camoufox reads of Python documentation, DOE PDF conversion, and a Python blog feed (50 entries). Private-address reads failed in HTTP, Chromium and Camoufox. Native browser observation/screenshot/text/find/scroll/wait, search form typing/submission, result clicking, navigation and session cleanup passed through worker RPC. Additional live checks passed for both Chromium and Camoufox: navigation and image/script/frame/fetch/WebSocket requests made zero hits on a worker-local HTTP fixture on port 80, while public WSS echo worked. The fixture document was locally fulfilled to establish the same origin, avoiding mixed-content/CSP/PNA false passes. Cancelling both interactive opens and disposable reads left no surviving browser processes in all four cases. Evidence: `.state/browser-egress.log` and `.state/worker-cancellation.log`; reproducible scripts: `scripts/check_browser_egress.py` and `scripts/check_worker_cancellation.py`. This does **not** prove renderer-exploit containment or multi-user isolation.

```bash
docker compose --env-file .env.runtime -f docker-compose.yml -f compose.workers.yml build egress fetch-worker
docker compose --env-file .env.runtime -f docker-compose.yml -f compose.workers.yml up -d --wait fetch-worker
docker compose --env-file .env.runtime -f docker-compose.yml -f compose.workers.yml run --rm --no-deps egress-check
```

The worker image is built from this checkout with its own Chromium/Camoufox assets (no personal browser mounts), and a cached source refresh was applied before live checks. Storage, egress and fetch-worker containers are running under `research-mcp-dev`. Initial build evidence: `.state/worker-start.log`; source-refresh build: `.state/workers-refresh.log`; live evidence: `.state/worker-live.log`; egress evidence: `.state/egress-check.log`. The first live suite's RSS URL returned 404; the corrected official blog feed succeeded separately and `scripts/check_worker.py` now uses it. Re-run the full suite after further source changes; never assume an already-built image contains them.

Live smoke command (no host code/data mounts):

```bash
docker compose --env-file .env.runtime -f docker-compose.yml -f compose.workers.yml exec -T fetch-worker python < scripts/check_worker.py
```

Reader, conversion and RSS service functions now route through `WorkerClient` when `WORKER_SOCKET` is configured; failures never fall back to local fetching. Standalone-library behavior remains available without that setting, so the eventual hosted gateway entry point must require it. Browser control supports only headless sessions, validates HTTP(S) navigation, reports session/screenshot limits, refreshes unique refs on each observation and resets all owned sessions on controller failure. These changes are confined to this repository.

Remaining before enabling tools: finish live worker checks (all reader modes, PDF/RSS, interaction, blocked subresources/redirects, cancellation); connect the gateway via worker RPC with authenticated/limited control ingress; orchestrate research using the existing MCP search rather than giving the storage gateway arbitrary outbound access; support large artifact retrieval; run real MCP calls. The live MCP endpoint still exposes only health/search. No public-deployment claim is made.

## Data lifecycle

Carry forward the copied retention defaults: 30-day documents, 90-day RSS entries, explicit pinning, subscriptions preserved. Keep state per person. Pins preserve a document ID/version, not every future version of a URL.

The copied CLI assumes a trusted local administrator and a paused gateway. Hosted cleanup must coordinate a per-user maintenance window/lock and reject new jobs while draining old ones. Do not introduce independent object-store lifecycle rules that bypass pinning.

Add per-person storage accounting and a defined quota-exceeded response. Pins and backups are not an excuse for unbounded disk use. Backups need access controls, off-host encrypted copies, retention and tested restoration. Account deletion must define treatment of live data, browser profiles, logs and backup expiry.

## First implementation sequence

1. Verify current official MCP transport/auth docs and identify the clients to support. Select authentication and a pinned SDK.
2. Implement a minimal authenticated MCP adapter for one person's backend; begin with search and read-only document retrieval. Use fake backends for protocol/auth tests.
3. Add independent second-person environments and prove that credentials, data, sessions and IDs cannot cross boundaries.
4. Build restricted fetch/browser workers, egress controls, bounded concurrency and session ownership. Only then expose tools that fetch arbitrary URLs or control browsers.
5. Add administrator provisioning, quotas, retention scheduling, backup/restore and a small staging deployment.
6. Conduct the release-gate tests before admitting real users or exposing a public endpoint.

## Release gates

- Build from a source-only checkout on an independent environment without the original repository, its venv, caches, browser binaries or credentials.
- Unauthorized, expired and revoked credentials fail; user A cannot access user B's documents, artifacts, RSS or browser handles.
- Redirect/DNS/subresource tests prove prohibited network destinations are unreachable, not merely filtered in one API path.
- Several sessions per person cannot exceed aggregate limits; overload/cancellation/timeouts do not leak workers or memory.
- Retention preserves pinned/shared objects; restore and account removal are tested on disposable data.
- No storage/admin ports are publicly exposed. Credentials and private content are absent from images and logs.
- No deployment or test modifies the original personal tool service.

## Not yet implemented

Live page-reading/document/RSS/browser MCP deployment, multi-user authentication and provisioning/routing, remotely owned browser sessions, enforced egress, worker-side aggregate quotas/deadlines, hosted maintenance, and production deployment. The full Compose file remains a private backend skeleton. The single-user MCP entry point connects only to the separately provisioned search-only stack in compose.search.yml, not the full backend or personal tool deployment.

The adapter layer now implements 15 web/document/RSS and 13 browser tool contracts, registered only through explicit backend injection into `create_app()`. A bounded fixed-origin gateway client and Unix worker transport are included; wiring the live MCP process through authenticated gateway ingress is still pending. Offline MCP and mock-HTTP tests verify schemas, dispatch, authentication, bounds and screenshot serialization, not runtime isolation. See README.md for the inventory and limits. No startup flags activate these adapters yet, and no live backend was provisioned by this step.

Before activation, complete live verification of fetch/browser egress and worker-side deadlines, cancellation and concurrency; verify owner-scoped browser handles and reconnect/expiry behavior; add authenticated large-artifact retrieval beyond the current inline limit. URL syntax validation and adapter timeouts are not substitutes for those controls.
