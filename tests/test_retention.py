import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from research_gateway.models import Document
from research_gateway.retention import document_candidates, object_candidates, apply_plan, StoredDocument, inventory
from research_gateway.main import retention_guard


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.cutoff = self.now - timedelta(days=30)

    def doc(self, name, days, **kwargs):
        return Document(doc_id=name, url='https://example.org/' + name,
                        retrieved_at=self.now - timedelta(days=days), **kwargs)

    def test_age_pins_and_processing(self):
        docs = {'old': self.doc('old', 31), 'new': self.doc('new', 2),
                'pin': self.doc('pin', 100), 'busy': self.doc('busy', 100, status='processing')}
        self.assertEqual(document_candidates(docs, {'pin'}, self.cutoff), {'old'})

    def test_naive_timestamp_is_not_deleted(self):
        doc = self.doc('old', 100)
        doc.retrieved_at = doc.retrieved_at.replace(tzinfo=None)
        self.assertEqual(document_candidates({'old': doc}, set(), self.cutoff), set())

    def test_shared_artifacts_and_recent_orphans_are_preserved(self):
        objects = [{'uri': name, 'modified': self.now - timedelta(days=days)}
                   for name, days in [('shared', 100), ('old-orphan', 100), ('new-orphan', 1), ('expired', 100)]]
        chosen = object_candidates(objects, {'shared'}, {'shared', 'expired'}, self.cutoff)
        self.assertEqual({obj['uri'] for obj in chosen}, {'old-orphan', 'expired'})

    def test_legacy_strategy_names_do_not_block_retention(self):
        doc = StoredDocument.model_validate({'retrieved_at': self.now.isoformat(),
            'strategy_used': 'scrapling', 'artifacts': {'legacy_artifact': 's3://test/legacy'}})
        self.assertEqual(doc.artifacts['legacy_artifact'], 's3://test/legacy')

    def test_inventory_rss_uses_fetch_not_publication_age(self):
        redis = MagicMock(); artifacts = MagicMock()
        redis.scan_iter.side_effect = [[], ['rss:entry:recent', 'rss:entry:old']]
        redis.get.side_effect = [
            '{"fetched_at":"' + self.now.isoformat() + '","published_at":"2000-01-01T00:00:00Z"}',
            '{"fetched_at":"2000-01-01T00:00:00Z"}']
        redis.smembers.return_value = set()
        redis.scard.return_value = 0
        redis.info.return_value = {'used_memory': 100}
        artifacts.client.bucket_exists.return_value = False
        plan = inventory(redis, artifacts)
        self.assertEqual(plan['expired_entries'], {'old'})
        self.assertEqual(plan['summary']['objects_to_delete'], 0)

    def test_artifact_failure_preserves_metadata_for_retry(self):
        redis = MagicMock(); artifacts = MagicMock()
        artifacts.client.remove_object.side_effect = RuntimeError('storage unavailable')
        with self.assertRaises(RuntimeError):
            apply_plan(redis, artifacts, {'objects': [{'bucket': 'test', 'name': 'object'}], 'expired_documents': {'old'}})
        redis.delete.assert_not_called()

    def test_indexes_and_subscriptions(self):
        redis = MagicMock(); artifacts = MagicMock()
        redis.scan_iter.side_effect = [['url_to_doc:old', 'url_to_doc:new'], ['rss:entries:feed']]
        redis.get.side_effect = ['old', 'new']
        redis.zscan_iter.side_effect = [[('old', 1), ('new', 2)], [('entry-old', 1), ('entry-new', 2)]]
        plan = {'objects': [], 'documents': {'old': None, 'new': None}, 'expired_documents': {'old'},
                'entries': {'entry-old': None, 'entry-new': None}, 'expired_entries': {'entry-old'}}
        apply_plan(redis, artifacts, plan)
        redis.delete.assert_any_call('doc:old')
        redis.delete.assert_any_call('url_to_doc:old')
        redis.delete.assert_any_call('rss:entry:entry-old')
        self.assertNotIn(unittest.mock.call('url_to_doc:new'), redis.delete.call_args_list)
        self.assertFalse(any('rss:feed' in str(call) for call in redis.delete.call_args_list))


class MaintenanceGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_requests_blocked_during_maintenance(self):
        next_handler = AsyncMock()
        with patch('research_gateway.main.redis_store.redis.exists', new=AsyncMock(return_value=1)):
            response = await retention_guard(SimpleNamespace(url=SimpleNamespace(path='/read_url')), next_handler)
        self.assertEqual(response.status_code, 503)
        next_handler.assert_not_awaited()

    async def test_health_still_available(self):
        next_handler = AsyncMock(return_value='healthy')
        with patch('research_gateway.main.redis_store.redis.exists', new=AsyncMock()) as exists:
            result = await retention_guard(SimpleNamespace(url=SimpleNamespace(path='/health')), next_handler)
        self.assertEqual(result, 'healthy')
        exists.assert_not_awaited()
