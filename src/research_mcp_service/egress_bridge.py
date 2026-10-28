"""Loopback-only TCP bridge to the egress proxy's Unix socket.

Intended to run INSIDE a network_mode=none worker. Browsers and HTTP clients use
http://127.0.0.1:3128 as their proxy; they have no direct external network route.
"""
import asyncio
import os

from research_mcp_service.egress import copy_stream


class Bridge:
    def __init__(self):
        self.active = 0

    async def handle(self, reader, writer):
        if self.active >= 64:
            writer.close()
            return
        self.active += 1
        remote = None
        tasks = []
        try:
            async with asyncio.timeout(125):
                upstream, remote = await asyncio.open_unix_connection(os.environ.get('EGRESS_SOCKET', '/egress/proxy.sock'))
                tasks = [asyncio.create_task(copy_stream(reader, remote)),
                         asyncio.create_task(copy_stream(upstream, writer))]
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except (OSError, TimeoutError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if remote:
                remote.close()
            writer.close()
            self.active -= 1


async def main():
    server = await asyncio.start_server(Bridge().handle, '127.0.0.1', 3128)
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
