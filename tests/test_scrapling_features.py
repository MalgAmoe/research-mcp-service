import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from pydantic import ValidationError

from research_mcp_service import browser_features as features
from research_mcp_service.scrapling_backend import start_chromium, render


class FeaturesTests(unittest.IsolatedAsyncioTestCase):
    async def test_extract_budget_counts_all_matches_and_preserves_structure(self):
        page = SimpleNamespace(url='https://example.org/docs/page')
        html = '<body><nav>junk</nav><table><tr><th>A</th></tr><tr><td>1</td></tr></table><a href="../ref">Link</a></body>'
        with patch('research_mcp_service.scrapling_backend.page_html', new=AsyncMock(return_value=html)) as capture:
            r = await features.extract(page, format='markdown')
            self.assertIn('| A |', r['matches'][0])
            self.assertIn('https://example.org/ref', r['matches'][0])
            self.assertNotIn('junk', r['matches'][0])
            r = await features.extract(page, selector='th,td', format='text', max_chars=1, pierce_shadow=True)
            self.assertEqual(r['match_count'], 2)
            self.assertEqual(sum(map(len, r['matches'])), 1)
            self.assertTrue(r['truncated'])
            self.assertTrue(capture.call_args.kwargs['pierce_shadow'])
            attr = await features.extract(page, selector='a::attr(href)', format='text')
            self.assertEqual(attr['matches'], ['../ref'])
            r = await features.extract(page, selector='.absent')
            self.assertEqual(r['matches'], [])
            self.assertFalse(r['truncated'])

    async def test_chain_validates_before_actions_and_reports_partial_effects(self):
        element = SimpleNamespace(click=AsyncMock(), hover=AsyncMock(side_effect=RuntimeError('private')))
        page = SimpleNamespace(locator=Mock(return_value=SimpleNamespace(first=element)))
        with self.assertRaises(ValidationError):
            await features.actions(page, [{'kind': 'click', 'ref': 'e1'}, {'kind': 'evaluate'}])
        element.click.assert_not_awaited()
        r = await features.actions(page, [{'kind': 'click', 'ref': 'e1'}, {'kind': 'hover', 'selector': '.x'}])
        self.assertEqual(r['completed'], 1)
        self.assertEqual(r['failed_action'], 2)
        self.assertNotIn('private', str(r))

    async def test_screenshot_bounds(self):
        page = SimpleNamespace(url='https://example.org/', screenshot=AsyncMock(return_value=b'x' * (1024*1024+1)))
        r = await features.screenshot(page)
        self.assertEqual(r['warnings'][0]['code'], 'screenshot_limit')
        self.assertNotIn('screenshot_base64', r)
        with self.assertRaises(ValueError):
            await features.screenshot(page, ref='e1', selector='#x')

    async def test_session_pins_proxy_and_disables_remote_features(self):
        session = SimpleNamespace(start=AsyncMock(), close=AsyncMock())
        with patch('scrapling.fetchers.AsyncStealthySession', return_value=session) as constructor:
            self.assertIs(await start_chromium(proxy='http://127.0.0.1:3128'), session)
            options = constructor.call_args.kwargs
            self.assertTrue(options['block_webrtc'])
            self.assertFalse(options['google_search'])
            self.assertEqual(options['additional_args']['proxy'], {'server': 'http://127.0.0.1:3128', 'bypass': '<-loopback>'})
            self.assertFalse(options['additional_args']['accept_downloads'])
            self.assertEqual(options['additional_args']['service_workers'], 'block')
            self.assertNotIn('cdp_url', options)
            self.assertEqual(options['extra_flags'], ['--disable-back-forward-cache'])
            session.start.side_effect = RuntimeError('failed')
            with self.assertRaises(RuntimeError):
                await start_chromium()
            session.close.assert_awaited_once()

    async def test_render_closes_on_failed_fetch(self):
        session = SimpleNamespace(fetch=AsyncMock(side_effect=RuntimeError()), close=AsyncMock())
        with patch('research_mcp_service.scrapling_backend.start_chromium', new=AsyncMock(return_value=session)):
            with self.assertRaises(RuntimeError):
                await render('https://example.org/')
            session.close.assert_awaited_once()


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.record = SimpleNamespace(meta={'network_id': 7, 'resource_type': 'fetch'}, url='https://example.org/api',
            method='GET', status=200, body=b'{"value":42}', encoding='utf-8',
            headers={'content-type': 'application/json', 'set-cookie': 'secret-cookie'})
        history = SimpleNamespace(search=Mock(return_value=[self.record]), get=Mock(return_value=self.record),
                                  dropped_count=2, last_id=7)
        self.session = SimpleNamespace(profile='standard', browser_manager=SimpleNamespace(network=history))

    def test_history_is_local_bounded_and_headers_not_exposed(self):
        r = features.network_requests(self.session)
        self.assertEqual(r['requests'][0]['request_id'], 7)
        self.assertEqual(r['dropped_count'], 2)
        self.assertNotIn('secret-cookie', str(r))
        r = features.network_response(self.session, request_id=7, max_chars=3)
        self.assertEqual(r['text'], '{"v')
        self.assertEqual(r['next_offset'], 3)
        self.assertNotIn('secret-cookie', str(r))
        self.session.browser_manager.network.get.return_value = None
        self.assertFalse(features.network_response(self.session, request_id=7)['available'])

    def test_camoufox_does_not_claim_history_support(self):
        self.session.profile = 'stealth'
        with self.assertRaises(ValueError):
            features.network_requests(self.session)
