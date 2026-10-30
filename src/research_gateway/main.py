from __future__ import annotations

import asyncio
import httpx

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from .config import settings
from research_mcp_service.build_info import SOURCE_SNAPSHOT
from .errors import GatewayError
from .models import (
    BatchFetchRequest,
    BatchFetchResponse,
    ConvertDocumentRequest,
    ConvertedDocument,
    Document,
    ReadUrlRequest,
    RssFeed,
    RssFeedEntry,
    RssFetchRequest,
    RssFetchResponse,
    RssListResponse,
    RssSubscribeRequest,
)
from .storage import artifact_store, redis_store
from .services import (
    batch_fetch,
    convert_document,
    get_document,
    list_recent_documents,
    read_url,
    rss_fetch,
    rss_get_entries,
    rss_get_entry,
    rss_list_feeds,
    rss_mark_read,
    rss_preview,
    rss_subscribe,
)

app = FastAPI(
    title="Local Web Research Gateway",
    version="0.1.0",
    description="Local-only web research interface for agents.",
)


@app.middleware("http")
async def retention_guard(request, call_next):
    # A restart during offline cleanup must not admit new reads/fetches. Existing
    # in-flight writers are drained by stopping the gateway before cleanup.
    if request.url.path not in {"/health", "/health/dependencies", "/capabilities"}:
        if await redis_store.redis.exists("retention:maintenance_lock"):
            return JSONResponse(status_code=503, content={"error": "retention_maintenance", "message": "Cache maintenance in progress; retry later."})
    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "source_snapshot": SOURCE_SNAPSHOT}


@app.get("/capabilities")
async def capabilities() -> dict[str, object]:
    return {
        "read_strategies": {
            "light": "fast static extraction: HTTP fetch + trafilatura/basic text fallback",
            "standard": "Playwright Chromium + structured Markdown (code, tables, links)",
            "browser": "browser-rendered extraction; profile standard or stealth",
            "auto": "light first, then structured Playwright and browser fallback when extracted text is unusable",
        },
        "search": {
            "primary": "searxng" if settings.search_provider == "auto" else settings.search_provider,
            "ddgs_backends": settings.ddgs_backend.split(","),
            "fallbacks": ["ddgs"] if settings.search_provider == "auto" else [],
        },
        "batch_fetch": {"max_urls": 15, "max_concurrency": 10, "default_concurrency": 5},
        "storage": ["redis", "s3"],
        "browser_profiles": {
            "standard": "Playwright Chromium; use with strategy=browser",
            "stealth": "Camoufox; set strategy=browser AND browser_profile=stealth",
        },
        "document_conversion": {
            "strategies": {
                "text": "lightweight parsers",
            },
            "supported_types": ["pdf", "txt", "md", "html", "docx", "pptx"],
            "detected_file_types": ["xlsx", "csv", "json", "parquet", "zip"],
            "methods": {
                "pdf": "pypdfium2",
                "txt": "text decode",
                "md": "text decode",
                "html": "trafilatura",
                "docx": "python-docx",
                "pptx": "python-pptx",
            },
        },
    }


@app.get("/health/dependencies")
async def health_dependencies() -> dict[str, str]:
    status: dict[str, str] = {}
    try:
        await redis_store.ping()
        status["redis"] = "ok"
        status["maintenance"] = "locked" if await redis_store.redis.exists('retention:maintenance_lock') else "ok"
    except Exception:
        status["redis"] = "unavailable"
        status["maintenance"] = "unknown"
    try:
        await asyncio.to_thread(artifact_store.ensure_buckets)
        status["s3"] = "ok"
    except Exception:
        status["s3"] = "unavailable"
    try:
        if not settings.worker_socket:
            raise ValueError('Worker socket missing')
        transport = httpx.AsyncHTTPTransport(uds=settings.worker_socket)
        async with httpx.AsyncClient(transport=transport, timeout=3, trust_env=False) as client:
            response = await client.get('http://worker/health')
            response.raise_for_status()
            status["worker"] = "ok" if response.json().get('status') == 'ok' else "unavailable"
    except Exception:
        status["worker"] = "unavailable"
    return status


@app.post("/read_url", response_model=Document)
async def api_read_url(req: ReadUrlRequest) -> Document:
    try:
        return await read_url(req)
    except GatewayError as exc:
        raise exc.to_http() from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "internal_error", "message": "Unexpected read_url failure"},
        ) from exc


