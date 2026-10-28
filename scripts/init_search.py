#!/usr/bin/env python3
"""Create private configuration for this project's standalone SearXNG instance."""
import argparse
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18080)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Use an unprivileged port between 1024 and 65535')
    path = ROOT / '.env.search'
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        parser.error('.env.search already exists; no changes made')
    with os.fdopen(fd, 'w') as handle:
        handle.write(f'MCP_INSTANCE_ID=dev\nMCP_SEARCH_PORT={args.port}\nSEARXNG_SECRET={secrets.token_hex(32)}\n')
    print('Created private .env.search (secret not displayed).')
    print(f'After starting compose.search.yml, enable MCP_ENABLE_SEARCH=true and SEARXNG_URL=http://127.0.0.1:{args.port} in .env.mcp, then restart MCP.')


if __name__ == '__main__':
    main()
