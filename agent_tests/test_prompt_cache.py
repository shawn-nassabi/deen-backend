#!/usr/bin/env python3
"""
Standalone cache verification script for Phase 17: ChatAgent Caching Foundation.

Makes two identical ChatAgent invoke() calls back-to-back and asserts:
  Call 1: cache_creation_input_tokens > 0 (cache WRITE — first call in TTL window)
  Call 2: cache_read_input_tokens > 0 (cache HIT — second call within 5-min TTL)

Usage:
    python agent_tests/test_prompt_cache.py

Prerequisites:
    - ANTHROPIC_API_KEY, PINECONE_API_KEY, REDIS_URL, DATABASE_URL env vars set
    - Run from the project root: python agent_tests/test_prompt_cache.py

Source for cache metrics: response.response_metadata["usage"] (raw Anthropic dict).
Do NOT use the LangChain usage wrapper — it double-counts cached tokens in
streaming paths (GitHub #32818, langchain-anthropic 0.3.x known bug).
"""

import os
import sys

# Allow running from project root or agent_tests/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import AIMessage

from agents.core.chat_agent import ChatAgent


_TEST_QUERY = "What is the ruling on performing wudu with tap water?"
_TEST_SESSION = "test_prompt_cache_session_001"


def _extract_cache_usage(final_state: dict) -> dict:
    """Extract cache_creation_input_tokens and cache_read_input_tokens from the
    last AIMessage in final_state['messages'].

    Falls back to zeros if no AIMessage with response_metadata is found.
    """
    messages = final_state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and hasattr(msg, "response_metadata"):
            usage = msg.response_metadata.get("usage", {})
            return {
                "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0) or 0,
                "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0) or 0,
                "input_tokens": usage.get("input_tokens", 0) or 0,
            }
    return {"cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "input_tokens": 0}


def test_prompt_cache():
    """Two-call cache write/hit assertion."""
    print("Phase 17: Prompt Cache Verification")
    print("=" * 50)

    agent = ChatAgent()
    passed = True

    # --- Call 1: expect cache WRITE ---
    print(f"\nCall 1 (expect cache WRITE): '{_TEST_QUERY}'")
    state1 = agent.invoke(
        user_query=_TEST_QUERY,
        session_id=_TEST_SESSION + "_call1",
    )
    usage1 = _extract_cache_usage(state1)
    cache_creation_1 = usage1["cache_creation_input_tokens"]
    cache_read_1 = usage1["cache_read_input_tokens"]

    if cache_creation_1 > 0:
        print(
            f"  cache_creation_input_tokens={cache_creation_1}, "
            f"cache_read_input_tokens={cache_read_1} -> WRITE OK"
        )
    else:
        print(
            f"  FAIL: cache_creation_input_tokens={cache_creation_1} (expected > 0). "
            f"cache_read_input_tokens={cache_read_1}. "
            "Combined prefix may be below 2048-token Sonnet minimum — "
            "check token count with: python -c \"import tiktoken; ...\""
        )
        passed = False

    # --- Call 2: expect cache HIT ---
    print(f"\nCall 2 (expect cache HIT):   '{_TEST_QUERY}'")
    state2 = agent.invoke(
        user_query=_TEST_QUERY,
        session_id=_TEST_SESSION + "_call2",
    )
    usage2 = _extract_cache_usage(state2)
    cache_creation_2 = usage2["cache_creation_input_tokens"]
    cache_read_2 = usage2["cache_read_input_tokens"]

    if cache_read_2 > 0:
        print(
            f"  cache_creation_input_tokens={cache_creation_2}, "
            f"cache_read_input_tokens={cache_read_2} -> HIT OK"
        )
    else:
        print(
            f"  FAIL: cache_read_input_tokens={cache_read_2} (expected > 0). "
            f"cache_creation_input_tokens={cache_creation_2}. "
            "Cache miss on second call — check that session IDs differ (they must) "
            "and that both calls share the same static tools+system prefix."
        )
        passed = False

    # --- Summary ---
    print("\n" + "=" * 50)
    if passed:
        print("RESULT: PASS — prompt cache is working correctly")
        print(f"  Write tokens cached: {cache_creation_1}")
        print(f"  Read tokens on hit:  {cache_read_2}")
    else:
        print("RESULT: FAIL — see messages above for diagnosis")
        sys.exit(1)


if __name__ == "__main__":
    test_prompt_cache()
