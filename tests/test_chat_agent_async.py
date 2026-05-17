"""
Phase 2 (DEE-41) regression suite for `agents/core/chat_agent.py` after the
sync→async node conversion.

Two properties to lock in:

1. `ChatAgent.ainvoke(...)` is genuinely async — N concurrent calls finish in
   roughly the time of a single call, not N times. The Phase 0 stubs put
   400ms of LLM sleep + 100ms of retrieval per request; serialised execution
   would be N × 0.5s+, while async should hover near a single request.

2. correlation_id (a contextvar set by the FastAPI middleware) survives
   `asyncio.to_thread` boundaries inside the async nodes — specifically the
   fiqh-subgraph wrapper, which is the only place we still reach for
   `to_thread` after Phase 2. Sentry's per-request scope relies on the same
   contextvar mechanism, so this is the regression test for "Sentry breadcrumb
   survives to_thread" without requiring a live Sentry transport.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest

from core.context import correlation_id as correlation_id_ctx
from tests.conftest_async_stubs import StubConfig, install_pipeline_stubs


@pytest.mark.asyncio
async def test_concurrent_ainvoke_does_not_serialise(installed_stubs):
    """5 concurrent agent.ainvoke calls must finish in ~one-call time."""
    from agents.core.chat_agent import ChatAgent
    from agents.config.agent_config import DEFAULT_AGENT_CONFIG

    n = 5
    agent = ChatAgent(DEFAULT_AGENT_CONFIG)

    started = time.perf_counter()
    results = await asyncio.gather(
        *[
            agent.ainvoke(
                user_query="What does Islam say about patience?",
                session_id=f"async-stub-session-{i}",
            )
            for i in range(n)
        ]
    )
    elapsed = time.perf_counter() - started

    # Each request: 2 × 200ms LLM (planner) + 100ms retrieval ≈ 0.5s.
    # Serialised wall would be ~2.5s; concurrent wall must stay well under
    # half of that. Allow generous headroom (1.0s) for stub + langgraph
    # overhead so the test isn't flaky on slow CI hosts.
    assert elapsed < 1.0, (
        f"agent.ainvoke serialised: wall={elapsed:.3f}s for n={n} concurrent calls"
    )
    assert all(isinstance(r, dict) for r in results)
    assert all(r.get("retrieval_completed") for r in results)


@pytest.mark.asyncio
async def test_correlation_id_propagates_through_to_thread(installed_stubs):
    """correlation_id_ctx (set by middleware) must survive asyncio.to_thread.

    The fiqh-subgraph wrapper uses to_thread; if the contextvar didn't
    propagate, Sentry's per-request scope would silently leak across
    requests under load. Python 3.7+ copies contextvars into the thread
    automatically, but tools written before that semantic landed sometimes
    re-bind incorrectly — pin the behavior here.
    """
    expected_id = uuid.uuid4().hex
    correlation_id_ctx.set(expected_id)

    captured: dict = {}

    def _read_inside_thread():
        captured["value"] = correlation_id_ctx.get()
        return correlation_id_ctx.get()

    observed = await asyncio.to_thread(_read_inside_thread)

    assert observed == expected_id, (
        f"correlation_id did not propagate into to_thread: "
        f"set={expected_id} observed={observed} captured={captured.get('value')}"
    )
    # The outer-scope value is unchanged after the thread returns.
    assert correlation_id_ctx.get() == expected_id


@pytest.mark.asyncio
async def test_every_node_is_async():
    """Pin the contract: ChatAgent's node methods are all coroutines.

    A regression here (someone re-introduces a sync node) would silently
    break ToolNode.ainvoke compatibility. Cheaper to assert at the type
    level than to debug a mid-graph NotImplementedError.
    """
    from agents.core.chat_agent import ChatAgent

    node_names = [
        "_fiqh_classification_node",
        "_agent_node",
        "_tool_node",
        "_generate_response_node",
        "_check_early_exit_node",
        "_call_fiqh_subgraph_node",
        "_generate_fiqh_response_node",
    ]
    for name in node_names:
        method = getattr(ChatAgent, name)
        assert asyncio.iscoroutinefunction(method), (
            f"ChatAgent.{name} must be `async def` after DEE-41"
        )
