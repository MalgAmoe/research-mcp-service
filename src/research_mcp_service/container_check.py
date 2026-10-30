"""Check the running container's MCP without host Python packages or model calls."""
import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def check(live=False):
    headers = {'Authorization': 'Bearer ' + Path(os.environ['MCP_TOKEN_FILE']).read_text().strip(),
               'Host': os.environ['MCP_BIND_HOST'] + ':' + os.environ['MCP_PORT']}
    async with httpx.AsyncClient(headers=headers, trust_env=False, timeout=150) as client:
        async with streamable_http_client('http://127.0.0.1:8766/mcp', http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                assert len((await session.list_tools()).tools) == 34
                async def call(name, **args):
                    result = await session.call_tool(name, args)
                    if result.is_error:
                        raise RuntimeError(name + ' failed; inspect deployment logs')
                    return json.loads(next(block.text for block in result.content if block.type == 'text'))
                await call('health')
                await call('web_capabilities')
                await call('web_recent_documents', limit=1)
                await call('rss_list')
                print('Authenticated MCP/control/Redis calls passed; 34 tools.', flush=True)
                if live:
                    await call('search', query='Python documentation', limit=1, diagnostics=True)
                    doc = await call('web_read', url='https://example.com/', strategy='light', force_refresh=True)
                    await call('web_document', doc_id=doc['doc_id'], include_markdown=True)
                    for profile in ['standard', 'stealth']:
                        page = await call('browser_open', url='https://example.com/', profile=profile)
                        try:
                            await call('browser_observe', session_id=page['session_id'])
                        finally:
                            await call('browser_close', session_id=page['session_id'])
                    print('Search call, acquisition/storage/readback, Chromium and Camoufox passed. Provider coverage not certified.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    asyncio.run(check(parser.parse_args().live))
