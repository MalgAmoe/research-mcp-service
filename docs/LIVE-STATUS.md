# Deployment status

Setup/update/backup: [INSTALL.md](INSTALL.md). TLS: [HTTPS.md](HTTPS.md). Runtime boundaries: [DESIGN.md](DESIGN.md). Local tool behavior and checks: [SCRAPLING-LOCAL.md](SCRAPLING-LOCAL.md).

## Running deployments

Both use `compose.deploy.yml`, separate credentials/data, Redis and SeaweedFS 4.51. Only MCP publishes a port; browser execution remains in a credential-free, network-none worker behind restricted egress. Neither shares resources with the original personal gateway.

| Deployment | Compose identity | MCP access | Status |
|---|---|---|---|
| Local test | `local-v2` | `http://100.69.41.80:8766/mcp`; named tokens + existing token | 40 tools; named credentials/request logs |
| VPS production | `contabo-v2` | Existing HTTPS endpoint; backend loopback; named tokens + existing token | 40 tools; named credentials/request logs |

Both frontends use published `malgamoe/mcps` app `auth-20261109-30c703e`, digest
`97a27451073ff542a73772de604d3604f18958cef14c9273bbcee4cd7079b1f8`.
Both `.env.runtime` app pins select this image for future app-role recreations.
Only the frontends and one-shot credential initializers were recreated; running
control/worker images remain as follows. Local retained images use the unpublished
`research-mcp-local` repository:

| Component | SHA-256 |
|---|---|
| Running control | `28aaba22373dbab40a7c34de30883e40a1f8af7297d44d629da978f3a5ea7d42` |
| Worker | `047c3f08e529bf23fdecfa069412e9b0aee14b80d9974d5668ca3caabf3099a8` |

VPS images (`malgamoe/mcps`); egress is also retained locally:

| Component | SHA-256 |
|---|---|
| Running control | `37ea21ea1f0756a750c4d49e395f530a0286db628d65a9b74adadf6c46eda301` |
| Worker | `e33c79cc4d46a216286a079f246210c6d2a19987696ca8c5d840dbe5aaaf8448` |
| Egress | `4506a720dd51235fd44e2a1e01022079a03e49202da283d1eee473818c3e49b3` |

## Named credentials and request accounting

Source `30c703e`, published app `auth-20261109-30c703e`, is active on both
frontends. Host suite: 173 tests pass; packaged app: 173 tests run, two expected
Docker-CLI-only skips. Authenticated discovery/control/Redis checks expose 40
tools on both deployments. Named and legacy health calls pass, invalid tokens
return 401; VPS verification uses trusted public HTTPS. Request logs identify
client, UTC timestamp, method/tool, duration, HTTP status and MCP outcome without
arguments, credentials or response contents. Registry management, `show` and
`apply` commands: [INSTALL.md](INSTALL.md#named-credentials-and-request-logs).

Local labels: `mrpi`, `hermes-local`; VPS label: `hermes-vps`. Pi's credential-file
reference and both Hermes private environment files were updated. Both Hermes
gateways and the local dashboard were restarted to load credentials; running Pi
sessions need `/reload`. Existing tokens remain valid as `legacy`, including
health checks. Clients on different deployments require that deployment's token;
registries are independent and permissions/storage are shared within each stack.

Only frontends restarted; browser workers, control, egress, search and storage
were retained, preserving browser handles and saved data. Runtime/config backups,
logs and verification: local `.state/named-tokens/`; VPS
`/root/research-named-tokens-20261109/`. Rollback restores prior runtime and Compose
files, recreates only the frontend and restores prior client credential configs;
never restore storage or delete volumes for this frontend-only change.
No model inference was invoked for verification. Actual-host reboot and fresh
installation of this release have not been tested.

## Retained VPS capacity and browser release

`docs-20261109-520d56b` control/worker remain active on the VPS,
from source commit `520d56b`. Action field descriptions/examples, one-based
numbering, form HTML serialization, defaults/scroll units and network subset/cursor
semantics are clarified in the exposed tool schema/descriptions; behavior is unchanged.
Worker RAM is 3 GiB / 2 CPU cores; frontend/control/worker acquisition admission
is 3. Interactive browser commands remain serialized. Control emits structured
queue/duration/outcome logs; see INSTALL.md. Host suite: 163 passes; packaged
app/worker: 163 each, two skips. Authenticated 40-tool checks and live search,
read/storage/readback, Chromium and Camoufox checks pass. Updated exposed descriptions
and action-field schema were verified through MCP discovery, including public trusted
HTTPS (anonymous 401, authenticated 40 tools). Three simultaneous
uncached light reads via MCP completed ready in 13.091 seconds wall time with
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
