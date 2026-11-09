import asyncio
import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

import httpx

from research_mcp_service.capacity import acquisition_concurrency
from research_mcp_service.worker_client import WorkerClient
from research_mcp_service.worker_server import create_worker_app


class CapacityTests(unittest.IsolatedAsyncioTestCase):
    def test_configuration_bounds(self):
        for value in ['0', '5', 'invalid']:
            with patch.dict(os.environ, {'ACQUISITION_CONCURRENCY': value}):
                with self.assertRaises(ValueError):
                    acquisition_concurrency()
        with patch.dict(os.environ, {'ACQUISITION_CONCURRENCY': '3'}):
            self.assertEqual(acquisition_concurrency(), 3)

    async def test_three_jobs_and_fourth_rejected(self):
        ready = asyncio.Event()
        release = asyncio.Event()
        count = 0

        async def execute(job):
            nonlocal count
            count += 1
            if count == 3:
                ready.set()
            await release.wait()
            return {'result': {}}

        with patch.dict(os.environ, {'ACQUISITION_CONCURRENCY': '3'}):
            app = create_worker_app(execute)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://worker') as client:
            tasks = [asyncio.create_task(client.post('/run', json={'action': 'read', 'request': {}})) for _ in range(3)]
            try:
                await asyncio.wait_for(ready.wait(), 3)
                self.assertEqual((await client.post('/run', json={'action': 'read', 'request': {}})).status_code, 503)
            finally:
                release.set()
                results = await asyncio.gather(*tasks)
            self.assertTrue(all(result.status_code == 200 for result in results))

    async def test_client_queue_and_metrics(self):
        active = peak = 0

        async def handle(request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(.03)
            active -= 1
            return httpx.Response(200, json={'result': {}})

        with patch.dict(os.environ, {'ACQUISITION_CONCURRENCY': '3'}):
            client = WorkerClient('/test.sock', transport=httpx.MockTransport(handle))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            await asyncio.gather(*(client.run('read', {'url': 'https://private.example/secret'}) for _ in range(4)))
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(peak, 3)
        self.assertEqual(len(rows), 4)
        self.assertTrue(any(row['queue_ms'] >= 20 for row in rows))
        self.assertTrue(all(row['outcome'] == 'ok' for row in rows))
        self.assertNotIn('private.example', output.getvalue())

    async def test_error_metric(self):
        client = WorkerClient('/test.sock', transport=httpx.MockTransport(lambda request: httpx.Response(504)))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(Exception):
                await client.run('read', {})
        self.assertEqual(json.loads(output.getvalue())['outcome'], 'worker_timeout')
