import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from core.context import correlation_id


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Generate a fresh UUID per request and propagate it via ContextVar.

    D-03: Always generates server-side UUID. Incoming X-Correlation-ID header
    from clients is ignored — never trusted as a source of truth.
    """

    async def dispatch(self, request: Request, call_next):
        cid = str(uuid.uuid4())
        correlation_id.set(cid)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response
