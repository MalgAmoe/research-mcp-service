"""Run inside the MCP container: three overlapping, uncached light reads via MCP."""
import asyncio
import json
import os
from pathlib import Path
import time

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    headers = {'Authorization': 'Bearer ' + Path(os.environ['MCP_TOKEN_FILE']).read_text().strip(),
               'Host': os.environ['MCP_BIND_HOST'] + ':' + os.environ['MCP_PORT']}
    urls = ['https://example.com/', 'https://docs.python.org/3/library/asyncio.html',
            'https://docs.python.org/3/library/tomllib.html']
    async with httpx.AsyncClient(headers=headers, trust_env=False, timeout=150) as client:
        async with streamable_http_client('http://127.0.0.1:8766/mcp', http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def read_url(url):
                    started = time.monotonic()
                    result = await session.call_tool('web_read', {'url': url, 'strategy': 'light', 'force_refresh': True})
                    if result.is_error:
                        return {'url': url, 'error': ' '.join(block.text for block in result.content if block.type == 'text')}
                    data = json.loads(next(block.text for block in result.content if block.type == 'text'))
                    assert data.get('status') == 'ready', 'Read did not produce a ready document'
                    return {'url': url, 'seconds': round(time.monotonic() - started, 3), 'status': data['status']}

                started = time.monotonic()
                results = await asyncio.gather(*(read_url(url) for url in urls))
                print(json.dumps({'reads': results, 'wall_seconds': round(time.monotonic() - started, 3)}), flush=True)
                assert all(result.get('status') == 'ready' for result in results), 'Concurrent read probe failed; see results'


if __name__ == '__main__':
    asyncio.run(main())
