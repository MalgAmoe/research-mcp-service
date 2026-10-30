import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import httpx
import yaml
from research_mcp_service.gateway import GatewayClient

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('setup_server', ROOT / 'scripts/setup_server.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def test_independent_storage_and_search_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = [Path(directory) / name for name in ['first', 'second']]
            for root in roots:
                root.mkdir()
                setup.initialize(root, root.name, '127.0.0.1', 28766, 'test')
            a, b = [setup.values(root, '.env.runtime') for root in roots]
            for key in ['S3_ACCESS_KEY', 'S3_SECRET_KEY', 'SEARXNG_SECRET']:
                self.assertNotEqual(a[key], b[key])
                self.assertGreaterEqual(len(a[key]), 20)

    def test_invalid_identity_creates_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for identity in ['', '../personal', 'DEV', 'x\nS3_SECRET_KEY=x', 'a' * 33, '-dev']:
                with self.subTest(identity=identity), self.assertRaises(ValueError):
                    setup.initialize(root, identity, '127.0.0.1', 28766, 'test')
                self.assertEqual(list(root.iterdir()), [])

    def test_pull_failure_stops_before_start(self):
        def run(args, *unused):
            if 'pull' in args:
                raise subprocess.CalledProcessError(1, args)
        with patch('sys.argv', ['setup_server.py', 'up']), patch.object(setup, 'require_server_setup'), \
             patch.object(setup, 'run', side_effect=run) as calls:
            with self.assertRaises(subprocess.CalledProcessError):
                setup.main()
            self.assertEqual(calls.call_count, 2)
            self.assertFalse(any('up' in call.args[0] for call in calls.call_args_list))

    def test_restart_never_builds_installs_or_implicitly_pulls(self):
        with patch('sys.argv', ['setup_server.py', 'up', '--no-pull']), \
             patch.object(setup, 'require_server_setup'), patch.object(setup, 'run') as calls:
            setup.main()
        commands = [call.args[0] for call in calls.call_args_list]
        self.assertEqual(len(commands), 2)
        self.assertTrue(all('build' not in cmd and 'uv' not in cmd for cmd in commands))
        self.assertIn('never', commands[-1])

    def test_private_configuration_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            setup.initialize(root, 'example', '127.0.0.1', 18766, 'test1')
            before = {name: (root / name).read_bytes() for name in setup.FILES}
            for name in setup.FILES:
                self.assertEqual((root / name).stat().st_mode & 0o777, 0o600)
            self.assertNotEqual(before['.secrets/mcp-token'], before['.secrets/gateway-token'])
            self.assertEqual(setup.values(root, '.env.control')['GATEWAY_TOKEN'], before['.secrets/gateway-token'].decode().strip())
            self.assertIn('research-mcp-app-test1', before['.env.runtime'].decode())
            with self.assertRaises(FileExistsError):
                setup.initialize(root, 'example', '127.0.0.1', 18766, 'test1')
            self.assertEqual(before, {name: (root / name).read_bytes() for name in setup.FILES})

    def test_invalid_configuration_leaves_no_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for host, version in [('0.0.0.0', 'test'), ('127.0.0.1', 'x\nSECRET=value')]:
                with self.assertRaises(ValueError):
                    setup.initialize(root, 'example', host, 8766, version)
            self.assertEqual(list(root.iterdir()), [])


class CollisionTests(unittest.TestCase):
    def test_reserved_namespace_or_port_fails_before_docker(self):
        record = dict(instance='alpha', root='/srv/alpha', host='127.0.0.1', port=8766)
        with patch.object(setup, 'capture') as capture:
            for identity, port in [('alpha', 8767), ('beta', 8766)]:
                with self.subTest(identity=identity), self.assertRaises(ValueError):
                    setup.check_collisions(identity, '127.0.0.1', port, [record])
            capture.assert_not_called()

    def test_existing_docker_resource_fails_before_port_checks(self):
        with patch.object(setup, 'capture', return_value='stopped-id'), patch.object(setup, 'port_available') as port:
            with self.assertRaisesRegex(ValueError, 'already owns Docker'):
                setup.check_collisions('alpha', '127.0.0.1', 8766, [])
            port.assert_not_called()

    def test_stopped_container_port_is_reserved(self):
        def capture(args):
            if '--filter' in args:
                return ''
            if args[-2:] == ['ps', '-aq']:
                return 'stopped-id'
            if 'inspect' in args:
                return json.dumps({'6379/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8766'}]})
            return ''
        with patch.object(setup, 'capture', side_effect=capture), patch.object(setup, 'port_available') as port:
            with self.assertRaisesRegex(ValueError, 'existing Docker container'):
                setup.check_collisions('alpha', '127.0.0.1', 8766, [])
            port.assert_not_called()

    def test_initialized_but_stopped_checkout_reserves_port(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); alpha = base / 'alpha'; beta = base / 'beta'
            alpha.mkdir(); beta.mkdir()
            with patch.object(setup, 'REGISTRY', base / 'registry'), \
                 patch.object(setup, 'require_admin'), patch.object(setup, 'trusted_path'), \
                 patch.object(setup, 'capture', return_value=''), patch.object(setup, 'port_available'):
                with patch.object(setup, 'ROOT', alpha):
                    setup.reserve_and_initialize('alpha', '127.0.0.1', 8766, 'test', 'malgamoe/mcps')
                with patch.object(setup, 'ROOT', beta), self.assertRaises(ValueError):
                    setup.reserve_and_initialize('beta', '127.0.0.1', 8766, 'test', 'malgamoe/mcps')
                self.assertEqual(list(beta.iterdir()), [])


