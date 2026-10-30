# Deployment status

Setup and maintenance commands: [INSTALL.md](INSTALL.md). Architecture: [DESIGN.md](DESIGN.md). Tool behavior: [README.md](README.md).

## Running installations

| Installation | Source revision | MCP access | Control connection | Startup |
|---|---|---|---|---|
| Local development | d3bbb97 | `http://100.69.41.80:8766/mcp`, bearer authentication | Internal container TCP | Background process |
| Ubuntu VPS | a44b645 | Same HTTPS endpoint/bearer; backend loopback | Named Unix-socket volume | Full Compose stack / Docker restart policies |

Both expose 34 tools and have separate credentials, caches and browser sessions. The original personal gateway is a separate service.

Both installations now use SeaweedFS 4.51. Each received a separately approved clean cache reset; old MinIO/cache volumes were removed. The VPS has migrated to the image-only Compose workflow; the local installation still uses its existing host frontend. VPS endpoint and bearer token were preserved; SSH, TLS/renewal and Hermes were unchanged.

## Local development operations

- MCP configuration: `.env.mcp`; PID/log: `.state/mcp.pid`, `.state/mcp.log`.
- Control credentials: `.env.control`, `.secrets/gateway-token`.
- After control recreation, inspect its internal IP and update `MCP_GATEWAY_URL` before restarting MCP. This installation does not use the fresh-server Unix-socket overlay.
- Coordinate restarts: recreating the worker expires browser sessions. Verify the saved MCP PID belongs to `research_mcp_service.server` before stopping it.

```sh
docker compose --env-file .env.runtime -f docker-compose.yml -f compose.workers.yml -f compose.control.yml --profile workers build fetch-worker control
docker compose --env-file .env.runtime -f docker-compose.yml -f compose.workers.yml -f compose.control.yml --profile workers up -d --wait control
# Update MCP_GATEWAY_URL, then restart MCP:
uv run --locked --env-file .env.mcp python -m research_mcp_service.server
```

VPS-specific connection and service commands are in private `.state/CONTABO.md`.

## Verification

- Local SeaweedFS deployment: 34-tool discovery, S3 capabilities, live search/page acquisition, artifact storage/retrieval, Chromium, Camoufox and retention dry run passed. Worker/control containers rebuilt; storage remains private.
- VPS: application/browser builds, 119 offline tests, live search, page storage/retrieval, Chromium/Camoufox, proxy isolation and retention dry run checked.
- Image-only candidate `candidate-20261030-181946`: 134 offline tests pass. All three images were published to `malgamoe/mcps` and pulled anonymously by exact digest in a disposable Ubuntu VM. Two independent Compose deployments passed 34-tool discovery, search calls, acquisition/artifact retrieval, Chromium/Camoufox, cross-token/document/browser isolation, and frontend denial of the other owner's storage network. No host application virtualenv or application systemd unit was used.
- Both Compose stacks recovered after a VM reboot without provisioning: saved evidence remained available, old browser handles expired, and fresh browser/API checks passed. This tested loopback publishing, not Tailnet address ordering at boot.
- Generated HTTPS routes passed trusted **test-CA** TLS, bearer/Host/Origin rejection and unknown-path checks. This is not new public ACME or certificate-renewal verification. RSS subscription and cached-entry isolation passed with the Django weblog feed; an initial Python feed fetch failed and was not diagnosed.
- Disposable-fixture retention rejected running writers, honored pins, deleted the selected Redis metadata and S3 objects, released its lock, and preserved subscriptions/cached RSS. Alpha stop/cleanup/restart left beta's saved data and live browser usable. The VPS subsequently received the verified workflow through an approved clean reset; the local installation was not migrated.
- VPS clean Compose migration: all containers healthy, 34 tools, search call, acquisition/artifact readback, Chromium/Camoufox and existing public HTTPS/authentication passed. Old MCP/search containers and cache volumes were removed after ownership checks; the host application unit is disabled. A fresh retention dry run passed.
- VPS host/network reboot fixes were verified previously with the old application layout (SSH 22s, MCP 38s). **The new VPS stack has not yet been reboot-tested on that host**; its reboot checks were in the disposable VM. No VPS reboot was performed during migration.
- VPS public TLS, bearer rejection and certificate-renewal/reload dry run passed. Renewal checks run every six hours.
- Destructive retention on production data and power-loss durability remain untested; the deletion check used only a deliberately aged disposable fixture.
- Search providers can return degraded results; request diagnostics when investigating coverage or failures.

## Operational limits

- Fresh installs use digest-pinned SeaweedFS. The Compose workflow was verified in a disposable local Ubuntu VM and then freshly installed on the existing VPS. This is not a production soak. Existing MinIO installations need an explicit migration or approved reset before updating; see INSTALL.md.
- Automatic cleanup is disabled. Use `python3 scripts/retention.py` for a read-only inventory; apply requires stopped writers and the guarded maintenance workflow in INSTALL.md.
- Cache IDs are not archives; refresh can replace cached content. Export irreplaceable evidence separately.
- Browser observations and successful extraction do not certify completeness or readiness. Full backend document retrieval still has a 2 MiB ceiling before passage slicing.

## Diagnostic logs

Local deployment/checks: `.state/deploy-seaweed/build.log`, `.state/deploy-seaweed/finish.log`, `.state/deploy-seaweed/tests.log`.
Retention: `.state/deploy-seaweed/retention-dry-run.log`.
MCP/worker source snapshot: `sha256:dfdf7b759f33a1b8eda861d2611907462043581096d81d45ea6efde3a5436f6a`.
Image-only candidate: `.state/compose-release/{tests-final,build,publish-public,pull-vm,start-vm,isolation-reboot,extra-retry}.log`. The initial RSS fixture failure is retained in `extra.log`. Completed one-off harness/scripts were removed after verification; only stopped-VM management metadata and selected evidence remain privately. See `.state/README.md` for the retained layout.
VPS: locations recorded in `.state/CONTABO.md`.
