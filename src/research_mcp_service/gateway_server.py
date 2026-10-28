"""Private storage gateway entry point. Requires isolated worker and explicit auth.

Not wired into the live MCP deployment until integration checks pass.
"""
import os
import re
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, Field
import uvicorn
from starlette.responses import JSONResponse

from .browser_process import ACTIONS
from .server import BearerAuth
from .worker_client import get_worker


class BrowserRequest(BaseModel):
    action: str = Field(max_length=32)
    params: dict


class HostedRoutes:
    """Do not expose legacy routes that can fetch/search outside worker RPC."""
    allowed = re.compile(r'^/(?:health|capabilities|read_url|batch_fetch|convert_document|browser|documents(?:/[^/]+(?:/artifacts/(?:original|markdown))?)?|rss(?:/.*)?)$')

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and not self.allowed.fullmatch(scope['path']):
            await JSONResponse({'error': 'route_not_enabled'}, status_code=404)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_gateway_app(token: str, worker_socket: str):
    if not worker_socket or not Path(worker_socket).is_absolute():
        raise ValueError('An absolute isolated worker socket is required')
    from research_gateway.config import settings
    if settings.worker_socket != worker_socket:
        raise ValueError('WORKER_SOCKET must match gateway configuration; local fetching is forbidden')
    from research_gateway.main import app

    @app.post('/browser')
    async def browser(request: BrowserRequest):
        if request.action not in ACTIONS:
            raise HTTPException(400, 'Unknown browser action')
        return await get_worker(worker_socket).browser(request.action, request.params)

    return BearerAuth(HostedRoutes(app), token)


def main():
    token = os.environ.get('GATEWAY_TOKEN', '')
    socket = os.environ.get('WORKER_SOCKET', '')
    if not socket or not Path(socket).is_socket():
        raise SystemExit('A running isolated worker socket is required')
    app = create_gateway_app(token, socket)
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False, proxy_headers=False,
                limit_concurrency=16, timeout_keep_alive=5)


if __name__ == '__main__':
    main()
