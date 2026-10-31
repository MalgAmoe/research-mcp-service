import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from research_gateway import main, services
from research_gateway.errors import GatewayError
from research_gateway.models import RssFeed, RssFeedEntry
from research_gateway.storage import RedisStore
from research_mcp_service.gateway_server import HostedRoutes
from research_mcp_service.server import BearerAuth

URL = 'https://example.org/feed.xml'
OTHER = 'https://example.org/other.xml'


class FeedStore:
    def __init__(self):
        self.feeds = {}
        self.entries = {}
        self.index = {}

    async def get_rss_feed(self, key):
        return self.feeds.get(key)

    async def save_rss_feed(self, key, feed):
        self.feeds[key] = feed

    async def unsubscribe_rss_feed(self, key):
        return self.feeds.pop(key, None) is not None

    async def update_subscribed_rss_feed(self, key, feed):
        if key not in self.feeds:
            return False
        self.feeds[key] = feed
        return True

    async def get_rss_entry_ids(self, key):
        return list(self.index.get(key, []))

    async def save_rss_entry(self, key, entry):
        self.entries[entry.entry_id] = entry
        self.index.setdefault(key, []).append(entry.entry_id)

    async def list_rss_feeds(self):
        return list(self.feeds.values())

    async def list_rss_entries(self, key, limit=50, include_read=False):
        return [self.entries[i] for i in self.index.get(key, [])
                if include_read or not self.entries[i].is_read][:limit]

    async def get_rss_entry(self, entry_id):
        return self.entries.get(entry_id)


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_atomic_unsubscribe_only_removes_subscription_keys(self):
        store = RedisStore.__new__(RedisStore)
        store.redis = MagicMock()
        pipe = store.redis.pipeline.return_value
        pipe.execute = AsyncMock(side_effect=[[1, 1], [0, 0]])
        self.assertTrue(await store.unsubscribe_rss_feed('feed-key'))
        self.assertFalse(await store.unsubscribe_rss_feed('feed-key'))
        self.assertEqual(pipe.srem.call_args_list[0].args, ('rss:feeds', 'feed-key'))
        self.assertEqual(pipe.delete.call_args_list[0].args, ('rss:feed:feed-key',))
        self.assertEqual(pipe.delete.call_count, 2)

    async def test_subscribe_is_a_single_transaction(self):
        store = RedisStore.__new__(RedisStore)
        store.redis = MagicMock()
        pipe = store.redis.pipeline.return_value
        pipe.execute = AsyncMock(return_value=[True, 1])
        await store.save_rss_feed('feed-key', RssFeed(feed_url=URL))
        pipe.set.assert_called_once()
        pipe.sadd.assert_called_once_with('rss:feeds', 'feed-key')
        pipe.execute.assert_awaited_once()


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeat_unsubscribe_preserves_entries_read_state_and_other_feed(self):
        store = FeedStore()
        key = services._feed_key(URL)
        entry = RssFeedEntry(entry_id='rss_saved', feed_url=URL, is_read=True)
        await store.save_rss_entry(key, entry)
        with patch.object(services, 'redis_store', store), patch.object(services, '_fetch_parsed_feed', new_callable=AsyncMock) as fetch:
            await services.rss_subscribe(URL)
            await services.rss_subscribe(OTHER)
            result = await services.rss_unsubscribe(URL)
            self.assertTrue(result.unsubscribed)
            self.assertTrue(result.cached_entries_preserved)
            self.assertFalse((await services.rss_unsubscribe(URL)).unsubscribed)
            self.assertEqual([f.feed_url for f in await services.rss_list_feeds()], [OTHER])
            self.assertEqual(await services.rss_get_entries(URL, include_read=True), [entry])
            self.assertEqual(await services.rss_get_entries(include_read=True), [])
            self.assertTrue((await services.rss_get_entry(entry.entry_id)).is_read)
            restored = await services.rss_subscribe(URL)
            self.assertEqual(restored.entry_count, 1)
            self.assertIn(key, store.feeds)
            self.assertEqual(store.entries[entry.entry_id], entry)
            fetch.assert_not_awaited()

    async def test_explicit_fetch_resubscribes_without_overwriting_read_state(self):
        store = FeedStore()
        key = services._feed_key(URL)
        entry_id = services._entry_id(URL, URL + '?item=1', 'Item', None)
        entry = RssFeedEntry(entry_id=entry_id, feed_url=URL, is_read=True)
        await store.save_rss_entry(key, entry)
        parsed = {'entries': [{'link': URL + '?item=1', 'title': 'Item'}]}
        with patch.object(services, 'redis_store', store), patch.object(services, '_fetch_parsed_feed', new_callable=AsyncMock, return_value=parsed):
            await services.rss_fetch(URL)
            self.assertIn(key, store.feeds)
            self.assertTrue(store.entries[entry_id].is_read)

    async def test_unsubscribe_wins_over_inflight_success_or_failure(self):
        for fail in [False, True]:
            with self.subTest(fetch_fails=fail):
                store = FeedStore()
                started, release = asyncio.Event(), asyncio.Event()
                async def fetch(url):
                    started.set()
                    await release.wait()
                    if fail:
                        raise GatewayError('rss_fetch_failed', 'Test fetch failure', status_code=502)
                    return {'entries': [{'title': 'Saved during fetch', 'link': URL + '?item=2'}]}
                with patch.object(services, 'redis_store', store), patch.object(services, '_fetch_parsed_feed', side_effect=fetch):
                    task = asyncio.create_task(services.rss_fetch(URL))
                    try:
                        await asyncio.wait_for(started.wait(), 2)
                        self.assertTrue((await services.rss_unsubscribe(URL)).unsubscribed)
                    finally:
                        release.set()
                    if fail:
                        with self.assertRaises(GatewayError):
                            await task
                    else:
                        await task
                        self.assertEqual(len(store.entries), 1)
                    self.assertEqual(await services.rss_list_feeds(), [])


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_route_auth_validation_and_maintenance_guard(self):
        token = 't' * 48
        store = SimpleNamespace(redis=SimpleNamespace(exists=AsyncMock(return_value=0)),
                                unsubscribe_rss_feed=AsyncMock(return_value=True))
        app = BearerAuth(HostedRoutes(main.app), token)
        with patch.object(main, 'redis_store', store), patch.object(services, 'redis_store', store):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://control') as client:
                self.assertEqual((await client.post('/rss/unsubscribe', json={'feed_url': URL})).status_code, 401)
                store.unsubscribe_rss_feed.assert_not_awaited()
                client.headers['Authorization'] = 'Bearer ' + token
                self.assertEqual((await client.post('/rss/unsubscribe', json={'feed_url': ''})).status_code, 422)
                response = await client.post('/rss/unsubscribe', json={'feed_url': URL})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {'feed_url': URL, 'unsubscribed': True, 'cached_entries_preserved': True})
                store.unsubscribe_rss_feed.assert_awaited_once_with(services._feed_key(URL))
                store.redis.exists.return_value = 1
                self.assertEqual((await client.post('/rss/unsubscribe', json={'feed_url': URL})).status_code, 503)
                self.assertEqual(store.unsubscribe_rss_feed.await_count, 1)
