# Fresh private Linux server

This is a **single-owner loopback/Tailscale deployment**, not a public hosting setup. It does not migrate the existing development installation. Use a fresh checkout and unique instance name/ports; initialization refuses existing configuration. No step automatically deletes stored data.

## Prerequisites

- Linux server with Docker Engine and Compose v2, Python 3, and `uv` on PATH. Use a non-root login that can run Docker (Docker access is effectively privileged).
- Target platform: Linux x86-64. Other architectures/rootless Docker/SELinux deployments have not been verified.
- Allow outbound public HTTP/HTTPS for search and the egress proxy, plus dependency/browser downloads during build. No public inbound ports are needed.
- For remote clients, install/connect Tailscale first and limit access with your Tailnet policy. Otherwise keep the default loopback bind and use SSH forwarding.
- Start with roughly 8 GiB RAM and 20 GiB free disk for images/browser assets/cache; actual needs depend on workload. No automatic retention is enabled.

Transfer **tracked source only** to a short path such as `/srv/research-mcp` owned by the service user. Use your Git checkout, or `git archive HEAD` from this repo. Do not copy another installation's `.env*`, `.secrets/`, `.state/`, `.venv/` or Docker volumes. The repo currently has no publication remote.

## Initialize and start

From the checkout root:

```sh
python3 scripts/setup_server.py init --instance myserver --host 127.0.0.1
# For Tailnet access instead, use --host YOUR_SERVER_TAILSCALE_IPV4.
# Optional: --port 8766 --search-port 18080 (choose unused ports).
```

This creates mode-0600 environment files and separate MCP/backend/storage credentials. Nothing is started and no token is printed. MCP reaches control through `.state/control-rpc/gateway.sock`, **not a container IP or TCP mapping**. The control service retains its internal storage network; browser execution retains network-none and proxy-mediated egress. Only the MCP listener is client-facing; search binds loopback.

Keep `.state` and `.secrets` private (0700). The socket subdirectory is intentionally writable by container UID 10001; its private host parent prevents access by other host users. Do not relocate the checkout after initialization without updating the absolute socket path and service unit.

Build/start the containers and install locked Python dependencies (Python 3.12). This may take several minutes and download browser assets. To retain progress without blocking your shell:

```sh
nohup python3 scripts/setup_server.py up > .state/setup.log 2>&1 &
echo $! > .state/setup.pid
# Inspect .state/setup.log and wait for successful completion before continuing.
python3 scripts/setup_server.py status
```

`up` starts the dedicated search project and this instance's storage/egress/worker/control project. Generated images and volumes are instance-scoped. Build/install failures stop the command; already-started components are left in place for inspection, not purged. `up --no-build` starts existing images without dependency synchronization.

For an initial foreground MCP run:

```sh
python3 scripts/setup_server.py run
```

From another terminal:

```sh
.venv/bin/python scripts/check_install.py
# Optional: public search/page acquisition, MinIO write/read, and one Chromium session:
.venv/bin/python scripts/check_install.py --live
```

The default check verifies authenticated MCP discovery/health and control/Redis calls. It does not certify browser launch, search coverage or arbitrary website access. The live check closes only its own browser session; it saves one page in the cache. No model calls are made.

Client endpoint: `http://YOUR_BIND_ADDRESS:8766/mcp`. Configure `Authorization: Bearer <token>` using the value in `.secrets/mcp-token`, transferred through a private channel. Never put it into a public URL, Git, logs or a shared prompt. Direct HTTP is suitable only over loopback or the encrypted Tailnet. Check Tailnet/firewall permissions if remote connections fail.

## Optional boot service

Stop the foreground MCP process first. Generate a unit; generation does **not** install or enable it:

```sh
python3 scripts/setup_server.py unit
mkdir -p ~/.config/systemd/user
cp .state/research-mcp-myserver.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now research-mcp-myserver.service
journalctl --user -u research-mcp-myserver.service -f
```

