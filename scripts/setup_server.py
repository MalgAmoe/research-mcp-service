#!/usr/bin/env python3
"""Initialize and operate an image-only Compose deployment (administrator only)."""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = Path('/var/lib/research-mcp/instances')
FILES = ['.env.runtime', '.env.control', '.env.mcp', '.secrets/mcp-token', '.secrets/gateway-token']
DOCKER = ['docker', '--host', 'unix:///var/run/docker.sock']


def private_write(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(text)


def values(root, name):
    return dict(line.split('=', 1) for line in (root / name).read_text().splitlines()
                if line and not line.startswith('#'))


def image_refs(repository, version):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*(?::[0-9]+)?(?:/[A-Za-z0-9._-]+)*', repository):
        raise ValueError('Invalid image repository')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', version):
        raise ValueError('Use an explicit release version, without whitespace or shell characters')
    return {f'MCP_{role.upper()}_IMAGE': f'{repository}:research-mcp-{role}-{version}'
            for role in ['app', 'worker', 'egress']}


def validate_initialization(root, identity, host, port):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', identity):
        raise ValueError('Instance ID: lowercase letter followed by up to 31 lowercase letters/digits/hyphens')
    address = ipaddress.IPv4Address(host)
    if not address.is_loopback and address not in ipaddress.IPv4Network('100.64.0.0/10'):
        raise ValueError('Bind only to loopback or your Tailscale IPv4 address')
    if not 1024 <= port <= 65535:
        raise ValueError('Choose an unprivileged MCP port')
    if not root.is_absolute():
        raise ValueError('Use an absolute checkout path')
    for name in FILES:
        if (root / name).exists() or (root / name).is_symlink():
            raise FileExistsError(f'{name} already exists; use a fresh checkout, not an in-place migration')
    for name in ['.state', '.secrets']:
        path = root / name
        if path.is_symlink() or (path.exists() and path.stat().st_mode & 0o077):
            raise ValueError(f'{name} must be a real private directory (mode 700)')


def initialize(root, identity, host, port, version, repository='malgamoe/mcps'):
    validate_initialization(root, identity, host, port)
    refs = image_refs(repository, version)
    for name in ['.state', '.secrets']:
        (root / name).mkdir(mode=0o700, exist_ok=True)
    backend = secrets.token_urlsafe(48)
    private_write(root / '.secrets/mcp-token', secrets.token_urlsafe(48) + '\n')
    private_write(root / '.secrets/gateway-token', backend + '\n')
    private_write(root / '.env.control', f'GATEWAY_TOKEN={backend}\n')
    private_write(root / '.env.runtime',
        f'DEPLOYMENT_LAYOUT=compose-v1\nTENANT_ID={identity}\nMCP_BIND_HOST={host}\nMCP_PORT={port}\n'
        f'S3_ACCESS_KEY=mcp{secrets.token_hex(10)}\nS3_SECRET_KEY={secrets.token_hex(32)}\n'
        f'SEARXNG_SECRET={secrets.token_hex(32)}\n' + ''.join(f'{k}={v}\n' for k, v in refs.items()))
    private_write(root / '.env.mcp',
        f'MCP_BIND_HOST={host}\nMCP_PORT={port}\nMCP_TOKEN_FILE=.secrets/mcp-token\n'
        'MCP_ENABLE_SEARCH=true\nSEARXNG_URL=http://searxng:8080\nSEARCH_PROVIDER=auto\n'
        'DDGS_BACKEND=duckduckgo,yahoo\nMCP_ENABLE_RESEARCH=true\nMCP_GATEWAY_URL=http://control\n'
        'MCP_GATEWAY_TOKEN_FILE=.secrets/gateway-token\nMCP_GATEWAY_SOCKET=/control-api/gateway.sock\n')


def command_env(env_file=None):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith('COMPOSE_') or key in ('DOCKER_HOST', 'DOCKER_CONTEXT'):
            env.pop(key)
    if env_file:
        for key in values(ROOT, env_file):
            env.pop(key, None)
    return env


def run(args, env_file=None):
    subprocess.run(args, cwd=ROOT, env=command_env(env_file), check=True)


def capture(args):
    return subprocess.check_output(args, text=True, env=command_env()).strip()


def compose():
    return DOCKER + ['compose', '--env-file', '.env.runtime', '-f', 'compose.deploy.yml']


def trusted_path(path):
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise ValueError(f'Symlink not allowed here: {parent}')
        st = parent.stat()
        if st.st_uid != 0 or st.st_mode & 0o022:
            raise ValueError(f'Use an administrator-owned path, not writable by other users: {parent}')


def require_admin():
    if os.geteuid() != 0:
        raise ValueError('Run this provisioning helper as administrator from a root-owned checkout')
    trusted_path(ROOT)
    for name in ['.state', '.secrets', 'compose.deploy.yml']:
        if (ROOT / name).exists():
            trusted_path(ROOT / name)


def port_available(host, port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
    except OSError as exc:
        raise ValueError(f'Port {host}:{port} is in use or unavailable') from exc


def check_collisions(identity, host, port, records):
    project = f'research-mcp-{identity}'
    for record in records:
        if identity == record['instance']:
            raise ValueError(f'Instance/project namespace is already reserved at {record["root"]}')
        if port == record['port']:
            raise ValueError(f'Port is reserved by {record["instance"]}')
    for listing in [['ps', '-aq'], ['network', 'ls', '-q'], ['volume', 'ls', '-q']]:
        if capture(DOCKER + listing + ['--filter', 'label=com.docker.compose.project=' + project]):
            raise ValueError(f'{project} already owns Docker resources')
    named = [
        (['ps', '-a', '--format', '{{.Names}}'], {f'{project}-{s}-1' for s in ['redis', 's3', 'control', 'fetch-worker', 'egress', 'mcp', 'credentials', 'searxng']}),
        (['network', 'ls', '--format', '{{.Name}}'], {project + '_' + n for n in ['storage', 'egress', 'frontend']}),
        (['volume', 'ls', '--format', '{{.Name}}'], {project + '_' + v for v in ['redis_data', 's3_data', 'worker_rpc', 'egress_socket', 'control_api', 'frontend_credentials']}),
    ]
    for listing, reserved in named:
        if reserved & set(capture(DOCKER + listing).splitlines()):
            raise ValueError('A generated Docker resource name is occupied, including unlabelled resources')
    ids = capture(DOCKER + ['ps', '-aq']).splitlines()
    if ids:
        for line in capture(DOCKER + ['inspect', '--format', '{{json .HostConfig.PortBindings}}', *ids]).splitlines():
            for bindings in (json.loads(line) or {}).values():
                if any(binding.get('HostPort') and int(binding['HostPort']) == port for binding in bindings or []):
                    raise ValueError('Port is assigned to an existing Docker container')
    port_available(host, port)


def registry_records():
    records = []
    for path in REGISTRY.glob('*.json'):
        trusted_path(path)
        record = json.loads(path.read_text())
        if (not isinstance(record, dict) or not {'instance', 'root', 'host', 'port'} <= record.keys()
                or not isinstance(record['instance'], str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', record['instance'])
                or not isinstance(record['root'], str) or not Path(record['root']).is_absolute()
                or type(record['port']) is not int or not 1024 <= record['port'] <= 65535):
            raise ValueError(f'Invalid reservation: {path}')
        records.append(record)
    return records


def reserve_and_initialize(identity, host, port, version, repository):
    require_admin()
    validate_initialization(ROOT, identity, host, port)
    image_refs(repository, version)
    REGISTRY.mkdir(parents=True, mode=0o700, exist_ok=True)
    trusted_path(REGISTRY)
    fd = os.open(REGISTRY / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        check_collisions(identity, host, port, registry_records())
        private_write(REGISTRY / f'{identity}.json', json.dumps(dict(instance=identity, root=str(ROOT), host=host, port=port)) + '\n')
        initialize(ROOT, identity, host, port, version, repository)


def require_server_setup():
    require_admin()
    for name in FILES:
        trusted_path(ROOT / name)
        if (ROOT / name).stat().st_mode & 0o077:
            raise ValueError(f'{name} must remain private')
    env = values(ROOT, '.env.runtime')
    identity = env['TENANT_ID']
    if env.get('DEPLOYMENT_LAYOUT') != 'compose-v1' or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', identity):
        raise ValueError('Requires fresh Compose configuration; existing installations are not migrated')
    path = REGISTRY / f'{identity}.json'
    trusted_path(path)
    record = json.loads(path.read_text())
    expected = dict(instance=identity, root=str(ROOT), host=env['MCP_BIND_HOST'], port=int(env['MCP_PORT']))
    frontend = values(ROOT, '.env.mcp')
    if any(record.get(k) != v for k, v in expected.items()) or any(frontend[k] != env[k] for k in ['MCP_BIND_HOST', 'MCP_PORT']):
        raise ValueError('Configuration differs from its instance reservation; inspect before proceeding')


def check_published_endpoint():
    env = values(ROOT, '.env.mcp')
    token = (ROOT / '.secrets/mcp-token').read_text().strip()
    request = urllib.request.Request(f'http://{env["MCP_BIND_HOST"]}:{env["MCP_PORT"]}/mcp',
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'text/event-stream'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except OSError:
        raise ValueError('Published MCP endpoint is unreachable from the host') from None
    if status not in (200, 405):
        raise ValueError(f'Published MCP endpoint check failed (HTTP {status})')
    print('Published MCP endpoint is reachable and accepts authentication.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    init = sub.add_parser('init')
    init.add_argument('--instance', required=True)
    init.add_argument('--version', required=True)
    init.add_argument('--repository', default='malgamoe/mcps')
    init.add_argument('--host', default='127.0.0.1')
    init.add_argument('--port', type=int, default=8766)
    up = sub.add_parser('up'); up.add_argument('--no-pull', action='store_true')
    sub.add_parser('status'); sub.add_parser('stop')
    check = sub.add_parser('check'); check.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if args.action == 'init':
        reserve_and_initialize(args.instance, args.host, args.port, args.version, args.repository)
        print('Created private configuration and reserved instance/port. No services started or credentials displayed.')
        return
    require_server_setup()
    if args.action == 'up':
        run(compose() + ['config', '--quiet'], '.env.runtime')
        if not args.no_pull:
            run(compose() + ['pull'], '.env.runtime')
        run(compose() + ['up', '-d', '--pull', 'never', '--wait', '--wait-timeout', '300'], '.env.runtime')
    elif args.action == 'check':
        check_published_endpoint()
        run(compose() + ['exec', '-T', 'mcp', 'python', '-m', 'research_mcp_service.container_check'] + (['--live'] if args.live else []), '.env.runtime')
    else:
        run(compose() + ['ps' if args.action == 'status' else 'stop'], '.env.runtime')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, FileExistsError, FileNotFoundError, PermissionError) as exc:
        sys.exit(str(exc))
    except subprocess.CalledProcessError as exc:
        sys.exit(f'Setup stopped (exit {exc.returncode}). No substitution, data cleanup or automatic rollback attempted.')
