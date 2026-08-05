"""
Internal state schema for the FiqhAgent LangGraph sub-graph.
This state is created fresh per-invocation and is never shared between sessions.
"""
from __future__ import annotations
from typing import TypedDict, Optional, List


class FiqhState(TypedDict):
    """
    State for the FiqhAgent sub-graph. Tracks one FAIR-RAG invocation from
    decompose through iterative retrieve-filter-assess-refine to exit.
    """
    query: str
    """Original fiqh query passed in from ChatState"""

    iteration: int
    """Current iteration count. Starts at 0, incremented in retrieve node. Max 3."""

    accumulated_docs: List[dict]
    """All unique docs retrieved across iterations, deduplicated by chunk_id"""

    prior_queries: List[str]
    """All retrieval queries tried (original + refinements). Fed to refiner to avoid repetition."""

    pending_queries: List[str]
    """Fresh sub-queries produced by the latest decompose/refine round, consumed
    (and cleared) by the next retrieve. Token-cost DEE-60 Phase 4: lets the
    retriever skip its internal re-decomposition and actually use the
    decomposer's full output instead of only prior_queries[-1]."""

    sea_result: Optional[object]
    """Latest SEAResult from assess node. None before first assess call."""

    verdict: str
    """Latest SEA verdict: 'SUFFICIENT' or 'INSUFFICIENT'. Default 'INSUFFICIENT'."""

    status_events: List[dict]
    """
    Status events appended by sub-graph nodes for surfacing to SSE stream.
    Format: [{"step": str, "message": str}, ...]
    pipeline_langgraph.py reads this after fiqh_subgraph node fires.
    """
