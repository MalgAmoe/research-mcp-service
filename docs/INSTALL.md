# Compose deployment

One owner per stack. Docker runs the MCP frontend, search, control, browser worker, egress proxy, Redis and S3 storage. There is **no host application virtualenv, application systemd unit or runtime Docker access**. Docker administrators remain trusted. Optional public TLS: [HTTPS.md](HTTPS.md).

**Production release:** `scrapling-20261108-223033-e9c05b2` (Linux amd64, 40 tools), built from source commit `e9c05b2dab16ff68b25c213623a27288c5b80d9f` and published in `malgamoe/mcps`. The VPS uses its app/control and worker images with the retained compatible egress image. Current deployment mix and verification limits: [LIVE-STATUS.md](LIVE-STATUS.md).

The examples below select this release. Local development build/check/rollback instructions: [SCRAPLING-LOCAL.md](SCRAPLING-LOCAL.md). Do not replace VPS image references with local-only development images.

Commands below run from the repository root, not the `docs/` directory.

## Prerequisites

- Linux x86-64 with Docker Engine and Compose v2. The optional setup/retention helpers need only the system Python 3 standard library, not installed application packages.
- An administrator/root shell for provisioning, from a root-owned checkout. Do not execute privileged setup scripts from another user's writable directory.
- Roughly 8 GiB RAM and sufficient disk for browser images and accumulated cache. Storage has no automatic expiry or quota.
- Outbound public HTTP/HTTPS for image pulls and research. No public inbound ports are needed for loopback/Tailnet use. Docker publishing can bypass UFW; never publish storage/control/search/worker ports.

On a fresh Ubuntu 24.04 host, install Docker/Compose, Python 3 and Git through your administrator. Enable Docker at boot. No MCP login account or Docker-group grant to an application is needed.

```sh
git clone https://github.com/MalgAmoe/research-mcp-service.git /srv/research-alice
cd /srv/research-alice
git checkout e9c05b2dab16ff68b25c213623a27288c5b80d9f
python3 scripts/setup_server.py init --instance alice --port 8766 --version scrapling-20261108-223033-e9c05b2
```

Use an explicit published version, not `latest`. Default image repository: `malgamoe/mcps`; override with `--repository` if required. Tags are `research-mcp-app-VERSION`, `research-mcp-worker-VERSION` and `research-mcp-egress-VERSION`. The app image runs frontend/control/credential-initialization roles with different commands and permissions. Upstream Redis, SeaweedFS and SearXNG images are pinned by digest.

Initialization creates private `.env.runtime`, `.env.mcp`, `.env.control` and two token files under `.secrets/`. No service starts and no credentials are printed. IDs/ports are reserved under `/var/lib/research-mcp/instances/`, including initialized but stopped installations. The helper checks existing labelled/unlabelled Docker resources, stopped-container port assignments and host listeners before creating configuration. Partial initialization retains its reservation for explicit inspection; there is no automatic reset or teardown.

The default published address is `127.0.0.1`. For Tailnet clients use `--host YOUR_TAILSCALE_IPV4`. For another owner, use another checkout, instance ID and MCP port. Search has no host port to allocate. Do not copy another owner's environment files, credentials or volumes.

### Verified image digests

After initialization, immutable image references use `malgamoe/mcps@sha256:DIGEST` from this table. Anonymous manifest checks and digest pulls passed on the build host (local layers cached). The VPS retains its compatible earlier egress pin, recorded in LIVE-STATUS.md; fresh installations use the matching published egress below.

| Setting | SHA-256 digest |
|---|---|
| `MCP_APP_IMAGE` | `93ef02a95b29d0445172874835a4123b18bb547fa9fc66559f81ee08059cf3f1` |
| `MCP_WORKER_IMAGE` | `3596ddab6d399d98875fd4c02515d9a31545fa75eb8dd1e325f85a8b31c202dc` |
| `MCP_EGRESS_IMAGE` | `22615abce4f34af367ac7c993422f15bac7935a969bdd8d5d61b76af5e127897` |

Fresh Dockerfile builds passed packaged suites (158 tests per app/worker image, respectively three/two expected skips), six egress unit tests, both-browser fixtures, four reader modes, 24 history traversals, private-network/WebSocket checks and cancellation. A 23-call MCP browser canary used the fresh app and real worker; unused search/storage backends were stubbed. Anonymous manifest checks and digest pulls passed with local layers cached. The VPS rolling update also passed 56 real MCP calls covering search, four reader modes, cached retrieval and both-browser features, plus public trusted TLS/authentication and original saved-document retrieval. Persistent Redis records and S3 object bytes were checked before acquisition probes. A complete fresh all-new-image installation, production soak and actual-host reboot remain unverified.

For an existing installation, take a consistent backup and save its image references; check out the release source and update app **and** worker pins together. References use `malgamoe/mcps@sha256:DIGEST`. The existing egress pin can remain unchanged for this rolling update; the matching release egress image is available for new installations. Pull the selected images before the coordinated restart:

```sh
docker compose --env-file .env.runtime -f compose.deploy.yml pull control mcp fetch-worker
docker compose --env-file .env.runtime -f compose.deploy.yml up -d --no-deps --pull never --wait --wait-timeout 300 fetch-worker control mcp
python3 scripts/setup_server.py check
python3 scripts/setup_server.py check --live
```

