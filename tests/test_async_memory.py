"""
Phase 4 (DEE-43) parity tests for `core/memory.py`.

Pin two contracts:

1. `AsyncRedisChatMessageHistory` is **wire-compatible** with the sync
   `langchain_community.RedisChatMessageHistory` — same key shape, same
   JSON encoding, newest-first lpush semantics. A history written with the
   sync writer is readable by the async reader and vice versa, so the
   migration can roll incrementally without orphaning live Redis data.

2. `AsyncEphemeralHistory` (+ `amake_history` fallback) preserves message
   ordering and supports `atrim_history`'s cap-and-replace semantics.

We use `fakeredis.aioredis` so the test runs entirely in-process — no real
Redis daemon required.
"""

from __future__ import annotations

import json

import fakeredis.aioredis
import pytest
from langchain_core.messages import AIMessage, HumanMessage, message_to_dict
from langchain_community.chat_message_histories import RedisChatMessageHistory


@pytest.fixture
def fake_redis_clients(monkeypatch):
    """Replace both the sync `redis.from_url` and the async
    `redis.asyncio.from_url` clients with fakeredis equivalents that share
    the same in-memory store, so the wire-compat parity test exercises a
    single round-trip."""
    import fakeredis
    import redis as sync_redis_mod

    server = fakeredis.FakeServer()
    sync_client = fakeredis.FakeRedis(server=server)
    async_client = fakeredis.aioredis.FakeRedis(server=server)

    monkeypatch.setattr(sync_redis_mod, "from_url", lambda *args, **kwargs: sync_client)

    # core.memory.py caches the async client at module level — patch the
    # internal getter so each test gets a fresh fake-backed client.
    from core import memory as memory_mod

    monkeypatch.setattr(memory_mod, "_get_async_redis", lambda: async_client)
    # Force `USE_REDIS=True` for these tests; the in-process loadtest sets
    # an unreachable URL elsewhere and falls back to ephemeral, but here
    # we want the Redis path exercised.
    monkeypatch.setattr(memory_mod, "USE_REDIS", True)

    yield sync_client, async_client


@pytest.mark.asyncio
async def test_async_history_reads_what_sync_history_writes(fake_redis_clients):
    """Sync write → async read parity. The sync `RedisChatMessageHistory`
    serialises messages via lpush-of-json-message-dict at
    `message_store:{session_id}`; the async wrapper must use the same key
    and decoder so live data isn't orphaned during the migration."""
    from core.memory import AsyncRedisChatMessageHistory

    session_id = "parity-1"
    sync_history = RedisChatMessageHistory(
        session_id=session_id,
        url="redis://stub",
        ttl=None,
    )
    sync_history.add_message(HumanMessage(content="hello"))
    sync_history.add_message(AIMessage(content="hi back"))

    async_history = AsyncRedisChatMessageHistory(session_id=session_id, ttl=None)
    messages = await async_history.aget_messages()

    assert [m.content for m in messages] == ["hello", "hi back"]
    assert isinstance(messages[0], HumanMessage)
    assert isinstance(messages[1], AIMessage)


@pytest.mark.asyncio
async def test_sync_history_reads_what_async_history_writes(fake_redis_clients):
    """The reverse: async write → sync read. Belt-and-braces — guarantees
    both directions work during a rolling deploy where some workers run the
    new code and some haven't restarted yet."""
    from core.memory import AsyncRedisChatMessageHistory

    session_id = "parity-2"
    async_history = AsyncRedisChatMessageHistory(session_id=session_id, ttl=None)
    await async_history.aadd_messages([
        HumanMessage(content="async write"),
        AIMessage(content="async ai"),
    ])

    sync_history = RedisChatMessageHistory(
        session_id=session_id,
        url="redis://stub",
        ttl=None,
    )
    messages = sync_history.messages

    assert [m.content for m in messages] == ["async write", "async ai"]


@pytest.mark.asyncio
async def test_aclear_removes_session(fake_redis_clients):
    from core.memory import AsyncRedisChatMessageHistory

    h = AsyncRedisChatMessageHistory(session_id="parity-3", ttl=None)
    await h.aadd_messages([HumanMessage(content="x")])
    assert len(await h.aget_messages()) == 1

    await h.aclear()
    assert await h.aget_messages() == []


@pytest.mark.asyncio
async def test_atrim_caps_message_count(fake_redis_clients):
    from core.memory import AsyncRedisChatMessageHistory, atrim_history

    h = AsyncRedisChatMessageHistory(session_id="parity-4", ttl=None)
    msgs = [HumanMessage(content=f"m{i}") for i in range(50)]
    await h.aadd_messages(msgs)

    await atrim_history(h, max_messages=10)
    kept = await h.aget_messages()
    assert len(kept) == 10
    # The most recent 10 messages must be kept (m40..m49 in arrival order).
    assert [m.content for m in kept] == [f"m{i}" for i in range(40, 50)]


@pytest.mark.asyncio
async def test_amake_history_fallback_when_redis_unreachable(monkeypatch):
    """When `USE_REDIS=False`, `amake_history` returns an
    `AsyncEphemeralHistory` keyed by session_id. Repeat calls within the
    same session must observe each other's writes (otherwise the fallback
    would silently drop history within a single request)."""
    from core import memory as memory_mod

    monkeypatch.setattr(memory_mod, "USE_REDIS", False)
    # Reset the per-process registry so the test is hermetic.
    monkeypatch.setattr(memory_mod, "_ephemeral_async_registry", {})

    h1 = memory_mod.amake_history("ephemeral-session")
    await h1.aadd_messages([HumanMessage(content="alpha")])

    h2 = memory_mod.amake_history("ephemeral-session")
    messages = await h2.aget_messages()
    assert [m.content for m in messages] == ["alpha"]
    assert h1 is h2  # same instance for the same session
