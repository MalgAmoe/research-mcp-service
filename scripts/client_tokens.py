#!/usr/bin/env python3
"""Manage named MCP credentials. Changes are staged until `apply`. Standard library only."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    if not path.exists():
        return {}
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode) or path.stat().st_mode & 0o077:
        raise ValueError('Credential file must be a regular private file (chmod 600)')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate client label in credential file')
            result[key] = value
        return result
    data = json.loads(path.read_text(), object_pairs_hook=unique)
    if not isinstance(data, dict):
        raise ValueError('Credential file must contain a JSON object')
    for label, token in data.items():
        validate_label(label)
        if not isinstance(token, str) or len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError('Invalid credential in file')
    if len(set(data.values())) != len(data):
        raise ValueError('Duplicate credentials in file')
    return data


def validate_label(label):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', label) or label == 'legacy':
        raise ValueError('Use 1–64 letters, digits, underscores or hyphens; legacy is reserved')


def save(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
            temporary = f.name
            os.fchmod(f.fileno(), 0o600)
            json.dump(data, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        temporary = None
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary:
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Deployment checkout (default: this checkout)')
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('add', help='Create a new client; prints its secret once to stdout')
    add.add_argument('label')
    commands.add_parser('list', help='List labels only, never secrets')
    show = commands.add_parser('show', help='Display one existing client token to stdout; keep private')
    show.add_argument('label')
    revoke = commands.add_parser('revoke', help='Stage revocation of a named client')
    revoke.add_argument('label')
    commands.add_parser('apply', help='Copy credentials and recreate ONLY the MCP frontend')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    directory = root / '.secrets'
    if directory.is_symlink():
        parser.exit(1, 'Error: .secrets must not be a symlink\n')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        parser.exit(1, 'Error: .secrets must be private (chmod 700)\n')
    path = directory / 'client-tokens.json'
    try:
        fd = os.open(directory / '.client-tokens.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = load(path)
            if args.command == 'list':
                print('legacy (existing token; managed separately)')
                for label in sorted(data):
                    print(label)
            elif args.command == 'add':
                validate_label(args.label)
                if args.label in data:
                    raise ValueError('Client already exists; refusing to replace its token')
                token = secrets.token_urlsafe(48)
                data[args.label] = token
                save(path, data)
                print(token)
                print(f'Created {args.label}. Save the token privately; run apply to activate it.', file=sys.stderr)
            elif args.command == 'show':
                validate_label(args.label)
                if args.label not in data:
                    raise ValueError('Unknown client')
                print(data[args.label])
            elif args.command == 'revoke':
                validate_label(args.label)
                if args.label not in data:
                    raise ValueError('Unknown client; nothing changed')
                del data[args.label]
                save(path, data)
                print(f'Revocation staged for {args.label}. Run apply to enforce it.')
            else:
                compose_file = root / 'compose.deploy.yml'
                if 'MCP_CLIENT_TOKENS_FILE' not in compose_file.read_text():
                    raise ValueError('Compose deployment is not upgraded for named tokens; nothing restarted')
                compose = ['docker', 'compose', '--env-file', '.env.runtime', '-f', 'compose.deploy.yml']
                # Refuse old images before touching the live credential volume.
                subprocess.run(compose + ['run', '--rm', '--no-deps', '--entrypoint', 'python', 'mcp',
                    '-c', 'import inspect; from research_mcp_service.server import create_app; '
                    'assert "client_tokens" in inspect.signature(create_app).parameters, "Upgrade app image first"'],
                    cwd=root, check=True)
                subprocess.run(compose + ['run', '--rm', '--no-deps', 'credentials'], cwd=root, check=True)
                subprocess.run(compose + ['up', '-d', '--no-deps', '--force-recreate', '--pull', 'never',
                    '--wait', '--wait-timeout', '90', 'mcp'], cwd=root, check=True)
                print('Applied named credentials; MCP frontend is healthy. Existing token remains valid.')
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        # Never render exception text: malformed files/process errors can contain secrets.
        if isinstance(exc, subprocess.CalledProcessError):
            parser.exit(1, 'Error: apply failed; inspect Compose status. Changes remain staged on disk; runtime may be partially updated.\n')
        parser.exit(1, 'Error: ' + (str(exc) if type(exc) is ValueError else 'Cannot access credential/deployment files') + '\n')


if __name__ == '__main__':
    main()
