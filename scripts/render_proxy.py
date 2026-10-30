#!/usr/bin/env python3
"""Render reviewable per-instance nginx snippets; never install or reload nginx."""
import argparse
import fcntl
import ipaddress
import json
import os
import re
import sys
import tempfile
from urllib.parse import urlsplit

import setup_server as setup


def validate_origin(origin):
    url = urlsplit(origin)
    if url.scheme != 'https' or url.username or url.password or url.path or url.query or url.fragment or url.port is not None:
        raise ValueError('Use an HTTPS origin without path, credentials or port, e.g. https://research.example.org')
    host = url.hostname or ''
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        labels = host.split('.')
        if len(host) > 253 or len(labels) < 2 or not re.search('[a-z]', host) or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels):
            raise ValueError('Use a DNS hostname or IPv4 address')
    return 'https://' + host


def render(identity, port, origin, path):
    origin = validate_origin(origin)
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', identity) or not 1024 <= port <= 65535:
        raise ValueError('Invalid instance or backend port')
    if not re.fullmatch(r'/(?:[a-z0-9-]+/)*mcp', path):
        raise ValueError('Use an exact path such as /mcp or /alice/mcp')
    key = 'mcp_' + identity.replace('-', '_')
    http = f'''# Include in nginx http context; separate limits for this deployment.
limit_req_zone $binary_remote_addr zone={key}_requests:1m rate=10r/s;
limit_conn_zone $binary_remote_addr zone={key}_connections:1m;
map $http_origin ${key}_origin_ok {{
    default 0;
    "" 1;
    "{origin}" 1;
}}
'''
    location = f'''# Include only in the TLS server for {origin}.
location = {path} {{
    if (${key}_origin_ok = 0) {{ return 403; }}
    limit_req zone={key}_requests burst=20 nodelay;
    limit_conn {key}_connections 10;
    client_max_body_size 1m;
    proxy_pass http://127.0.0.1:{port}/mcp;
    proxy_http_version 1.1;
    proxy_set_header Host "127.0.0.1:{port}";
    proxy_set_header Origin "";
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_connect_timeout 5s;
    proxy_read_timeout 180s;
    proxy_send_timeout 180s;
    # Authorization is forwarded unchanged; nginx never supplies a bearer token.
    access_log off;
}}
'''
    return http, location


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--path', default='/mcp')
    args = parser.parse_args()
    setup.require_server_setup()
    root = setup.ROOT
    env = setup.values(root, '.env.mcp')
    if env['MCP_BIND_HOST'] != '127.0.0.1':
        raise ValueError('Public proxy requires a loopback-only MCP backend')
    identity = setup.values(root, '.env.runtime')['TENANT_ID']
    origin = validate_origin(args.origin)
    http, location = render(identity, int(env['MCP_PORT']), origin, args.path)
    files = [(root / '.state' / f'{identity}.http.conf', http),
             (root / '.state' / f'{identity}.location.conf', location)]
    if any(path.exists() or path.is_symlink() for path, _ in files):
        raise FileExistsError('Generated proxy files already exist; review and archive them before regeneration')
    claim = dict(origin=origin, path=args.path)
    fd = os.open(setup.REGISTRY / '.lock', os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        records = setup.registry_records()
        for record in records:
            if record['instance'] != identity and record.get('proxy') == claim:
                raise ValueError(f'Public endpoint already reserved by {record["instance"]}')
        record = next(r for r in records if r['instance'] == identity)
        if record.get('proxy') and record['proxy'] != claim:
            raise ValueError('Instance already reserves another public endpoint; inspect before changing it')
        record['proxy'] = claim
        with tempfile.NamedTemporaryFile(mode='w', dir=setup.REGISTRY, delete=False) as temp:
            json.dump(record, temp)
            temporary = temp.name
        os.replace(temporary, setup.REGISTRY / f'{identity}.json')
        for path, text in files:
            setup.private_write(path, text)
    print('Generated .state/' + identity + '.{http,location}.conf. Review HTTPS.md before installing. No nginx changes applied.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, FileExistsError, FileNotFoundError, PermissionError) as exc:
        sys.exit(str(exc))
