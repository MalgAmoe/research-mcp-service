from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from minio import Minio
from redis.asyncio import Redis

from .config import settings
from .models import Document, RssFeed, RssFeedEntry


class RedisStore:
    def __init__(self, redis_url: str) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)

    async def ping(self) -> bool:
        return bool(await self.redis.ping())

    async def get_by_url(self, url: str) -> Document | None:
        doc_id = await self.redis.get(f"url_to_doc:{url}")
        if not doc_id:
            return None
        return await self.get_document(doc_id)

    async def save_document(self, doc: Document) -> Document:
        # Redis keeps metadata/state only. Heavy content stays in MinIO.
        metadata_doc = doc.model_copy(update={"markdown": None})
        pipe = self.redis.pipeline()
        pipe.set(f"doc:{doc.doc_id}", metadata_doc.model_dump_json())
        pipe.set(f"url_to_doc:{doc.url}", doc.doc_id)
        if doc.canonical_url:
            pipe.set(f"url_to_doc:{doc.canonical_url}", doc.doc_id)
        pipe.zadd("zset:docs:recent", {doc.doc_id: doc.retrieved_at.timestamp()})
        await pipe.execute()
        return doc

    async def get_document(self, doc_id: str) -> Document | None:
        raw = await self.redis.get(f"doc:{doc_id}")
        if not raw:
            return None
        return Document.model_validate_json(raw)

    async def list_recent_documents(self, limit: int = 20) -> list[Document]:
        doc_ids = await self.redis.zrevrange("zset:docs:recent", 0, max(limit - 1, 0))
        docs: list[Document] = []
        for doc_id in doc_ids:
            doc = await self.get_document(doc_id)
            if doc:
                docs.append(doc)
        return docs

    # ── RSS ──────────────────────────────────────────────────────────────────

    async def save_rss_feed(self, key: str, feed: RssFeed) -> None:
        await self.redis.set(f"rss:feed:{key}", feed.model_dump_json())
        await self.redis.sadd("rss:feeds", key)

    async def get_rss_feed(self, key: str) -> RssFeed | None:
        raw = await self.redis.get(f"rss:feed:{key}")
        if not raw:
            return None
        return RssFeed.model_validate_json(raw)

    async def list_rss_feeds(self) -> list[RssFeed]:
        keys = await self.redis.smembers("rss:feeds")
        feeds: list[RssFeed] = []
        for key in keys:
            feed = await self.get_rss_feed(key)
            if feed:
                feeds.append(feed)
        return feeds

    async def save_rss_entry(self, feed_key: str, entry: RssFeedEntry) -> None:
        pipe = self.redis.pipeline()
        pipe.set(f"rss:entry:{entry.entry_id}", entry.model_dump_json())
        pipe.zadd(f"rss:entries:{feed_key}", {entry.entry_id: (entry.published_at or entry.fetched_at).timestamp()})
        await pipe.execute()

    async def get_rss_entry(self, entry_id: str) -> RssFeedEntry | None:
        raw = await self.redis.get(f"rss:entry:{entry_id}")
        if not raw:
            return None
        return RssFeedEntry.model_validate_json(raw)

    async def get_rss_entry_ids(self, feed_key: str) -> list[str]:
        return await self.redis.zrevrange(f"rss:entries:{feed_key}", 0, -1)

    async def list_rss_entries(self, feed_key: str, limit: int = 50, include_read: bool = False) -> list[RssFeedEntry]:
        ids = await self.redis.zrevrange(f"rss:entries:{feed_key}", 0, max(limit - 1, 0))
        entries: list[RssFeedEntry] = []
        for entry_id in ids:
            entry = await self.get_rss_entry(entry_id)
            if entry and (include_read or not entry.is_read):
                entries.append(entry)
        return entries

    async def update_rss_entry_read(self, entry_id: str, is_read: bool) -> RssFeedEntry | None:
        entry = await self.get_rss_entry(entry_id)
        if not entry:
            return None
        updated = entry.model_copy(update={"is_read": is_read})
        await self.redis.set(f"rss:entry:{entry_id}", updated.model_dump_json())
        return updated


@dataclass(frozen=True)
class ArtifactObject:
    data: bytes
    content_type: str
    bucket: str
    object_name: str

    @property
    def filename(self) -> str:
        return self.object_name.rsplit("/", 1)[-1]


class ArtifactStore:
    def __init__(self) -> None:
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self._ready = False

    def ping(self) -> bool:
        return self.client.bucket_exists(settings.minio_bucket_raw) or True

    def ensure_buckets(self) -> None:
        if self._ready:
            return
        for bucket in (settings.minio_bucket_raw, settings.minio_bucket_processed, settings.minio_bucket_documents):
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)
        self._ready = True

    def put_bytes(self, bucket: str, object_name: str, data: bytes, content_type: str) -> str:
        self.ensure_buckets()
        self.client.put_object(
            bucket,
            object_name,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return f"s3://{bucket}/{object_name}"

    def put_text(self, bucket: str, object_name: str, text: str, content_type: str) -> str:
        return self.put_bytes(bucket, object_name, text.encode("utf-8"), content_type)

    def get_text(self, bucket: str, object_name: str) -> str:
        response = self.client.get_object(bucket, object_name)
        try:
            return response.read().decode("utf-8")
        finally:
            response.close()
            response.release_conn()

    def get_text_uri(self, uri: str) -> str:
        return self.get_object_uri(uri).data.decode("utf-8")

    def get_object_uri(self, uri: str) -> ArtifactObject:
        if not uri.startswith("s3://"):
            raise ValueError(f"unsupported artifact uri: {uri}")
        bucket_and_key = uri.removeprefix("s3://")
        bucket, object_name = bucket_and_key.split("/", 1)
        stat = self.client.stat_object(bucket, object_name)
        response = self.client.get_object(bucket, object_name)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()
        return ArtifactObject(
            data=data,
            content_type=stat.content_type or "application/octet-stream",
            bucket=bucket,
            object_name=object_name,
        )


redis_store = RedisStore(settings.redis_url)
artifact_store = ArtifactStore()
