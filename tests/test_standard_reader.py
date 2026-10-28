"""Lightweight rendered Markdown contract, without network access."""
import unittest
from unittest.mock import AsyncMock, patch

from research_gateway.models import ReadStrategy, ReadUrlRequest, ExtractionAttempt
from research_gateway.services import _structured_markdown, _read_with_strategy


class MarkdownTests(unittest.TestCase):
    def test_structure_and_conservative_cleanup(self):
        html = '''<html><body><nav>Navigation junk</nav><aside>Sidebar junk</aside>
        <article><header><h1>Technical title</h1></header>
        <pre><code>def example():\n    return 42\n</code></pre>
        <table><tr><th>Name</th><th>Value</th></tr><tr><td>A</td><td>1</td></tr></table>
        <a href="../reference">Reference</a><p>Important evidence</p></article>
        <footer>Footer junk</footer><script>bad()</script></body></html>'''
        result = _structured_markdown(html, 'https://example.org/docs/page')
        self.assertIn('# Technical title', result)
        self.assertIn('def example():\n    return 42', result)
        self.assertIn('| Name | Value |', result)
        self.assertIn('| A | 1 |', result)
        self.assertIn('[Reference](https://example.org/reference)', result)
        self.assertIn('Important evidence', result)
        for junk in ('Navigation junk', 'Sidebar junk', 'Footer junk', 'bad()'):
            self.assertNotIn(junk, result)

    def test_base_url_and_navigation_role(self):
        html = '<base href="/assets/"><div role="navigation">Menu</div><a href="doc">Document</a>'
        result = _structured_markdown(html, 'https://example.org/page')
        self.assertIn('https://example.org/assets/doc', result)
        self.assertNotIn('Menu', result)


class StandardRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_standard_uses_structured_playwright_and_retains_original(self):
        original = '<nav>Menu</nav><p>Article</p>'
        attempt = ExtractionAttempt(tool='playwright', status='success')
        with patch('research_gateway.services._extract_with_playwright', new=AsyncMock(
            return_value=('Article', 'Title', 'playwright+markdownify', attempt, original)
        )) as render:
            req = ReadUrlRequest(url='https://example.org/', strategy=ReadStrategy.standard)
            result = await _read_with_strategy(req)
            render.assert_awaited_once_with(str(req.url), structured=True)
        self.assertEqual(result[2], 'playwright+markdownify')
        self.assertEqual(result[3], ReadStrategy.standard)
        self.assertEqual(result[5], original)
