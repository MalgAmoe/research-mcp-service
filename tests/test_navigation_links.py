import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from playwright.async_api import TimeoutError as BrowserTimeout
from research_gateway.pdf_links import extract_pdf_links, link_metadata


def pdf_fixture():
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << >> /Annots [4 0 R 5 0 R] >>',
               b'<< /Type /Annot /Subtype /Link /Rect [10 10 100 30] /A << /S /URI /URI (https://example.org/evidence) >> >>',
               b'<< /Type /Annot /Subtype /Link /Rect [10 40 100 60] /Dest [3 0 R /Fit] >>']
    data = b'%PDF-1.4\n'
    offsets = [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(data))
        data += str(index).encode() + b' 0 obj\n' + value + b'\nendobj\n'
    xref = len(data)
    data += b'xref\n0 6\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets[1:])
    return data + f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()


class PDFLinksTests(unittest.TestCase):
    def test_real_pdf_annotations(self):
        result = extract_pdf_links(pdf_fixture())
        self.assertEqual(result['links'], [{'page': 1, 'uri': 'https://example.org/evidence'},
                                           {'page': 1, 'destination_page': 1}])
        self.assertEqual(result['status'], 'complete')

    def test_corrupt_pdf_metadata_fails_without_claiming_no_links(self):
        self.assertEqual(link_metadata(b'bad PDF', '.pdf')['pdf_links']['status'], 'failed')
        self.assertEqual(link_metadata(b'text', '.txt'), {})


class NavigationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/browser_controller.py'
        spec = importlib.util.spec_from_file_location('navigation_controller', path)
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.module
        spec.loader.exec_module(self.module)
        self.page = SimpleNamespace(url='https://example.org/', wait_for_function=AsyncMock(),
                                    go_back=AsyncMock(return_value=None))
        self.module.sessions['s'] = self.module.BrowserSession('s', 'standard', None, self.page)
        self.module.observe_session = AsyncMock(return_value={'visible_text': 'observation'})

    async def test_conditional_timeout_retains_observation(self):
        self.page.wait_for_function.side_effect = BrowserTimeout('timeout')
        result = await self.module.wait_for_session({'session_id': 's', 'text': 'new results', 'timeout_ms': 10})
        self.assertEqual(result['wait_condition']['outcome'], 'timed_out')
        self.assertEqual(result['visible_text'], 'observation')
        self.page.wait_for_function.assert_awaited_once()

    async def test_null_history_result_is_not_claimed_as_navigation(self):
        result = await self.module.history_session({'session_id': 's', 'direction': 'back'})
        self.assertFalse(result['history']['url_changed'])
        self.assertEqual(result['history']['outcome'], 'same_document_or_no_entry')
