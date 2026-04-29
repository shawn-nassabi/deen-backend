# core/memory.py
import json
from typing import Callable, List, Optional, Union

import redis  # legacy sync client — still used by `make_history` callers
import redis.asyncio as aioredis
from langchain_community.chat_message_histories import (
    RedisChatMessageHistory,
    ChatMessageHistory as EphemeralHistory,
)
from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict
from langchain_core.runnables.history import RunnableWithMessageHistory

from core.config import REDIS_URL, KEY_PREFIX, TTL_SECONDS, MAX_MESSAGES

HistoryT = Union[RedisChatMessageHistory, EphemeralHistory]


# ---------------------------------------------------------------------------
# Connectivity check (sync ping at import time — cheap and works fine for both
# sync and async paths since "is Redis reachable" doesn't need an event loop).
# ---------------------------------------------------------------------------


def _redis_ok(url: str) -> bool:
    try:
        client = redis.from_url(url)
        client.ping()
        print("USING REDIS, MEMORY PERSISTENCE ENABLED")
        return True
    except Exception as e:
        print(f"[memory] Redis not reachable: {e}")
        return False


USE_REDIS = _redis_ok(REDIS_URL)


# ---------------------------------------------------------------------------
# Sync API (kept for legacy callers — /chat/, /references, /hikmah/elaborate
# until DEE-44 lands; safe to call from sync code paths).
# ---------------------------------------------------------------------------


def make_history(session_id: str) -> HistoryT:
    """Return a sync message history bound to this session.

    Uses Redis when available; otherwise falls back to in-process ephemeral.
    Prefer `amake_history` from inside an event loop (DEE-43).
    """
    if USE_REDIS:
        return RedisChatMessageHistory(
            session_id=f"{KEY_PREFIX}:{session_id}",
            url=REDIS_URL,
            ttl=TTL_SECONDS,
        )
    print(f"[memory] Using ephemeral in-memory history for session: {session_id}")
    return EphemeralHistory()


def trim_history(history: HistoryT, max_messages: int = MAX_MESSAGES):
    """Hard-cap the number of stored messages to avoid unbounded growth.
    Keeps most recent N messages.
    """
    msgs = history.messages
    if len(msgs) > max_messages:
        keep = msgs[-max_messages:]
        history.clear()
        history.add_messages(keep)


def with_redis_history(chain) -> Callable[[dict, dict], str]:
    """Wrap a Runnable (prompt | model | parser) with Redis-backed message history."""
    return RunnableWithMessageHistory(
        chain,
        lambda session_id: make_history(session_id),
        input_messages_key="query",
        history_messages_key="chat_history",
    )


# ---------------------------------------------------------------------------
# Async API (DEE-43)
#
# AsyncRedisChatMessageHistory is wire-compatible with langchain-community's
# `RedisChatMessageHistory`: same key shape (`message_store:{session_id}`),
# same JSON-encoded message-dict list-element format with newest-first lpush
# storage, same TTL semantics. Sessions written by the sync version are
# readable by the async one and vice versa, so the migration can roll
# incrementally without orphaning Redis data.
# ---------------------------------------------------------------------------


_DEFAULT_REDIS_KEY_PREFIX = "message_store:"

_async_redis_client: Optional[aioredis.Redis] = None


def _get_async_redis() -> aioredis.Redis:
    """Module-level connection pool. One client per process; redis.asyncio
    multiplexes over the underlying connection pool."""
    global _async_redis_client
    if _async_redis_client is None:
        _async_redis_client = aioredis.from_url(REDIS_URL, decode_responses=False)
    return _async_redis_client


class AsyncRedisChatMessageHistory:
    """Async-native chat history. Wire-compatible with the sync
    `RedisChatMessageHistory`."""

    def __init__(self, session_id: str, ttl: Optional[int] = TTL_SECONDS):
        self.session_id = session_id
        self.ttl = ttl
        self._client = _get_async_redis()

    @property
    def key(self) -> str:
        return _DEFAULT_REDIS_KEY_PREFIX + self.session_id

    async def aget_messages(self) -> List[BaseMessage]:
        items = await self._client.lrange(self.key, 0, -1)
        # Stored newest-first via lpush; reverse for chronological order.
        decoded = [json.loads(m.decode("utf-8")) for m in items[::-1]]
        return messages_from_dict(decoded)

    async def aadd_messages(self, messages: List[BaseMessage]) -> None:
        if not messages:
            return
        async with self._client.pipeline(transaction=False) as pipe:
            for msg in messages:
                await pipe.lpush(self.key, json.dumps(message_to_dict(msg)))
            if self.ttl:
                await pipe.expire(self.key, self.ttl)
            await pipe.execute()

    async def aclear(self) -> None:
        await self._client.delete(self.key)


class AsyncEphemeralHistory:
    """In-memory async fallback when Redis is unreachable. Same async API as
    `AsyncRedisChatMessageHistory` so callers don't need to branch on type.
    Process-local: history evaporates on restart."""

    def __init__(self):
        self._messages: List[BaseMessage] = []

    async def aget_messages(self) -> List[BaseMessage]:
        return list(self._messages)

    async def aadd_messages(self, messages: List[BaseMessage]) -> None:
        self._messages.extend(messages)

    async def aclear(self) -> None:
        self._messages.clear()


AsyncHistoryT = Union[AsyncRedisChatMessageHistory, AsyncEphemeralHistory]


# Per-process ephemeral fallback registry, keyed by session_id. Mirrors the
# sync EphemeralHistory behaviour (each call to `make_history` returns a
# fresh instance, but for the async path we want repeat calls within the
# same session to see each other's messages — otherwise the fallback would
# silently drop history between calls inside a single request).
_ephemeral_async_registry: dict = {}


def amake_history(session_id: str) -> AsyncHistoryT:
    """Return an async message history bound to this session.

    Uses redis.asyncio when Redis is reachable; otherwise an
    `AsyncEphemeralHistory` keyed by session_id (so the fallback still
    accumulates within a request).
    """
    if USE_REDIS:
        return AsyncRedisChatMessageHistory(
            session_id=f"{KEY_PREFIX}:{session_id}",
            ttl=TTL_SECONDS,
        )
    if session_id not in _ephemeral_async_registry:
        _ephemeral_async_registry[session_id] = AsyncEphemeralHistory()
    return _ephemeral_async_registry[session_id]


async def atrim_history(history: AsyncHistoryT, max_messages: int = MAX_MESSAGES):
    """Async equivalent of `trim_history`."""
    msgs = await history.aget_messages()
    if len(msgs) > max_messages:
        keep = msgs[-max_messages:]
        await history.aclear()
        await history.aadd_messages(keep)
