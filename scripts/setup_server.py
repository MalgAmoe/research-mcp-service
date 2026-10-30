#!/usr/bin/env python3
"""Provision a fresh private Linux deployment. Never overwrites configuration or deletes data."""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FILES = ['.env.runtime', '.env.search', '.env.control', '.env.mcp',
         '.secrets/mcp-token', '.secrets/gateway-token']


def private_write(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(text)


def initialize(root, identity, host, port, search_port):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', identity):
        raise ValueError('Instance ID: lowercase letter followed by up to 31 lowercase letters/digits/hyphens')
    address = ipaddress.IPv4Address(host)
    if not address.is_loopback and address not in ipaddress.IPv4Network('100.64.0.0/10'):
        raise ValueError('Bind only to loopback or your Tailscale IPv4 address')
    if not all(1024 <= p <= 65535 for p in [port, search_port]) or port == search_port:
        raise ValueError('Choose distinct unprivileged MCP and search ports')
    if any(c.isspace() or c in ('%', '"', "'", '\\', '$') for c in str(root)) or len(str(root / '.state/control-rpc/gateway.sock').encode()) >= 104:
        raise ValueError('Use a short absolute checkout path without whitespace, quotes, percent, dollar or backslash')
    for name in FILES:
        if (root / name).exists() or (root / name).is_symlink():
            raise FileExistsError(f'{name} already exists; no configuration changed. Use a fresh checkout.')
    for name in ['.state', '.secrets']:
        path = root / name
        if path.is_symlink() or (path.exists() and (path.stat().st_mode & 0o077)):
            raise ValueError(f'{name} must be a real private directory (mode 700)')
    if (root / '.state/control-rpc').exists():
        raise FileExistsError('Control socket directory already exists; inspect it manually')
    for name in ['.state', '.secrets']:
        (root / name).mkdir(mode=0o700, exist_ok=True)
    # Parent .state is 0700; only the control container gets this subdirectory bind mount.
    socket_dir = root / '.state/control-rpc'
    socket_dir.mkdir(mode=0o777)
    socket_dir.chmod(0o777)  # allow container UID 10001 without privileged host chown
    backend_token = secrets.token_urlsafe(48)
    private_write(root / '.secrets/mcp-token', secrets.token_urlsafe(48) + '\n')
    private_write(root / '.secrets/gateway-token', backend_token + '\n')
    private_write(root / '.env.control', f'GATEWAY_TOKEN={backend_token}\n')
    private_write(root / '.env.runtime', f'TENANT_ID={identity}\nS3_ACCESS_KEY=mcp{secrets.token_hex(10)}\nS3_SECRET_KEY={secrets.token_hex(32)}\n')
    private_write(root / '.env.search', f'MCP_INSTANCE_ID={identity}\nMCP_SEARCH_PORT={search_port}\nSEARXNG_SECRET={secrets.token_hex(32)}\n')
    private_write(root / '.env.mcp',
        f'MCP_BIND_HOST={host}\nMCP_PORT={port}\nMCP_TOKEN_FILE=.secrets/mcp-token\n'
        f'MCP_ENABLE_SEARCH=true\nSEARXNG_URL=http://127.0.0.1:{search_port}\n'
        'SEARCH_PROVIDER=auto\nDDGS_BACKEND=duckduckgo,yahoo\nMCP_ENABLE_RESEARCH=true\n'
        'MCP_GATEWAY_URL=http://control\nMCP_GATEWAY_TOKEN_FILE=.secrets/gateway-token\n'
        f'MCP_GATEWAY_SOCKET={socket_dir}/gateway.sock\n')


def values(root, name):
    return dict(line.split('=', 1) for line in (root / name).read_text().splitlines()
                if line and not line.startswith('#'))


def run(args, env_file=None):
    env = os.environ.copy()
    if env_file:
        for key in values(ROOT, env_file):
            env.pop(key, None)  # shell exports must not override this instance's configuration
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def compose(search=False):
    env_file = '.env.search' if search else '.env.runtime'
    files = ['compose.search.yml'] if search else ['docker-compose.yml', 'compose.workers.yml', 'compose.control.yml', 'compose.server.yml']
    args = ['docker', 'compose', '--env-file', env_file]
    for file in files:
        args += ['-f', file]
    if not search:
        args += ['--profile', 'workers', '--profile', 'control']
    return args, env_file


def require_server_setup():
    env = values(ROOT, '.env.mcp')
    if env.get('MCP_GATEWAY_SOCKET') != str(ROOT / '.state/control-rpc/gateway.sock'):
        raise ValueError('This workflow requires its own fresh-server configuration; it will not migrate a live development deployment')
    if (ROOT / '.state').stat().st_mode & 0o077:
        raise ValueError('.state must remain private (mode 700)')


def unit_text(root, uv):
    return f'''[Unit]
Description=Private research MCP service
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory={root}
EnvironmentFile={root}/.env.mcp
ExecStartPre=/usr/bin/python3 {root}/scripts/setup_server.py up --no-build
ExecStart={uv} run --locked --no-sync --env-file .env.mcp python -m research_mcp_service.server
Restart=on-failure
RestartSec=10
TimeoutStartSec=300
TimeoutStopSec=30
UMask=0077

[Install]
WantedBy=default.target
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    init = sub.add_parser('init')
    init.add_argument('--instance', required=True)
    init.add_argument('--host', default='127.0.0.1')
    init.add_argument('--port', type=int, default=8766)
    init.add_argument('--search-port', type=int, default=18080)
    up = sub.add_parser('up'); up.add_argument('--no-build', action='store_true')
    sub.add_parser('run'); sub.add_parser('status'); sub.add_parser('unit')
    args = p.parse_args()
    if args.action == 'init':
        initialize(ROOT, args.instance, args.host, args.port, args.search_port)
        print('Created private configuration. No services started; no credentials displayed.')
        return
    require_server_setup()
    if args.action == 'unit':
        uv = shutil.which('uv')
        if not uv or any(c.isspace() or c in ('%', '"', "'", '\\', '$') for c in uv):
            raise ValueError('Install uv at an absolute path without special characters')
        name = 'research-mcp-' + values(ROOT, '.env.runtime')['TENANT_ID'] + '.service'
        private_write(ROOT / '.state' / name, unit_text(ROOT, uv))
        print(f'Wrote .state/{name}; not installed or enabled.')
    elif args.action == 'run':
        run(['uv', 'run', '--locked', '--no-sync', '--env-file', '.env.mcp', 'python', '-m', 'research_mcp_service.server'], '.env.mcp')
    elif args.action == 'status':
        for search in [True, False]:
            cmd, env = compose(search); run(cmd + ['ps'], env)
    elif args.action == 'up':
        if args.no_build and not (ROOT / '.venv/bin/python').exists():
            raise FileNotFoundError('Python environment is missing; run up without --no-build first')
        if not args.no_build:
            # Fail before expensive browser builds or starting any services if
            # an upstream image is unavailable. Never substitute cached exports.
            cmd, env = compose(); run(cmd + ['pull', 's3', 'redis'], env)
            cmd, env = compose(True); run(cmd + ['pull', 'searxng'], env)
            run(['uv', 'sync', '--locked', '--no-dev', '--python', '3.12'])
            cmd, env = compose(); run(cmd + ['build', 'egress', 'fetch-worker', 'control'], env)
        for search in [True, False]:
            cmd, env = compose(search)
            run(cmd + ['up', '-d', '--no-build', '--wait', '--wait-timeout', '180'] + (['searxng'] if search else ['control']), env)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        sys.exit(str(exc))
    except subprocess.CalledProcessError as exc:
        sys.exit(f'Setup stopped (exit {exc.returncode}). Review the command output; no image substitution or automatic rollback was attempted.')
