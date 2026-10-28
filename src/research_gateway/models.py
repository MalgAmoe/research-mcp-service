from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class Freshness(StrEnum):
    any = "any"
    day = "day"
    week = "week"
    month = "month"
    year = "year"


class RenderJs(StrEnum):
    auto = "auto"
    never = "never"
    always = "always"


class ReadStrategy(StrEnum):
    light = "light"
    standard = "standard"
    browser = "browser"
    auto = "auto"


class BrowserProfile(StrEnum):
    standard = "standard"
    stealth = "stealth"


class ResearchDepth(StrEnum):
    shallow = "shallow"
    normal = "normal"
    deep = "deep"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class SearchWebRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)
    freshness: Freshness = Freshness.any
    category: Literal["general"] = "general"
    page: int = Field(default=1, ge=1, le=10)
    language: str | None = None
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)


class ResourceType(StrEnum):
    webpage = "webpage"
    document = "document"
    file = "file"
    unknown = "unknown"


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str | None = None
    source: str = "searxng"
    rank: int
    published_at: datetime | None = None
    engines: list[str] = Field(default_factory=list)
    category: str | None = None
    domain: str | None = None
    resource_type: ResourceType = ResourceType.unknown
    detected_suffix: str | None = None


class SearchAttempt(BaseModel):
    provider: str
    status: str
    result_count: int = 0
    engine_failures: list[list[str]] = Field(default_factory=list)
    error_code: str | None = None


class SearchWebResponse(BaseModel):
    query: str
    results: list[SearchResult]
    status: Literal["ok", "degraded", "no_results", "unavailable"] = "ok"
    provider: str = "searxng"
    engine_failures: list[list[str]] = Field(default_factory=list)
    attempts: list[SearchAttempt] = Field(default_factory=list)


class PublicReadRequest(BaseModel):
    url: HttpUrl
    max_chars: int = Field(default=30000, ge=1000, le=50000)


class PublicReadResponse(BaseModel):
    url: str
    final_url: str
    title: str | None = None
    text: str
    excerpt: str
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    word_count: int
    method: str = "safe-http+trafilatura"


class ReadUrlRequest(BaseModel):
    url: HttpUrl
    force_refresh: bool = False
    strategy: ReadStrategy = ReadStrategy.standard
    browser_profile: BrowserProfile = BrowserProfile.standard
    render_js: RenderJs = RenderJs.auto
    include_markdown: bool = True
    include_diagnostics: bool = True


class DocumentStrategy(StrEnum):
    text = "text"
    structured = "structured"


class ConvertDocumentRequest(BaseModel):
    url: HttpUrl
    strategy: DocumentStrategy = DocumentStrategy.text
    include_markdown: bool = True


class Artifacts(BaseModel):
    raw_html: str | None = None
    markdown: str | None = None
    screenshot: str | None = None


class DocumentMetadata(BaseModel):
    domain: str | None = None
    content_hash: str | None = None
    word_count: int | None = None
    language: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ExtractionAttempt(BaseModel):
    tool: str
    status: Literal["success", "failed", "skipped"]
    word_count: int | None = None
    duration_ms: int | None = None
    error: str | None = None


class Document(BaseModel):
    doc_id: str
    url: str
    canonical_url: str | None = None
    title: str | None = None
    markdown: str | None = None
    excerpt: str | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    method: str | None = None
    strategy_requested: ReadStrategy | None = None
    strategy_used: ReadStrategy | None = None
    attempts: list[ExtractionAttempt] = Field(default_factory=list)
    status: Literal["ready", "failed", "processing"] = "ready"
    artifacts: Artifacts = Field(default_factory=Artifacts)
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1)
    max_sources: int = Field(default=5, ge=1, le=20)
    freshness: Freshness = Freshness.any
    depth: ResearchDepth = ResearchDepth.shallow
    read_strategy: ReadStrategy = ReadStrategy.light
    browser_profile: BrowserProfile = BrowserProfile.standard
    include_markdown: bool = False


class BatchFetchRequest(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1, max_length=15)
    strategy: ReadStrategy = ReadStrategy.light
    browser_profile: BrowserProfile = BrowserProfile.standard
    force_refresh: bool = False
    include_markdown: bool = False
    include_diagnostics: bool = True
    max_concurrency: int = Field(default=5, ge=1, le=10)


class ResearchSource(BaseModel):
    doc_id: str
    title: str | None = None
    url: str
    excerpt: str | None = None
    retrieved_at: datetime
    method: str | None = None
    strategy_used: ReadStrategy | None = None
    attempts: list[ExtractionAttempt] = Field(default_factory=list)
    markdown: str | None = None


class ResearchFailure(BaseModel):
    url: str
    code: str = "read_failed"
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ResearchResponse(BaseModel):
    query: str
    job_id: str | None = None
    status: JobStatus = JobStatus.done
    sources: list[ResearchSource]
    failed_urls: list[ResearchFailure] = Field(default_factory=list)


class BatchFetchResponse(BaseModel):
    status: JobStatus = JobStatus.done
    sources: list[ResearchSource]
    failed_urls: list[ResearchFailure] = Field(default_factory=list)


class ConvertedDocument(BaseModel):
    doc_id: str
    url: str
    title: str | None = None
    markdown: str | None = None
    excerpt: str | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    method: str = "document_converter"
    status: Literal["ready", "failed", "processing"] = "ready"
    artifacts: Artifacts = Field(default_factory=Artifacts)
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)


class RssFeed(BaseModel):
    feed_url: str
    title: str | None = None
    description: str | None = None
    site_url: str | None = None
    subscribed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_fetched_at: datetime | None = None
    fetch_status: Literal["ok", "error", "never"] = "never"
    fetch_error: str | None = None
    entry_count: int = 0


class RssFeedEntry(BaseModel):
    entry_id: str
    feed_url: str
    title: str | None = None
    link: str | None = None
    published_at: datetime | None = None
    summary: str | None = None
    content: str | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_read: bool = False


class RssSubscribeRequest(BaseModel):
    feed_url: str = Field(min_length=1)


class RssFetchRequest(BaseModel):
    feed_url: str = Field(min_length=1)
    max_entries: int = Field(default=20, ge=1, le=100)
    force_refresh: bool = False


class RssListResponse(BaseModel):
    feeds: list[RssFeed]


class RssFetchResponse(BaseModel):
    feed: RssFeed
    entries: list[RssFeedEntry]
    new_entries: int = 0


class JobProgress(BaseModel):
    queued: int = 0
    processed: int = 0
    failed: int = 0


class Job(BaseModel):
    job_id: str
    type: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    progress: JobProgress = Field(default_factory=JobProgress)
    result: dict[str, Any] | None = None
    error: str | None = None
