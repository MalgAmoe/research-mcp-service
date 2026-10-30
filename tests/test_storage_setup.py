import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/init_storage.py'
spec = importlib.util.spec_from_file_location('init_storage', SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class StorageSetupTests(unittest.TestCase):
    def test_private_unique_configuration_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'first', Path(directory) / 'second'
            setup.initialize(first, 'dev')
            setup.initialize(second, 'other-person')
            self.assertEqual(first.stat().st_mode & 0o777, 0o600)
            a = dict(line.split('=', 1) for line in first.read_text().splitlines())
            b = dict(line.split('=', 1) for line in second.read_text().splitlines())
            self.assertEqual(a['TENANT_ID'], 'dev')
            for key in ['S3_ACCESS_KEY', 'S3_SECRET_KEY', 'SEARXNG_SECRET']:
                self.assertNotEqual(a[key], b[key])
                self.assertGreaterEqual(len(a[key]), 20)
            before = first.read_bytes()
            with self.assertRaises(FileExistsError):
                setup.initialize(first, 'dev')
            self.assertEqual(first.read_bytes(), before)

    def test_invalid_identity_creates_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config'
            for identity in ['', '../personal', 'DEV', 'x\nS3_SECRET_KEY=x', 'a' * 33, '-dev']:
                with self.subTest(identity=identity), self.assertRaises(ValueError):
                    setup.initialize(path, identity)
                self.assertFalse(path.exists())
