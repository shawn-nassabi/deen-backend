"""
modules/fiqh/filter.py

LLM-based evidence filter for the FAIR-RAG pipeline.
Removes clearly irrelevant documents from a retrieved set using a single
batch LLM call. Uses inclusive bias — when in doubt, keep the document.

Public interface: filter_evidence(query, docs) -> list[dict]
"""
from __future__ import annotations
import json
import logging

from langchain_core.messages import HumanMessage
from core import chat_models
from core.chat_models import make_cached_system_message

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an evidence filter for a fiqh (Islamic jurisprudence) question-answering system based on Ayatollah Sistani's "Islamic Laws".

Given a user query and a numbered list of retrieved evidence passages, determine which passages are relevant to answering the query.

Return ONLY a JSON array of chunk IDs to KEEP — do not include explanation or markdown.

IMPORTANT RULES:
- Use INCLUSIVE bias: when in doubt, KEEP the document
- Keep any document that is even partially relevant to any aspect of the query
- Keep any document that provides context for understanding the ruling
- Only exclude documents that are CLEARLY about a completely different topic with no connection to the query
- If all documents seem relevant, return all of them
- Do NOT return an empty array unless every document is completely unrelated

The chunk IDs are listed at the start of each evidence passage in format [chunk_id]."""

def _build_messages(query: str, evidence: str) -> list:
    return [
        make_cached_system_message(SYSTEM_PROMPT),
        HumanMessage(content=f"Query: {query}\n\nEvidence passages:\n{evidence}"),
    ]


def _format_evidence_with_ids(docs: list[dict]) -> str:
    """Format docs as numbered evidence list showing chunk_ids for LLM selection."""
    lines = []
    for doc in docs:
        chunk_id = doc.get("chunk_id", "unknown")
        text = doc.get("page_content", "")
        lines.append(f"[{chunk_id}] {text}")
    return "\n\n".join(lines)


def filter_evidence(query: str, docs: list[dict]) -> list[dict]:
    """
    Filters retrieved evidence using a single batch LLM call.
    Inclusive bias — returns all docs on any error or if LLM returns empty list.
    Never raises.

    Args:
        query: The original fiqh query string
        docs: List of doc dicts with chunk_id, metadata, page_content keys

    Returns:
        list[dict]: Subset of input docs to keep. Returns all docs on error.
    """
    if not docs:
        return []
    try:
        model = chat_models.get_generator_model()
        response = model.invoke(_build_messages(
            query=query,
            evidence=_format_evidence_with_ids(docs),
        ))
        content = response.content.strip()
        # Strip markdown code fences if LLM wraps output
        if content.startswith("```"):
            parts = content.split("```")
            content = parts[1] if len(parts) > 1 else content
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        chunk_ids_to_keep: list[str] = json.loads(content)
        if not isinstance(chunk_ids_to_keep, list) or not chunk_ids_to_keep:
            # Empty list = over-aggressive filtering — fail open, keep all
            logger.warning("[FIQH_FILTER] LLM returned empty keep list — keeping all %d docs", len(docs))
            return docs
        keep_set = set(str(cid) for cid in chunk_ids_to_keep)
        filtered = [doc for doc in docs if doc.get("chunk_id") in keep_set]
        if not filtered:
            # No known chunk_ids matched — fail open
            return docs
        return filtered
    except Exception as e:
        logger.warning("[FIQH_FILTER] filter_evidence error, returning all docs: %s", e)
        return docs
