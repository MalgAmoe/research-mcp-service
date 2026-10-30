"""Bounded, unprivileged startup gate. Never invokes Docker or external providers."""
import asyncio
import os
from pathlib import Path

from .gateway import GatewayClient


async def wait_ready(client, timeout=180, interval=2):
    try:
        async with asyncio.timeout(timeout):
            while True:
                try:
                    async with asyncio.timeout(5):
                        status = await client('GET', '/health/dependencies')
                    if all(status.get(key) == 'ok' for key in ('redis', 's3', 'worker', 'maintenance')):
                        return
                except Exception:
                    # Do not log backend exceptions or credentials during boot retries.
                    pass
                await asyncio.sleep(interval)
    except TimeoutError:
        raise SystemExit('Private research dependencies did not become ready before the startup deadline') from None


def main():
    token = Path(os.environ['MCP_GATEWAY_TOKEN_FILE']).read_text().strip()
    client = GatewayClient(os.environ['MCP_GATEWAY_URL'], token=token,
                           socket=os.environ['MCP_GATEWAY_SOCKET'])
    asyncio.run(wait_ready(client))


if __name__ == '__main__':
    main()
