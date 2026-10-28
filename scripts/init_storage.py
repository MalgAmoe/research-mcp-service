#!/usr/bin/env python3
"""Create this project's private storage configuration, without starting services."""
import argparse
import os
from pathlib import Path
import re
import secrets

ROOT = Path(__file__).resolve().parents[1]


def initialize(path: Path, tenant_id: str):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', tenant_id):
        raise ValueError('Tenant ID must start with a lowercase letter and contain only lowercase letters, digits or hyphens (max 32 characters)')
    config = (f'TENANT_ID={tenant_id}\n'
              f'MINIO_ACCESS_KEY=mcp{secrets.token_hex(10)}\n'
              f'MINIO_SECRET_KEY={secrets.token_hex(32)}\n'
              f'SEARXNG_SECRET={secrets.token_hex(32)}\n')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(config)
        handle.flush()
        os.fsync(handle.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tenant-id', default='dev')
    args = parser.parse_args()
    try:
        initialize(ROOT / '.env.runtime', args.tenant_id)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print('Created private .env.runtime; credentials were not displayed.')
    print('Start storage only: docker compose --env-file .env.runtime up -d --wait redis minio')


if __name__ == '__main__':
    main()
