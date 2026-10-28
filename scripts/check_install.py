#!/usr/bin/env python3
"""Check a configured MCP endpoint without a model call. --live adds public fetch/browser probes."""
import argparse
import asyncio
import json
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]


async def check(live):
    env = dict(line.split('=', 1) for line in (ROOT / '.env.mcp').read_text().splitlines()
               if line and not line.startswith('#'))
    token = (ROOT / env['MCP_TOKEN_FILE']).read_text().strip()
    url = f"http://{env['MCP_BIND_HOST']}:{env['MCP_PORT']}/mcp"
    async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + token}, trust_env=False, timeout=150) as client:
        async with streamable_http_client(url, http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {'health', 'search', 'web_read', 'web_document_find', 'browser_wait_for', 'rss_list'} <= names
                async def call(name, **args):
                    result = await session.call_tool(name, args)
                    if result.is_error:
                        raise RuntimeError(f'{name} failed; inspect service logs and retry deliberately')
                    return json.loads(next(block.text for block in result.content if block.type == 'text'))
                await call('health')
                await call('web_capabilities')
                await call('web_recent_documents', limit=1)
                await call('rss_list')
                print(f'Authenticated MCP, control and Redis calls passed; {len(names)} tools. Browser/provider availability not implied.', flush=True)
                if live:
                    await call('search', query='Python documentation', limit=1, diagnostics=True)
                    doc = await call('web_read', url='https://example.com/', strategy='light', force_refresh=True)
                    await call('web_document', doc_id=doc['doc_id'], include_markdown=True)
                    page = await call('browser_open', url='https://example.com/')
                    try:
                        await call('browser_observe', session_id=page['session_id'])
                    finally:
                        await call('browser_close', session_id=page['session_id'])
                    print('Search call, public page acquisition/storage/retrieval and Chromium observation passed. Only the probe session was closed.', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live', action='store_true')
    asyncio.run(check(p.parse_args().live))
