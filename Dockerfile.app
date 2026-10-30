FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" HOME=/tmp
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-cache
COPY src ./src
COPY README.md LICENSE ./
RUN uv sync --locked --no-dev --no-cache
RUN mkdir -p /control-api /credentials && chown 10001:10001 /control-api /credentials
USER 10001:10001
CMD ["python", "-m", "research_mcp_service.gateway_server"]
