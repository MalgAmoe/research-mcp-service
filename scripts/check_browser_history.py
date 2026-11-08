"""Cross-document history readiness regression, using operator-owned sessions only.

Run in the isolated worker, or with --standalone in a disposable network-none
worker image mounting only its read-only egress socket. No MCP/schema changes.
"""
import argparse
import asyncio
from contextlib import AsyncExitStack
import json
from pathlib import Path
import sys
import time

from research_mcp_service.egress_bridge import Bridge

sys.path.insert(0, '/app/scripts')
import browser_controller as controller

PAIRS = [
    ('https://quotes.toscrape.com/login', 'https://quotes.toscrape.com/'),
    ('https://docs.python.org/3/library/asyncio.html', 'https://docs.python.org/3/library/sqlite3.html'),
]


async def main(standalone, profiles):
    assert {p.name for p in Path('/sys/class/net').iterdir()} == {'lo'}
    assert controller.FETCH_PROXY == 'http://127.0.0.1:3128'
    async with AsyncExitStack() as stack:
        if standalone:
            await stack.enter_async_context(await asyncio.start_server(Bridge().handle, '127.0.0.1', 3128))
        try:
            for profile in profiles:
                for first, second in PAIRS:
                    opened = await controller.open_session({'url': first, 'profile': profile, 'wait_ms': 0})
                    sid = opened['session_id']
                    try:
                        for cycle in range(3):
                            if cycle:
                                await controller.goto_session({'session_id': sid, 'url': first, 'wait_ms': 0})
                            await controller.goto_session({'session_id': sid, 'url': second, 'wait_ms': 0})
                            for direction, expected in [('back', first), ('forward', second)]:
                                start = time.perf_counter()
                                result = await controller.history_session({'session_id': sid, 'direction': direction})
                                receipt = {'profile': profile, 'cycle': cycle + 1,
                                           'seconds': round(time.perf_counter() - start, 3), **result['history']}
                                print(json.dumps(receipt), flush=True)
                                assert receipt['outcome'] == 'completed', receipt
                                assert result['url'] == expected, receipt
                    finally:
                        await controller.close_session({'session_id': sid})
        finally:
            await controller.close_all_sessions()
    print('HISTORY READINESS CHECKS PASSED', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--standalone', action='store_true')
    p.add_argument('--profiles', nargs='+', choices=['standard', 'stealth'], default=['standard', 'stealth'])
    args = p.parse_args()
    asyncio.run(main(args.standalone, args.profiles))
