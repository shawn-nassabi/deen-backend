"""
DEE-55 regression test: elaboration refusal boundary.

Verifies that the reworded bullet in hikmahElaborationSystemTemplate:
  - Does NOT refuse single meaningful Islamic/Arabic terms (Imam, Tawhid, 'Adl, hadith).
  - DOES refuse genuinely empty/nonsensical input (punctuation-only, whitespace-only, random chars).

Skipped by default — runs only when the `real_llm` marker is requested explicitly:

    pytest tests/test_hikmah_elaboration_refusal.py -m real_llm

Requirements:
- A valid .env with ANTHROPIC_API_KEY (or whichever LLM provider is active).
- No running server required — calls `agenerate_elaboration_response_stream` directly.
"""
from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest

from modules.generation.stream_generator import agenerate_elaboration_response_stream

pytestmark = pytest.mark.real_llm

_REFUSAL_FRAGMENT = "not sufficient for me to provide an explanation"

_CONTEXT_TEXT = "This lesson covers core Islamic beliefs."
_HIKMAH_TREE_NAME = "Islamic Beliefs"
_LESSON_NAME = "Core Principles"
_LESSON_SUMMARY = "Overview of Twelver Shia beliefs."


async def _run(selected_text: str) -> str:
    """Call agenerate_elaboration_response_stream and return joined output."""
    chunks: list[str] = []
    async for chunk in agenerate_elaboration_response_stream(
        selected_text=selected_text,
        context_text=_CONTEXT_TEXT,
        hikmah_tree_name=_HIKMAH_TREE_NAME,
        lesson_name=_LESSON_NAME,
        lesson_summary=_LESSON_SUMMARY,
        retrieved_docs=[],
        user_id=None,
    ):
        if chunk:
            chunks.append(chunk)
    return "".join(chunks)


@pytest.mark.asyncio
async def test_meaningful_terms_not_refused() -> None:
    """Single meaningful Islamic/Arabic terms must receive an elaboration, not the refusal."""
    meaningful_terms = ["Imam", "Tawhid", "'Adl", "hadith"]
    for term in meaningful_terms:
        result = await _run(term)
        assert _REFUSAL_FRAGMENT not in result, (
            f"Term '{term}' was incorrectly refused. "
            f"Response: {result[:300]!r}"
        )


@pytest.mark.asyncio
async def test_junk_input_refused() -> None:
    """Genuinely empty or nonsensical input must still trigger the refusal sentence."""
    junk_inputs = ["...", "   ", "###"]
    for junk in junk_inputs:
        result = await _run(junk)
        assert _REFUSAL_FRAGMENT in result, (
            f"Junk input {junk!r} was not refused as expected. "
            f"Response: {result[:300]!r}"
        )
