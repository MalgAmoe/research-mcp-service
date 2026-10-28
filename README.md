# Research MCP Service

A new, self-contained project for a hosted research tool service used by a small, approved group, with private environments for each person.

**Status: project skeleton and copied research engine. There is no MCP endpoint or user authentication yet. Do not expose this application publicly.**

## Boundaries

- This repository owns its code. It does not import, mount, symlink, or execute code from the original personal tool project.
- Dependencies are ordinary third-party packages declared in `pyproject.toml` and resolved in `uv.lock`.
- No personal credentials, caches, databases, browser profiles, agent configurations, or Git history were copied.
- The original project and its running services are not part of this deployment.
- Nothing is provisioned or started automatically by cloning/installing this project.

See [DESIGN.md](DESIGN.md) for the security model, first implementation steps, and release gates. See [ORIGIN.md](ORIGIN.md) for the copied source revision and license attribution.

## Included today

- Research engine: search, page reading, document conversion, storage and RSS.
- Chromium/Camoufox interactive controller source, not yet exposed remotely.
- Cache retention/pinning implementation; service-side maintenance orchestration is still to be designed.
- Offline tests for the copied engine and repository isolation boundaries.
- A locked Python environment, Docker build, and a private per-user backend Compose skeleton.

## Local development checks

Python 3.12+ and `uv`:

```bash
uv sync --locked --no-dev
uv run python -m unittest discover -s tests -v
```

These tests do not start Redis, MinIO, SearXNG, browsers, or live model/API calls. Browser binaries are not needed for the offline tests. The Docker build installs Chromium and Camoufox explicitly; do not install extra browsers on the host unless developing the standalone controller.

The Compose file describes ONE private user's backend, not the shared MCP entry point. It publishes no host ports. It requires an administrator-provided tenant ID and unique storage/SearXNG secrets. See `.env.example`; do not reuse credentials from another deployment. The `.env` file is not created by installation.

Different `TENANT_ID` values produce distinct Compose project networks and data volumes when managed from separate tenant configuration directories. Do not override `COMPOSE_PROJECT_NAME` or use `docker compose -p` to point at an existing deployment. Automated provisioning, safe tenant-ID validation, and HTTP access are not implemented yet.

**A separate Compose network is not sufficient protection against malicious URLs or a compromised browser. Network egress enforcement and browser isolation are public-deployment blockers.**

## License

[MIT](LICENSE). Copied notices are retained. Third-party dependencies retain their own licenses.
