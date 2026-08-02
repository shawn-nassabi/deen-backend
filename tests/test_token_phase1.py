"""
Token-cost DEE-60 Phase 1 tests.

Covers:
- The final_state delta-merge in chat_pipeline_streaming_agentic, which makes
  the fiqh streaming branch reachable (fiqh answers token-stream and the
  fiqh_references SSE event is emitted) — this is the first fiqh-path SSE
  test (previously a known gap: stubs forced OUT_OF_SCOPE_FIQH).
- The streaming_mode guard on _generate_fiqh_response_node (no LLM call on
  the SSE path; the ainvoke path still generates).
- num_documents clamping at both the graph level (_apply_tool_call_defaults)
  and the tool level (retrieval_tools._clamp).

Hermetic — no Anthropic/Pinecone/Redis network calls.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from core import pipeline_langgraph


# ---------------------------------------------------------------------------
# Fiqh streaming path (delta-merge + guard)
# ---------------------------------------------------------------------------


class _FakeFiqhStreamModel:
    """Minimal astream-able fake for the fiqh generation call."""

    tokens = ["Wudu ", "is ", "required."]

    async def astream(self, messages):
        for tok in self.tokens:
            yield SimpleNamespace(content=tok, usage_metadata=None, response_metadata={})


def _make_fiqh_agent_class():
    """FakeAgent yielding the three fiqh-path node deltas the real graph
    emits (updates mode): classification, subgraph, then the (now empty,
    guarded) generation node. Only a delta-merging pipeline can see
    fiqh_category + fiqh_filtered_docs together at the end."""

    class FakeAgent:
        def __init__(self, config):
            self.config = config

        async def astream(self, **kwargs):
            yield {
                "fiqh_classification": {
                    "classification_checked": True,
                    "is_non_islamic": False,
                    "is_casual": False,
                    "fiqh_category": "VALID_OBVIOUS",
                    "is_fiqh": True,
                }
            }
            yield {
                "fiqh_subgraph": {
                    "fiqh_filtered_docs": [
                        {"chunk_id": "c1", "page_content": "Ruling 261: wudu is required for salah."}
                    ],
                    "fiqh_sea_result": SimpleNamespace(verdict="SUFFICIENT"),
                    "fiqh_status_events": [],
                }
            }
            # Real LangGraph emits None (not {}) as the update of a node
            # that returned an empty dict — the merge must not let this
            # clobber the accumulated state (found live in the phase-1
            # bench smoke: fiqh requests errored "No response generated.").
            yield {"generate_fiqh_response": None}

    return FakeAgent


def _drain(response):
    async def _run():
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    return asyncio.run(_run())


def test_fiqh_streaming_path_streams_tokens_and_emits_references(monkeypatch):
    import modules.fiqh.generator as fiqh_generator
    from core import chat_models, utils

    monkeypatch.setattr(pipeline_langgraph, "ChatAgent", _make_fiqh_agent_class())
    monkeypatch.setattr(chat_models, "get_generator_model", lambda: _FakeFiqhStreamModel())
    monkeypatch.setattr(
        fiqh_generator, "_build_references_section", lambda answer, docs: "\n\n## Sources\n[1] Ruling 261."
    )
    monkeypatch.setattr(utils, "format_fiqh_references_as_json", lambda docs: [{"chunk_id": "c1"}])

    async def _noop_append(**kwargs):
        return None

    monkeypatch.setattr(
        "services.chat_persistence_service.aappend_turn_to_runtime_history", _noop_append
    )

    async def _get():
        return await pipeline_langgraph.chat_pipeline_streaming_agentic(
            user_query="Is wudu required before salah?",
            session_id="test-p1-fiqh-stream",
            target_language="english",
        )

    body = _drain(asyncio.run(_get()))

    # Token streaming: the three fake tokens arrive as separate chunks.
    assert body.count("event: response_chunk") >= 3
    assert "Wudu " in body and "required." in body
    # The fiqh branch post-processing made it into the stream.
    assert "## Sources" in body
    assert "event: fiqh_references" in body, "fiqh_references SSE event must be emitted"
    assert "event: done" in body
    # Disclaimer contract preserved.
    assert "Ayatollah Sistani's published rulings" in body


def test_generate_fiqh_response_node_is_noop_in_streaming_mode(monkeypatch):
    from agents.core.chat_agent import ChatAgent
    from core import chat_models

    def _fail():
        raise AssertionError("get_generator_model must not be called in streaming mode")

    monkeypatch.setattr(chat_models, "get_generator_model", _fail)

    agent = ChatAgent()
    state = {
        "streaming_mode": True,
        "fiqh_filtered_docs": [{"chunk_id": "c1", "page_content": "x"}],
        "fiqh_sea_result": None,
        "user_query": "Is wudu required?",
    }
    result = asyncio.run(agent._generate_fiqh_response_node(state))
    assert result == {}


def test_generate_fiqh_response_node_still_generates_on_ainvoke_path(monkeypatch):
    import modules.fiqh.generator as fiqh_generator
    from agents.core.chat_agent import ChatAgent
    from core import chat_models

    class _FakeModel:
        async def ainvoke(self, messages):
            return SimpleNamespace(content="Wudu is required.", response_metadata={})

    monkeypatch.setattr(chat_models, "get_generator_model", lambda: _FakeModel())
    monkeypatch.setattr(fiqh_generator, "_build_references_section", lambda answer, docs: "")

    agent = ChatAgent()
    state = {
        # streaming_mode absent => ainvoke path
        "fiqh_filtered_docs": [{"chunk_id": "c1", "page_content": "Ruling 261."}],
        "fiqh_sea_result": SimpleNamespace(verdict="SUFFICIENT"),
        "user_query": "Is wudu required?",
        "errors": [],
    }
    result = asyncio.run(agent._generate_fiqh_response_node(state))
    assert result["response_generated"] is True
    assert "Wudu is required." in result["final_response"]
    assert "Ayatollah Sistani's published rulings" in result["final_response"]


# ---------------------------------------------------------------------------
# num_documents clamping
# ---------------------------------------------------------------------------


def test_clamp_doc_count_bounds_and_fallback():
    from agents.core.chat_agent import _clamp_doc_count

    assert _clamp_doc_count(50, 1, 10) == 10
    assert _clamp_doc_count(0, 1, 10) == 1
    assert _clamp_doc_count(7, 1, 10) == 7
    assert _clamp_doc_count(-3, 0, 5) == 0
    assert _clamp_doc_count("garbage", 1, 10) == 1
    assert _clamp_doc_count(None, 0, 5) == 0
    assert _clamp_doc_count("4", 0, 5) == 4


def test_apply_tool_call_defaults_clamps_llm_supplied_counts():
    from agents.core.chat_agent import ChatAgent

    agent = ChatAgent()
    state = {"working_query": "patience", "runtime_session_id": "s1", "config": {}}
    tool_calls = [
        {"name": "retrieve_shia_documents_tool", "args": {"num_documents": 50}},
        {"name": "retrieve_sunni_documents_tool", "args": {"num_documents": 50}},
        {"name": "retrieve_quran_tafsir_tool", "args": {"num_documents": -2}},
        {"name": "retrieve_shia_documents_tool", "args": {}},  # default-filled then clamped
    ]
    agent._apply_tool_call_defaults(state, tool_calls)

    assert tool_calls[0]["args"]["num_documents"] == 10
    assert tool_calls[1]["args"]["num_documents"] == 5
    assert tool_calls[2]["args"]["num_documents"] == 0
    assert tool_calls[3]["args"]["num_documents"] == 5  # config default, within bounds
    assert tool_calls[3]["args"]["query"] == "patience"


def test_retrieval_tool_level_clamp():
    from agents.tools.retrieval_tools import _clamp

    assert _clamp(999, 1, 10) == 10
    assert _clamp(3, 0, 5) == 3
    assert _clamp("x", 0, 5) == 0


def test_check_if_non_islamic_tool_not_bound():
    """Token-cost Phase 1: intent classification runs deterministically in
    _fiqh_classification_node; the agent-side tool must not be bound (its
    schema cost ~1.3k chars per agent call and duplicated the classifier)."""
    from agents.core.chat_agent import ChatAgent

    agent = ChatAgent()
    tool_names = {getattr(t, "name", None) for t in agent.tools}
    assert "check_if_non_islamic_tool" not in tool_names
    assert tool_names == {
        "translate_to_english_tool",
        "enhance_query_tool",
        "retrieve_shia_documents_tool",
        "retrieve_sunni_documents_tool",
        "retrieve_quran_tafsir_tool",
    }


def test_max_iterations_default_is_3():
    from agents.config.agent_config import AgentConfig

    config = AgentConfig()
    assert config.max_iterations == 3
    with pytest.raises(Exception):
        AgentConfig(max_iterations=50)  # le=10 now
