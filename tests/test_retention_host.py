import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from research_gateway import retention

spec = importlib.util.spec_from_file_location('retention_host', Path(__file__).resolve().parents[1] / 'scripts/retention.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class HostRetentionTests(unittest.TestCase):
    def test_missing_running_or_uncertain_control_refused(self):
        for state in ['running', 'paused', 'restarting', 'created', 'dead', None]:
            with self.subTest(state=state), self.assertRaises(RuntimeError):
                host.check_stopped([{'Service': 'control', 'State': state}])
        with self.assertRaises(RuntimeError):
            host.check_stopped([])
        with self.assertRaises(RuntimeError):
            host.check_stopped([{'Service': 'control', 'State': 'exited'}])
        host.check_stopped([{'Service': 'control', 'State': 'exited'}, {'Service': 'mcp', 'State': 'exited'}])

    def test_inspection_ignores_oneoff_but_not_real_control(self):
        def container(oneoff, status, service='control'):
            return {'Config': {'Labels': {'com.docker.compose.oneoff': oneoff,
                                          'com.docker.compose.service': service}}, 'State': {'Status': status}}
        for state in ['running', 'exited']:
            with patch.object(host.subprocess, 'check_output', side_effect=['main\nprobe\n',
                 json.dumps([container('False', state), container('True', 'running'), container('False', 'exited', 'mcp')])]):
                if state == 'running':
                    with self.assertRaises(RuntimeError):
                        host.require_stopped_control(['docker', 'compose'], Path('/tmp'), {})
                else:
                    host.require_stopped_control(['docker', 'compose'], Path('/tmp'), {})

    def test_unknown_layout_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for marker in ['', 'DEPLOYMENT_LAYOUT=unknown\n']:
                (root / '.env.runtime').write_text(marker + 'TENANT_ID=own\n')
                with self.assertRaises(ValueError):
                    host.deployment(root)

    def test_image_only_layout_and_frontend_stop_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env.runtime').write_text('DEPLOYMENT_LAYOUT=compose-v1\nTENANT_ID=own\n')
            (root / '.env.mcp').write_text('MCP_GATEWAY_SOCKET=/control-api/gateway.sock\n')
            with patch.dict('os.environ', {'DOCKER_HOST': 'tcp://other:2375', 'TENANT_ID': 'other', 'COMPOSE_PROJECT_NAME': 'other'}):
                command, env = host.deployment(root)
            self.assertIn('compose.deploy.yml', command)
            self.assertNotIn('TENANT_ID', env)
            self.assertNotIn('COMPOSE_PROJECT_NAME', env)
            self.assertNotIn('DOCKER_HOST', env)
            self.assertIn('unix:///var/run/docker.sock', command)
        with self.assertRaisesRegex(RuntimeError, 'mcp must exist and be stopped'):
            host.check_stopped([{'Service': 'control', 'State': 'exited'}, {'Service': 'mcp', 'State': 'running'}])

    def test_dry_run_never_checks_or_stops_writers(self):
        with patch.object(host.subprocess, 'run') as run, patch.object(host, 'require_stopped_control') as check:
            host.run_retention(['docker', 'compose'], Path('/tmp'), {}, [])
        check.assert_not_called()
        command = run.call_args.args[0]
        self.assertIn('--no-deps', command)
        self.assertNotIn('--apply', command)
        self.assertNotIn('stop', command)

    def test_handshake_authorizes_only_after_second_stopped_check(self):
        for restarted in [True, False]:
            process = MagicMock()
            process.__enter__.return_value = process
            process.stdout = io.StringIO(host.HOST_CHECK + '\n')
            process.stdin = io.StringIO()
            process.wait.return_value = 0
            with patch.object(host.subprocess, 'Popen', return_value=process) as launch, \
                 patch.object(host, 'require_stopped_control', side_effect=[None, RuntimeError('control restarted') if restarted else None]) as check:
                if restarted:
                    with self.assertRaisesRegex(RuntimeError, 'restarted'):
                        host.run_retention(['docker', 'compose'], Path('/tmp'), {}, ['--apply', '--writers-stopped'], apply=True)
                else:
                    host.run_retention(['docker', 'compose'], Path('/tmp'), {}, ['--apply', '--writers-stopped'], apply=True)
            self.assertEqual(check.call_count, 2)
            self.assertEqual(process.stdin.getvalue(), '' if restarted else 'WRITERS_STOPPED\n')
            self.assertEqual(launch.call_args.args[0][-2:], ['--host-guard-protocol', '1'])
        self.assertEqual(host.HOST_CHECK, retention.HOST_CHECK)


class GuardedApplyTests(unittest.TestCase):
    def test_refused_confirmation_releases_lock_without_inventory(self):
        redis = MagicMock()
        lock = redis.lock.return_value
        with patch.object(retention, 'inventory') as inventory, patch.object(retention, 'apply_plan') as apply:
            with self.assertRaises(RuntimeError):
                retention.guarded_apply(redis, MagicMock(), 30, 90, confirm=MagicMock(side_effect=RuntimeError('refused')))
        inventory.assert_not_called()
        apply.assert_not_called()
        lock.release.assert_called_once()

    def test_failure_after_deletion_begins_keeps_lock(self):
        redis = MagicMock()
        lock = redis.lock.return_value
        with patch.object(retention, 'inventory', return_value={'summary': {}}), \
             patch.object(retention, 'apply_plan', side_effect=RuntimeError('failed')), \
             patch('sys.stdout', io.StringIO()), patch('sys.stderr', io.StringIO()):
            with self.assertRaises(RuntimeError):
                retention.guarded_apply(redis, MagicMock(), 30, 90, confirm=lambda: None)
        lock.release.assert_not_called()

    def test_success_releases_lock_and_inventory_failure_is_nondestructive(self):
        for failure in [False, True]:
            redis = MagicMock(); lock = redis.lock.return_value
            def confirm():
                lock.acquire.assert_called_once()
            with patch.object(retention, 'inventory', return_value={'summary': {}},
                              side_effect=RuntimeError('invalid record') if failure else None), \
                 patch.object(retention, 'apply_plan') as apply, patch('sys.stdout', io.StringIO()):
                if failure:
                    with self.assertRaises(RuntimeError):
                        retention.guarded_apply(redis, MagicMock(), 30, 90, confirm=confirm)
                    apply.assert_not_called()
                else:
                    retention.guarded_apply(redis, MagicMock(), 30, 90, confirm=confirm)
                    apply.assert_called_once()
            lock.release.assert_called_once()
