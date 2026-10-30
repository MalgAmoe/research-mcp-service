"""Explicit cache retention. Dry-run by default; apply only with all writers stopped.

Run through scripts/retention.py on the Docker host; storage access stays inside control's network.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import sys

from redis import Redis
from pydantic import BaseModel, Field

from .config import settings
from .storage import ArtifactStore

PIN_KEY = 'retention:pinned_documents'
LOCK_KEY = 'retention:maintenance_lock'


class StoredDocument(BaseModel):
    # Only validate retention-critical fields: old reader strategy names must
    # not make historical cache records impossible to inspect/clean.
    retrieved_at: datetime
    status: str = 'ready'
    artifacts: dict[str, str | None] = Field(default_factory=dict)


class StoredEntry(BaseModel):
    fetched_at: datetime


def old(timestamp: datetime, cutoff: datetime) -> bool:
    # Fail closed for legacy records without a timezone.
    return timestamp.tzinfo is not None and timestamp < cutoff


def document_candidates(documents, pinned, cutoff):
    return {key for key, doc in documents.items()
            if key not in pinned and doc.status == 'ready' and old(doc.retrieved_at, cutoff)}


def object_candidates(objects, retained_refs, expired_refs, cutoff):
    return [obj for obj in objects if obj['uri'] not in retained_refs
            and (obj['uri'] in expired_refs or old(obj['modified'], cutoff))]


def load_records(redis, pattern, model):
    records = {}
    for key in redis.scan_iter(match=pattern, count=500):
        raw = redis.get(key)
        if raw is not None:
            record = model.model_validate_json(raw)  # Malformed records abort, never guess.
            records[key.split(':', 1)[1] if pattern == 'doc:*' else key.removeprefix('rss:entry:')] = record
    return records


def inventory(redis, artifacts, days=30, rss_days=90):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    docs = load_records(redis, 'doc:*', StoredDocument)
    entries = load_records(redis, 'rss:entry:*', StoredEntry)
    pinned = redis.smembers(PIN_KEY)
    expired = document_candidates(docs, pinned, cutoff)
    refs = lambda doc: {uri for uri in doc.artifacts.values() if uri}
    retained_refs = set().union(*(refs(doc) for key, doc in docs.items() if key not in expired))
    expired_refs = set().union(*(refs(docs[key]) for key in expired))
    objects = []
    for bucket in {settings.s3_bucket_raw, settings.s3_bucket_processed, settings.s3_bucket_documents}:
        if not artifacts.client.bucket_exists(bucket):
            continue
        if artifacts.client.get_bucket_versioning(bucket).status in {'Enabled', 'Suspended'}:
            raise RuntimeError(f'Retention requires unversioned buckets; inspect version history in {bucket} separately')
        for obj in artifacts.client.list_objects(bucket, recursive=True):
            objects.append({'bucket': bucket, 'name': obj.object_name,
                            'uri': f's3://{bucket}/{obj.object_name}',
                            'bytes': obj.size, 'modified': obj.last_modified})
    doomed_objects = object_candidates(objects, retained_refs, expired_refs, cutoff)
    expired_entries = {key for key, entry in entries.items()
                       if old(entry.fetched_at, now - timedelta(days=rss_days))}
    return {
        'documents': docs, 'expired_documents': expired,
        'entries': entries, 'expired_entries': expired_entries,
        'objects': doomed_objects,
        'summary': {
            'document_days': days, 'rss_days': rss_days,
            'documents_total': len(docs), 'documents_pinned': len(pinned & docs.keys()),
            'documents_to_delete': len(expired),
            'rss_entries_total': len(entries), 'rss_entries_to_delete': len(expired_entries),
            'objects_total': len(objects), 'artifact_bytes_total': sum(obj['bytes'] for obj in objects),
            'objects_to_delete': len(doomed_objects),
            'artifact_bytes_to_delete': sum(obj['bytes'] for obj in doomed_objects),
            'redis_used_memory_bytes': redis.info('memory')['used_memory'],
            'unused_seen_members_to_remove': redis.scard('seen_urls') + redis.scard('seen_content_hashes'),
        },
    }


def apply_plan(redis, artifacts, plan):
    # Maintenance is exclusive and fetch writers must be stopped. Delete artifacts
    # first: on failure metadata remains available for a retry. No cross-store
    # transaction is possible; partial failures require rerunning maintenance.
    for obj in plan['objects']:
        artifacts.client.remove_object(obj['bucket'], obj['name'])
    for doc_id in plan['expired_documents']:
        redis.delete(f'doc:{doc_id}')
    remaining = set(plan['documents']) - plan['expired_documents']
    for key in redis.scan_iter(match='url_to_doc:*', count=500):
        if redis.get(key) not in remaining:
            redis.delete(key)
    for doc_id in redis.zscan_iter('zset:docs:recent', count=500):
        if doc_id[0] not in remaining:
            redis.zrem('zset:docs:recent', doc_id[0])
    for entry_id in plan['expired_entries']:
        redis.delete(f'rss:entry:{entry_id}')
    remaining_entries = set(plan['entries']) - plan['expired_entries']
    for key in redis.scan_iter(match='rss:entries:*', count=500):
        for entry_id, _ in redis.zscan_iter(key, count=500):
            if entry_id not in remaining_entries:
                redis.zrem(key, entry_id)
    # Subscriptions are deliberately untouched.
    redis.delete('seen_urls', 'seen_content_hashes')


HOST_CHECK = 'RETENTION_WRITER_CHECK_V1'


def confirm_host_writers():
    # The host launcher checks Docker AFTER this process holds the Redis lock.
    # A restarted control is then blocked from admitting new requests.
    print(HOST_CHECK, flush=True)
    if sys.stdin.readline().strip() != 'WRITERS_STOPPED':
        raise RuntimeError('Host did not confirm stopped writers; nothing deleted')


def guarded_apply(redis, artifacts, days, rss_days, confirm=confirm_host_writers):
    lock = redis.lock(LOCK_KEY, timeout=None, blocking_timeout=0)
    if not lock.acquire():
        raise RuntimeError('Maintenance lock is already held; inspect the active/stale maintenance operation')
    release = True
    try:
        confirm()
        plan = inventory(redis, artifacts, days, rss_days)
        print(json.dumps({'mode': 'apply', **plan['summary']}, indent=2), flush=True)
        release = False
        apply_plan(redis, artifacts, plan)
        release = True
    finally:
        if release:
            lock.release()
        else:
            print('Cleanup failed after deletion began. Maintenance lock retained; keep writers stopped and inspect recovery before clearing it.', file=sys.stderr)
    print('Cleanup complete. Restart MCP/control when ready.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--rss-days', type=int, default=90)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--writers-stopped', action='store_true', help='Confirm ALL other host/remote fetch writers are stopped')
    parser.add_argument('--host-guard-protocol', type=int, choices=[1], help=argparse.SUPPRESS)
    pins = parser.add_mutually_exclusive_group()
    pins.add_argument('--pin', metavar='DOC_ID')
    pins.add_argument('--unpin', metavar='DOC_ID')
    pins.add_argument('--list-pins', action='store_true')
    args = parser.parse_args()
    if args.days < 1 or args.rss_days < 1:
        parser.error('retention must be at least one day')
    if args.apply and (args.pin or args.unpin or args.list_pins):
        parser.error('--apply cannot be combined with pin operations')
    if args.apply and (not args.writers_stopped or args.host_guard_protocol != 1):
        parser.error('Apply requires scripts/retention.py --apply --writers-stopped on the Docker host')
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    artifacts = ArtifactStore()
    if args.list_pins:
        print(json.dumps(sorted(redis.smembers(PIN_KEY)), indent=2)); return
    if args.pin or args.unpin:
        with redis.lock(LOCK_KEY, timeout=None, blocking_timeout=0):
            doc_id = args.pin or args.unpin
            if args.pin:
                if not redis.exists(f'doc:{doc_id}'):
                    raise RuntimeError('Document not found')
                redis.sadd(PIN_KEY, doc_id)
            else:
                redis.srem(PIN_KEY, doc_id)
            print(('Pinned ' if args.pin else 'Unpinned ') + doc_id)
        return
    if not args.apply:
        plan = inventory(redis, artifacts, args.days, args.rss_days)
        print(json.dumps({'mode': 'dry-run', **plan['summary']}, indent=2)); return
    guarded_apply(redis, artifacts, args.days, args.rss_days)


if __name__ == '__main__':
    main()
