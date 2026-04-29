"""
Phase 5 (DEE-44) regression suite for the fiqh subsystem.

Pin three properties:

1. Every node in `agents/fiqh/fiqh_graph.py` is `async def`. ToolNode-style
   wiring won't fire here, but mixing sync and async nodes in a LangGraph
   compiled with `.ainvoke` produces hard-to-debug warnings — cheaper to
   assert at the type level than to chase a regression in production.

2. Every public `modules/fiqh/*` LLM-touching function exposes an `a`-prefixed
   async variant. New code must call the async variant from inside an event
   loop; the sync variant is kept only for legacy /chat/ and /references
   callers (until DEE-45 retires them).

3. `aretrieve_fiqh_documents` fans out per-sub-query retrievals via
   `asyncio.gather`. With a stubbed `_aretrieve_for_sub_query` that sleeps
   200ms, a 4-sub-query decomposition must complete in well under
   4 × 200ms = 800ms — proves the gather is real, not sequential awaits.
"""

from __future__ import annotations

import asyncio
import time

import pytest


@pytest.mark.asyncio
async def test_every_fiqh_subgraph_node_is_async():
    from agents.fiqh import fiqh_graph

    node_names = [
        "_decompose_node",
        "_retrieve_node",
        "_filter_node",
        "_assess_node",
        "_refine_node",
    ]
    for name in node_names:
        node_fn = getattr(fiqh_graph, name)
        assert asyncio.iscoroutinefunction(node_fn), (
            f"agents/fiqh/fiqh_graph.{name} must be `async def` after DEE-44"
        )


@pytest.mark.asyncio
async def test_fiqh_modules_expose_async_variants():
    """If any of these go missing, callers that dropped the to_thread wrapper
    in DEE-44 will start raising AttributeError at runtime. Prefer a clean
    test failure here."""
    from modules.fiqh import classifier as fc
    from modules.fiqh import decomposer
    from modules.fiqh import filter as fiqh_filter
    from modules.fiqh import generator as fiqh_generator
    from modules.fiqh import refiner
    from modules.fiqh import retriever as fiqh_retriever
    from modules.fiqh import sea

    expected = {
        fc: "aclassify_fiqh_query",
        decomposer: "adecompose_query",
        fiqh_filter: "afilter_evidence",
        fiqh_generator: "agenerate_answer",
        refiner: "arefine_query",
        fiqh_retriever: "aretrieve_fiqh_documents",
        sea: "aassess_evidence",
    }
    for module, attr in expected.items():
        fn = getattr(module, attr, None)
        assert asyncio.iscoroutinefunction(fn), (
            f"{module.__name__}.{attr} must exist as `async def` after DEE-44"
        )


@pytest.mark.asyncio
async def test_aretrieve_fiqh_documents_fans_out_concurrently(monkeypatch):
    """Stub the per-sub-query retriever to sleep, then prove the public
    `aretrieve_fiqh_documents` runs the 4 sub-query retrievals concurrently
    via asyncio.gather (wall ~200ms) instead of sequentially (~800ms)."""
    from modules.fiqh import retriever as fiqh_retriever

    async def _astub_decompose(query: str):
        return [f"sq{i}" for i in range(4)]

    async def _astub_per_subquery(sub_query: str):
        await asyncio.sleep(0.2)
        return [{"chunk_id": f"{sub_query}-doc"}]

    monkeypatch.setattr(fiqh_retriever, "adecompose_query", _astub_decompose)
    monkeypatch.setattr(fiqh_retriever, "_aretrieve_for_sub_query", _astub_per_subquery)

    started = time.perf_counter()
    docs = await fiqh_retriever.aretrieve_fiqh_documents("anything")
    elapsed = time.perf_counter() - started

    # 4 × 200ms sequential ≈ 800ms; concurrent should be ~200ms + small overhead.
    assert elapsed < 0.5, f"sub-query retrieval serialised: wall={elapsed:.3f}s for 4 sub-queries"
    assert {d["chunk_id"] for d in docs} == {f"sq{i}-doc" for i in range(4)}
