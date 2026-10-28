"""Cancel real in-flight browser work and check for surviving browser processes.

Run only inside the isolated worker: docker compose ... exec -T fetch-worker python < this-file.
"""
import json
from pathlib import Path
import select
import socket
import time

BROWSERS = {'chrome', 'chrome-headless-shell', 'chrome_headless_shell', 'headless_shell',
            'chrome_crashpad_handler', 'camoufox', 'camoufox-bin', 'firefox', 'firefox-bin'}


def browsers():
    found = {}
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        try:
            command = (directory / 'cmdline').read_bytes().split(b'\0', 1)[0].decode()
            name = Path(command).name
            if name in BROWSERS:
                found[directory.name] = name
        except (OSError, UnicodeError):
            pass
    return found


assert {p.name for p in Path('/sys/class/net').iterdir()} <= {'lo'}, 'Run inside the network-none worker'
for action in ['browser', 'read']:
    for profile in ['standard', 'stealth']:
        assert not browsers(), 'Unexpected pre-existing browser processes'
        params = {'url': 'https://docs.python.org/3/library/urllib.parse.html'}
        if action == 'browser':
            params.update(profile=profile, wait_ms=120000)
            payload = {'action': 'open', 'params': params}
            path = '/browser'
        else:
            params.update(strategy='browser', browser_profile=profile)
            payload = {'action': 'read', 'request': params}
            path = '/run'
        body = json.dumps(payload).encode()
        connection = socket.socket(socket.AF_UNIX)
        connection.connect('/rpc/worker.sock')
        connection.sendall(f'POST {path} HTTP/1.1\r\nHost: worker\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n'.encode() + body)
        deadline = time.monotonic() + 20
        try:
            while not browsers() and time.monotonic() < deadline:
                time.sleep(.05)
            active = browsers()
            assert active, 'Browser did not start'
            if action == 'browser':
                time.sleep(2)  # let the interactive page start rendering before cancellation
            assert not select.select([connection], [], [], 0)[0], 'Operation completed before cancellation'
        finally:
            connection.close()
        deadline = time.monotonic() + 10
        while browsers() and time.monotonic() < deadline:
            time.sleep(.1)
        remaining = browsers()
        print(json.dumps({'check': f'cancel-{action}-{profile}', 'started': len(active), 'remaining': remaining}), flush=True)
        assert not remaining, 'Browser processes survived caller cancellation'
