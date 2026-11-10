"""Offline browser parity fixture. Run in a disposable network-none worker image.

No egress bridge, storage or credentials required. Sets no production policy:
controller FETCH_PROXY must be absent; separate check_browser_egress.py verifies
real deployment proxy denial. Exercises real browsers, not MCP transport.
"""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, '/app/scripts')
import browser_controller as controller


HTML = b'''<!doctype html><html><body><nav>Navigation junk</nav><h1>Acquisition fixture</h1>
<label>Name<input id="name"></label><button id="submit" onclick="document.querySelector('#output').textContent=document.querySelector('#name').value">Submit</button>
<div id="output"></div><label><input type="checkbox" id="check">Checkbox</label>
<select id="select"><option>First</option><option>Second</option></select>
<a href="/next" id="next">Next page</a><table id="table"><tr><th>Name</th><th>Value</th></tr><tr><td>A</td><td>42</td></tr></table>
<div id="api"></div><custom-card></custom-card><script>
fetch('/api/items').then(r=>r.json()).then(d=>document.querySelector('#api').textContent=d.items[0].title);
document.querySelector('custom-card').attachShadow({mode:'open'}).innerHTML='<p class="inside">Shadow evidence</p>';
</script></body></html>'''


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"items":[{"title":"API evidence","value":42}]}' if self.path.startswith('/api/') else (b'<h1>Next page</h1>' if self.path == '/next' else HTML)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json' if self.path.startswith('/api/') else 'text/html')
        self.send_header('Set-Cookie', 'fixture-secret=not-for-output')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


async def main():
    assert not controller.FETCH_PROXY, 'Use a disposable image, not the deployed worker'
    assert {p.name for p in Path('/sys/class/net').iterdir()} <= {'lo'}
    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}/'
    try:
        for profile in ['standard', 'stealth']:
            opened = await controller.open_session({'url': url, 'profile': profile, 'wait_ms': 100})
            sid = opened['session_id']
            assert opened['diagnostics']['engine'] == ('scrapling' if profile == 'standard' else 'camoufox')
            refs = {node['name']: node['ref'] for node in opened['snapshot']}
            assert 'Submit' in refs and opened['visible_text']
            page = controller.sessions[sid].page
            await page.locator('#api').wait_for(state='visible')
            # Existing tools and references stay usable.
            name_ref = next(node['ref'] for node in opened['snapshot'] if node['role'] == 'textbox')
            await controller.type_session({'session_id': sid, 'ref': name_ref, 'text': 'Existing tool', 'wait_ms': 0})
            current = await controller.observe_session({'session_id': sid})
            submit_ref = next(node['ref'] for node in current['snapshot'] if node['name'] == 'Submit')
            await controller.click_session({'session_id': sid, 'ref': submit_ref, 'wait_ms': 0})
            assert await page.locator('#output').inner_text() == 'Existing tool'
            result = await controller.actions_session({'session_id': sid, 'actions': [
                {'kind': 'fill', 'selector': '#name', 'value': 'Chained tool'},
                {'kind': 'check', 'selector': '#check'},
                {'kind': 'select', 'selector': '#select', 'value': 'Second'},
                {'kind': 'hover', 'selector': '#submit'},
                {'kind': 'click', 'selector': '#submit'}]})
            assert result['actions']['completed'] == 5, result
            assert await page.locator('#output').inner_text() == 'Chained tool'
            assert await page.locator('#check').is_checked()
            assert await page.locator('#select').input_value() == 'Second'
            selected = await controller.extract_session({'session_id': sid, 'selector': '#table'})
            assert '| A | 42 |' in selected['matches'][0]
            shadow = await controller.extract_session({'session_id': sid, 'selector': 'shadow-root .inside', 'format': 'text', 'pierce_shadow': True})
            assert shadow['matches'] == ['Shadow evidence'], shadow
            screenshot = await controller.screenshot_session({'session_id': sid, 'selector': '#table'})
            assert screenshot.get('screenshot_base64')
            timed = await controller.wait_for_session({'session_id': sid, 'selector': '#missing', 'timeout_ms': 20})
            assert timed['wait_condition']['outcome'] == 'timed_out'
            found = await controller.find_session({'session_id': sid, 'query': 'API evidence'})
            assert found['matches'] == 1
            if profile == 'standard':
                await asyncio.sleep(.1)
                listing = await controller.network_requests_session({'session_id': sid, 'url_contains': '/api/'})
                assert len(listing['requests']) == 1, listing
                response = await controller.network_response_session({'session_id': sid, 'request_id': listing['requests'][0]['request_id']})
                assert json.loads(response['text'])['items'][0]['value'] == 42, response
                assert 'fixture-secret' not in json.dumps(response)
            await controller.goto_session({'session_id': sid, 'url': url + 'next', 'wait_ms': 0})
            back = await controller.history_session({'session_id': sid, 'direction': 'back'})
            assert back['url'] == url and back['history']['outcome'] == 'completed', back
            forward = await controller.history_session({'session_id': sid, 'direction': 'forward'})
            assert forward['url'] == url + 'next' and forward['history']['outcome'] == 'completed', forward
            # Camoufox must support the installed Playwright interception protocol.
            await page.route(url + 'routed', lambda route: route.fulfill(
                status=200, content_type='text/html', body='<h1>Routed fixture</h1>'))
            await page.goto(url + 'routed')
            assert await page.locator('h1').inner_text() == 'Routed fixture'
            # Check actual movement, not just the wheel arguments or tool receipt.
            await page.add_style_tag(content='body { width: 3000px; height: 3000px; }')
            await page.mouse.move(400, 400)
            for direction in ['right', 'left', 'down', 'up']:
                await page.evaluate('window.scrollTo(200, 200)')
                await page.wait_for_timeout(100)
                before = await page.evaluate('[window.scrollX, window.scrollY]')
                await controller.scroll_session({'session_id': sid, 'direction': direction, 'amount': 100, 'wait_ms': 300})
                after = await page.evaluate('[window.scrollX, window.scrollY]')
                axis = 0 if direction in {'left', 'right'} else 1
                sign = 1 if direction in {'right', 'down'} else -1
                assert sign * (after[axis] - before[axis]) > 0, (direction, before, after)
                assert abs(after[1-axis] - before[1-axis]) <= 1, (direction, before, after)
                print(json.dumps({'profile': profile, 'scroll': direction, 'before': before, 'after': after}), flush=True)
            scratch = Path(controller.sessions[sid].scratch)
            assert scratch.is_dir()
            assert (await controller.close_session({'session_id': sid}))['closed']
            assert not scratch.exists(), 'Closed browser profile leaked'
            # Repetition catches growth hidden by a single successful close.
            for _ in range(3):
                repeated = await controller.open_session({'url': url, 'profile': profile, 'wait_ms': 0})
                scratch = Path(controller.sessions[repeated['session_id']].scratch)
                assert (await controller.close_session({'session_id': repeated['session_id']}))['closed']
                assert not scratch.exists(), 'Repeated browser profile leaked'
            print(json.dumps({'profile': profile, 'checks': 'refs/forms/chains/extract/shadow/screenshot/wait/find/history/route/scroll-axes/cleanup', 'passed': True}), flush=True)
        assert not controller.sessions
    finally:
        await controller.close_all_sessions()
        server.shutdown()
        server.server_close()


asyncio.run(main())
