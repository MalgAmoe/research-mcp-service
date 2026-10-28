"""Test actual controller proxy behavior against a worker-local HTTP fixture.

Uses operator-only page evaluation, not an exposed MCP evaluation capability.
No fixture port is published; run inside the network-none worker.
"""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, '/app/scripts')
import browser_controller as controller

hits = []


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        hits.append(self.path)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'fixture reached')

    def log_message(self, *_):
        pass


async def main():
    assert {p.name for p in Path('/sys/class/net').iterdir()} <= {'lo'}
    try:
        server = ThreadingHTTPServer(('127.0.0.1', 80), Fixture)
    except PermissionError:
        server = ThreadingHTTPServer(('127.0.0.1', 8081), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = 'http://127.0.0.1' + (f':{server.server_port}' if server.server_port != 80 else '')
    try:
        for profile in ['standard', 'stealth']:
            opened = await controller.open_session({'url': 'https://docs.python.org/3/', 'profile': profile, 'block_resources': False})
            session = controller.sessions[opened['session_id']]
            try:
                await session.page.goto(url)
            except Exception:
                pass  # Firefox reports the proxy's empty 403 as a navigation error.
            assert not hits, f'{profile} bypassed proxy for navigation'
            # Fulfill only this document locally to establish a same-origin HTTP
            # page, avoiding false passes caused by CSP/mixed-content/PNA blocks.
            # All subresource requests still use the real browser/proxy network.
            html = f'''<img src="{url}/image"><script src="{url}/script"></script>
                <iframe src="{url}/frame"></iframe><script>
                fetch('{url}/fetch').catch(() => {{}});
                new WebSocket('ws://127.0.0.1:{server.server_port}/websocket');
                </script>'''
            await session.page.route(url + '/fixture', lambda route: route.fulfill(status=200, content_type='text/html', body=html))
            await session.page.goto(url + '/fixture')
            await asyncio.sleep(2)
            assert not hits, f'{profile} bypassed proxy for a subresource: {hits}'
            print(json.dumps({'check': f'{profile}-private-navigation-subresources-websocket',
                              'fixture_port': server.server_port, 'fixture_hits': len(hits)}), flush=True)
            echoed = await session.page.evaluate('''() => new Promise(resolve => {
                const socket = new WebSocket('wss://ws.postman-echo.com/raw');
                const timer = setTimeout(() => { socket.close(); resolve(false); }, 15000);
                socket.onopen = () => socket.send('research-mcp-probe');
                socket.onmessage = event => { clearTimeout(timer); socket.close(); resolve(event.data === 'research-mcp-probe'); };
                socket.onerror = () => { clearTimeout(timer); socket.close(); resolve(false); };
            })''')
            print(json.dumps({'check': f'{profile}-public-wss', 'echoed': echoed}), flush=True)
            assert echoed, f'{profile} public WSS probe failed'
            await controller.close_session({'session_id': session.session_id})
    finally:
        await controller.close_all_sessions()
        server.shutdown()
        server.server_close()


asyncio.run(main())
