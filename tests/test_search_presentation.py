import unittest
from research_mcp_service.presentation import present_search


class PresentationTests(unittest.TestCase):
    def result(self, **updates):
        data = {'query': 'example', 'provider': 'searxng', 'status': 'degraded',
                'results': [{'title': 'Example', 'url': 'https://example.org', 'engines': ['brave']}],
                'attempts': [{'provider': 'searxng', 'status': 'degraded'}],
                'engine_failures': [['duckduckgo', 'CAPTCHA']]}
        data.update(updates)
        return data

    def test_success_is_not_labelled_degraded_and_input_is_unchanged(self):
        source = self.result()
        output = present_search(source)
        self.assertEqual(set(output), {'query', 'results', 'returned_count'})
        self.assertNotIn('engines', output['results'][0])
        self.assertEqual(source['results'][0]['engines'], ['brave'])

    def test_debug_preserves_engine_details(self):
        output = present_search(self.result(), diagnostics=True)
        self.assertEqual(output['diagnostics']['status'], 'degraded')
        self.assertEqual(output['results'][0]['engines'], ['brave'])

    def test_fallback_note_not_added_for_explicit_ddgs(self):
        self.assertIn('backup', present_search(self.result(provider='ddgs'))['notes'][0])
        direct = self.result(provider='ddgs', attempts=[{'provider': 'ddgs', 'status': 'ok'}])
        self.assertNotIn('notes', present_search(direct))

    def test_no_results_and_unavailable_remain_distinct(self):
        empty = present_search(self.result(results=[], status='no_results'))
        failed = present_search(self.result(results=[], status='unavailable'))
        self.assertIn('No results', empty['message'])
        self.assertIn('unavailable', failed['message'])

    def test_material_limitations_remain_visible(self):
        output = present_search(self.result(truncation=['snippet'], warnings=[
            'DDGS per-result engine provenance is unavailable; engines is empty.',
            'Requested language is not independently enforced.']))
        self.assertEqual(len(output['notes']), 2)
        self.assertIn('shortened', output['notes'][0])
        self.assertIn('language', output['notes'][1])
