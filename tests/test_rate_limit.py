"""Tests for the chat abuse rate limiter (`core/rate_limit.py`).

The limiter is a fixed-window counter, so these tests drive a fake clock
rather than sleeping. Redis is `fakeredis.aioredis`, so the whole suite runs
in-process with no daemon.

Thresholds come from env via `core.config` (see `tests/conftest.py` defaults).
The test app mirrors the real wiring in `api/chat.py`: auth first in the
route-level dependency list, then the limiter.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from core import rate_limit as rate_limit_mod
from core.config import (
    CHAT_RATE_LIMIT_LONG_MAX_REQUESTS,
    CHAT_RATE_LIMIT_LONG_WINDOW_SECONDS,
    CHAT_RATE_LIMIT_SHORT_MAX_REQUESTS,
    CHAT_RATE_LIMIT_SHORT_WINDOW_SECONDS,
)
from core.rate_limit import CHAT_RATE_LIMIT_MESSAGE, enforce_chat_rate_limit


class _FakeClock:
    """Stands in for the `time` module inside `core.rate_limit`."""

    def __init__(self, start: float) -> None:
        self._now = start

    def time(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture
def clock(monkeypatch) -> _FakeClock:
    # Start on a long-window boundary so multi-bucket tests stay in one bucket.
    fake = _FakeClock(CHAT_RATE_LIMIT_LONG_WINDOW_SECONDS * 1_000_000)
    monkeypatch.setattr(rate_limit_mod, "time", fake)
    return fake


@pytest.fixture
def fake_redis(monkeypatch) -> fakeredis.aioredis.FakeRedis:
    client = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(rate_limit_mod, "_get_async_redis", lambda: client)
    return client


@pytest.fixture
def client(clock, fake_redis) -> TestClient:
    app = FastAPI()

    async def stub_auth(request: Request) -> None:
        """Stand-in for `core.auth.auth`, which sets the same attribute."""
        request.state.user_id = request.headers.get("x-test-user")

    @app.post(
        "/chat/stream/agentic",
        dependencies=[Depends(stub_auth), Depends(enforce_chat_rate_limit)],
    )
    async def chat() -> dict:
        return {"ok": True}

    return TestClient(app)


def _post(client: TestClient, user: str = "user-a"):
    return client.post("/chat/stream/agentic", headers={"x-test-user": user})


def _assert_generic_429(response) -> None:
    assert response.status_code == 429
    assert response.json()["detail"] == CHAT_RATE_LIMIT_MESSAGE
    assert "Retry-After" not in response.headers


def test_short_window_limit_is_rejected(client):
    short_max = CHAT_RATE_LIMIT_SHORT_MAX_REQUESTS
    for i in range(short_max):
        assert _post(client).status_code == 200, f"call {i + 1} should have passed"

    _assert_generic_429(_post(client))


def test_short_window_resets_on_the_next_bucket(client, clock):
    short_max = CHAT_RATE_LIMIT_SHORT_MAX_REQUESTS
    for _ in range(short_max):
        assert _post(client).status_code == 200
    _assert_generic_429(_post(client))

    clock.advance(CHAT_RATE_LIMIT_SHORT_WINDOW_SECONDS)
    assert _post(client).status_code == 200


def test_long_window_limit_is_rejected(client, clock):
    """Stay under the short-window rule each minute so only the long rule trips."""
    short_max = CHAT_RATE_LIMIT_SHORT_MAX_REQUESTS
    long_max = CHAT_RATE_LIMIT_LONG_MAX_REQUESTS
    calls_per_minute = short_max - 1

    calls = 0
    while calls < long_max:
        batch = min(calls_per_minute, long_max - calls)
        for _ in range(batch):
            calls += 1
            assert _post(client).status_code == 200, f"call {calls} should have passed"
        if calls < long_max:
            clock.advance(CHAT_RATE_LIMIT_SHORT_WINDOW_SECONDS + 1)

    _assert_generic_429(_post(client))


def test_limit_is_keyed_per_user(client):
    short_max = CHAT_RATE_LIMIT_SHORT_MAX_REQUESTS
    for _ in range(short_max):
        assert _post(client, user="user-a").status_code == 200
    _assert_generic_429(_post(client, user="user-a"))

    # A different caller must not inherit user-a's exhausted budget.
    assert _post(client, user="user-b").status_code == 200


def test_falls_back_to_client_ip_when_unauthenticated(client):
    short_max = CHAT_RATE_LIMIT_SHORT_MAX_REQUESTS
    for _ in range(short_max):
        assert client.post("/chat/stream/agentic").status_code == 200
    _assert_generic_429(client.post("/chat/stream/agentic"))


@pytest.mark.asyncio
async def test_key_is_scoped_to_the_user_id(client, fake_redis, clock):
    """Guards the dependency ordering: if the limiter ran before auth,
    `request.state.user_id` would be unset and the key would be IP-scoped."""
    _post(client, user="user-a")

    keys = {key.decode() for key in await fake_redis.keys("*")}
    bucket = int(clock.time()) // CHAT_RATE_LIMIT_SHORT_WINDOW_SECONDS
    assert (
        f"ratelimit:chat:user:user-a:{CHAT_RATE_LIMIT_SHORT_WINDOW_SECONDS}:{bucket}"
        in keys
    )


def test_fails_open_when_redis_is_unavailable(client, monkeypatch):
    """Availability beats perfect blocking: a broken Redis must not 500 chat."""

    def exploding_client():
        raise ConnectionError("redis is down")

    monkeypatch.setattr(rate_limit_mod, "_get_async_redis", exploding_client)

    over_limit = CHAT_RATE_LIMIT_SHORT_MAX_REQUESTS + 5
    for _ in range(over_limit):
        assert _post(client).status_code == 200
