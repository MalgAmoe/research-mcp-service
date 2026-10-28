"""Offline repository/deployment checks. Never starts containers."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProjectBoundaryTests(unittest.TestCase):
    def test_application_source_is_local_not_linked(self):
        for directory in ['src', 'scripts']:
            for path in (ROOT / directory).rglob('*'):
                self.assertFalse(path.is_symlink(), str(path))
                if path.is_file() and path.suffix == '.py':
                    source = path.read_text()
                    self.assertNotIn('/home/malg/', source, str(path))
                    self.assertNotIn('biz/auto', source, str(path))

    def test_package_is_independent(self):
        import tomllib
        project = tomllib.loads((ROOT / 'pyproject.toml').read_text())
        self.assertEqual(project['project']['name'], 'research-mcp-service')
        for dependency in project['project']['dependencies']:
            self.assertNotIn('file:', dependency)
        self.assertNotIn('[tool.uv.sources]', (ROOT / 'pyproject.toml').read_text())

    @unittest.skipUnless(shutil.which('docker'), 'Docker CLI unavailable; daemon not needed')
    def test_search_stack_is_separate_and_loopback_only(self):
        env = {key: value for key, value in os.environ.items() if not key.startswith('COMPOSE_')}
        env.update(MCP_INSTANCE_ID='offline-tests', MCP_SEARCH_PORT='18080',
                   SEARXNG_SECRET='test-only-not-for-deployment')
        raw = subprocess.check_output(['docker', 'compose', '--env-file', os.devnull,
            '-f', str(ROOT / 'compose.search.yml'), 'config', '--format', 'json'],
            cwd=ROOT, env=env, text=True)
        config = json.loads(raw)
        self.assertEqual(config['name'], 'research-mcp-search-offline-tests')
        self.assertEqual(set(config['services']), {'searxng'})
        self.assertFalse(config.get('volumes'))
        service = config['services']['searxng']
        self.assertEqual(service['ports'][0]['host_ip'], '127.0.0.1')
        self.assertEqual(int(service['ports'][0]['published']), 18080)
        for mount in service['volumes']:
            self.assertTrue(Path(mount['source']).resolve().is_relative_to(ROOT))
            self.assertTrue(mount['read_only'])

    @unittest.skipUnless(shutil.which('docker'), 'Docker CLI unavailable; daemon not needed')
    def test_compose_has_private_project_scoped_storage(self):
        env = {key: value for key, value in os.environ.items() if not key.startswith('COMPOSE_')}
        env.update(TENANT_ID='offline-tests', MINIO_ACCESS_KEY='test-only-user',
                   MINIO_SECRET_KEY='test-only-not-for-deployment', SEARXNG_SECRET='test-only-not-for-deployment')
        raw = subprocess.check_output(['docker', 'compose', '--env-file', os.devnull,
            '-f', str(ROOT / 'docker-compose.yml'), 'config', '--format', 'json'],
            cwd=ROOT, env=env, text=True)
        config = json.loads(raw)
        self.assertEqual(config['name'], 'research-mcp-offline-tests')
        for service in config['services'].values():
            self.assertFalse(service.get('ports'))
            self.assertFalse(service.get('extra_hosts'))
            for mount in service.get('volumes', []):
                if mount['type'] == 'bind':
                    self.assertTrue(Path(mount['source']).resolve().is_relative_to(ROOT))
                    self.assertTrue(mount.get('read_only'))
        for volume in config['volumes'].values():
            self.assertFalse(volume.get('external'))
            self.assertTrue(volume['name'].startswith('research-mcp-offline-tests_'))
