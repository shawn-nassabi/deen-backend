"""Tests for the chat abuse rate limiter (`core/rate_limit.py`).

The limiter is a fixed-window counter, so these tests drive a fake clock
rather than sleeping. Redis is `fakeredis.aioredis`, so the whole suite runs
in-process with no daemon.

The test app mirrors the real wiring in `api/chat.py`: auth first in the
route-level dependency list, then the limiter. That ordering is load-bearing
— it is what makes `request.state.user_id` available for per-user keying —
so `test_limit_is_keyed_per_user` and `test_key_is_scoped_to_the_user_id`
exist to catch a regression if someone reorders them.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from core import rate_limit as rate_limit_mod
from core.rate_limit import enforce_chat_rate_limit


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
    # Start on a 300s boundary so a test can fill the long window without
    # accidentally straddling two buckets.
    fake = _FakeClock(300 * 1_000_000)
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


def test_twenty_first_call_in_a_minute_is_rejected(client):
    for i in range(20):
        assert _post(client).status_code == 200, f"call {i + 1} should have passed"

    blocked = _post(client)
    assert blocked.status_code == 429
    assert "20 per 60 seconds" in blocked.json()["detail"]
    assert blocked.headers["Retry-After"] == "60"


def test_short_window_resets_on_the_next_bucket(client, clock):
    for _ in range(20):
        assert _post(client).status_code == 200
    assert _post(client).status_code == 429

    clock.advance(60)
    assert _post(client).status_code == 200


def test_fifty_first_call_in_five_minutes_is_rejected(client, clock):
    """Stay under the 60s rule (15 calls per minute) so only the 300s rule
    can trip. 15 calls in each of four sub-windows crosses 50 on call 51."""
    calls = 0
    for _ in range(3):
        for _ in range(15):
            calls += 1
            assert _post(client).status_code == 200, f"call {calls} should have passed"
        clock.advance(61)

    # 45 calls so far, all inside the same 300s bucket. Five more to reach 50.
    for _ in range(5):
        calls += 1
        assert _post(client).status_code == 200, f"call {calls} should have passed"

    blocked = _post(client)
    assert blocked.status_code == 429
    assert "50 per 300 seconds" in blocked.json()["detail"]


def test_limit_is_keyed_per_user(client):
    for _ in range(20):
        assert _post(client, user="user-a").status_code == 200
    assert _post(client, user="user-a").status_code == 429

    # A different caller must not inherit user-a's exhausted budget.
    assert _post(client, user="user-b").status_code == 200


def test_falls_back_to_client_ip_when_unauthenticated(client):
    for _ in range(20):
        assert client.post("/chat/stream/agentic").status_code == 200
    assert client.post("/chat/stream/agentic").status_code == 429


@pytest.mark.asyncio
async def test_key_is_scoped_to_the_user_id(client, fake_redis, clock):
    """Guards the dependency ordering: if the limiter ran before auth,
    `request.state.user_id` would be unset and the key would be IP-scoped."""
    _post(client, user="user-a")

    keys = {key.decode() for key in await fake_redis.keys("*")}
    bucket = int(clock.time()) // 60
    assert f"ratelimit:chat:user:user-a:60:{bucket}" in keys


def test_fails_open_when_redis_is_unavailable(client, monkeypatch):
    """Availability beats perfect blocking: a broken Redis must not 500 chat."""

    def exploding_client():
        raise ConnectionError("redis is down")

    monkeypatch.setattr(rate_limit_mod, "_get_async_redis", exploding_client)

    for _ in range(25):
        assert _post(client).status_code == 200
