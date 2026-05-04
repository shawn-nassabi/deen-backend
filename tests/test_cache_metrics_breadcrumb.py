"""
Phase 19 (OBS-01): Cache metrics breadcrumb tests.

Verifies that the per-turn cache efficiency breadcrumb fired at the SSE `done`
boundary (core/pipeline_langgraph.py:_emit_cache_metrics_breadcrumb):
  - emits the locked D-08 payload shape
  - sums cache_creation/cache_read across all _agent_node iterations (D-05)
  - returns ratio = 0.0 on the cold-cache denominator-zero path (D-06)
  - is a no-op when SENTRY_ENABLED is false (D-09)
  - fires on both the normal path and the early-exit path (D-02)

All tests are hermetic — no Anthropic API calls, no Pinecone, no Redis.
Pipeline-level tests patch `pipeline_langgraph.ChatAgent` with a FakeAgent
that yields a controlled final_state (D-07 option b: ChatState fields carry the
accumulated token counts). This mirrors the pattern in test_agentic_streaming_pipeline.py.
"""

import asyncio

import pytest

from core import pipeline_langgraph, sentry as core_sentry


# ---------------------------------------------------------------------------
# Shared FakeAgent helpers
# ---------------------------------------------------------------------------


def _make_fake_agent_class(node_state: dict):
    """Return a FakeAgent class whose astream yields a single event
    with the provided node_state.  The node key ('agent') is arbitrary
    for the pipeline — what matters is that `final_state` ends up set to
    `node_state` at the end of the astream loop."""

    class FakeAgent:
        def __init__(self, config):
            self.config = config

        async def astream(self, **kwargs):
            yield {"agent": node_state}

    return FakeAgent


def _make_early_exit_agent_class(node_state: dict):
    """Return a FakeAgent whose astream yields via check_early_exit node."""

    class FakeAgent:
        def __init__(self, config):
            self.config = config

        async def astream(self, **kwargs):
            yield {"check_early_exit": node_state}

    return FakeAgent


