import asyncio
import importlib.util
from pathlib import Path
import tempfile
import unittest
import subprocess
from unittest.mock import patch

from research_mcp_service.gateway import GatewayClient

spec = importlib.util.spec_from_file_location('setup_server', Path(__file__).resolve().parents[1] / 'scripts/setup_server.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def test_image_pull_failure_stops_before_build_or_start(self):
        with patch('sys.argv', ['setup_server.py', 'up']), \
             patch.object(setup, 'require_server_setup'), \
             patch.object(setup, 'run', side_effect=subprocess.CalledProcessError(1, ['docker', 'compose', 'pull'])) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                setup.main()
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][-3:], ['pull', 's3', 'redis'])

    def test_registry_preflight_precedes_build_but_is_not_needed_for_restart(self):
        with patch('sys.argv', ['setup_server.py', 'up']), \
             patch.object(setup, 'require_server_setup'), patch.object(setup, 'run') as run:
            setup.main()
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][-3:], ['pull', 's3', 'redis'])
        self.assertEqual(commands[1][-2:], ['pull', 'searxng'])
        self.assertEqual(commands[2][:2], ['uv', 'sync'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.venv/bin').mkdir(parents=True)
            (root / '.venv/bin/python').touch()
            with patch('sys.argv', ['setup_server.py', 'up', '--no-build']), \
                 patch.object(setup, 'ROOT', root), patch.object(setup, 'require_server_setup'), \
                 patch.object(setup, 'run') as run:
                setup.main()
            self.assertEqual(run.call_count, 2)
            self.assertTrue(all('up' in call.args[0] and 'pull' not in call.args[0] for call in run.call_args_list))

    def test_private_complete_configuration_no_overwrite_and_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            setup.initialize(root, 'example', '127.0.0.1', 18766, 18081)
            before = {name: (root / name).read_bytes() for name in setup.FILES}
            for name in setup.FILES:
                self.assertEqual((root / name).stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / '.state').stat().st_mode & 0o777, 0o700)
            self.assertEqual((root / '.secrets').stat().st_mode & 0o777, 0o700)
            self.assertEqual(setup.values(root, '.env.control')['GATEWAY_TOKEN'], (root / '.secrets/gateway-token').read_text().strip())
            self.assertNotEqual(before['.secrets/gateway-token'], before['.secrets/mcp-token'])
            self.assertIn('MCP_GATEWAY_SOCKET=', before['.env.mcp'].decode())
            self.assertEqual(setup.values(root, '.env.search')['MCP_INSTANCE_ID'], 'example')
            with self.assertRaises(FileExistsError):
                setup.initialize(root, 'example', '127.0.0.1', 18766, 18081)
            self.assertEqual(before, {name: (root / name).read_bytes() for name in setup.FILES})
            unit = setup.unit_text(root, '/usr/local/bin/uv')
            self.assertIn('up --no-build', unit)
            self.assertIn(f'EnvironmentFile={root}/.env.mcp', unit)
            self.assertNotIn(before['.secrets/mcp-token'].decode().strip(), unit)

    def test_invalid_or_existing_configuration_is_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                setup.initialize(root, 'example', '0.0.0.0', 8766, 18080)
            self.assertEqual(list(root.iterdir()), [])
            (root / '.env.control').write_text('preserve')
            with self.assertRaises(FileExistsError):
                setup.initialize(root, 'example', '127.0.0.1', 8766, 18080)
            self.assertEqual(list(root.iterdir()), [root / '.env.control'])


class UnixTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_authenticated_requests_use_socket(self):
        requests = []
        async def handle(reader, writer):
            requests.append(await reader.readuntil(b'\r\n\r\n'))
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 15\r\nConnection: close\r\n\r\n{"status":"ok"}')
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        with tempfile.TemporaryDirectory() as directory:
            socket = str(Path(directory) / 'control.sock')
            server = await asyncio.start_unix_server(handle, path=socket)
            try:
                client = GatewayClient('http://control.invalid', token='x' * 48, socket=socket)
                for _ in range(2):
                    self.assertEqual(await client('GET', '/health'), {'status': 'ok'})
                self.assertEqual(len(requests), 2)
                self.assertTrue(all(b'Authorization: Bearer ' + b'x' * 48 in request for request in requests))
            finally:
                server.close()
                await server.wait_closed()
