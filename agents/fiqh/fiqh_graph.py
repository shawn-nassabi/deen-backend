"""
agents/fiqh/fiqh_graph.py

Compiled FiqhAgent LangGraph sub-graph for the FAIR-RAG pipeline.
Runs the iterative retrieve -> filter -> assess -> [refine -> repeat] loop.
Max 3 iterations enforced via FiqhState.iteration counter.

Public interface: fiqh_subgraph (compiled CompiledGraph)
Call pattern: fiqh_subgraph.invoke({...FiqhState initial dict...})
"""
from __future__ import annotations
import logging
from core.context import correlation_id as correlation_id_ctx
from typing import Literal

from langgraph.graph import END, StateGraph

from agents.state.fiqh_state import FiqhState

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Node functions
# --------------------------------------------------------------------------- #

async def _decompose_node(state: FiqhState) -> dict:
    """Decompose original query into 1-4 keyword-rich sub-queries for retrieval."""
    from modules.fiqh.decomposer import adecompose_query

    new_event = {"step": "fiqh_decompose", "message": "Decomposing fiqh query..."}
    try:
        sub_queries = await adecompose_query(state["query"])
        logger.info("Fiqh query decomposed", extra={
            "correlation_id": correlation_id_ctx.get(),
        })
    except Exception as exc:
        logger.error("Fiqh decompose_node error", exc_info=True, extra={
            "correlation_id": correlation_id_ctx.get(),
            "error": str(exc),
        })
        sub_queries = [state["query"]]

    # prior_queries starts empty; seed with original query on first decompose
    prior = list(state["prior_queries"])
    for sq in sub_queries:
        if sq not in prior:
            prior.append(sq)

    return {
        "prior_queries": prior,
        "status_events": list(state["status_events"]) + [new_event],
    }


async def _retrieve_node(state: FiqhState) -> dict:
    """Retrieve fiqh documents for the latest query in prior_queries."""
    from modules.fiqh.retriever import aretrieve_fiqh_documents

    iteration = state["iteration"] + 1
    new_event = {"step": "fiqh_retrieve", "message": f"Retrieving fiqh documents (iteration {iteration})..."}

    # Use the last query in prior_queries for this retrieval
    current_query = state["prior_queries"][-1] if state["prior_queries"] else state["query"]

    try:
        new_docs = await aretrieve_fiqh_documents(current_query)
        if len(new_docs) == 0:
            logger.warning("Fiqh retrieval returned zero documents", extra={
                "correlation_id": correlation_id_ctx.get(),
                "iteration": iteration,
                "doc_count": 0,
            })
        else:
            logger.info("Fiqh documents retrieved", extra={
                "correlation_id": correlation_id_ctx.get(),
                "iteration": iteration,
                "doc_count": len(new_docs),
            })
    except Exception as exc:
        logger.error("Fiqh retrieve_node error", exc_info=True, extra={
            "correlation_id": correlation_id_ctx.get(),
            "iteration": iteration,
            "error": str(exc),
        })
        new_docs = []

    # Accumulate unique docs by chunk_id (D-03 pattern)
    existing = list(state["accumulated_docs"])
    seen_ids = {d["chunk_id"] for d in existing}
    for doc in new_docs:
        if doc.get("chunk_id") not in seen_ids:
            existing.append(doc)
            seen_ids.add(doc["chunk_id"])

    return {
        "iteration": iteration,
        "accumulated_docs": existing,
        "status_events": list(state["status_events"]) + [new_event],
    }


async def _filter_node(state: FiqhState) -> dict:
    """Filter accumulated docs to keep relevant evidence (inclusive bias)."""
    from modules.fiqh.filter import afilter_evidence

    new_event = {"step": "fiqh_filter", "message": "Filtering fiqh evidence..."}
    try:
        filtered = await afilter_evidence(state["query"], state["accumulated_docs"])
        if len(filtered) == 0:
            logger.warning("Fiqh evidence filter removed all documents", extra={
                "correlation_id": correlation_id_ctx.get(),
                "iteration": state["iteration"],
                "doc_count": 0,
            })
        else:
            logger.info("Fiqh evidence filtered", extra={
                "correlation_id": correlation_id_ctx.get(),
                "iteration": state["iteration"],
                "doc_count": len(filtered),
            })
    except Exception as exc:
        logger.error("Fiqh filter_node error", exc_info=True, extra={
            "correlation_id": correlation_id_ctx.get(),
            "iteration": state["iteration"],
            "error": str(exc),
        })
        filtered = list(state["accumulated_docs"])  # fail open

    return {
        "accumulated_docs": filtered,
        "status_events": list(state["status_events"]) + [new_event],
    }


