from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    searxng_url: str = os.getenv("SEARXNG_URL", "http://searxng:8080")
    search_provider: str = os.getenv("SEARCH_PROVIDER", "auto").lower()
    ddgs_backend: str = os.getenv(
        "DDGS_BACKEND",
        "duckduckgo,yahoo",
    )
    ddgs_region: str = os.getenv("DDGS_REGION", "us-en")
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "minio:9000")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "")
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "")
    minio_secure: bool = os.getenv("MINIO_SECURE", "false").lower() == "true"
    minio_bucket_raw: str = os.getenv("MINIO_BUCKET_RAW", "web-raw")
    minio_bucket_processed: str = os.getenv("MINIO_BUCKET_PROCESSED", "web-processed")
    minio_bucket_documents: str = os.getenv("MINIO_BUCKET_DOCUMENTS", "web-documents")


settings = Settings()
