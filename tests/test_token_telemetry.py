"""
Unit tests for core/token_telemetry.py (token-cost initiative, Phase 0).

Covers: accumulator lifecycle/no-op safety, raw-usage extraction from ainvoke
responses, stream-chunk max-merge (never sum — LangChain #32818), the
structured-output callback path, and the extended Sentry breadcrumb emission.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import core.pipeline_langgraph as pipeline_mod
from core import sentry as core_sentry
from core.token_telemetry import (
    StreamUsageTracker,
    UsageCallbackHandler,
    record_llm_usage,
    reset_usage_accumulator,
    restore_usage_accumulator,
    snapshot_usage,
    usage_totals,
)


def _response(usage: dict | None):
    metadata = {"usage": usage} if usage is not None else {}
    return SimpleNamespace(response_metadata=metadata, content="x")


RAW_USAGE = {
    "input_tokens": 100,
    "output_tokens": 20,
    "cache_read_input_tokens": 300,
    "cache_creation_input_tokens": 50,
}


def test_record_is_noop_without_active_accumulator():
    record_llm_usage("agent", _response(RAW_USAGE))
    assert snapshot_usage() == {}


def test_record_accumulates_per_site_and_call_count():
    token = reset_usage_accumulator()
    try:
        record_llm_usage("agent", _response(RAW_USAGE))
        record_llm_usage("agent", _response(RAW_USAGE))
        record_llm_usage("intent_classifier", _response({"input_tokens": 7, "output_tokens": 1}))
        snap = snapshot_usage()
    finally:
        restore_usage_accumulator(token)

    assert snap["agent"]["calls"] == 2
    assert snap["agent"]["input_tokens"] == 200
    assert snap["agent"]["cache_read_input_tokens"] == 600
    assert snap["intent_classifier"] == {
        "calls": 1,
        "input_tokens": 7,
        "output_tokens": 1,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }

    totals = usage_totals(snap)
    assert totals["calls"] == 3
    assert totals["input_tokens"] == 207
    assert totals["output_tokens"] == 41


def test_record_noops_on_fakes_and_empty_usage():
    token = reset_usage_accumulator()
    try:
        record_llm_usage("agent", None)
        record_llm_usage("agent", SimpleNamespace(content="no metadata attr at all"))
        record_llm_usage("agent", _response(None))
        record_llm_usage("agent", _response({}))
        record_llm_usage("agent", _response({"input_tokens": 0, "output_tokens": 0}))
        assert snapshot_usage() == {}
    finally:
        restore_usage_accumulator(token)


def test_accumulator_reset_isolates_requests():
    token1 = reset_usage_accumulator()
    record_llm_usage("agent", _response(RAW_USAGE))
    assert snapshot_usage()["agent"]["calls"] == 1
    restore_usage_accumulator(token1)

    token2 = reset_usage_accumulator()
    try:
        assert snapshot_usage() == {}, "second request must not inherit the first's usage"
    finally:
        restore_usage_accumulator(token2)


def test_stream_tracker_subtracts_cache_from_langchain_input_and_max_merges():
    """LangChain usage_metadata.input_tokens INCLUDES cache read+creation
    (langchain_anthropic._create_usage_metadata); the tracker must recover the
    raw Anthropic split and must max-merge across chunks, never sum."""
    token = reset_usage_accumulator()
    try:
        tracker = StreamUsageTracker("generation_stream")
        # message_start-like chunk: no usage_metadata at all (0.3.22 behavior)
        tracker.feed(SimpleNamespace(usage_metadata=None, response_metadata={"model_name": "m"}))
        # content chunks: nothing to record
        tracker.feed(SimpleNamespace(usage_metadata=None, response_metadata={}))
        # message_delta chunk: complete usage, LangChain shape
        delta_usage = {
            "input_tokens": 100 + 300 + 50,  # raw + cache_read + cache_creation
            "output_tokens": 42,
            "total_tokens": 492,
            "input_token_details": {"cache_read": 300, "cache_creation": 50},
        }
        tracker.feed(SimpleNamespace(usage_metadata=delta_usage, response_metadata={}))
        # duplicate delta (defensive): max-merge keeps values identical, not doubled
        tracker.feed(SimpleNamespace(usage_metadata=delta_usage, response_metadata={}))
        tracker.commit()

        rec = snapshot_usage()["generation_stream"]
    finally:
        restore_usage_accumulator(token)

    assert rec == {
        "calls": 1,
        "input_tokens": 100,
        "output_tokens": 42,
        "cache_read_input_tokens": 300,
        "cache_creation_input_tokens": 50,
    }


def test_stream_tracker_commit_without_usage_is_noop():
    token = reset_usage_accumulator()
    try:
        tracker = StreamUsageTracker("generation_stream")
        tracker.feed(SimpleNamespace(usage_metadata=None, response_metadata={}))
        tracker.commit()
        assert snapshot_usage() == {}
    finally:
        restore_usage_accumulator(token)


def test_usage_callback_handler_reads_generation_message():
    message = _response(RAW_USAGE)
    llm_result = SimpleNamespace(generations=[[SimpleNamespace(message=message)]])
    token = reset_usage_accumulator()
    try:
        handler = UsageCallbackHandler("fiqh_sea")
        asyncio.run(handler.on_llm_end(llm_result))
        snap = snapshot_usage()
    finally:
        restore_usage_accumulator(token)
    assert snap["fiqh_sea"]["input_tokens"] == 100
    assert snap["fiqh_sea"]["calls"] == 1


def test_usage_callback_handler_safe_on_garbage():
    token = reset_usage_accumulator()
    try:
        handler = UsageCallbackHandler("fiqh_sea")
        asyncio.run(handler.on_llm_end(None))
        asyncio.run(handler.on_llm_end(SimpleNamespace(generations=[])))
        assert snapshot_usage() == {}
    finally:
        restore_usage_accumulator(token)


# ---------------------------------------------------------------------------
# Breadcrumb integration (additive fields only when usage was recorded)
# ---------------------------------------------------------------------------


def _capture_breadcrumb_kwargs(monkeypatch):
    captured = []

    def _spy(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(pipeline_mod, "record_cache_metrics_breadcrumb", _spy)
    return captured


def test_emit_breadcrumb_omits_usage_fields_when_accumulator_empty(monkeypatch):
    captured = _capture_breadcrumb_kwargs(monkeypatch)
    token = reset_usage_accumulator()
    try:
        pipeline_mod._emit_cache_metrics_breadcrumb({"iterations": 1})
    finally:
        restore_usage_accumulator(token)
    assert len(captured) == 1
    assert "input_tokens_total" not in captured[0]
    assert "usage_by_site" not in captured[0]


def test_emit_breadcrumb_attaches_totals_when_usage_recorded(monkeypatch):
    captured = _capture_breadcrumb_kwargs(monkeypatch)
    token = reset_usage_accumulator()
    try:
        record_llm_usage("agent", _response(RAW_USAGE))
        record_llm_usage("generation_stream", _response({"input_tokens": 10, "output_tokens": 5}))
        pipeline_mod._emit_cache_metrics_breadcrumb({"iterations": 2})
    finally:
        restore_usage_accumulator(token)
    assert len(captured) == 1
    assert captured[0]["input_tokens_total"] == 110
    assert captured[0]["output_tokens_total"] == 25
    assert set(captured[0]["usage_by_site"]) == {"agent", "generation_stream"}


def test_sentry_helper_keeps_d08_shape_without_new_kwargs(monkeypatch):
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
    assert set(sdk_calls[0]["data"].keys()) == {
        "cache_efficiency_ratio",
        "cache_read_tokens",
        "cache_creation_tokens",
        "iterations",
    }

    core_sentry.record_cache_metrics_breadcrumb(
        cache_efficiency_ratio=0.5,
        cache_read_tokens=10,
        cache_creation_tokens=10,
        iterations=2,
        input_tokens_total=100,
        output_tokens_total=20,
        usage_by_site={"agent": {"calls": 1}},
    )
    assert sdk_calls[1]["data"]["input_tokens_total"] == 100
    assert sdk_calls[1]["data"]["usage_by_site"] == {"agent": {"calls": 1}}


def test_maybe_usage_sse_is_env_gated(monkeypatch):
    monkeypatch.delenv("TOKEN_BENCH_DEBUG", raising=False)
    assert pipeline_mod._maybe_usage_sse() is None

    monkeypatch.setenv("TOKEN_BENCH_DEBUG", "1")
    token = reset_usage_accumulator()
    try:
        record_llm_usage("agent", _response(RAW_USAGE))
        event = pipeline_mod._maybe_usage_sse()
    finally:
        restore_usage_accumulator(token)
    assert event is not None and event.startswith("event: usage\n")
    assert '"agent"' in event
