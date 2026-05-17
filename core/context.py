import asyncio
import logging
from contextvars import ContextVar
from typing import Optional

# Per-request correlation ID. Set once in CorrelationIdMiddleware.dispatch();
# readable from any coroutine in the same async task chain without threading
# the request object through function signatures.
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

# Per-request asyncio.Queue used to surface fiqh sub-graph status events to
# the SSE stream in real-time, instead of accumulating them in FiqhState and
# replaying after the sub-graph completes (~10-15s atomic node from the parent
# graph's perspective). Set in core.pipeline_langgraph.response_generator
# before invoking agent.astream(); read from any fiqh sub-graph node via
# _push_fiqh_status(...). Default None so non-streaming code paths and tests
# that don't set it become a silent no-op.
fiqh_status_queue: ContextVar[Optional[asyncio.Queue]] = ContextVar(
    "fiqh_status_queue", default=None
)

_logger = logging.getLogger(__name__)


def _push_fiqh_status(step: str, message: str) -> None:
    """Push a status event into the contextvar-bound queue if one is set.

    Used by fiqh sub-graph nodes to emit progress updates the moment a stage
    starts. The pipeline's producer/consumer loop drains the queue interleaved
    with agent.astream events, so the SSE stream sees real-time progress
    instead of a 10-15s silent gap followed by a rapid-fire trail.

    Errors (full queue, missing event loop, etc.) are swallowed and logged at
    DEBUG so a transient queue issue can never abort the sub-graph itself.
    """
    queue = fiqh_status_queue.get()
    if queue is None:
        return
    try:
        queue.put_nowait({"step": step, "message": message})
    except Exception as exc:
        _logger.debug(
            "fiqh status queue put failed",
            extra={"correlation_id": correlation_id.get(), "error": str(exc)},
        )
