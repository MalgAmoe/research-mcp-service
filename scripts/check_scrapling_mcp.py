"""Read-only public-site smoke through the actual MCP transport; opens only own sessions.

--baseline exercises existing tools only. New-feature checks default to enabled.
Saves receipts/timing, not credentials or complete response bodies. No model calls.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]


async def main(baseline, output):
    env = dict(line.split('=', 1) for line in (ROOT / '.env.mcp').read_text().splitlines()
               if line and not line.startswith('#'))
    token = (ROOT / env['MCP_TOKEN_FILE']).read_text().strip()
    url = f"http://{env['MCP_BIND_HOST']}:{env['MCP_PORT']}/mcp"
    receipts = []
    def save():
        if output:
            Path(output).write_text(json.dumps(receipts, indent=2))
    async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + token}, trust_env=False, timeout=150) as client:
        async with streamable_http_client(url, http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                assert len(names) == (35 if baseline else 40), len(names)
                async def call(name, **args):
                    start = time.monotonic()
                    result = await session.call_tool(name, args)
                    receipt = {'tool': name, 'seconds': round(time.monotonic()-start, 3), 'error': result.is_error}
                    receipts.append(receipt)
                    save()
                    assert not result.is_error, (name, result)
                    texts = [c.text for c in result.content if c.type == 'text']
                    data = json.loads(texts[0]) if texts else {}
                    if name in {'browser_back', 'browser_forward'}:
                        receipt['history'] = data.get('history')
                        save()
                    return data, result
                await call('health')
                await call('web_recent_documents', limit=2)
                await call('rss_list')
                await call('search', query='Python asyncio documentation', limit=1, diagnostics=True)
                for strategy, profile in [('light', 'standard'), ('standard', 'standard'), ('browser', 'standard'), ('browser', 'stealth')]:
                    doc, _ = await call('web_read', url='https://docs.python.org/3/library/asyncio.html',
                                        strategy=strategy, browser_profile=profile, force_refresh=True)
                    assert doc.get('doc_id'), doc
                    receipts[-1].update(strategy=strategy, profile=profile, method=doc.get('method'), doc_id=doc['doc_id'])
                    await call('web_document', doc_id=doc['doc_id'], include_markdown=True)
                for profile in ['standard', 'stealth']:
                    opened, _ = await call('browser_open', url='https://quotes.toscrape.com/scroll', profile=profile, wait_ms=500)
                    sid = opened['session_id']
                    try:
                        if not baseline:
                            assert opened['diagnostics']['engine'] == ('scrapling' if profile == 'standard' else 'camoufox')
                        await call('browser_wait_for', session_id=sid, selector='.quote')
                        observed, screenshot = await call('browser_observe', session_id=sid, include_screenshot=True)
                        assert any(c.type == 'image' for c in screenshot.content)
                        assert observed['snapshot']
                        await call('browser_text', session_id=sid)
                        found, _ = await call('browser_find', session_id=sid, query='Albert Einstein')
                        assert found['matches'] > 0, found
                        if not baseline:
                            extracted, _ = await call('browser_extract', session_id=sid, selector='.quote .text', format='text', max_matches=2)
                            assert len(extracted['matches']) == 2, extracted
                            assert extracted['truncated']
                            _, image = await call('browser_screenshot', session_id=sid, selector='.quote')
                            assert any(c.type == 'image' for c in image.content)
                            if profile == 'standard':
                                listing, _ = await call('browser_network_requests', session_id=sid, url_contains='/api/quotes')
                                assert listing['requests'], listing
                                body, _ = await call('browser_network_response', session_id=sid, request_id=listing['requests'][0]['request_id'])
                                assert json.loads(body['text'])['quotes'], body
                        await call('browser_goto', session_id=sid, url='https://quotes.toscrape.com/login', wait_ms=100)
                        login, _ = await call('browser_wait_for', session_id=sid, selector='input[name="username"]')
                        username = next(n['ref'] for n in login['snapshot'] if n['role'] == 'textbox')
                        typed, _ = await call('browser_type', session_id=sid, ref=username, text='Legacy', wait_ms=0)
                        username = next(n['ref'] for n in typed['snapshot'] if n['role'] == 'textbox')
                        appended, _ = await call('browser_type', session_id=sid, ref=username, text=' + append', clear=False, wait_ms=0)
                        assert next(n['name'] for n in appended['snapshot'] if n['role'] == 'textbox') == 'Legacy + append'
                        if not baseline:
                            acted, _ = await call('browser_actions', session_id=sid, actions=[
                                {'kind': 'fill', 'selector': 'input[name="username"]', 'value': 'MCP local test'},
                                {'kind': 'press', 'selector': 'input[name="username"]', 'value': 'Tab'}])
                            assert acted['actions']['completed'] == 2 and acted['actions']['failed_action'] is None
                        back, _ = await call('browser_back', session_id=sid)
                        assert back['history']['outcome'] == 'completed', back['history']
                        forward, _ = await call('browser_forward', session_id=sid)
                        assert forward['history']['outcome'] == 'completed', forward['history']
                        if not baseline and profile == 'standard':
                            # Cross-document BFCache regression: URL changes alone are not success.
                            for _ in range(3):
                                await call('browser_goto', session_id=sid, url='https://quotes.toscrape.com/login', wait_ms=0)
                                await call('browser_goto', session_id=sid, url='https://quotes.toscrape.com/', wait_ms=0)
                                back, _ = await call('browser_back', session_id=sid)
                                assert back['history']['outcome'] == 'completed' and back['url'].endswith('/login'), back['history']
                                forward, _ = await call('browser_forward', session_id=sid)
                                assert forward['history']['outcome'] == 'completed' and forward['url'].rstrip('/') == 'https://quotes.toscrape.com', forward['history']
                    finally:
                        await call('browser_close', session_id=sid)
                save()
                print(json.dumps({'passed': True, 'tools': len(names), 'calls': len(receipts), 'receipts': output}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--output')
    args = parser.parse_args()
    asyncio.run(main(args.baseline, args.output))
