"""
DEE-61a/c: configurable effort_level / answer_length contract tests.

Covers:
  - resolve_agent_config precedence (effort_level baseline, explicit config
    override, malformed-config fallback)
  - default request (both fields omitted) reproduces current behaviour
    exactly — identical AgentConfig, identical SSE event-type sequence
  - all four (effort_level, answer_length) combinations round-trip through
    the SSE response_end/done payloads and the /chat/agentic JSON body
  - fiqh-classified queries report settings_overridden=True regardless of
    the requested effort_level/answer_length
  - invalid enum values 422 at the ChatRequest layer
"""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

from agents.config.agent_config import (
    DEFAULT_AGENT_CONFIG,
    AgentConfig,
    resolve_agent_config,
)
from core.pipeline_langgraph import compute_effective_settings
from models.schemas import ChatRequest
from tests.conftest_async_stubs import (
    StubConfig,
    install_pipeline_stubs,
    run_pipeline_once,
)


# --- helpers ---------------------------------------------------------------- #


def _decode(chunks) -> str:
    parts: List[str] = []
    for ch in chunks:
        if isinstance(ch, bytes):
            ch = ch.decode("utf-8", errors="ignore")
        parts.append(str(ch))
    return "".join(parts)


def _events(sse_text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in re.split(r"\n\n+", sse_text):
        if not raw.strip():
            continue
        event_type = None
        data_lines: List[str] = []
        for line in raw.split("\n"):
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if event_type is None:
            continue
        try:
            data = json.loads("\n".join(data_lines)) if data_lines else {}
        except json.JSONDecodeError:
            data = {}
        out.append({"event": event_type, "data": data})
    return out


def _event_type_sequence(events: List[Dict[str, Any]]) -> List[str]:
    return [e["event"] for e in events]


# --- resolve_agent_config precedence ---------------------------------------- #


def test_resolve_agent_config_high_reproduces_default():
    assert resolve_agent_config("high", None) == DEFAULT_AGENT_CONFIG
    assert resolve_agent_config("high", {}) == DEFAULT_AGENT_CONFIG


def test_resolve_agent_config_quick_trims_iterations_retrieval_and_enhancement():
    quick = resolve_agent_config("quick", None)
    assert quick.max_iterations == 1
    assert quick.enable_enhancement is False
    assert quick.retrieval.shia_doc_count < DEFAULT_AGENT_CONFIG.retrieval.shia_doc_count
    assert quick.retrieval.sunni_doc_count <= DEFAULT_AGENT_CONFIG.retrieval.sunni_doc_count
    assert quick.retrieval.quran_doc_count <= DEFAULT_AGENT_CONFIG.retrieval.quran_doc_count


def test_explicit_config_field_wins_but_other_effort_derived_fields_survive():
    """The exact scenario flagged in review: config={"max_iterations": 5} on
    top of effort_level="quick" must NOT wipe out quick's enable_enhancement
    override — only max_iterations (the field actually present in the raw
    client dict) is allowed to change."""
    merged = resolve_agent_config("quick", {"max_iterations": 5})
    assert merged.max_iterations == 5  # explicit override wins
    assert merged.enable_enhancement is False  # untouched effort-derived value
    assert merged.retrieval.shia_doc_count == resolve_agent_config("quick", None).retrieval.shia_doc_count


def test_explicit_config_partial_retrieval_override_leaves_siblings_alone():
    merged = resolve_agent_config("quick", {"retrieval": {"shia_doc_count": 9}})
    assert merged.retrieval.shia_doc_count == 9
    quick_base = resolve_agent_config("quick", None)
    assert merged.retrieval.sunni_doc_count == quick_base.retrieval.sunni_doc_count
    assert merged.retrieval.quran_doc_count == quick_base.retrieval.quran_doc_count


def test_malformed_config_falls_back_to_effort_derived_not_global_default():
    # max_iterations has its own lenient int-coercion clamp in
    # AgentConfig.from_dict (pre-existing, unrelated to this ticket) so an
    # unparsable value there is silently popped rather than raising. Use a
    # field with no such clamp (shia_doc_count is a strict pydantic int) to
    # exercise resolve_agent_config's actual fallback-to-effort-baseline path.
    bad = resolve_agent_config("quick", {"retrieval": {"shia_doc_count": "not-an-int"}})
    # Falls back to the pure quick baseline, not DEFAULT_AGENT_CONFIG("high").
    assert bad == resolve_agent_config("quick", None)
    assert bad.enable_enhancement is False


# --- ChatRequest schema ------------------------------------------------------ #


def test_chat_request_defaults_omitted_fields_to_high_long():
    req = ChatRequest(user_query="x", session_id="s", language="english")
    assert req.effort_level == "high"
    assert req.answer_length == "long"


@pytest.mark.parametrize("field,value", [("effort_level", "medium"), ("answer_length", "verbose")])
def test_chat_request_invalid_enum_422(field, value):
    kwargs = {"user_query": "x", "session_id": "s", "language": "english", field: value}
    with pytest.raises(ValidationError):
        ChatRequest(**kwargs)


# --- compute_effective_settings (pure function) ------------------------------ #


def test_compute_effective_settings_fiqh_always_high_long_and_overridden():
    for effort, length in [("high", "long"), ("quick", "short"), ("quick", "long"), ("high", "short")]:
        result = compute_effective_settings(effort, length, True)
        assert result == {
            "applied_effort_level": "high",
            "applied_answer_length": "long",
            "settings_overridden": True,
            "override_reason": "fiqh",
        }


def test_compute_effective_settings_non_fiqh_echoes_request():
    result = compute_effective_settings("quick", "short", False)
    assert result == {
        "applied_effort_level": "quick",
        "applied_answer_length": "short",
        "settings_overridden": False,
        "override_reason": None,
    }


def test_compute_effective_settings_unknown_verdict_echoes_like_non_fiqh():
    """Request terminates before the fiqh verdict exists (e.g. producer
    crashed before fiqh_classification completed) -> treated as non-fiqh:
    echoed values, settings_overridden=False, never omitted."""
    assert compute_effective_settings("quick", "short", None) == compute_effective_settings(
        "quick", "short", False
    )


# --- SSE integration: default path is byte-for-byte event-type identical --- #


def test_default_request_sse_event_sequence_matches_explicit_high_long():
    """Omitting both fields must reproduce identical behaviour to sending
    effort_level='high', answer_length='long' explicitly — the acceptance
    bar from the ticket."""
    cfg = StubConfig()
    with install_pipeline_stubs(cfg):
        asyncio.run(run_pipeline_once())  # warmup
        _, chunks_default = asyncio.run(run_pipeline_once(session_id="omit-fields"))
        _, chunks_explicit = asyncio.run(
            run_pipeline_once(session_id="explicit-high-long", effort_level="high", answer_length="long")
        )

    seq_default = _event_type_sequence(_events(_decode(chunks_default)))
    seq_explicit = _event_type_sequence(_events(_decode(chunks_explicit)))
    assert seq_default == seq_explicit


@pytest.mark.parametrize("effort_level", ["high", "quick"])
@pytest.mark.parametrize("answer_length", ["long", "short"])
def test_all_combinations_round_trip_through_response_end_and_done(effort_level, answer_length):
    cfg = StubConfig()
    with install_pipeline_stubs(cfg):
        asyncio.run(run_pipeline_once())  # warmup
        _, chunks = asyncio.run(
            run_pipeline_once(
                session_id=f"combo-{effort_level}-{answer_length}",
                effort_level=effort_level,
                answer_length=answer_length,
            )
        )

    events = _events(_decode(chunks))
    response_end_events = [e for e in events if e["event"] == "response_end"]
    done_events = [e for e in events if e["event"] == "done"]
    assert response_end_events, "expected at least one response_end event"
    assert done_events, "expected a done event"

    for e in response_end_events + done_events:
        data = e["data"]
        assert data.get("applied_effort_level") == effort_level
        assert data.get("applied_answer_length") == answer_length
        assert data.get("settings_overridden") is False
        assert data.get("override_reason") is None


def test_non_streaming_body_carries_same_four_fields():
    from core import pipeline_langgraph

    cfg = StubConfig()
    with install_pipeline_stubs(cfg):
        result = asyncio.run(
            pipeline_langgraph.chat_pipeline_agentic(
                user_query="What does Islam say about patience?",
                session_id="non-streaming-effort-test",
                config=resolve_agent_config("quick", None),
                effort_level="quick",
                answer_length="short",
            )
        )

    assert result["applied_effort_level"] == "quick"
    assert result["applied_answer_length"] == "short"
    assert result["settings_overridden"] is False
    assert result["override_reason"] is None


# --- fiqh path: settings_overridden=True regardless of request -------------- #


@contextmanager
def _fiqh_routed_stubs():
    """Force the fiqh path: classifier returns a VALID_ category and the
    (heavy, LLM/Pinecone-backed) fiqh_subgraph itself is replaced with a
    canned result. Must be entered INSIDE install_pipeline_stubs — that
    context manager also patches modules.fiqh.classifier.aclassify_fiqh_query
    (to force OUT_OF_SCOPE_FIQH for the other tests) and would otherwise
    clobber this override on entry/restore it as the "original" on exit."""
    from modules.fiqh import classifier as fiqh_classifier_mod

    original_aclassify = fiqh_classifier_mod.aclassify_fiqh_query

    async def _astub_valid_fiqh(query):
        return "VALID_OBVIOUS"

    fiqh_classifier_mod.aclassify_fiqh_query = _astub_valid_fiqh

    async def _fake_fiqh_ainvoke(initial_state, *args, **kwargs):
        return {
            "accumulated_docs": [
                {
                    "chunk_id": "fake-fiqh-1",
                    "page_content_en": "Ruling text.",
                    "metadata": {"ruling_number": "1"},
                }
            ],
            "sea_result": SimpleNamespace(verdict="SUFFICIENT"),
            "status_events": [{"step": "fiqh_decompose", "message": "Decomposing fiqh query..."}],
        }

    import agents.fiqh.fiqh_graph as fiqh_graph_mod

    original_subgraph = fiqh_graph_mod.fiqh_subgraph
    fiqh_graph_mod.fiqh_subgraph = SimpleNamespace(ainvoke=_fake_fiqh_ainvoke)

    try:
        yield
    finally:
        fiqh_classifier_mod.aclassify_fiqh_query = original_aclassify
        fiqh_graph_mod.fiqh_subgraph = original_subgraph


@pytest.mark.parametrize("effort_level,answer_length", [("quick", "short"), ("high", "long")])
def test_fiqh_path_reports_settings_overridden_regardless_of_request(effort_level, answer_length):
    cfg = StubConfig()
    with install_pipeline_stubs(cfg), _fiqh_routed_stubs():
        _, chunks = asyncio.run(
            run_pipeline_once(
                session_id=f"fiqh-{effort_level}-{answer_length}",
                effort_level=effort_level,
                answer_length=answer_length,
            )
        )

    events = _events(_decode(chunks))
    done_events = [e for e in events if e["event"] == "done"]
    assert done_events, f"expected a done event; got {[e['event'] for e in events]}"
    data = done_events[-1]["data"]
    assert data.get("applied_effort_level") == "high"
    assert data.get("applied_answer_length") == "long"
    assert data.get("settings_overridden") is True
    assert data.get("override_reason") == "fiqh"
