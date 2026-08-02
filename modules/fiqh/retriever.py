"""
modules/fiqh/retriever.py

Hybrid fiqh retrieval with inline Reciprocal Rank Fusion (RRF).
Public interface: retrieve_fiqh_documents(query) -> list[dict]

Architecture:
  1. Decompose query into 1-4 sub-queries (via decomposer)
  2. For each sub-query: dense query + sparse query against dedicated fiqh indexes
  3. Merge with RRF (k=60), retain top-5 per sub-query
  4. Deduplicate across sub-queries, return up to 20 unique docs
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from pinecone_text.sparse import BM25Encoder

from core.config import DEEN_FIQH_DENSE_INDEX_NAME, DEEN_FIQH_SPARSE_INDEX_NAME
from core.resilience import pinecone_retry
from core.vectorstore import _get_sparse_vectorstore
from modules.embedding.embedder import getDenseEmbedder
from modules.fiqh.decomposer import adecompose_query, decompose_query

logger = logging.getLogger(__name__)

# Resolve BM25 encoder path relative to this file — works regardless of process cwd
BM25_ENCODER_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "fiqh_bm25_encoder.json"

# Module-level lazy singleton — loaded once on first call
_bm25_encoder: BM25Encoder | None = None


def _get_bm25_encoder() -> BM25Encoder:
    """Load BM25Encoder from disk on first call, then cache."""
    global _bm25_encoder
    if _bm25_encoder is None:
        enc = BM25Encoder()
        enc.load(str(BM25_ENCODER_PATH))
        _bm25_encoder = enc
    return _bm25_encoder


def _rrf_merge(
    dense_matches: list,
    sparse_matches: list,
    k: int = 60,
    top_n: int = 5,
) -> list[dict]:
    """
    Merge dense and sparse Pinecone match objects using Reciprocal Rank Fusion.

    RRF score for each document = sum of 1/(k + rank) across result lists.
    Rank is 0-based position in the list (already sorted by relevance).

    Args:
        dense_matches: Pinecone match objects from dense index query (list of match objects)
        sparse_matches: Pinecone match objects from sparse index query (list of match objects)
        k: RRF smoothing constant (default 60, standard value from literature)
        top_n: Number of top documents to return after merge

    Returns:
        list[dict]: Up to top_n documents in RRF-ranked order, each with
                    chunk_id, metadata, and page_content.
    """
    scores: dict[str, float] = {}
    metadata_store: dict[str, dict] = {}
    content_store: dict[str, str] = {}

    # Dense pass — rank by position (dense_matches already sorted descending by score)
    for rank, match in enumerate(dense_matches):
        chunk_id = match.id
        md = match.metadata or {}
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
        metadata_store[chunk_id] = md
        content_store[chunk_id] = md.get("text_en", "")

    # Sparse pass — rank by position (sparse_matches already sorted descending by score)
    for rank, match in enumerate(sparse_matches):
        chunk_id = match.id
        md = match.metadata or {}
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
        if chunk_id not in metadata_store:
            metadata_store[chunk_id] = md
        if chunk_id not in content_store:
            content_store[chunk_id] = md.get("text_en", "")

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_n]
    return [
        {
            "chunk_id": cid,
            "metadata": metadata_store[cid],
            "page_content": content_store[cid],
        }
        for cid in sorted_ids
    ]


def _retrieve_for_sub_query(sub_query: str) -> list[dict]:
    """
    Dense + sparse retrieval + RRF merge for a single sub-query.
    Returns up to 5 documents. Returns [] on any error.
    """
    try:
        # Dense retrieval via raw Pinecone index (same pattern as retrieve_quran_documents)
        dense_vec = getDenseEmbedder().embed_query(sub_query)
        dense_index = _get_sparse_vectorstore(DEEN_FIQH_DENSE_INDEX_NAME)
        dense_response = dense_index.query(
            vector=dense_vec,
            top_k=20,
            include_metadata=True,
            namespace="ns1",
        )
        dense_matches = dense_response.matches if hasattr(dense_response, "matches") else \
                        dense_response.get("matches", [])

        # Sparse retrieval — MUST use sparse_vector= (not vector=) for sparse-type index
        encoder = _get_bm25_encoder()
        sparse_vec = encoder.encode_queries(sub_query)
        sparse_index = _get_sparse_vectorstore(DEEN_FIQH_SPARSE_INDEX_NAME)
        sparse_response = sparse_index.query(
            sparse_vector=sparse_vec,
            top_k=20,
            include_metadata=True,
            namespace="ns1",
        )
        sparse_matches = sparse_response.matches if hasattr(sparse_response, "matches") else \
                         sparse_response.get("matches", [])

        return _rrf_merge(dense_matches, sparse_matches, k=60, top_n=5)

    except Exception:
        logger.error("[FIQH_RETRIEVER] sub-query retrieval error", exc_info=True)
        return []


def retrieve_fiqh_documents(query: str) -> list[dict]:
    """
    Sync variant kept for legacy callers. Prefer `aretrieve_fiqh_documents`
    from inside an event loop (DEE-44).

    Decomposes the query into sub-queries, retrieves top-5 per sub-query via
    hybrid dense+sparse search with RRF merging, deduplicates by chunk_id.

    Returns up to 20 unique documents on success; [] on total failure.
    """
    try:
        sub_queries = decompose_query(query)
        seen: set[str] = set()
        result: list[dict] = []
        for sq in sub_queries:
            for doc in _retrieve_for_sub_query(sq):
                if doc["chunk_id"] not in seen:
                    seen.add(doc["chunk_id"])
                    result.append(doc)
        return result[:20]
    except Exception:
        logger.error("[FIQH_RETRIEVER] retrieve_fiqh_documents error", exc_info=True)
        return []


@pinecone_retry
async def _afiqh_dense_query(dense_index, dense_vec):
    return await asyncio.to_thread(
        dense_index.query,
        vector=dense_vec,
        top_k=20,
        include_metadata=True,
        namespace="ns1",
    )


@pinecone_retry
async def _afiqh_sparse_query(sparse_index, sparse_vec):
    return await asyncio.to_thread(
        sparse_index.query,
        sparse_vector=sparse_vec,
        top_k=20,
        include_metadata=True,
        namespace="ns1",
    )


async def _aretrieve_for_sub_query(sub_query: str) -> list[dict]:
    """Async variant of `_retrieve_for_sub_query`. CPU-bound bits (dense
    embedding via sentence-transformers, BM25 sparse encoding) and the sync
    Pinecone v1 .query() call are offloaded to a thread until PineconeAsyncio
    is adopted; the dense and sparse Pinecone calls fire concurrently."""
    try:
        # Dense embedding: HuggingFaceEmbeddings.aembed_query handles the
        # CPU work via LangChain's executor.
        dense_vec = await getDenseEmbedder().aembed_query(sub_query)
        encoder = _get_bm25_encoder()
        sparse_vec = await asyncio.to_thread(encoder.encode_queries, sub_query)

        dense_index = _get_sparse_vectorstore(DEEN_FIQH_DENSE_INDEX_NAME)
        sparse_index = _get_sparse_vectorstore(DEEN_FIQH_SPARSE_INDEX_NAME)

        dense_response, sparse_response = await asyncio.gather(
            _afiqh_dense_query(dense_index, dense_vec),
            _afiqh_sparse_query(sparse_index, sparse_vec),
        )
        dense_matches = dense_response.matches if hasattr(dense_response, "matches") else \
                        dense_response.get("matches", [])
        sparse_matches = sparse_response.matches if hasattr(sparse_response, "matches") else \
                         sparse_response.get("matches", [])

        return _rrf_merge(dense_matches, sparse_matches, k=60, top_n=5)
    except Exception:
        logger.error("[FIQH_RETRIEVER] async sub-query retrieval failed after retries", exc_info=True)
        return []


async def aretrieve_fiqh_documents(query: str, sub_queries: list[str] | None = None) -> list[dict]:
    """Native async variant of `retrieve_fiqh_documents`. Per-sub-query
    retrievals run concurrently via `asyncio.gather`.

    Token-cost DEE-60 Phase 4: callers that already decomposed (the fiqh
    graph's decompose/refine nodes) pass `sub_queries` so the internal
    `adecompose_query` LLM call is skipped — previously the graph decomposed,
    forwarded only `prior_queries[-1]`, and this function re-decomposed it
    (a duplicate LLM call per iteration that also DISCARDED the graph-level
    decomposition). Kill-switch FIQH_V2_RETRIEVAL=0 restores the legacy
    re-decompose behavior; `sub_queries=None` always decomposes here.
    """
    try:
        import os

        if sub_queries is None or os.getenv("FIQH_V2_RETRIEVAL", "1") == "0" or not sub_queries:
            sub_queries = await adecompose_query(query)
        per_sub_results = await asyncio.gather(
            *[_aretrieve_for_sub_query(sq) for sq in sub_queries]
        )
        seen: set[str] = set()
        result: list[dict] = []
        for batch in per_sub_results:
            for doc in batch:
                if doc["chunk_id"] not in seen:
                    seen.add(doc["chunk_id"])
                    result.append(doc)
        return result[:20]
    except Exception:
        logger.error("[FIQH_RETRIEVER] aretrieve_fiqh_documents error", exc_info=True)
        return []
