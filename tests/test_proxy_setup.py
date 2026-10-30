import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('setup_server', ROOT / 'scripts/setup_server.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
spec = importlib.util.spec_from_file_location('render_proxy', ROOT / 'scripts/render_proxy.py')
proxy = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'setup_server': setup}):
    spec.loader.exec_module(proxy)


class ProxyTests(unittest.TestCase):
    def test_exact_route_origin_limits_and_no_token_injection(self):
        http, location = proxy.render('alpha', 8766, 'https://203.0.113.10', '/alpha/mcp')
        self.assertIn('location = /alpha/mcp', location)
        self.assertIn('proxy_pass http://127.0.0.1:8766/mcp;', location)
        self.assertIn('"https://203.0.113.10" 1;', http)
        self.assertIn('"" 1;', http)
        self.assertIn('default 0;', http)
        self.assertIn('return 403', location)
        self.assertNotIn('proxy_set_header Authorization', location)
        other, _ = proxy.render('beta', 8767, 'https://203.0.113.10', '/beta/mcp')
        self.assertNotIn('mcp_alpha_', other)

    def test_rejects_ambiguous_origins_and_configuration_injection(self):
        for origin in ['http://example.org', 'https://example.org/path', 'https://user@example.org',
                       'https://example.org:443', 'https://example.org?x=1', 'https://example.org;evil',
                       'https://[::1]', 'https://example.org/#fragment']:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                proxy.render('alpha', 8766, origin, '/mcp')
        for path in ['/mcp/', '/a/../mcp', '/mcp;evil', '/mcp?x=1', '/mcp\n}']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                proxy.render('alpha', 8766, 'https://example.org', path)
