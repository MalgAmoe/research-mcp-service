# Deployment status

Setup/update/backup: [INSTALL.md](INSTALL.md). TLS: [HTTPS.md](HTTPS.md). Runtime boundaries: [DESIGN.md](DESIGN.md). Local tool behavior and checks: [SCRAPLING-LOCAL.md](SCRAPLING-LOCAL.md).

## Running deployments

Both use `compose.deploy.yml`, separate credentials/data, Redis and SeaweedFS 4.51. Only MCP publishes a port; browser execution remains in a credential-free, network-none worker behind restricted egress. Neither shares resources with the original personal gateway.

| Deployment | Compose identity | MCP access | Status |
|---|---|---|---|
| Local test | `local-v2` | `http://100.69.41.80:8766/mcp`, existing token | 40-tool Scrapling trial, branch `test/scrapling-acquisition` |
| VPS production | `contabo-v2` | Existing HTTPS endpoint/token; backend loopback | 40-tool `capacity-20261109` update |

Local-only image repository: `research-mcp-local` (not published). References in `.env.runtime` are digest-pinned:

| Component | SHA-256 |
|---|---|
| App/control | `28aaba22373dbab40a7c34de30883e40a1f8af7297d44d629da978f3a5ea7d42` |
| Worker | `047c3f08e529bf23fdecfa069412e9b0aee14b80d9974d5668ca3caabf3099a8` |

VPS images (`malgamoe/mcps`); egress is also retained locally:

| Component | SHA-256 |
|---|---|
| App | `2d71b5eaa3a608a9708d53f868032d07728c48d5d0dd0f082fcacfaffb1cabfb` |
| Worker | `477ffa84c57ad1fed3678f5d69104f4d7351fad3ab60dbc7cfecb7bded0bad9c` |
| Egress | `4506a720dd51235fd44e2a1e01022079a03e49202da283d1eee473818c3e49b3` |

## VPS capacity update

`capacity-20261109` app/worker images are published and active on the VPS.
Worker RAM is 3 GiB / 2 CPU cores; frontend/control/worker acquisition admission
is 3. Interactive browser commands remain serialized. Control emits structured
queue/duration/outcome logs; see INSTALL.md. Host suite: 162 passes; packaged
app/worker: 162 each, two skips. Authenticated 40-tool checks and live search,
read/storage/readback, Chromium and Camoufox checks pass. Three simultaneous
uncached light reads via MCP completed ready in 11.41 seconds wall time with
0 ms control-admission queue wait each and no worker OOM/memory-limit events.
This is a small functional concurrency check, not a sustained capacity benchmark.
Egress, search,
Redis/S3, credentials, TLS and local running deployment were not changed.
Rollback references/receipts: private `.state/CONTABO.md`.

## Published release and VPS verification

`scrapling-20261108-223033-e9c05b2` is published in `malgamoe/mcps` for Linux amd64, from commit `e9c05b2`. Fresh app/worker/egress builds passed packaged suites, browser/RPC/MCP canaries, isolation and cancellation checks, plus anonymous registry manifest checks and digest pulls (local layers cached). Exact digests, verification limits and update instructions: [INSTALL.md](INSTALL.md). Private publication receipts: `.state/scrapling-release/public-images.json` and `progress.log`.

VPS promotion passed 56 real MCP calls: search, four reader modes, storage/readback, both browsers, extraction, actions, network inspection, screenshots and history. Public trusted TLS, anonymous 401 and authenticated 40-tool discovery passed; original saved-document IDs remained retrievable through HTTPS. Persistent Redis records and S3 object hashes were preserved before acquisition probes; credentials and non-image configuration were unchanged. Only app/control and worker were recreated. Redis/S3 were stopped briefly for consistent backups; their container IDs, egress and search were retained. Local remains unchanged. VPS backup/receipts and rollback references: private `.state/CONTABO.md`.

## Local verification

- Scrapling 0.5.1 / Patchright 1.64.4; Playwright pinned to 1.62.0 for Camoufox interception compatibility. Chromium BFCache is disabled for reliable history readiness.
- 158 host tests pass. The worker suite passes with two Docker-CLI-only skips.
- Real offline fixtures pass in both browsers: forms, refs, action chains, extraction, Shadow DOM, screenshots, history, routing, manager-owned shutdown and scrolling on each axis.
- 56 authenticated MCP calls pass, including append typing and completed history receipts; the endpoint still exposes 40 tools.
- Both profiles pass private-navigation/subresource/WebSocket denial, public WSS and cancellation without surviving browser processes.
- Only app/control/worker were recreated. Credentials, Redis/S3/search/egress containers and data volumes were preserved. These receipts describe the local deployment; VPS promotion is verified separately above.

## Operations

Run from this checkout using the existing local Docker access:

```sh
docker compose --env-file .env.runtime -f compose.deploy.yml ps
docker compose --env-file .env.runtime -f compose.deploy.yml logs --tail 100 mcp control fetch-worker
docker compose --env-file .env.runtime -f compose.deploy.yml exec -T mcp python -m research_mcp_service.container_check
python3 scripts/retention.py  # read-only inventory
# After backing up configuration and setting matching image references:
# Coordinate downtime and browser-session loss before recreating services.
docker compose --env-file .env.runtime -f compose.deploy.yml up -d --no-deps --pull never --wait --wait-timeout 180 fetch-worker control mcp
```

Preserve private `.env*`, `.secrets/`, `.state/` and data volumes. Do not initialize over an existing deployment or use `down -v`/Docker prune for maintenance. The administrator setup helper requires a root-owned server checkout; local management uses Compose directly. VPS recovery/TLS/SSH commands: private `.state/CONTABO.md`.

## Rollback and retained records

- Current local receipts/configuration: `.state/local-maintenance/`. Its `rollback.sh` restores the preceding 40-tool deployment with the history fix intact.
- `.state/scrapling-local/rollback.sh` restores the pre-Scrapling published 35-tool stack. Both rollback paths preserve data/secrets and expire browser sessions; reconnect clients when schemas change.
- History-fix receipts: `.state/scrapling-cleanup/`. Initial trial build/deployment receipts: `.state/scrapling-local/`.
- Published release/VM/RSS/storage records remain indexed in private `.state/README.md`; published image installation and update instructions are in INSTALL.md.

## Limits

- Local images reuse verified dependency/browser/OS layers. Fresh candidate image builds are verified separately above; a complete fresh Compose installation, sustained soak and actual-host reboot are not verified for this trial. Local Tailscale bind availability at Docker startup also needs a host reboot check; prior VM checks do not establish current-host recovery.
- Frontend `arp_ignore=0` is scoped to its container network namespace; the host remains unchanged.
- Retention is manual and guarded; apply requires both MCP and control stopped. No automatic cleanup is enabled. Backups must preserve consistent configuration and storage.
- Document IDs are cache handles, not archives. Refresh may replace evidence; export irreplaceable records. Retrieval still has a 2 MiB backend ceiling before passage slicing.
- Site/provider availability, extraction completeness, CAPTCHA access and unique pagination are not guaranteed.
