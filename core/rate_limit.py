"""Abuse rate limiting for the chat endpoints.

Deliberately narrow in scope: this blocks scripted floods against the four
chat POST routes. It is not general-purpose quota enforcement — per-user
token/question budgets are out of scope.

All Redis I/O reuses the shared async client from `core.memory`; this module
never opens a connection of its own.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import List, Tuple

from fastapi import HTTPException, Request

from core.config import (
    CHAT_RATE_LIMIT_LONG_MAX_REQUESTS,
    CHAT_RATE_LIMIT_LONG_WINDOW_SECONDS,
    CHAT_RATE_LIMIT_SHORT_MAX_REQUESTS,
    CHAT_RATE_LIMIT_SHORT_WINDOW_SECONDS,
)
from core.memory import _get_async_redis

logger = logging.getLogger(__name__)

# Public 429 copy — intentionally generic; never expose thresholds or timing.
CHAT_RATE_LIMIT_MESSAGE = "Too many requests, please slow down."

# The limiter must never become the slowest part of a request.
REDIS_TIMEOUT_SECONDS = 1.0


def chat_rate_limit_rules() -> Tuple[Tuple[int, int], ...]:
    """Return (window_seconds, max_calls) rules from env-backed config."""
    return (
        (CHAT_RATE_LIMIT_SHORT_WINDOW_SECONDS, CHAT_RATE_LIMIT_SHORT_MAX_REQUESTS),
        (CHAT_RATE_LIMIT_LONG_WINDOW_SECONDS, CHAT_RATE_LIMIT_LONG_MAX_REQUESTS),
    )


def _rate_limit_key(request: Request) -> str:
    """Per-user when authenticated, per-IP otherwise.

    `request.state.user_id` is set by the auth dependency, which must resolve
    before this one — see the route declarations in `api/chat.py`.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    client = request.client
    return f"ip:{client.host if client else 'unknown'}"


async def _incr_windows(key: str, now: int, rules: Tuple[Tuple[int, int], ...]) -> List[int]:
    """INCR + EXPIRE every rule's window in a single pipeline round-trip."""
    client = _get_async_redis()
    async with client.pipeline(transaction=False) as pipe:
        for window, _limit in rules:
            redis_key = f"ratelimit:chat:{key}:{window}:{now // window}"
            await pipe.incr(redis_key)
            await pipe.expire(redis_key, window)
        results = await pipe.execute()
    return [int(count) for count in results[::2]]


async def enforce_chat_rate_limit(request: Request) -> None:
    """FastAPI dependency: raise 429 when the caller exceeds any chat rule."""
    rules = chat_rate_limit_rules()
    key = _rate_limit_key(request)
    now = int(time.time())

    try:
        counts = await asyncio.wait_for(
            _incr_windows(key, now, rules),
            REDIS_TIMEOUT_SECONDS,
        )
    except Exception:
        # Fail open: an unreachable or slow Redis must not take chat down.
        logger.warning("chat rate limit skipped, redis unavailable", exc_info=True)
        return

    user_id = getattr(request.state, "user_id", None)
    for count, (window, limit) in zip(counts, rules):
        if count > limit:
            logger.warning(
                "chat rate limit exceeded",
                extra={
                    "user_id": user_id,
                    "rate_limit_key": key,
                    "window_seconds": window,
                    "limit": limit,
                    "count": count,
                },
            )
            raise HTTPException(status_code=429, detail=CHAT_RATE_LIMIT_MESSAGE)
