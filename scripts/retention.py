#!/usr/bin/env python3
"""Inspect/manage this deployment's cache. Dry-run by default; never stops or restarts services."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HOST_CHECK = 'RETENTION_WRITER_CHECK_V1'


def deployment(root):
    # Match the existing dev layout or the fresh-server overlay. Do not inherit
    # shell overrides that could redirect Compose to another instance's storage.
    runtime = dict(line.split('=', 1) for line in (root / '.env.runtime').read_text().splitlines()
                   if line and not line.startswith('#'))
    mcp = dict(line.split('=', 1) for line in (root / '.env.mcp').read_text().splitlines()
               if line and not line.startswith('#'))
    env = os.environ.copy()
    for key in {*runtime, 'COMPOSE_PROJECT_NAME', 'COMPOSE_FILE', 'COMPOSE_PROFILES'}:
        env.pop(key, None)
    args = ['docker', 'compose', '--env-file', '.env.runtime', '-f', 'docker-compose.yml',
            '-f', 'compose.workers.yml', '-f', 'compose.control.yml']
    if mcp.get('MCP_GATEWAY_SOCKET'):
        args += ['-f', 'compose.server.yml']
    return args + ['--profile', 'workers', '--profile', 'control'], env


def check_stopped(rows):
    controls = [row for row in rows if row.get('Service') == 'control']
    if not controls or any(row.get('State') != 'exited' for row in controls):
        raise RuntimeError('Control must exist and be stopped (exited). No deletion authorized.')
    if any(row.get('Service') == 'gateway' and row.get('State') != 'exited' for row in rows):
        raise RuntimeError('A legacy gateway may still be writing. No deletion authorized.')


def require_stopped_control(command, root, env):
    ids = subprocess.check_output(command + ['ps', '--all', '--quiet'],
                                  cwd=root, env=env, text=True).split()
    if not ids:
        raise RuntimeError('No deployment containers found; refusing cleanup')
    containers = json.loads(subprocess.check_output(['docker', 'inspect', *ids],
                            cwd=root, env=env, text=True))
    # Exclude Compose run containers, including our own maintenance process.
    # Other direct/one-off writers remain covered by --writers-stopped confirmation.
    rows = []
    for container in containers:
        labels = container['Config'].get('Labels') or {}
        if labels.get('com.docker.compose.oneoff', '').lower() == 'true':
            continue
        rows.append({'Service': labels.get('com.docker.compose.service'),
                     'State': container['State']['Status']})
    check_stopped(rows)


def run_retention(command, root, env, arguments, apply=False):
    if apply:
        require_stopped_control(command, root, env)  # refuse before launching a container
    run = command + ['run', '--rm', '--no-deps', '--pull', 'never', '-T', '--entrypoint',
                     'python', 'control', '-m', 'research_gateway.retention', *arguments]
    if not apply:
        subprocess.run(run, cwd=root, env=env, check=True)
        return
    # Old images reject this argument BEFORE any deletion; rebuild control first.
    run += ['--host-guard-protocol', '1']
    checked = False
    with subprocess.Popen(run, cwd=root, env=env, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True, bufsize=1) as process:
        for line in process.stdout:
            if line.strip() == HOST_CHECK:
                if checked:
                    raise RuntimeError('Repeated maintenance handshake; refusing')
                require_stopped_control(command, root, env)  # now under the Redis maintenance lock
                process.stdin.write('WRITERS_STOPPED\n')
                process.stdin.flush()
                checked = True
            else:
                print(line, end='', flush=True)
        code = process.wait()
    if code or not checked:
        raise RuntimeError('Retention did not complete successfully. Keep writers stopped; inspect logs and maintenance lock. A current control image is required for apply.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--rss-days', type=int, default=90)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--writers-stopped', action='store_true', help='Confirm MCP and all other direct-storage writers are stopped')
    pins = parser.add_mutually_exclusive_group()
    pins.add_argument('--pin', metavar='DOC_ID')
    pins.add_argument('--unpin', metavar='DOC_ID')
    pins.add_argument('--list-pins', action='store_true')
    args = parser.parse_args()
    if args.days < 1 or args.rss_days < 1:
        parser.error('Retention must be at least one day')
    if args.apply and (not args.writers_stopped or args.pin or args.unpin or args.list_pins):
        parser.error('Apply requires --writers-stopped and cannot be combined with pin operations')
    command, env = deployment(ROOT)
    run_retention(command, ROOT, env, sys.argv[1:], apply=args.apply)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        sys.exit(str(exc))