def _capture_breadcrumb(monkeypatch):
    """Capture every record_cache_metrics_breadcrumb call.

    Patches BOTH the canonical name (core.sentry.record_cache_metrics_breadcrumb)
    AND the import-bound copy in core.pipeline_langgraph (Python imports a
    function by reference at module load — patching only core.sentry is
    insufficient for an already-imported `from core.sentry import ...`).
    """
    captured = []

    def _spy(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr("core.sentry.record_cache_metrics_breadcrumb", _spy)
    monkeypatch.setattr(
        "core.pipeline_langgraph.record_cache_metrics_breadcrumb", _spy
    )
    return captured


def _drive_pipeline(node_state: dict, monkeypatch, user_query: str = "What does Islam teach about patience?", session_id: str = "test-19-03"):
    """Drive chat_pipeline_streaming_agentic with a FakeAgent yielding node_state.
    Patches append_turn_to_runtime_history to avoid DB calls.
    Returns drained SSE output string."""
    monkeypatch.setattr(
        pipeline_langgraph,
        "ChatAgent",
        _make_fake_agent_class(node_state),
    )
    monkeypatch.setattr(
        "services.chat_persistence_service.append_turn_to_runtime_history",
        lambda **kwargs: None,
    )

    async def _run():
        response = await pipeline_langgraph.chat_pipeline_streaming_agentic(
            user_query=user_query,
            session_id=session_id,
            target_language="english",
        )
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    return asyncio.run(_run())


def _drive_early_exit_pipeline(node_state: dict, monkeypatch, user_query: str = "Is shrimp halal?", session_id: str = "test-19-03-exit"):
    """Drive pipeline via early_exit path."""
    monkeypatch.setattr(
        pipeline_langgraph,
        "ChatAgent",
        _make_early_exit_agent_class(node_state),
    )
    monkeypatch.setattr(
        "services.chat_persistence_service.append_turn_to_runtime_history",
        lambda **kwargs: None,
    )

    async def _run():
        response = await pipeline_langgraph.chat_pipeline_streaming_agentic(
            user_query=user_query,
            session_id=session_id,
            target_language="english",
        )
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# Tests — pipeline-level (breadcrumb shape and math via controlled final_state)
# ---------------------------------------------------------------------------


def test_cold_cache_ratio_is_zero(monkeypatch):
    """ROADMAP success criterion 2 + D-06: empty-cache turn -> ratio 0.0, no ZeroDivisionError."""
    final_state = {
        "runtime_session_id": "test-19-03",
        "early_exit_message": None,
        "retrieved_docs": [],
        "quran_docs": [],
        "errors": [],
        "fiqh_category": "",
        "final_response": None,
        "cache_creation_tokens_total": 0,
        "cache_read_tokens_total": 0,
        "iterations": 1,
        "messages": [],
    }
    captured = _capture_breadcrumb(monkeypatch)
    _drive_pipeline(final_state, monkeypatch)

    assert len(captured) >= 1, "breadcrumb must fire at least once per turn (D-02)"
    last = captured[-1]
    assert last["cache_efficiency_ratio"] == 0.0
    assert last["cache_read_tokens"] == 0
    assert last["cache_creation_tokens"] == 0


def test_warm_cache_ratio_matches_sum_then_divide(monkeypatch):
    """Pure cache-read turn -> ratio 1.0 (sum_read / (sum_read + sum_creation))."""
    final_state = {
        "runtime_session_id": "test-19-03",
        "early_exit_message": None,
        "retrieved_docs": [],
        "quran_docs": [],
        "errors": [],
        "fiqh_category": "",
        "final_response": None,
        "cache_creation_tokens_total": 0,
        "cache_read_tokens_total": 1842,
        "iterations": 1,
        "messages": [],
    }
    captured = _capture_breadcrumb(monkeypatch)
    _drive_pipeline(final_state, monkeypatch)

    assert len(captured) >= 1
    last = captured[-1]
    assert last["cache_read_tokens"] == 1842
    assert last["cache_creation_tokens"] == 0
    # ratio = 1842 / (1842 + 0) = 1.0
    assert abs(last["cache_efficiency_ratio"] - 1.0) < 1e-9


def test_multi_iteration_aggregation_is_token_weighted(monkeypatch):
    """D-05: multi-iteration turn with equal creation+read -> ratio 0.5."""
    final_state = {
        "runtime_session_id": "test-19-03",
        "early_exit_message": None,
        "retrieved_docs": [],
        "quran_docs": [],
        "errors": [],
        "fiqh_category": "",
        "final_response": None,
        "cache_creation_tokens_total": 1842,
        "cache_read_tokens_total": 1842,
        "iterations": 2,
        "messages": [],
    }
    captured = _capture_breadcrumb(monkeypatch)
    _drive_pipeline(final_state, monkeypatch)

    assert len(captured) >= 1
    last = captured[-1]
    assert last["cache_creation_tokens"] == 1842
    assert last["cache_read_tokens"] == 1842
    assert last["iterations"] == 2
    # ratio = 1842 / (1842 + 1842) = 0.5
    assert abs(last["cache_efficiency_ratio"] - 0.5) < 1e-9


def test_breadcrumb_payload_shape_locked_to_d08(monkeypatch):
    """D-08: data dict must carry exactly the four canonical keys."""
    final_state = {
        "runtime_session_id": "test-19-03",
        "early_exit_message": None,
        "retrieved_docs": [],
        "quran_docs": [],
        "errors": [],
        "fiqh_category": "",
        "final_response": None,
        "cache_creation_tokens_total": 0,
        "cache_read_tokens_total": 0,
        "iterations": 1,
        "messages": [],
    }
    captured = _capture_breadcrumb(monkeypatch)
    _drive_pipeline(final_state, monkeypatch)

    assert len(captured) >= 1
    keys = set(captured[-1].keys())
    assert keys == {
        "cache_efficiency_ratio",
        "cache_read_tokens",
        "cache_creation_tokens",
        "iterations",
    }, f"unexpected breadcrumb shape: {keys}"


def test_breadcrumb_fires_on_early_exit_path(monkeypatch):
    """D-02: breadcrumb fires on the early-exit (non-Islamic / fiqh) path too."""
    final_state = {
        "runtime_session_id": "test-19-03-exit",
        "early_exit_message": "Please consult a qualified scholar.",
        "retrieved_docs": [],
        "quran_docs": [],
        "errors": [],
        "fiqh_category": "",
        "final_response": None,
        "cache_creation_tokens_total": 0,
        "cache_read_tokens_total": 0,
        "iterations": 1,
        "messages": [],
    }
    captured = _capture_breadcrumb(monkeypatch)
    _drive_early_exit_pipeline(final_state, monkeypatch)

    assert len(captured) >= 1, "breadcrumb must fire on early-exit path (D-02)"
    last = captured[-1]
    # Cold-cache on early-exit path still emits ratio=0.0
    assert last["cache_efficiency_ratio"] == 0.0


# ---------------------------------------------------------------------------
# Tests — direct unit tests on the helper functions (no pipeline)
# ---------------------------------------------------------------------------


def test_breadcrumb_no_op_when_sentry_disabled(monkeypatch):
    """D-09: helper must short-circuit when SENTRY_ENABLED is false."""
    sdk_calls = []

    class _SDKSpy:
        @staticmethod
        def add_breadcrumb(**kwargs):
            sdk_calls.append(kwargs)

    monkeypatch.setattr(core_sentry, "SENTRY_ENABLED", False)
    monkeypatch.setattr(core_sentry, "sentry_sdk", _SDKSpy)

    core_sentry.record_cache_metrics_breadcrumb(
        cache_efficiency_ratio=0.5,
        cache_read_tokens=10,
        cache_creation_tokens=10,
        iterations=2,
    )

    assert sdk_calls == [], "helper called sentry_sdk.add_breadcrumb when SENTRY_ENABLED was false"


def test_breadcrumb_helper_emits_when_sentry_enabled(monkeypatch):
    """Inverse of the no-op test — when SENTRY_ENABLED is true, sentry_sdk is called once with the D-08 shape."""
    sdk_calls = []

    class _SDKSpy:
        @staticmethod
        def add_breadcrumb(**kwargs):
            sdk_calls.append(kwargs)

    monkeypatch.setattr(core_sentry, "SENTRY_ENABLED", True)
    monkeypatch.setattr(core_sentry, "sentry_sdk", _SDKSpy)

    core_sentry.record_cache_metrics_breadcrumb(
        cache_efficiency_ratio=0.5,
        cache_read_tokens=10,
        cache_creation_tokens=10,
        iterations=2,
    )

    assert len(sdk_calls) == 1
    call = sdk_calls[0]
    assert call["category"] == "cache_metrics"
    assert call["level"] == "info"
    assert call["message"] == "cache_efficiency"
    assert call["data"] == {
        "cache_efficiency_ratio": 0.5,
        "cache_read_tokens": 10,
        "cache_creation_tokens": 10,
        "iterations": 2,
    }


def test_emit_helper_direct_cold_cache(monkeypatch):
    """Direct unit test of _emit_cache_metrics_breadcrumb with zero tokens (D-06)."""
    captured = _capture_breadcrumb(monkeypatch)

    final_state = {
        "cache_creation_tokens_total": 0,
        "cache_read_tokens_total": 0,
        "iterations": 1,
    }
    pipeline_langgraph._emit_cache_metrics_breadcrumb(final_state)

    assert len(captured) == 1
    call = captured[0]
    assert call["cache_efficiency_ratio"] == 0.0
    assert call["cache_read_tokens"] == 0
    assert call["cache_creation_tokens"] == 0
    assert call["iterations"] == 1


def test_emit_helper_handles_none_final_state(monkeypatch):
    """_emit_cache_metrics_breadcrumb must not raise when final_state is None (defensive path)."""
    captured = _capture_breadcrumb(monkeypatch)

    # Must not raise ZeroDivisionError or AttributeError
    pipeline_langgraph._emit_cache_metrics_breadcrumb(None)

    assert len(captured) == 1
    call = captured[0]
    assert call["cache_efficiency_ratio"] == 0.0
    assert call["cache_read_tokens"] == 0
    assert call["cache_creation_tokens"] == 0
