"""
Token-cost DEE-60 Phase 3 tests (caching architecture, flag AGENT_CACHE_V2).

Covers:
- Cache-aware generator prompt: static byte-identical system block (no
  placeholders, objectives/examples retained), dynamic content moved to the
  final human message, rolling breakpoint on the last history message
  (copy-marked — originals never mutated), legacy shape behind the flag.
- Agent loop: system prompt on every iteration, append-only persisted human
  turns (iteration N+1 renders an exact prefix-extension of iteration N),
  exactly one messages-tier cache marker per request, legacy behavior with
  the kill-switch.
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import agents.core.chat_agent as chat_agent_mod
from agents.core.chat_agent import ChatAgent
from core import prompt_templates
from core.prompt_templates import _GENERATOR_STATIC, generator_messages


# ---------------------------------------------------------------------------
# Generator prompt (cache-aware layout)
# ---------------------------------------------------------------------------


def test_generator_static_block_has_no_placeholders_and_keeps_contracts():
    assert "{target_language}" not in _GENERATOR_STATIC
    assert "{references}" not in _GENERATOR_STATIC
    for required in ("Do Not Fabricate Sources", "Example citations", "Voice", "follow-up questions"):
        assert required in _GENERATOR_STATIC, f"static block lost: {required}"


def test_generator_messages_v2_shape(monkeypatch):
    monkeypatch.delenv("AGENT_CACHE_V2", raising=False)
    history = [HumanMessage(content="Who was Imam Ali?"), AIMessage(content="He was...")]
    msgs = generator_messages(
        query="What did he say about justice?",
        references="**Retrieved References:** ...",
        target_language="english",
        chat_history=history,
    )

    system = msgs[0]
    assert isinstance(system, SystemMessage)
    assert isinstance(system.content, list) and len(system.content) == 1
    assert system.content[0]["text"] == _GENERATOR_STATIC
    assert system.content[0]["cache_control"] == {"type": "ephemeral"}

    # Rolling breakpoint on the LAST history message — as a copy.
    marked = msgs[-2]
    assert isinstance(marked.content, list)
    assert marked.content[0]["cache_control"] == {"type": "ephemeral"}
    assert history[-1].content == "He was...", "original history message must not be mutated"
    assert isinstance(history[-1].content, str)

    # Dynamic content lives in the final human message.
    final = msgs[-1]
    assert "this target language: english" in final.content
    assert "**Retrieved References:**" in final.content
    assert "User Query: What did he say about justice?" in final.content


def test_generator_messages_legacy_shape_with_kill_switch(monkeypatch):
    monkeypatch.setenv("AGENT_CACHE_V2", "0")
    msgs = generator_messages(query="q", references="r", target_language="english", chat_history=[])
    assert isinstance(msgs[0].content, str)
    assert "this target language: english" in msgs[0].content
    assert msgs[-1].content == "User Query: q"


def test_generator_messages_v2_without_history_has_single_marker(monkeypatch):
    monkeypatch.delenv("AGENT_CACHE_V2", raising=False)
    msgs = generator_messages(query="q", references="r", chat_history=[])
    markers = sum(
        1
        for m in msgs
        if isinstance(getattr(m, "content", None), list)
        for b in m.content
        if isinstance(b, dict) and "cache_control" in b
    )
    assert markers == 1  # system only


# ---------------------------------------------------------------------------
# Agent loop (append-only + system every iteration + rolling marker)
# ---------------------------------------------------------------------------


def _make_state(agent):
    from agents.state.chat_state import create_initial_state

    return create_initial_state(
        user_query="What does Islam say about patience?",
        session_id="p3-test",
        target_language="english",
        config=agent.config.to_dict(),
        initial_messages=[],
    )


def _run_two_iterations(monkeypatch):
    rendered = []

    async def _fake_retry_ainvoke(llm, messages):
        rendered.append(list(messages))
        return AIMessage(content="planning", tool_calls=[])

    monkeypatch.setattr(chat_agent_mod, "_retry_ainvoke", _fake_retry_ainvoke)
    agent = ChatAgent()
    state = _make_state(agent)

    asyncio.run(agent._agent_node(state))
    # Simulate the tools round-trip between iterations.
    state["messages"].append(
        ToolMessage(content='{"count": 3}', name="retrieve_shia_documents_tool", tool_call_id="t1")
    )
    asyncio.run(agent._agent_node(state))
    return rendered, state


def test_agent_v2_sends_system_every_iteration_and_extends_prefix(monkeypatch):
    monkeypatch.delenv("AGENT_CACHE_V2", raising=False)
    rendered, _ = _run_two_iterations(monkeypatch)
    iter1, iter2 = rendered

    assert isinstance(iter1[0], SystemMessage)
    assert isinstance(iter2[0], SystemMessage), "iteration >= 2 must send the system prompt"
    assert iter2[0].content == iter1[0].content

    # Exact prefix extension: iteration 2's rendered request begins with
    # iteration 1's request — the property Anthropic prefix caching needs —
    # apart from the rolling marker moving off iteration 1's human message.
    def _shape(msgs):
        return [
            (type(m).__name__, str(getattr(m, "content", ""))[:80]) for m in msgs
        ]

    assert _shape(iter2)[: len(iter1)] == _shape(iter1)
    assert len(iter2) > len(iter1)


def test_agent_v2_keeps_exactly_one_messages_tier_marker(monkeypatch):
    monkeypatch.delenv("AGENT_CACHE_V2", raising=False)
    rendered, state = _run_two_iterations(monkeypatch)
    iter2 = rendered[1]

    message_tier_markers = 0
    for m in iter2[1:]:  # skip system (its marker is the system-tier breakpoint)
        content = getattr(m, "content", None)
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "cache_control" in block:
                    message_tier_markers += 1
    assert message_tier_markers == 1, "only the newest human message may carry the marker"

    # And it is the newest human message (the iteration summary).
    newest_human = [m for m in iter2 if isinstance(m, HumanMessage)][-1]
    assert newest_human.content[0].get("cache_control") == {"type": "ephemeral"}


def test_agent_legacy_shape_with_kill_switch(monkeypatch):
    monkeypatch.setenv("AGENT_CACHE_V2", "0")
    rendered, state = _run_two_iterations(monkeypatch)
    iter1, iter2 = rendered

    assert isinstance(iter1[0], SystemMessage)
    assert not isinstance(iter2[0], SystemMessage), "legacy: no system on iteration >= 2"
    # Legacy keeps human turns local — nothing but AI/Tool messages persisted.
    assert not any(isinstance(m, HumanMessage) for m in state["messages"])
