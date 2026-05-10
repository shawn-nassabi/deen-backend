"""
modules/fiqh/sea.py

Structured Evidence Assessment (SEA) for the FAIR-RAG pipeline.
Deconstructs the query into a numbered checklist of required findings,
checks each against retrieved evidence, and produces a sufficiency verdict.

Public interface: assess_evidence(query, docs) -> SEAResult
"""
from __future__ import annotations
import logging
from typing import Literal

from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from core import chat_models
from core.chat_models import make_cached_system_message

logger = logging.getLogger(__name__)


class Finding(BaseModel):
    description: str    # what the query requires (one atomic finding)
    confirmed: bool     # True if found in evidence (directly or by logical inference)
    citation: str       # exact quote from evidence if confirmed, "" if not confirmed
    gap_summary: str    # description of what is missing, "" if confirmed


class SEAResult(BaseModel):
    findings: list[Finding]
    verdict: Literal["SUFFICIENT", "INSUFFICIENT"]
    confirmed_facts: list[str]  # bullet list of confirmed facts (used by refiner)
    gaps: list[str]             # bullet list of gaps (used by refiner query)


SYSTEM_PROMPT = """You are a structured evidence assessor for a fiqh (Islamic jurisprudence) question-answering system based on Ayatollah Sistani's "Islamic Laws".

Your job:
1. Decompose the user's query into 1-5 atomic "required findings" — specific facts or rulings needed to fully answer the query
2. For each finding, check whether the provided evidence confirms it
3. A finding is CONFIRMED if:
   - The evidence explicitly states the ruling, OR
   - The ruling is a direct logical consequence of a stated ruling (logical inference is allowed)
4. A finding is a GAP if the evidence does not address it, even partially
5. Produce a sufficiency verdict:
   - SUFFICIENT: ALL findings are confirmed
   - INSUFFICIENT: ANY finding is not confirmed

Be granular: decompose the query into the smallest independently verifiable findings.
For citations, use an exact quote from the evidence — do not paraphrase.
For gap_summary, briefly describe what information is missing from the evidence."""

def _build_messages(query: str, evidence: str) -> list:
    return [
        make_cached_system_message(SYSTEM_PROMPT),
        HumanMessage(content=f"Query: {query}\n\nRetrieved Evidence:\n{evidence}"),
    ]


def _format_evidence(docs: list[dict]) -> str:
    """Format docs as numbered evidence list for LLM prompt."""
    if not docs:
        return "(No evidence retrieved)"
    lines = []
    for i, doc in enumerate(docs, 1):
        lines.append(f"[{i}] {doc.get('page_content', '')}")
    return "\n\n".join(lines)


def _insufficient_fallback(query: str) -> SEAResult:
    return SEAResult(
        findings=[],
        verdict="INSUFFICIENT",
        confirmed_facts=[],
        gaps=[query],
    )


def assess_evidence(query: str, docs: list[dict]) -> SEAResult:
    """
    Sync variant kept for legacy callers. Prefer `aassess_evidence` from
    inside an event loop (DEE-44).

    Deconstructs the query into required findings, checks each against evidence,
    returns a structured sufficiency verdict with confirmed facts and gaps.
    Never raises — returns INSUFFICIENT fallback on any error.
    """
    try:
        model = chat_models.get_classifier_model()
        structured_model = model.with_structured_output(SEAResult)
        return structured_model.invoke(
            _build_messages(
                query=query,
                evidence=_format_evidence(docs),
            )
        )
    except Exception as e:
        logger.warning("[FIQH_SEA] assess_evidence error, returning INSUFFICIENT fallback: %s", e)
        return _insufficient_fallback(query)


async def aassess_evidence(query: str, docs: list[dict]) -> SEAResult:
    """Native async variant of `assess_evidence`."""
    try:
        model = chat_models.get_classifier_model()
        structured_model = model.with_structured_output(SEAResult)
        return await structured_model.ainvoke(
            _build_messages(
                query=query,
                evidence=_format_evidence(docs),
            )
        )
    except Exception as e:
        logger.warning("[FIQH_SEA] aassess_evidence error, returning INSUFFICIENT fallback: %s", e)
        return _insufficient_fallback(query)