async def _assess_node(state: FiqhState) -> dict:
    """Run Structured Evidence Assessment (SEA) against accumulated docs."""
    from modules.fiqh.sea import aassess_evidence, SEAResult

    new_event = {"step": "fiqh_assess", "message": "Assessing evidence sufficiency..."}
    try:
        sea_result = await aassess_evidence(state["query"], state["accumulated_docs"])
        verdict = sea_result.verdict
        logger.info("Fiqh SEA assessment complete", extra={
            "correlation_id": correlation_id_ctx.get(),
            "iteration": state["iteration"],
            "verdict": verdict,
            "doc_count": len(state["accumulated_docs"]),
        })
    except Exception as exc:
        logger.error("Fiqh assess_node error", exc_info=True, extra={
            "correlation_id": correlation_id_ctx.get(),
            "iteration": state["iteration"],
            "error": str(exc),
        })
        sea_result = SEAResult(
            findings=[],
            verdict="INSUFFICIENT",
            confirmed_facts=[],
            gaps=[state["query"]],
        )
        verdict = "INSUFFICIENT"

    return {
        "sea_result": sea_result,
        "verdict": verdict,
        "status_events": list(state["status_events"]) + [new_event],
    }


async def _refine_node(state: FiqhState) -> dict:
    """Generate targeted refinement queries from confirmed facts and gaps."""
    from modules.fiqh.refiner import arefine_query

    new_event = {"step": "fiqh_refine", "message": "Refining query for next retrieval iteration..."}
    try:
        refinements = await arefine_query(
            original_query=state["query"],
            sea_result=state["sea_result"],
            prior_queries=state["prior_queries"],
        )
        logger.info("Fiqh query refined", extra={
            "correlation_id": correlation_id_ctx.get(),
        })
    except Exception as exc:
        logger.error("Fiqh refine_node error", exc_info=True, extra={
            "correlation_id": correlation_id_ctx.get(),
            "error": str(exc),
        })
        refinements = [state["query"]]

    prior = list(state["prior_queries"])
    for q in refinements:
        if q not in prior:
            prior.append(q)

    return {
        "prior_queries": prior,
        "status_events": list(state["status_events"]) + [new_event],
    }


# --------------------------------------------------------------------------- #
# Routing function
# --------------------------------------------------------------------------- #

def _route_after_assess(state: FiqhState) -> Literal["exit", "refine"]:
    """
    Exit if SEA is SUFFICIENT or max iterations (3) reached.
    Otherwise route to refine -> retrieve for another iteration.
    """
    if state["verdict"] == "SUFFICIENT" or state["iteration"] >= 3:
        logger.info("Fiqh FAIR-RAG exiting", extra={
            "correlation_id": correlation_id_ctx.get(),
            "iteration": state["iteration"],
            "verdict": state["verdict"],
            "doc_count": len(state["accumulated_docs"]),
        })
        if state["iteration"] >= 3 and state["verdict"] != "SUFFICIENT":
            logger.warning(
                "Fiqh FAIR-RAG exhausted max iterations with insufficient evidence",
                extra={
                    "correlation_id": correlation_id_ctx.get(),
                    "iteration": state["iteration"],
                    "verdict": state["verdict"],
                    "doc_count": len(state["accumulated_docs"]),
                },
            )
        return "exit"
    return "refine"


# --------------------------------------------------------------------------- #
# Build and compile sub-graph
# --------------------------------------------------------------------------- #

_fiqh_builder = StateGraph(FiqhState)
_fiqh_builder.add_node("decompose", _decompose_node)
_fiqh_builder.add_node("retrieve", _retrieve_node)
_fiqh_builder.add_node("filter", _filter_node)
_fiqh_builder.add_node("assess", _assess_node)
_fiqh_builder.add_node("refine", _refine_node)

_fiqh_builder.set_entry_point("decompose")
_fiqh_builder.add_edge("decompose", "retrieve")
_fiqh_builder.add_edge("retrieve", "filter")
_fiqh_builder.add_edge("filter", "assess")
_fiqh_builder.add_conditional_edges(
    "assess",
    _route_after_assess,
    {"exit": END, "refine": "refine"},
)
_fiqh_builder.add_edge("refine", "retrieve")

# checkpointer=False: stateless per-invocation; no cross-session leakage (per Pitfall 2)
fiqh_subgraph = _fiqh_builder.compile(checkpointer=False)
