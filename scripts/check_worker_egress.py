"""Real network check, run only in compose.deploy.yml's network-none fetch-worker container."""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

bridge = subprocess.Popen([sys.executable, '-m', 'research_mcp_service.egress_bridge'])
try:
    for _ in range(50):
        try:
            with socket.create_connection(('127.0.0.1', 3128), timeout=.2):
                break
        except OSError:
            time.sleep(.1)
    else:
        raise RuntimeError('Proxy bridge did not start')

    # A worker must have no route to public, private, Tailnet or metadata addresses.
    for host in ['1.1.1.1', '10.0.0.1', '172.17.0.1', '192.168.1.1', '100.64.0.1', '169.254.169.254']:
        try:
            connection = socket.create_connection((host, 80), timeout=1)
        except OSError:
            continue
        connection.close()
        raise AssertionError('Worker unexpectedly has a direct network route')

    # Override urllib's built-in localhost proxy bypass for these explicit tests.
    urllib.request.proxy_bypass = lambda host: False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({
        'http': 'http://127.0.0.1:3128', 'https': 'http://127.0.0.1:3128'}))
    forbidden = ['http://127.0.0.1/', 'http://localhost/', 'http://10.0.0.1/',
                 'http://169.254.169.254/latest/meta-data/', 'http://100.64.0.1/',
                 'http://2130706433/', 'http://0x7f000001/', 'http://127.1/',
                 'http://[::ffff:127.0.0.1]/', 'http://1.1.1.1:9000/']
    for url in forbidden:
        try:
            with opener.open(url, timeout=15):
                raise AssertionError('Forbidden destination was reachable')
        except urllib.error.HTTPError as exc:
            assert exc.code == 403, f'Expected explicit denial, got {exc.code}'
    for url in ['http://docs.python.org/3/', 'https://docs.python.org/3/']:
        with opener.open(url, timeout=30) as response:
            assert response.status == 200
            assert b'Python' in response.read(65536)
    print(json.dumps({'direct_network': 'blocked', 'forbidden_proxy_targets': len(forbidden),
                      'public_http': 'ok', 'public_https': 'ok'}), flush=True)
finally:
    bridge.terminate()
    bridge.wait(timeout=5)
