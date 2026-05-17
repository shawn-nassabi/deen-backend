"""Shared retry policies for transient infrastructure errors (DEE-51).

Two decorators wrap async functions that hit Anthropic or Pinecone:
- `anthropic_retry`: retries Anthropic 5xx/529/429/connection/timeout errors.
- `pinecone_retry`: retries Pinecone 5xx + transport-layer errors.

Both decorators only retry on *transient* failures. Authentication,
permission, validation, and 4xx-not-429 errors are surfaced immediately so
configuration mistakes are not silently absorbed by the retry layer.

Streaming call sites (`.astream`) MUST NOT be wrapped — partial-token
retries would emit duplicate output to the SSE consumer.
"""

from __future__ import annotations

import logging

import anthropic
from pinecone import exceptions as pinecone_exceptions
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger(__name__)


_ANTHROPIC_TRANSIENT_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


def _is_anthropic_transient(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
            anthropic.RateLimitError,
            anthropic.InternalServerError,
        ),
    ):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        status = getattr(exc, "status_code", None)
        return status in _ANTHROPIC_TRANSIENT_STATUS
    return False


def _is_pinecone_transient(exc: BaseException) -> bool:
    if isinstance(exc, pinecone_exceptions.ServiceException):
        return True
    if isinstance(exc, pinecone_exceptions.PineconeApiException):
        status = getattr(exc, "status", None)
        if isinstance(status, int) and status >= 500:
            return True
        if status == 429:
            return True
        return False
    if isinstance(exc, pinecone_exceptions.PineconeProtocolError):
        return True
    if isinstance(exc, (OSError, TimeoutError)):
        return True
    return False


def _log_before_sleep(provider: str):
    def hook(retry_state: RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        attempt = retry_state.attempt_number
        next_wait = getattr(retry_state.next_action, "sleep", None)
        logger.warning(
            "%s transient error on attempt %d, retrying in %.2fs: %s",
            provider,
            attempt,
            next_wait if next_wait is not None else 0.0,
            exc,
        )

    return hook


def _build_async_retry(
    *,
    provider: str,
    is_transient,
    attempts: int = 3,
    initial: float = 0.5,
    max_wait: float = 8.0,
):
    """Construct an AsyncRetrying-based decorator for async functions."""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            retrying = AsyncRetrying(
                stop=stop_after_attempt(attempts),
                wait=wait_exponential_jitter(initial=initial, max=max_wait),
                retry=retry_if_exception(is_transient),
                reraise=True,
                before_sleep=_log_before_sleep(provider),
            )
            async for attempt in retrying:
                with attempt:
                    return await func(*args, **kwargs)

        wrapper.__wrapped__ = func
        wrapper.__name__ = getattr(func, "__name__", "wrapper")
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator


anthropic_retry = _build_async_retry(
    provider="anthropic",
    is_transient=_is_anthropic_transient,
)

pinecone_retry = _build_async_retry(
    provider="pinecone",
    is_transient=_is_pinecone_transient,
)
