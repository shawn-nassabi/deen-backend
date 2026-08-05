"""
modules/fiqh/generator.py

Answer generator for the FAIR-RAG pipeline.
Generates a response exclusively from retrieved evidence using inline [n] citation
tokens, appends a ## Sources section, and always includes the fatwa disclaimer.

Public interface: generate_answer(query, docs, sea_result, is_sufficient) -> str
"""
from __future__ import annotations
import logging
import re

from langchain_core.messages import HumanMessage
from core import chat_models
from core.chat_models import make_cached_system_message
from core.resilience import anthropic_retry
from modules.fiqh.sea import SEAResult

logger = logging.getLogger(__name__)

FATWA_DISCLAIMER = (
    "\n\n---\n"
    "Note: This is based on Ayatollah Sistani's published rulings. "
    "For a definitive ruling, consult a qualified jurist or Sistani's official office."
)

INSUFFICIENT_WARNING = (
    "\n\n\u26a0\ufe0f Insufficient Evidence: The retrieved sources do not fully address this question. "
    "For a complete ruling, please consult Sistani's official resources at sistani.org "
    "or contact his office directly."
)

SYSTEM_PROMPT = """You are a fiqh (Islamic jurisprudence) answer generator for a system based on Ayatollah Sistani's "Islamic Laws" (4th edition).

Generate a clear, accurate answer to the user's question using ONLY the numbered evidence passages provided below.

STRICT RULES:
- Answer ONLY from the numbered evidence below — do not use any knowledge not present in the evidence
- If the evidence does not support a claim, state this explicitly rather than inferring
- Cite every factual claim with an inline citation token in the format [n] where n is the evidence number
- You MUST use at least one [n] citation in your response
- Write in a clear, respectful tone appropriate for a religious legal question
- Do NOT issue fatwas — present what Sistani's published rulings state
- Do NOT speculate beyond what the evidence states"""

def _build_messages(query: str, evidence: str) -> list:
    return [
        make_cached_system_message(SYSTEM_PROMPT),
        HumanMessage(content=f"""Question: {query}

Evidence:
{evidence}

Generate a comprehensive answer with inline [n] citations referencing the evidence numbers above."""),
    ]


def _format_evidence(docs: list[dict]) -> str:
    """Format docs as numbered evidence list for LLM prompt."""
    if not docs:
        return "(No evidence available)"
    lines = []
    for i, doc in enumerate(docs, 1):
        lines.append(f"[{i}] {doc.get('page_content', '')}")
    return "\n\n".join(lines)


def _build_references_section(text: str, docs: list[dict]) -> str:
    """Extract [n] tokens from generated text, build ## Sources section from doc metadata."""
    citation_nums = sorted(set(int(n) for n in re.findall(r'\[(\d+)\]', text)))
    if not citation_nums:
        return ""
    lines = ["", "## Sources"]
    for n in citation_nums:
        idx = n - 1  # [1] maps to docs[0]
        if 0 <= idx < len(docs):
            md = docs[idx].get("metadata", {})
            book = md.get("source_book", "Islamic Laws")
            chapter = md.get("chapter", "")
            section = md.get("section", "")
            ruling = md.get("ruling_number", "")
            parts = [p for p in [book, chapter, section] if p]
            location = ", ".join(parts)
            ruling_str = f", Ruling {ruling}" if ruling else ""
            lines.append(f"[{n}] {location}{ruling_str}")
    return "\n".join(lines)


def _post_process_answer(answer_text: str, docs: list[dict], is_sufficient: bool) -> str:
    references = _build_references_section(answer_text, docs)
    full_answer = answer_text + references
    if not is_sufficient:
        full_answer += INSUFFICIENT_WARNING
    full_answer += FATWA_DISCLAIMER
    return full_answer


def generate_answer(
    query: str,
    docs: list[dict],
    sea_result: SEAResult,
    is_sufficient: bool,
) -> str:
    """
    Sync variant kept for legacy callers. Prefer `agenerate_answer` from
    inside an event loop (DEE-44).

    Generates a fiqh answer from retrieved evidence with inline [n] citations,
    a ## Sources section, and a mandatory fatwa disclaimer.
    """
    try:
        model = chat_models.get_generator_model()
        response = model.invoke(_build_messages(
            query=query,
            evidence=_format_evidence(docs),
        ))
        return _post_process_answer(response.content.strip(), docs, is_sufficient)

    except Exception as e:
        logger.error("[FIQH_GENERATOR] generate_answer error: %s", e)
        fallback = (
            "I was unable to generate an answer from the retrieved evidence. "
            "Please consult Sistani's official resources at sistani.org or contact his office directly."
            + FATWA_DISCLAIMER
        )
        return fallback


@anthropic_retry
async def _agenerate_answer_call(query: str, docs: list[dict]):
    model = chat_models.get_generator_model()
    return await model.ainvoke(_build_messages(
        query=query,
        evidence=_format_evidence(docs),
    ))


async def agenerate_answer(
    query: str,
    docs: list[dict],
    sea_result: SEAResult,
    is_sufficient: bool,
) -> str:
    """Native async variant of `generate_answer`."""
    try:
        response = await _agenerate_answer_call(query, docs)
        from core.token_telemetry import record_llm_usage

        record_llm_usage("fiqh_generator", response)
        return _post_process_answer(response.content.strip(), docs, is_sufficient)
    except Exception:
        logger.error(
            "[FIQH_GENERATOR] agenerate_answer failed after retries",
            exc_info=True,
        )
        return (
            "I was unable to generate an answer from the retrieved evidence. "
            "Please consult Sistani's official resources at sistani.org or contact his office directly."
            + FATWA_DISCLAIMER
        )
