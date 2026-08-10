"""
Token-cost DEE-60 Phase 4 tests (fiqh structural fixes, flag FIQH_V2_RETRIEVAL).

Covers:
- Double-decompose removal: the retriever skips its internal adecompose_query
  when the graph hands it pre-decomposed sub-queries; the decompose/refine
  nodes hand their FULL output to retrieve via pending_queries (previously
  only prior_queries[-1] was forwarded and re-decomposed).
- Kill-switch FIQH_V2_RETRIEVAL=0 restores legacy re-decomposition.
- Evidence hard cap (30 docs) entering the filter LLM call.
- Flattened retry stack (SDK 2 x outer 2 = 6 worst-case attempts, was 18).
"""

from __future__ import annotations

import asyncio

import agents.fiqh.fiqh_graph as fiqh_graph_mod
import modules.fiqh.retriever as fiqh_retriever_mod


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Retriever: sub_queries bypasses internal decomposition
# ---------------------------------------------------------------------------


def _patch_retrieval_internals(monkeypatch):
    decompose_calls = []
    retrieved = []

    async def _fake_decompose(query):
        decompose_calls.append(query)
        return [f"decomposed:{query}"]

    async def _fake_sub_query(sq):
        retrieved.append(sq)
        return [{"chunk_id": f"c-{sq}", "page_content": "text"}]

    monkeypatch.setattr(fiqh_retriever_mod, "adecompose_query", _fake_decompose)
    monkeypatch.setattr(fiqh_retriever_mod, "_aretrieve_for_sub_query", _fake_sub_query)
    return decompose_calls, retrieved


def test_retriever_uses_provided_sub_queries_without_decomposing(monkeypatch):
    monkeypatch.delenv("FIQH_V2_RETRIEVAL", raising=False)
    decompose_calls, retrieved = _patch_retrieval_internals(monkeypatch)

    docs = _run(fiqh_retriever_mod.aretrieve_fiqh_documents(
        "Is wudu required?", sub_queries=["wudu salah requirement", "wudu nullifiers"]
    ))

    assert decompose_calls == [], "internal decomposition must be skipped"
    assert set(retrieved) == {"wudu salah requirement", "wudu nullifiers"}
    assert len(docs) == 2


def test_retriever_decomposes_when_no_sub_queries(monkeypatch):
    monkeypatch.delenv("FIQH_V2_RETRIEVAL", raising=False)
    decompose_calls, retrieved = _patch_retrieval_internals(monkeypatch)

    _run(fiqh_retriever_mod.aretrieve_fiqh_documents("Is wudu required?"))

    assert decompose_calls == ["Is wudu required?"]
    assert retrieved == ["decomposed:Is wudu required?"]


def test_retriever_kill_switch_restores_legacy_redecompose(monkeypatch):
    monkeypatch.setenv("FIQH_V2_RETRIEVAL", "0")
    decompose_calls, retrieved = _patch_retrieval_internals(monkeypatch)

    _run(fiqh_retriever_mod.aretrieve_fiqh_documents(
        "Is wudu required?", sub_queries=["provided sub-query"]
    ))

    assert decompose_calls == ["Is wudu required?"], "legacy mode must re-decompose"
    assert retrieved == ["decomposed:Is wudu required?"]


# ---------------------------------------------------------------------------
# Graph nodes: pending_queries handoff + one decomposition per request
# ---------------------------------------------------------------------------


def _base_state(**overrides):
    state = {
        "query": "Is wudu required before salah?",
        "iteration": 0,
        "accumulated_docs": [],
        "prior_queries": [],
        "pending_queries": [],
        "sea_result": None,
        "verdict": "INSUFFICIENT",
        "status_events": [],
    }
    state.update(overrides)
    return state


def test_decompose_then_retrieve_uses_full_decomposition_once(monkeypatch):
    monkeypatch.delenv("FIQH_V2_RETRIEVAL", raising=False)

    decompose_calls = []
    retriever_kwargs = []

    async def _fake_decompose(query):
        decompose_calls.append(query)
        return ["sq-one", "sq-two", "sq-three"]

    async def _fake_retrieve(query, sub_queries=None):
        retriever_kwargs.append({"query": query, "sub_queries": sub_queries})
        return [{"chunk_id": "c1", "page_content": "t"}]

    import modules.fiqh.decomposer as decomposer_mod

    monkeypatch.setattr(decomposer_mod, "adecompose_query", _fake_decompose)
    monkeypatch.setattr(fiqh_retriever_mod, "aretrieve_fiqh_documents", _fake_retrieve)

    state = _base_state()
    state.update(_run(fiqh_graph_mod._decompose_node(state)))
    assert state["pending_queries"] == ["sq-one", "sq-two", "sq-three"]

    state.update(_run(fiqh_graph_mod._retrieve_node(state)))

    assert decompose_calls == [state["query"]], "exactly ONE decomposition per request"
    assert retriever_kwargs[0]["sub_queries"] == ["sq-one", "sq-two", "sq-three"], (
        "retrieve must receive the decomposer's FULL output"
    )
    assert state["pending_queries"] == [], "pending queries consumed after retrieve"


def test_refine_hands_all_refinements_to_next_retrieve(monkeypatch):
    async def _fake_refine(original_query, sea_result, prior_queries):
        return ["refined-a", "refined-b"]

    import modules.fiqh.refiner as refiner_mod

    monkeypatch.setattr(refiner_mod, "arefine_query", _fake_refine)

    state = _base_state(prior_queries=["sq-one"], sea_result=object())
    state.update(_run(fiqh_graph_mod._refine_node(state)))
    assert state["pending_queries"] == ["refined-a", "refined-b"]
    assert state["prior_queries"] == ["sq-one", "refined-a", "refined-b"]


def test_filter_node_caps_evidence_at_30(monkeypatch):
    captured = {}

    async def _fake_filter(query, docs):
        captured["n"] = len(docs)
        return docs

    import modules.fiqh.filter as filter_mod

    monkeypatch.setattr(filter_mod, "afilter_evidence", _fake_filter)

    docs = [{"chunk_id": f"c{i}", "page_content": "t"} for i in range(45)]
    state = _base_state(iteration=1, accumulated_docs=docs)
    _run(fiqh_graph_mod._filter_node(state))
    assert captured["n"] == 30


# ---------------------------------------------------------------------------
# Retry stack flattening
# ---------------------------------------------------------------------------


def test_retry_stack_flattened():
    from core import chat_models

    assert chat_models._ANTHROPIC_MAX_RETRIES == 2

    # anthropic_retry wraps with 2 outer attempts: a function that fails once
    # with a transient error succeeds on attempt 2; one that always fails
    # transiently is attempted exactly twice.
    from core import resilience

    calls = {"n": 0}

    class _FakeOverloaded(Exception):
        pass

    monkey_is_transient = lambda exc: isinstance(exc, _FakeOverloaded)
    retry = resilience._build_async_retry(
        provider="anthropic-test", is_transient=monkey_is_transient, attempts=2
    )

    @retry
    async def _always_fails():
        calls["n"] += 1
        raise _FakeOverloaded()

    try:
        _run(_always_fails())
    except _FakeOverloaded:
        pass
    assert calls["n"] == 2
