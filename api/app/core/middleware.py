from __future__ import annotations

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send


class SelectiveGZipMiddleware:
    """Compress JSON while leaving packed binary and SSE responses untouched."""

    def __init__(self, app: ASGIApp, minimum_size: int = 1024, compresslevel: int = 5) -> None:
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size, compresslevel=compresslevel)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        query = bytes(scope.get("query_string", b""))
        if path.endswith("/stream") or b"format=bin" in query:
            await self.app(scope, receive, send)
            return
        await self.gzip(scope, receive, send)
