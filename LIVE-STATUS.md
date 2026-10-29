# Deployment status

Setup and maintenance commands: [INSTALL.md](INSTALL.md). Architecture: [DESIGN.md](DESIGN.md). Tool behavior: [README.md](README.md).

## Running installations

| Installation | Source revision | MCP access | Control connection | Startup |
|---|---|---|---|---|
| Local development | 283b6f2 | `http://100.69.41.80:8766/mcp`, bearer authentication | Internal container TCP | Background process |
| Ubuntu VPS | 3ca1223 | Loopback port 8766 through SSH, bearer authentication | Private Unix socket | Enabled user-systemd service |

Both expose 34 tools and have separate credentials, caches and browser sessions. The original personal gateway is a separate service.

The repository's named MinIO release and early-pull preflight changes are not deployed to either installation.

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

- Local: live search/acquisition, saved passages/headings, browser history/condition waits, screenshot-limit fallback, PDF annotation links and RSS preview checked.
- VPS: application/browser builds, 119 offline tests, live search, page storage/retrieval, Chromium/Camoufox, proxy isolation and retention dry run checked.
- Current repository: 121 offline tests pass.
- Reboot recovery and destructive retention execution on real data remain untested.
- Search providers can return degraded results; request diagnostics when investigating coverage or failures.

## Operational limits

- The configured MinIO release could not be pulled from official registries. The VPS currently has a cached official image. Fresh setup stops at image-pull failure; verify an accessible image source before proceeding.
- Automatic cleanup is disabled. Use `python3 scripts/retention.py` for a read-only inventory; apply requires stopped writers and the guarded maintenance workflow in INSTALL.md.
- Cache IDs are not archives; refresh can replace cached content. Export irreplaceable evidence separately.
- Browser observations and successful extraction do not certify completeness or readiness. Full backend document retrieval still has a 2 MiB ceiling before passage slicing.

## Diagnostic logs

Local deployment: `.state/deploy-283b6f2.log`, `.state/check-283b6f2.log`, `.state/tests-deploy-283b6f2.log`.
Retention: `.state/retention-dry-run.log`, `.state/tests-retention-host.log`.
VPS: locations recorded in `.state/CONTABO.md`.
