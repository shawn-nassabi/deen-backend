from contextvars import ContextVar

# Per-request correlation ID. Set once in CorrelationIdMiddleware.dispatch();
# readable from any coroutine in the same async task chain without threading
# the request object through function signatures.
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
