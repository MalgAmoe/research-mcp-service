#!/usr/bin/env python3
"""Generate private configuration for the single-user MCP connectivity test."""
import argparse
import ipaddress
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    address = ipaddress.IPv4Address(args.host)
    if not address.is_loopback and address not in ipaddress.IPv4Network('100.64.0.0/10'):
        parser.error('Use a loopback or Tailscale IPv4 address')
    if not 1 <= args.port <= 65535:
        parser.error('Invalid port')
    env = ROOT / '.env.mcp'
    if env.exists():
        parser.error('.env.mcp already exists; review it manually, no configuration or token changed')
    private = ROOT / '.secrets'
    private.mkdir(mode=0o700, exist_ok=True)
    private.chmod(0o700)
    token = private / 'mcp-token'
    if not token.exists():
        fd = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(secrets.token_urlsafe(48) + '\n')
    token.chmod(0o600)
    fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(f'MCP_BIND_HOST={args.host}\nMCP_PORT={args.port}\nMCP_TOKEN_FILE=.secrets/mcp-token\n')
    print('Created private .env.mcp; token stored in .secrets/mcp-token (not displayed).')


if __name__ == '__main__':
    main()
