FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgtk-3-0 libx11-xcb1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md LICENSE ./
# Install dependencies and heavyweight browser assets before application source.
# A minimal package stub lets the editable install point at /app/src; the real
# source is copied afterward, so ordinary code changes reuse this expensive layer.
# Install only our standard Chromium and stealth Camoufox browsers.
RUN mkdir -p src/research_gateway \
    && touch src/research_gateway/__init__.py \
    && uv sync --locked --no-dev --no-cache \
    && playwright install --with-deps chromium \
    && python -m camoufox fetch

COPY src ./src

EXPOSE 8000

CMD ["uvicorn", "research_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
