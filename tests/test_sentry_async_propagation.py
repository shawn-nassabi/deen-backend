"""
DEE-46 / Phase 7: Sentry async propagation gate.

Verifies that under concurrent asyncio execution:
  1. Per-coroutine isolation_scope() actually isolates Sentry tags between
     coroutines. If an async refactor accidentally shared a Hub or scope
     across tasks, captured events would have mixed-up tags — this gate
     catches that.
  2. The CorrelationIdMiddleware stamps a fresh correlation_id per HTTP
     request and exposes it via response header. This is the contract the
     `bind_sentry_scope()` helper depends on at every route handler.

We install an in-memory `sentry_sdk.transport.Transport` so no real Sentry
calls are made. The first test fires 5 concurrent coroutines, each setting
its own correlation_id tag and capturing an exception under
`sentry_sdk.isolation_scope()` — exactly the pattern `bind_sentry_scope()`
relies on. We then assert each captured event carries one (and only one)
distinct correlation_id matching its request.

Run:
    pytest tests/test_sentry_async_propagation.py -q
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, List, Optional

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport


# --- in-memory Sentry transport -------------------------------------------- #


class _InMemoryTransport(Transport):
    """Captures every sentry_sdk envelope into `self.events` and skips real
    network I/O. Subclasses sentry_sdk.transport.Transport so the SDK picks
    it up correctly when passed to `sentry_sdk.init(transport=...)`.

    Thread-safe so concurrent coroutines don't race on append.
    """

    def __init__(self, options=None) -> None:
        super().__init__(options or {})
        self._lock = threading.Lock()
        self.envelopes: List[Any] = []
        self.events: List[Dict[str, Any]] = []

    def capture_envelope(self, envelope) -> None:
        with self._lock:
            self.envelopes.append(envelope)
            for item in envelope.items:
                if item.headers.get("type") == "event":
                    # `item.payload.json` returns the parsed event dict.
                    payload = item.payload.json
                    if isinstance(payload, dict):
                        self.events.append(payload)

    def flush(self, timeout=None, callback=None) -> None:
        return None

    def kill(self) -> None:
        return None


def _tags_dict(event: Dict[str, Any]) -> Dict[str, str]:
    """Sentry serializes event tags as either a dict or a list-of-pairs;
    normalize to a flat dict for assertions."""
    tags = event.get("tags") or {}
    if isinstance(tags, list):
        return {k: v for k, v in tags}
    return dict(tags)


# --- fixtures -------------------------------------------------------------- #


@pytest.fixture
def in_memory_sentry():
    """Install a fresh sentry_sdk client wired to an in-memory transport for
    the duration of a single test, then tear it down."""
    transport = _InMemoryTransport()

    sentry_sdk.init(
        dsn="https://public@sentry.example/1",
        transport=transport,
        traces_sample_rate=0.0,
        environment="test",
        send_default_pii=False,
        # Empty integrations -> avoid auto-wiring FastApi/Starlette to a
        # global app instance (we want pure asyncio scope behavior here).
        default_integrations=False,
        auto_enabling_integrations=False,
    )

    yield transport

    client = sentry_sdk.get_client()
    if client is not None:
        client.close(timeout=0.0)


# --- the gates ------------------------------------------------------------- #


def test_per_coroutine_isolation_scopes_dont_leak_under_concurrency(in_memory_sentry):
    """Fire 5 concurrent coroutines, each:
      - opens its own isolation_scope() (mirrors what FastApi integration
        does per-request and what bind_sentry_scope() relies on)
      - sets a unique correlation_id tag
      - awaits — yielding to the loop so other coroutines interleave
      - raises and captures a RuntimeError

    Assertions:
      - exactly 5 events were captured (one per coroutine)
      - each event's correlation_id tag is unique
      - each correlation_id appears exactly once across all events (no
        scope leakage; if a tag bled into another coroutine's scope, we'd
        see duplicates and a missing CID)
    """
    import sentry_sdk

    cids = [f"cid-{i:04d}-{asyncio.get_event_loop_policy().__class__.__name__}" for i in range(5)]

    async def _task(cid: str, delay: float) -> None:
        with sentry_sdk.isolation_scope() as scope:
            scope.set_tag("correlation_id", cid)
            await asyncio.sleep(delay)  # interleave with other coroutines
            try:
                raise RuntimeError(f"intentional-failure-{cid}")
            except RuntimeError as exc:
                sentry_sdk.capture_exception(exc)

    async def _drive() -> None:
        # Vary delays so coroutines don't all complete in submission order
        # — gives scope leakage maximum opportunity to manifest.
        delays = [0.05, 0.01, 0.04, 0.02, 0.03]
        await asyncio.gather(*[_task(cid, d) for cid, d in zip(cids, delays)])

    asyncio.run(_drive())

    assert len(in_memory_sentry.events) == 5, (
        f"Expected 5 captured events, got {len(in_memory_sentry.events)}. "
        f"Events: {in_memory_sentry.events}"
    )

    captured_cids: List[str] = []
    for evt in in_memory_sentry.events:
        tags = _tags_dict(evt)
        cid = tags.get("correlation_id")
        assert cid, f"Captured event missing correlation_id tag: {evt}"
        captured_cids.append(cid)

    assert sorted(captured_cids) == sorted(cids), (
        f"Captured CIDs {sorted(captured_cids)} did not match expected "
        f"{sorted(cids)} — scope isolation leaked between coroutines."
    )


def test_isolation_scope_tags_dont_leak_to_outer_scope(in_memory_sentry):
    """Outer scope captures must not pick up tags set inside an inner
    isolation_scope(). Catches the "scope stacking" regression."""
    import sentry_sdk

    async def _drive() -> None:
        with sentry_sdk.isolation_scope() as inner:
            inner.set_tag("correlation_id", "inner-cid")

        # After the with-block exits, the inner scope's tags must NOT
        # appear on a subsequent capture from the outer scope.
        try:
            raise RuntimeError("outer-failure")
        except RuntimeError as exc:
            sentry_sdk.capture_exception(exc)

    asyncio.run(_drive())

    assert len(in_memory_sentry.events) == 1
    tags = _tags_dict(in_memory_sentry.events[0])
    assert tags.get("correlation_id") != "inner-cid", (
        f"Inner isolation_scope tag leaked to outer scope: {tags}"
    )


def test_correlation_id_middleware_stamps_unique_id_per_request():
    """Lower-bound regression test: confirm the middleware itself produces
    a fresh CID per call. If this breaks, every other Sentry assertion in
    the test suite is moot."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.middleware import CorrelationIdMiddleware

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/_cid")
    async def _read_cid():
        return {"ok": True}

    client = TestClient(app)
    seen: List[str] = []
    for _ in range(5):
        response = client.get("/_cid")
        cid = response.headers.get("x-correlation-id")
        assert cid, f"middleware did not stamp x-correlation-id header: {response.headers!r}"
        seen.append(cid)

    assert len(set(seen)) == 5, f"CIDs were not unique across 5 requests: {seen}"