Preserve secrets, cache, volumes and TLS configuration. Browser sessions expire; saved data remains. Rollback restores the prior pins and recreates the same three services. Never rerun initialization on an existing installation. VPS promotion is verified; the local development deployment remains unchanged.

## Start and check

```sh
# Can take several minutes on the first image pull; no browser builds occur here.
nohup python3 scripts/setup_server.py up > .state/setup.log 2>&1 &
echo $! > .state/setup.pid
# Wait for successful completion; inspect .state/setup.log.
python3 scripts/setup_server.py status
python3 scripts/setup_server.py check
# Optional external search/page acquisition, artifact readback and both browsers:
python3 scripts/setup_server.py check --live
```

The helper first checks the published endpoint from the host using standard-library Python, then runs tool checks inside the frontend container. No host application packages or model calls are needed. The live check saves a test page and closes only its own browser sessions; it does not certify every provider/site. The default check verifies authenticated discovery and private control/Redis calls.

`up` validates Compose, pulls the selected images and starts the stack with a bounded health wait. A pull failure stops before container startup; there is no cached-image substitution. `up --no-pull` restarts already downloaded images and refuses implicit pulls; it is not a workaround for an incomplete installation.

Direct Compose equivalent:

```sh
docker compose --env-file .env.runtime -f compose.deploy.yml pull
docker compose --env-file .env.runtime -f compose.deploy.yml up -d --pull never --wait --wait-timeout 300
```

Keep `.env*` mode 0600 and `.secrets/` and `.state/` private. A network-none, one-shot initializer copies only the two frontend bearer tokens into a private named volume. The frontend mounts that volume read-only, runs as UID 10001 and receives no storage credentials. Control communicates over a separate named Unix-socket volume. The browser worker remains credential-free and network-none. No application container mounts the Docker socket.

Client endpoint: `http://YOUR_BIND_ADDRESS:PORT/mcp`, with `Authorization: Bearer <token>` from `.secrets/mcp-token`. Transfer tokens privately, never in URLs, Git or shared prompts. Plain HTTP is appropriate only over loopback or the encrypted Tailnet. The container listens internally on all its interfaces, but accepted HTTP Host/Origin values remain tied to the configured published endpoint; they are not wildcarded.

## Stop, boot and update

```sh
python3 scripts/setup_server.py stop       # stops this stack, preserves volumes
python3 scripts/setup_server.py up --no-pull
```

Docker restart policies recover running services after a host reboot. A Tailnet-specific published address must already exist when Docker restores that port binding; restart policies do not guarantee recovery from a failed port allocation. Default loopback publishing with SSH/HTTPS avoids that dependency. Tailnet boot ordering needs a separate check on the actual host.

The frontend waits for authenticated Redis/S3/worker readiness and a clear maintenance lock before serving. Credentials remain in their named volume; the initializer need not rerun at boot. Intentionally stopped containers stay stopped until an administrator starts them. Browser handles expire when their worker restarts; saved evidence is persistent.

For updates: coordinate downtime and back up configuration plus consistent stopped-storage volumes. Record source revision and image references. Stop the stack, review/pull the intended repository revision and set the required image references in `.env.runtime` to the matching release (app and worker together for Scrapling; retain egress only when explicitly compatible), then run `up` and checks. Source/configuration and images must match. No automatic rollback is promised; storage changes can require a compatible data backup. Never use `down -v` or Docker prune as routine maintenance.

`compose.deploy.yml` is the only supported deployment layout. Initialization refuses existing configuration; there are no old-layout compatibility files or automatic data migrations. Never mount another storage engine's data directory into SeaweedFS. Preserve credentials/data unless an explicit reset has been approved.

## Manual retention

```sh
python3 scripts/retention.py                         # read-only inventory
python3 scripts/retention.py --days 30 --rss-days 90
python3 scripts/retention.py --pin DOC_ID
python3 scripts/retention.py --list-pins
python3 scripts/retention.py --unpin DOC_ID
```

The helper launches a temporary control-image process on this stack's storage network; it never starts dependencies or mounts Docker inside a container. Dry-run counts can change while writers remain active. Pins protect the current artifact references from cleanup, not from replacement by refresh. Cache IDs are not archives: export irreplaceable evidence separately. Malformed metadata and versioned buckets abort cleanup. Subscriptions are retained; no automatic TTL/lifecycle policy is installed.

After reviewing the plan and making a consistent backup, stop MCP and control while leaving Redis/S3 running:

```sh
docker compose --env-file .env.runtime -f compose.deploy.yml stop mcp control
python3 scripts/retention.py --apply --writers-stopped
# Only after successful completion and inspection:
python3 scripts/setup_server.py up --no-pull
```

Stop any other direct/one-off writers too. The launcher checks the real control/MCP container states and rechecks under a nonexpiring Redis maintenance lock. Redis/S3 deletion is not atomic. Failure after deletion starts retains the lock: keep writers stopped, inspect partial state and confirm no maintenance job remains before explicitly clearing this deployment's `retention:maintenance_lock`. There is no automatic unlock, restart or deletion schedule.
