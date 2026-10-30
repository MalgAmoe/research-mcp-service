import unittest
from unittest.mock import AsyncMock

from research_mcp_service.wait_ready import wait_ready


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_all_private_dependencies(self):
        client = AsyncMock(side_effect=[ConnectionError('must not be logged'),
            {'redis': 'ok', 's3': 'unavailable', 'worker': 'ok'},
            {'redis': 'ok', 's3': 'ok', 'worker': 'ok', 'maintenance': 'locked'},
            {'redis': 'ok', 's3': 'ok', 'worker': 'ok', 'maintenance': 'ok'}])
        await wait_ready(client, timeout=1, interval=.001)
        self.assertEqual(client.await_count, 4)
        client.assert_awaited_with('GET', '/health/dependencies')

    async def test_deadline_is_bounded_and_does_not_leak_error(self):
        client = AsyncMock(side_effect=RuntimeError('private-detail'))
        with self.assertRaisesRegex(SystemExit, 'startup deadline') as caught:
            await wait_ready(client, timeout=.02, interval=.001)
        self.assertNotIn('private-detail', str(caught.exception))
