"""One-shot, network-none credential copy into a private named volume.

Only this initializer runs as container root. Application containers remain
non-root and receive the credential volume read-only, never host directories.
"""
import json
import os

from .request_auth import BearerAuth
from pathlib import Path
import tempfile


def main():
    target = Path('/credentials')
    # Validate both inputs before changing either destination.
    tokens = {}
    for name in ('mcp-token', 'gateway-token'):
        token = (Path('/inputs') / name).read_text().strip()
        if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise SystemExit('Invalid credential input')
        tokens[name] = token + '\n'
    clients_path = Path('/client-inputs/client-tokens.json')
    clients = {}
    if clients_path.exists():
        if clients_path.stat().st_mode & 0o077 or clients_path.is_symlink():
            raise SystemExit('Client credential input must be a private regular file')
        clients = json.loads(clients_path.read_text())
        if not isinstance(clients, dict):
            raise SystemExit('Client credentials must be a JSON object')
    # Validate named and legacy tokens together before changing any destination.
    BearerAuth(None, tokens['mcp-token'].strip(), clients)
    tokens['client-tokens.json'] = json.dumps(clients) + '\n'
    for name, token in tokens.items():
        with tempfile.NamedTemporaryFile(mode='w', dir=target, delete=False) as f:
            f.write(token)
            os.fchmod(f.fileno(), 0o600)
            os.fchown(f.fileno(), 10001, 10001)
            temporary = f.name
        os.replace(temporary, target / name)
    os.chown(target, 10001, 10001)
    os.chmod(target, 0o700)


if __name__ == '__main__':
    main()
