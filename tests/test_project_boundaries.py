"""Offline repository/deployment checks. Never starts containers."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def compose_configuration():
    spec = importlib.util.spec_from_file_location('boundary_setup', ROOT / 'scripts/setup_server.py')
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        setup.initialize(root, 'offline-tests', '127.0.0.1', 28766, 'offline')
        shutil.copyfile(ROOT / 'compose.deploy.yml', root / 'compose.deploy.yml')
        (root / 'infra').mkdir()
        shutil.copyfile(ROOT / 'infra/searxng-primary.yml', root / 'infra/searxng-primary.yml')
        runtime = setup.values(root, '.env.runtime')
        env = {k: v for k, v in os.environ.items() if k not in runtime and not k.startswith('COMPOSE_')}
        raw = subprocess.check_output(['docker', 'compose', '--env-file', '.env.runtime',
            '-f', 'compose.deploy.yml', 'config', '--format', 'json'], cwd=root, env=env, text=True)
        return json.loads(raw), root


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
    def test_only_mcp_is_published(self):
        config, root = compose_configuration()
        self.assertEqual(config['name'], 'research-mcp-offline-tests')
        self.assertEqual({name for name, service in config['services'].items() if service.get('ports')}, {'mcp'})
        self.assertEqual(config['services']['mcp']['sysctls']['net.ipv4.conf.all.arp_ignore'], '0')
        self.assertNotEqual(config['services']['mcp'].get('network_mode'), 'host')
        port = config['services']['mcp']['ports'][0]
        self.assertEqual(port['host_ip'], '127.0.0.1')
        self.assertEqual(int(port['published']), 28766)
        self.assertEqual(set(config['services']['searxng']['networks']), {'frontend'})
        for mount in config['services']['searxng']['volumes']:
            self.assertTrue(Path(mount['source']).is_relative_to(root))
            self.assertTrue(mount['read_only'])

    @unittest.skipUnless(shutil.which('docker'), 'Docker CLI unavailable; daemon not needed')
    def test_private_project_scoped_storage(self):
        config, root = compose_configuration()
        self.assertTrue(config['networks']['storage']['internal'])
        for name in ['control', 'redis', 's3']:
            self.assertEqual(set(config['services'][name]['networks']), {'storage'})
        self.assertEqual(config['services']['fetch-worker']['network_mode'], 'none')
        for service in config['services'].values():
            self.assertFalse(service.get('extra_hosts'))
            for mount in service.get('volumes', []):
                if mount['type'] == 'bind':
                    self.assertTrue(Path(mount['source']).is_relative_to(root))
                    self.assertTrue(mount.get('read_only'))
        for volume in config['volumes'].values():
            self.assertFalse(volume.get('external'))
            self.assertTrue(volume['name'].startswith('research-mcp-offline-tests_'))
