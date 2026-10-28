# Runtime design and boundaries

Current scope: one private owner, authenticated MCP over Tailscale/loopback. Several clients with that token share the owner's cache and browser worker. No tenant router, OAuth, public ingress or multi-user security claim. See [README.md](README.md) for tools and [LIVE-STATUS.md](LIVE-STATUS.md) for operations and verification.

## Execution paths

```text
Client → bearer-authenticated MCP process
  ├─ search → disposable search process → dedicated SearXNG / DDGS
  └─ fixed-origin authenticated control gateway
       ├─ Redis / MinIO on internal storage network
       └─ read-only Unix RPC mount → execution worker (network_mode: none)
                                     └─ loopback bridge → Unix egress proxy
                                                          └─ public HTTP(S)
```

The control gateway requires WORKER_SOCKET; read/conversion/feed failures do not fall back to host fetching. Legacy direct-search/research/safe-read HTTP routes have been removed, and the route allowlist still rejects them. MCP research uses the configured search backend followed by isolated batch reading; missing search configuration fails closed rather than falling back to a legacy route. Document conversion requires worker RPC even when called directly. Shared extraction functions remain in the gateway package for execution inside the isolated worker.

The worker is non-root, read-only, capability-dropped, resource-limited, without storage credentials or storage-network membership. It rejects startup with non-loopback interfaces or prohibited credential environment variables. The control mounts worker RPC read-only; the worker mounts the egress socket read-only. Browser profiles and downloaded working files live in bounded temporary storage, not personal host mounts.

Egress permits public IPv4 destinations on ports 80/443 only. It validates all resolved A answers and dials the validated numeric address. Private, loopback, link-local, CGNAT/Tailnet, special ranges and Azure's platform virtual IP are denied. IPv6 is deliberately unsupported. There are connection, stream-size and deadline bounds. Ordinary logs do not record URLs, credentials or page contents.

Stateless reading/conversion/feed jobs have two worker slots, a 75-second deadline and process-group cancellation. Interactive browser control is separate: one action at a time, four sessions, 128-bit handles, idle expiry, and controller reset after timeout/transport failure. Browser handles belong to the owner's worker, not to a distinct authenticated MCP client session. A controller reset can invalidate all that owner's browser sessions.

## Evidence and limitations

Live checks have covered public HTTP/HTTPS, denied destinations, all four reader modes, PDF/RSS, browser interaction, same-origin private subresources and WebSockets, public WSS, and cancellation without surviving browser processes. Scripts are retained under `scripts/check_*.py`; historical logs are under private `.state/`. Application-level tests do not prove renderer-exploit containment or public-deployment safety.

Gateway/MCP admission and transfer limits are distinct from worker limits. Worker RPC disconnect cleanup has been tested; complete end-to-end cancellation propagation through every gateway route has not. Broad client acceptance testing exercised Office conversion, cache version retention and refresh, feeds, browser limits and real research. Exact document fidelity, cache races, sustained workload reliability and all timeout paths are not established.

Main-content extraction remains imperfect. Standard Markdown favors structure; light extraction can lose indentation/tables. Saved text and successful extraction status are not guarantees of fidelity. Output bounds and targeted retrieval do not repair extraction. CAPTCHA access and reliable unique pagination are not promised.

## Data and operations

Redis retains metadata; MinIO retains artifacts. Refresh can update the URL lookup while preserving older content-addressed document IDs. Retention/pinning code remains useful maintenance functionality, not dead code. Cleanup must coordinate writers and preserve pinned/shared artifacts; automatic retention, quotas, backup orchestration and account deletion are not deployed.

Runtime configuration/secrets, cached evidence and data volumes must survive repository cleanup. The original personal gateway is unrelated to this deployment and must remain untouched. Source provenance is recorded in ORIGIN.md.

## Before any public or multi-user deployment

Require reviewed TLS/authentication, per-owner provisioning and isolation tests, appropriate browser sandbox hardening, global/per-owner quotas, end-to-end cancellation and recovery tests, reproducible builds, secret-safe diagnostics, and tested backup/restore/deletion procedures. Separate containers alone are not a sufficient security guarantee. Client-supplied tenant IDs must never authorize routing.
