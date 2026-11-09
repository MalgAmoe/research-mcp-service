"""Offline CLI checks; no Docker or real credentials."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/client_tokens.py'


class ClientTokensTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / '.secrets/client-tokens.json'

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), '--root', str(self.root), *args],
            capture_output=True, text=True)

    def test_create_list_revoke(self):
        result = self.run_cli('add', 'hermes-vps')
        self.assertEqual(result.returncode, 0, result.stderr)
        token = result.stdout.strip()
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(self.path.read_text()), {'hermes-vps': token})
        self.assertEqual(self.run_cli('show', 'hermes-vps').stdout.strip(), token)
        self.assertNotEqual(self.run_cli('show', 'unknown').returncode, 0)
        listing = self.run_cli('list')
        self.assertIn('hermes-vps', listing.stdout)
        self.assertNotIn(token, listing.stdout + listing.stderr)
        self.assertEqual(self.run_cli('revoke', 'hermes-vps').returncode, 0)
        self.assertEqual(json.loads(self.path.read_text()), {})

    def test_duplicate_does_not_rotate(self):
        self.run_cli('add', 'mrpi')
        before = self.path.read_bytes()
        self.assertNotEqual(self.run_cli('add', 'mrpi').returncode, 0)
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_labels(self):
        for label in ('legacy', '../escape', 'bad label', 'x' * 65):
            self.assertNotEqual(self.run_cli('add', label).returncode, 0)
        self.assertFalse(self.path.exists())

    def test_corrupt_file_not_overwritten_or_disclosed(self):
        self.run_cli('add', 'mrpi')
        bad = '{"secret-do-not-display"'
        self.path.write_text(bad)
        result = self.run_cli('add', 'other')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('secret-do-not-display', result.stdout + result.stderr)
        self.assertEqual(self.path.read_text(), bad)

    def test_permissions_and_symlinks_rejected(self):
        self.run_cli('add', 'mrpi')
        self.path.chmod(0o644)
        self.assertNotEqual(self.run_cli('list').returncode, 0)
        self.path.unlink()
        target = self.root / 'target'
        target.write_text('{}')
        target.chmod(0o600)
        self.path.symlink_to(target)
        self.assertNotEqual(self.run_cli('add', 'other').returncode, 0)
        self.assertEqual(target.read_text(), '{}')

    def test_unknown_revoke_does_not_change_file(self):
        self.run_cli('add', 'mrpi')
        before = self.path.read_bytes()
        self.assertNotEqual(self.run_cli('revoke', 'unknown').returncode, 0)
        self.assertEqual(self.path.read_bytes(), before)

    def test_apply_refuses_old_compose_without_docker(self):
        (self.root / 'compose.deploy.yml').write_text('services: {}')
        result = self.run_cli('apply')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not upgraded', result.stderr)
