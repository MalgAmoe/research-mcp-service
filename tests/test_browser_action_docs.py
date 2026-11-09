"""Keep consequential action conventions visible in the generated tool schema."""
import unittest

from research_mcp_service.browser_features import BrowserAction


class BrowserActionDocumentationTests(unittest.TestCase):
    def test_field_descriptions_and_unchanged_defaults(self):
        fields = BrowserAction.model_json_schema()['properties']
        for name in ['ref', 'selector', 'value', 'destination', 'x', 'y', 'ms']:
            self.assertTrue(fields[name]['description'])
        self.assertIn('visible option label', fields['value']['description'])
        self.assertIn('CSS selector', fields['destination']['description'])
        self.assertIn('positive right', fields['x']['description'])
        self.assertIn('positive down', fields['y']['description'])
        for name in ['x', 'y', 'ms']:
            self.assertEqual(fields[name]['default'], 0)
