# Deployment status

Setup and maintenance: [INSTALL.md](INSTALL.md). Architecture: [DESIGN.md](DESIGN.md). Tools: [README.md](../README.md).

## Published update; rollout pending

Candidate `rss-unsubscribe-20261031-104428`, built from `dda1475`, is public in `malgamoe/mcps`; exact digests and update commands are in [INSTALL.md](INSTALL.md). It adds `rss_unsubscribe(feed_url)` (35 tools): idempotent subscription removal preserving cached entries/read states, with an atomic guard against in-flight fetch re-subscription.

142 host tests and a separate real Redis fixture check pass. The worker image passed the suite with two Docker-CLI-only tests skipped; the app image passed 22 RSS/MCP tests. Offline Chromium/Camoufox launch/content checks, egress imports, anonymous registry manifest checks and anonymous digest pulls passed (local image layers were cached). These exact images have not yet undergone a full Compose rollout or reboot check.

Both live deployments remain unchanged at 34 tools. Enabling unsubscribe requires a coordinated frontend/control update, not a cache reset or browser-worker restart.

## Running installations

Both installations use **`compose.deploy.yml`**, the published `candidate-20261030-181946` images and private Redis/SeaweedFS 4.51 storage. Current deployment digests are below; INSTALL.md lists the newer, not-yet-deployed candidate. They expose 34 tools with separate credentials, caches and browser workers; neither shares resources with the original personal gateway.

| Current image | SHA-256 digest (`malgamoe/mcps`) |
|---|---|
| App | `b3a026c1be9a84347d170944707d1d9ccc43abe1ded06df640638726446a79df` |
| Worker | `ede7f5f79e95215080d02c9fa1c89cf80747055633282edc8e746109a38b07f8` |
| Egress | `4506a720dd51235fd44e2a1e01022079a03e49202da283d1eee473818c3e49b3` |

| Installation | Compose identity | MCP access | Management |
|---|---|---|---|
| Local | `local-v2` | Same `http://100.69.41.80:8766/mcp` and bearer token | User-owned checkout, direct Docker Compose |
| VPS | `contabo-v2` | Same HTTPS endpoint and bearer token, backend loopback | Root-owned checkout, setup helper or direct Compose |

Both host frontends and their old MCP/search containers have been replaced. Separately approved clean resets discarded the old cache/storage; current caches contain newly acquired evidence and smoke-test data. No old deployment overlays or component initialization helpers remain in the repository.

## Operations

For the current local checkout, using the user's existing Docker access:

```sh
docker compose --env-file .env.runtime -f compose.deploy.yml ps
docker compose --env-file .env.runtime -f compose.deploy.yml exec -T mcp python -m research_mcp_service.container_check
python3 scripts/retention.py  # read-only inventory
# Coordinate downtime and browser-session loss before restarting:
docker compose --env-file .env.runtime -f compose.deploy.yml up -d --pull never --wait
```

This is the same Compose deployment as the VPS, not a second runtime mode. The administrator setup helper requires a root-owned server checkout and maintains its host reservation inventory. Current local configuration was generated during the coordinated reset; its existing Docker project/resources also prevent conflicting initialization. Do not initialize over either installation.

MCP logs now come from Docker Compose, not a background host process or `.state/mcp.pid`. Browser handles expire on worker restart. Configuration and secrets remain private in `.env*` and `.secrets/`. Do not delete data volumes for routine maintenance.

VPS connection, certificate and service commands: private `.state/CONTABO.md`. The migration preserved SSH, firewall, TLS/renewal and Hermes; no model calls were made.

## Verified behavior

- The deployed release's deployment/maintenance tooling passed 136 offline tests, including published-endpoint failure handling and the requirement that both MCP and control be stopped before deletion.

- The previous `candidate-20261030-181946` images were pulled anonymously by exact digest into a disposable Ubuntu VM. Two independent deployments passed 34-tool discovery, search calls, acquisition/artifact retrieval, Chromium/Camoufox, cross-token/document/browser isolation and frontend denial of another owner's storage network.
- Both VM stacks recovered after reboot without provisioning: saved evidence remained available, old browser handles expired and fresh browser/API checks passed.
- Generated HTTPS routes passed trusted **test-CA** TLS, bearer/Host/Origin rejection and unknown-path checks. RSS subscription and cached-entry isolation passed using the Django weblog feed; an initial Python feed fetch failed and was not diagnosed.
- Disposable retention rejected running writers, honored pins, deleted selected Redis metadata and S3 objects, released its lock and preserved RSS. Alpha maintenance left beta's data and browser usable.
- VPS clean installation passed live API/storage/Chromium/Camoufox checks, existing public trusted HTTPS/authentication, and retention dry run. Old containers/volumes were removed after ownership checks; its host application unit is disabled. Public certificate renewal/reload had been verified previously and its six-hour timer was preserved.
- Local clean installation passed the same live tool/browser checks, authenticated access through its original Tailscale URL, and retention dry run. An initial external connection failure triggered rollback without deleting data. Subsequent recreation exposed intermittent published-port reachability with the host's inherited `arp_ignore=2`. The frontend now sets `arp_ignore=0` only in its own network namespace; the host remains at 2. Authenticated host access passed after recreation and again after 100 seconds idle. The setup helper's check now also probes the published endpoint instead of relying solely on internal health. Old MCP containers/volumes were removed only after successful cutover. Personal gateway containers were untouched.

## Limits

- Reboot recovery was tested with loopback publishing in the VM. **Neither new live stack has yet been reboot-tested on its actual host.** Local Tailscale-address availability at Docker startup requires a separate host check. Previous VPS host/network boot fixes were verified with its former application layout, not the new one.
- Test-CA HTTPS is not public ACME issuance/renewal verification. Neither this rollout nor the VM tests establish production-soak or power-loss reliability.
- Destructive retention used only a deliberately aged disposable fixture, not production evidence. Automatic cleanup remains disabled; apply requires both MCP and control stopped plus the guarded maintenance handshake.
- Cache IDs are not archives; refresh may replace content. Export irreplaceable evidence separately. Backend document retrieval still has a 2 MiB ceiling before passage slicing.
- Provider availability, extraction completeness and unique pagination are not guaranteed; request diagnostics when investigating failures.

## Private evidence

- `.state/compose-release/`: build/publication, anonymous pull, two-owner/reboot and HTTPS/RSS/retention test records. Exact digests: `public-images.json`.
- `.state/local-compose-reset/`: local reset outcome and initial/retry logs.
- `.state/deploy-seaweed/`, `.state/evidence/`: selected earlier storage/security checks.
- VPS migration logs: paths in `.state/CONTABO.md`.
- `.state/README.md`: retained state layout. One-off VM harness files were removed; stopped-VM management metadata remains private and is not shipped.