class PublishedEndpointTests(unittest.TestCase):
    def test_authenticated_method_rejection_proves_published_reachability(self):
        error = setup.urllib.error.HTTPError('http://127.0.0.1:8766/mcp', 405, 'Method not allowed', {}, None)
        with patch.object(setup, 'values', return_value={'MCP_BIND_HOST': '127.0.0.1', 'MCP_PORT': '8766'}), \
             patch.object(Path, 'read_text', return_value='test-token'), \
             patch.object(setup.urllib.request, 'build_opener') as build, patch('builtins.print'):
            build.return_value.open.side_effect = error
            setup.check_published_endpoint()
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header('Authorization'), 'Bearer test-token')

    def test_connection_or_authentication_failure_is_not_healthy(self):
        for error in [OSError('unreachable'), setup.urllib.error.HTTPError('http://localhost', 401, 'Unauthorized', {}, None)]:
            with patch.object(setup, 'values', return_value={'MCP_BIND_HOST': '127.0.0.1', 'MCP_PORT': '8766'}), \
                 patch.object(Path, 'read_text', return_value='test-token'), \
                 patch.object(setup.urllib.request, 'build_opener') as build:
                build.return_value.open.side_effect = error
                with self.assertRaises(ValueError):
                    setup.check_published_endpoint()


class ComposeTests(unittest.TestCase):
    def test_python_health_commands_parse_after_yaml_decoding(self):
        services = yaml.safe_load((ROOT / 'compose.deploy.yml').read_text())['services']
        for name, service in services.items():
            command = service.get('healthcheck', {}).get('test', [])
            if command[:3] == ['CMD', 'python', '-c']:
                compile(command[3], name + '-healthcheck', 'exec')

    def test_role_and_network_boundaries(self):
        services = yaml.safe_load((ROOT / 'compose.deploy.yml').read_text())['services']
        self.assertEqual(services['mcp']['networks'], ['frontend'])
        self.assertEqual(services['control']['networks'], ['storage'])
        self.assertEqual(services['fetch-worker']['network_mode'], 'none')
        self.assertEqual(set(services['fetch-worker']['environment']), {'FETCH_PROXY'})
        self.assertEqual([name for name, config in services.items() if 'ports' in config], ['mcp'])
        self.assertNotIn('docker.sock', json.dumps(services))
        self.assertTrue(all('build' not in config for config in services.values()))

    def test_only_initializer_receives_host_tokens(self):
        services = yaml.safe_load((ROOT / 'compose.deploy.yml').read_text())['services']
        init = services['credentials']
        self.assertEqual(init['network_mode'], 'none')
        self.assertEqual(init['restart'], 'no')
        self.assertEqual(services['mcp']['user'], '10001:10001')
        self.assertIn('frontend_credentials:/credentials:ro', services['mcp']['volumes'])
        self.assertTrue(all('.secrets' not in json.dumps(config) for name, config in services.items() if name != 'credentials'))


class UnixTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_authenticated_requests_use_socket(self):
        requests = []
        async def handle(reader, writer):
            requests.append(await reader.readuntil(b'\r\n\r\n'))
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 15\r\nConnection: close\r\n\r\n{"status":"ok"}')
            await writer.drain(); writer.close(); await writer.wait_closed()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'control.sock')
            server = await asyncio.start_unix_server(handle, path=path)
            try:
                client = GatewayClient('http://control.invalid', token='x' * 48, socket=path)
                for _ in range(2):
                    self.assertEqual(await client('GET', '/health'), {'status': 'ok'})
                self.assertEqual(len(requests), 2)
                self.assertTrue(all(b'Authorization: Bearer ' + b'x' * 48 in request for request in requests))
            finally:
                server.close(); await server.wait_closed()
