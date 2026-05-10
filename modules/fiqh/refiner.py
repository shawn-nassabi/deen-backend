"""
modules/fiqh/refiner.py

Query refiner for the FAIR-RAG pipeline.
Generates 1-4 targeted refinement sub-queries based on confirmed facts and
identified gaps from Structured Evidence Assessment (SEA).

Public interface: refine_query(original_query, sea_result, prior_queries) -> list[str]
"""
from __future__ import annotations
import json
import logging

from langchain_core.messages import HumanMessage
from core import chat_models
from core.chat_models import make_cached_system_message
from modules.fiqh.sea import SEAResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a query refiner for a fiqh (Islamic jurisprudence) question-answering system based on Ayatollah Sistani's "Islamic Laws".

The evidence assessment has identified gaps — questions that could not be answered from the retrieved evidence.
Your task: generate 1-4 new, targeted retrieval sub-queries to find the missing information.

Rules:
- Return ONLY a JSON array of strings — no markdown, no explanation, no preamble
- Each query must target a specific gap identified in the assessment
- Ground each query in confirmed facts to narrow the search scope
- Include relevant Arabic/Persian fiqh terminology in transliteration (wudu, ghusl, salah, tahara, najis, etc.)
- Each query must be self-contained and retrievable independently
- NEVER repeat or rephrase any query from the "Previously tried queries" list
- Generate 1-4 new queries — never an empty array

Example output: ["tayammum conditions when water unavailable", "wudu substitute dry ablution ruling"]"""

def _build_messages(
    original_query: str,
    confirmed_facts: str,
    gaps: str,
    prior_queries: str,
) -> list:
    return [
        make_cached_system_message(SYSTEM_PROMPT),
        HumanMessage(content=f"""Original query: {original_query}

Confirmed facts so far:
{confirmed_facts}

Information gaps to fill:
{gaps}

Previously tried queries (DO NOT REPEAT OR REPHRASE THESE):
{prior_queries}

Generate 1-4 new retrieval sub-queries targeting the gaps above."""),
    ]


def _build_refine_messages(
    original_query: str,
    sea_result: SEAResult,
    prior_queries: list[str],
):
    confirmed_facts_text = "\n".join(f"- {f}" for f in sea_result.confirmed_facts) or "(none yet)"
    gaps_text = "\n".join(f"- {g}" for g in sea_result.gaps) or "(no specific gaps identified)"
    prior_queries_text = "\n".join(f"- {q}" for q in prior_queries) or "(none)"
    return _build_messages(
        original_query=original_query,
        confirmed_facts=confirmed_facts_text,
        gaps=gaps_text,
        prior_queries=prior_queries_text,
    )


def _parse_refinements(content: str, original_query: str) -> list[str]:
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else content
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()
    try:
        new_queries = json.loads(content)
    except Exception:
        return [original_query]
    if not isinstance(new_queries, list) or not new_queries:
        return [original_query]
    return [str(q).strip() for q in new_queries[:4] if str(q).strip()] or [original_query]


def refine_query(
    original_query: str,
    sea_result: SEAResult,
    prior_queries: list[str] | None = None,
) -> list[str]:
    """
    Sync variant kept for legacy callers. Prefer `arefine_query` from inside
    an event loop (DEE-44).

    Generates 1-4 targeted refinement sub-queries based on SEA gaps and
    confirmed facts. Falls back to [original_query] on any error.
    """
    if prior_queries is None:
        prior_queries = []
    try:
        model = chat_models.get_generator_model()
        response = model.invoke(_build_refine_messages(original_query, sea_result, prior_queries))
        return _parse_refinements(response.content.strip(), original_query)
    except Exception as e:
        logger.warning("[FIQH_REFINER] refine_query error, falling back to original: %s", e)
        return [original_query]


async def arefine_query(
    original_query: str,
    sea_result: SEAResult,
    prior_queries: list[str] | None = None,
) -> list[str]:
    """Native async variant of `refine_query`."""
    if prior_queries is None:
        prior_queries = []
    try:
        model = chat_models.get_generator_model()
        response = await model.ainvoke(
            _build_refine_messages(original_query, sea_result, prior_queries)
        )
        return _parse_refinements(response.content.strip(), original_query)
    except Exception as e:
        logger.warning("[FIQH_REFINER] arefine_query error, falling back to original: %s", e)
        return [original_query]
