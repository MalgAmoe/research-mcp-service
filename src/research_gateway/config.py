from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    fetch_proxy: str | None = os.getenv("FETCH_PROXY")
    worker_socket: str | None = os.getenv("WORKER_SOCKET")
    searxng_url: str = os.getenv("SEARXNG_URL", "http://searxng:8080")
    search_provider: str = os.getenv("SEARCH_PROVIDER", "auto").lower()
    ddgs_backend: str = os.getenv(
        "DDGS_BACKEND",
        "duckduckgo,yahoo",
    )
    ddgs_region: str = os.getenv("DDGS_REGION", "us-en")
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    s3_endpoint: str = os.getenv("S3_ENDPOINT", "s3:8333")
    s3_access_key: str = os.getenv("S3_ACCESS_KEY", "")
    s3_secret_key: str = os.getenv("S3_SECRET_KEY", "")
    s3_secure: bool = os.getenv("S3_SECURE", "false").lower() == "true"
    s3_bucket_raw: str = os.getenv("S3_BUCKET_RAW", "web-raw")
    s3_bucket_processed: str = os.getenv("S3_BUCKET_PROCESSED", "web-processed")
    s3_bucket_documents: str = os.getenv("S3_BUCKET_DOCUMENTS", "web-documents")


settings = Settings()
