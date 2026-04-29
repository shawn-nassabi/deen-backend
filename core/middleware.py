import uuid

from starlette.types import ASGIApp, Receive, Scope, Send

from core.context import correlation_id


class CorrelationIdMiddleware:
    """Generate a fresh UUID per request and propagate it via ContextVar.

    D-03: Always generates server-side UUID. Incoming X-Correlation-ID header
    from clients is ignored — never trusted as a source of truth.

    Implemented as a pure ASGI middleware (not BaseHTTPMiddleware) to ensure
    ContextVar propagation works correctly for sync route handlers executed
    in a thread-pool executor. BaseHTTPMiddleware copies the context before
    calling set(), so sync handlers would inherit the empty-string default.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        cid = str(uuid.uuid4())
        correlation_id.set(cid)

        async def send_with_header(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-correlation-id", cid.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_header)