@app.post("/batch_fetch", response_model=BatchFetchResponse)
async def api_batch_fetch(req: BatchFetchRequest) -> BatchFetchResponse:
    try:
        return await batch_fetch(req)
    except GatewayError as exc:
        raise exc.to_http() from exc


@app.post("/convert_document", response_model=ConvertedDocument)
async def api_convert_document(req: ConvertDocumentRequest) -> ConvertedDocument:
    try:
        return await convert_document(req)
    except GatewayError as exc:
        raise exc.to_http() from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "internal_error", "message": "Unexpected convert_document failure"},
        ) from exc


@app.get("/documents/recent", response_model=list[Document])
async def api_list_recent_documents(
    limit: int = Query(default=20, ge=1, le=100),
    include_markdown: bool = Query(default=False),
) -> list[Document]:
    return await list_recent_documents(limit=limit, include_markdown=include_markdown)


@app.get("/documents/{doc_id}", response_model=Document)
async def api_get_document(
    doc_id: str,
    include_markdown: bool = Query(default=True),
) -> Document:
    doc = await get_document(doc_id, include_markdown=include_markdown)
    if not doc:
        raise HTTPException(status_code=404, detail="document not found")
    return doc


@app.get("/documents/{doc_id}/artifacts/{kind}")
async def api_get_document_artifact(doc_id: str, kind: str) -> Response:
    if kind not in {"original", "markdown"}:
        raise HTTPException(
            status_code=400,
            detail={"code": "unsupported_artifact_kind", "message": "Artifact kind must be original or markdown"},
        )

    doc = await get_document(doc_id, include_markdown=False)
    if not doc:
        raise HTTPException(status_code=404, detail="document not found")

    uri = doc.artifacts.raw_html if kind == "original" else doc.artifacts.markdown
    if not uri:
        raise HTTPException(
            status_code=404,
            detail={"code": "artifact_not_found", "message": f"No {kind} artifact is recorded for this document"},
        )

    try:
        artifact = artifact_store.get_object_uri(uri)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "invalid_artifact_uri", "message": str(exc), "uri": uri},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "artifact_not_found", "message": "Could not load artifact", "uri": uri},
        ) from exc

    return Response(
        content=artifact.data,
        media_type=artifact.content_type,
        headers={"content-disposition": f'attachment; filename="{artifact.filename}"'},
    )


@app.post("/rss/subscribe", response_model=RssFeed)
async def api_rss_subscribe(req: RssSubscribeRequest) -> RssFeed:
    try:
        feed = await rss_subscribe(req.feed_url)
        return feed
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "rss_subscribe_failed", "message": str(exc)}) from exc


@app.get("/rss/feeds", response_model=RssListResponse)
async def api_rss_list_feeds() -> RssListResponse:
    feeds = await rss_list_feeds()
    return RssListResponse(feeds=feeds)


@app.get("/rss/preview", response_model=RssFetchResponse)
async def api_rss_preview(
    feed_url: str = Query(min_length=1),
    max_entries: int = Query(default=20, ge=1, le=100),
) -> RssFetchResponse:
    try:
        return await rss_preview(feed_url, max_entries=max_entries)
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "rss_preview_failed", "message": str(exc)}) from exc


@app.post("/rss/fetch", response_model=RssFetchResponse)
async def api_rss_fetch(req: RssFetchRequest) -> RssFetchResponse:
    try:
        return await rss_fetch(req.feed_url, max_entries=req.max_entries, force_refresh=req.force_refresh)
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "rss_fetch_failed", "message": str(exc)}) from exc


@app.get("/rss/entries")
async def api_rss_entries(
    feed_url: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    include_read: bool = Query(default=False),
) -> list[RssFeedEntry]:
    return await rss_get_entries(feed_url=feed_url, limit=limit, include_read=include_read)


@app.get("/rss/entries/{entry_id}", response_model=RssFeedEntry)
async def api_rss_get_entry(entry_id: str) -> RssFeedEntry:
    entry = await rss_get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="entry not found")
    return entry


@app.post("/rss/entries/{entry_id}/read")
async def api_rss_mark_read(entry_id: str, is_read: bool = Query(default=True)) -> RssFeedEntry:
    entry = await rss_mark_read(entry_id, is_read)
    if not entry:
        raise HTTPException(status_code=404, detail="entry not found")
    return entry
