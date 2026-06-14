from __future__ import annotations

import json
import logging
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(message)s")


class RequestLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = logging.getLogger("lpe.request")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status_code = 500
        response_bytes = 0
        request_id = str(uuid.uuid4())

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_bytes
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            elif message["type"] == "http.response.body":
                response_bytes += len(message.get("body", b""))
            await send(message)

        await self.app(scope, receive, send_wrapper)
        route = scope.get("route")
        route_path = getattr(route, "path", scope.get("path", "unknown"))
        payload = {
            "request_id": request_id,
            "method": scope.get("method"),
            "route": route_path,
            "status": status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "response_bytes": response_bytes,
        }
        state = scope.get("state")
        if route_path == "/api/transactions" and isinstance(state, dict):
            if "response_mode" in state:
                payload["mode"] = state["response_mode"]
            if "response_count" in state:
                payload["count"] = state["response_count"]
        self.logger.info(json.dumps(payload, separators=(",", ":")))