Replace `myserver` with your instance ID. Have the administrator enable Docker at boot and, if desired, `loginctl enable-linger YOUR_USER` so the user service starts without login. These are privileged administrative decisions; the setup script does not perform them. The service starts/waits for its containers before MCP and retries failures. A Tailnet bind may fail until Tailscale is ready; the restart policy retries it. No package downloads/builds occur in `ExecStartPre`; run `up` once successfully beforehand.

`systemctl --user stop research-mcp-myserver.service` stops MCP only. Containers keep their restart policies. To stop this installation's containers without deleting volumes:

```sh
docker compose --env-file .env.search -f compose.search.yml stop
docker compose --env-file .env.runtime -f docker-compose.yml -f compose.workers.yml -f compose.control.yml -f compose.server.yml --profile workers --profile control stop
```

## Updates, recovery and data

Coordinate downtime: worker recreation expires browser sessions. Back up private configuration and Redis/MinIO volumes before significant changes; this workflow does not implement automated backups or migrations. Use a consistent stopped-storage backup rather than copying live database files. Preserve the matching credentials with any volume backup.

For an update, stop MCP, update the checkout, run `setup_server.py up`, then restart MCP and rerun checks. The Unix endpoint path remains stable across container recreation; no IP edits are needed. Never run initialization over existing data or use `down -v` as routine cleanup. A rollback may require the previous source/image and compatible data backup; this script does not claim automatic transactional rollback.

## Manual cache retention

The existing retention policy is available through a host launcher for both development and fresh-server layouts:

```sh
python3 scripts/retention.py                       # read-only inventory, no deletion
python3 scripts/retention.py --days 30 --rss-days 90
python3 scripts/retention.py --list-pins
python3 scripts/retention.py --pin DOC_ID           # explicitly changes pin state
python3 scripts/retention.py --unpin DOC_ID
```

The launcher runs a temporary control-image process on this instance's private storage network, with no dependency startup and no Docker socket inside the container. It does not stop/restart services. A dry run may run while clients are active, so its counts are advisory and can change. Defaults: documents older than 30 days since retrieval, RSS entries older than 90 days since fetching; cached reads do not extend retention. Pins protect document IDs and their currently referenced artifacts from retention, not from replacement by refresh. Subscriptions remain. Export irreplaceable evidence separately.

Cleanup also removes stale URL/recent/RSS indexes and old unreferenced artifacts, while keeping shared artifacts referenced by retained documents. Malformed records and versioned MinIO buckets abort rather than guessing. This is an age policy, not a disk quota: pins, recent downloads and backups can still grow. It does not prune browser temp files, logs, Docker images or backups.

**Apply is manual and requires the updated control image.** After reviewing a dry run and making a consistent backup, coordinate downtime:

1. Stop MCP using its existing supervisor and stop this deployment's `control` service using the matching Compose files. Leave Redis/MinIO running. Stop any other direct/one-off storage writers too.
2. Run `python3 scripts/retention.py --apply --writers-stopped`.
3. Restart control/MCP only after successful completion and inspect health.

The launcher refuses a missing/running/paused/restarting control. It checks again **after** the maintenance process holds the Redis lock, before authorizing deletion. A restarted control rejects ordinary requests while that lock exists. Other direct-storage clients cannot honor this guard: `--writers-stopped` is your explicit confirmation about them. An old control image rejects the guard protocol before deletion; rebuild it rather than bypassing the launcher.

Redis and MinIO deletion is not atomic. Failure after deletion starts, or a killed maintenance process, leaves the non-expiring maintenance lock in place. Keep writers stopped. Verify no maintenance/pin process is active, inspect the error and partial state, and only then explicitly clear `retention:maintenance_lock` in this deployment's Redis and rerun the approved cleanup. There is intentionally no automatic unlock/restart. A failure before any deletion releases its lock normally.

No cleanup timer or automatic deletion is installed. Do not add independent Redis TTLs or MinIO lifecycle rules: those would bypass coordinated deletion and pin protection.

## Verification status

Verified here: fresh-directory generation and overwrite refusal, generated Compose validation, retained isolation settings, authenticated repeated Unix-socket calls, and a non-root network-none Docker process serving the host through the socket mount. Offline suite passes. **A complete cold build and boot-cycle on a separate fresh server has not yet been performed.** Existing live deployment was not switched to this topology.
