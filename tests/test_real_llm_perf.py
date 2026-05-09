"""
DEE-46 / Phase 7: opt-in real-Anthropic perf gate.

Skipped by default — runs only when the `real_llm` marker is requested
explicitly:

    pytest tests/test_real_llm_perf.py -q -m real_llm

Why an opt-in suite (not a default CI gate):
- Stub-based gates in `test_async_concurrency_full.py` prove event-loop
  concurrency is healthy under deterministic latencies. They cannot
  catch real-API latency regressions because there is no real API.
- During DEE-46 local testing we observed ~50–60s wall-clock per
  request on real Anthropic, with multi-second silent gaps after the
  `Searching Quran and Tafsir` SSE event. The cause is most likely
  agent reasoning turns between tool calls (no SSE status emitted) plus
  Claude first-token latency. This gate is the regression-floor that
  catches it if anyone makes it worse.
- It hits real Anthropic + real Pinecone + real Redis + real Postgres
  (Supabase) and so it must NEVER run in default CI. Engineers run it
  locally before/after perf-sensitive changes; ops can pin it to a
  scheduled nightly job if that's wanted later.

Requirements:
- A `.env` with valid ANTHROPIC_API_KEY, PINECONE_API_KEY,
  DEEN_*_INDEX_NAME, REDIS_URL (optional but recommended), DB_*.
- A local server running at REAL_LLM_PERF_URL (default http://127.0.0.1:8000)
  with `ENV=development` so DevBypassBearer accepts unauthenticated
  requests.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Tuple

import httpx
import pytest

REAL_LLM_PERF_URL = os.getenv("REAL_LLM_PERF_URL", "http://127.0.0.1:8000")
REAL_LLM_PERF_P50_BUDGET_S = float(os.getenv("REAL_LLM_PERF_P50_BUDGET_S", "30"))
REAL_LLM_PERF_P95_BUDGET_S = float(os.getenv("REAL_LLM_PERF_P95_BUDGET_S", "60"))


pytestmark = pytest.mark.real_llm


async def _drain_one(query: str, session_suffix: str) -> Tuple[float, str]:
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        body = {
            "user_query": query,
            "session_id": f"real-llm-perf-{session_suffix}",
            "language": "english",
        }
        async with client.stream(
            "POST",
            f"{REAL_LLM_PERF_URL}/chat/stream/agentic",
            json=body,
        ) as resp:
            resp.raise_for_status()
            text_chunks: List[str] = []
            async for chunk in resp.aiter_text():
                text_chunks.append(chunk)
            elapsed = time.perf_counter() - started
            return elapsed, "".join(text_chunks)


def test_real_llm_agentic_p50_under_budget():
    """Run 3 sequential real-LLM agentic requests and assert p50 elapsed
    is under REAL_LLM_PERF_P50_BUDGET_S (default 30s)."""
    queries = [
        "What does Islam say about patience? Two sentences.",
        "Tell me about Imam Hussain in two sentences.",
        "What is tawhid? Two sentences.",
    ]

    async def _drive() -> List[float]:
        results: List[float] = []
        for i, q in enumerate(queries):
            elapsed, _ = await _drain_one(q, f"p50-{i}")
            results.append(elapsed)
        return results

    durations = asyncio.run(_drive())
    durations.sort()
    p50 = durations[len(durations) // 2]
    assert p50 <= REAL_LLM_PERF_P50_BUDGET_S, (
        f"Real-LLM agentic p50={p50:.1f}s exceeds budget "
        f"{REAL_LLM_PERF_P50_BUDGET_S:.1f}s. All durations: "
        f"{[round(d, 1) for d in durations]}. "
        f"Likely cause: agent-reasoning turn between tool calls or first-token "
        f"latency. Profile with LangSmith to localise."
    )


def test_real_llm_agentic_concurrent_p95_under_budget():
    """Run 3 concurrent real-LLM requests and assert p95 wall-clock is under
    REAL_LLM_PERF_P95_BUDGET_S (default 60s). Catches regressions where
    concurrent requests serialise under real-LLM contention."""
    queries = [
        ("Tell me about patience in one sentence.", "concur-A"),
        ("Tell me about justice in one sentence.", "concur-B"),
        ("Tell me about humility in one sentence.", "concur-C"),
    ]

    async def _drive() -> List[float]:
        results = await asyncio.gather(
            *[_drain_one(q, s) for q, s in queries]
        )
        return [elapsed for elapsed, _ in results]

    durations = asyncio.run(_drive())
    durations.sort()
    # p95 over 3 samples is the max
    p95 = durations[-1]
    assert p95 <= REAL_LLM_PERF_P95_BUDGET_S, (
        f"Real-LLM agentic concurrent p95={p95:.1f}s exceeds budget "
        f"{REAL_LLM_PERF_P95_BUDGET_S:.1f}s. All durations: "
        f"{[round(d, 1) for d in durations]}. "
        f"If durations are uniformly ~3x p50, the pipeline is serialising "
        f"under load."
    )
