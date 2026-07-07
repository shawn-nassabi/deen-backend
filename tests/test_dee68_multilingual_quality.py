"""
DEE-68 multilingual chatbot response quality — opt-in real_llm eval harness.

Requires ANTHROPIC_API_KEY and other env vars to be set. Run with:
    pytest -m real_llm tests/test_dee68_multilingual_quality.py

Drives ChatAgent.ainvoke() with a fixed general-Islamic (non-fiqh) question
across all 6 supported target languages and verifies the response is
substantively in-language:
- Arabic, Farsi, Urdu: script-detection via Unicode-block arithmetic
  (Arabic script block U+0600-U+06FF covers all three languages' scripts)
- German, French, Bahasa Melayu: LLM-judge via core.chat_models.get_classifier_model()

Also asserts basic routing correctness (not misclassified as non_islamic/
casual) and a lightweight religious-sensitivity guard against self-attributed
fatwa language.
"""
from __future__ import annotations

import uuid

import pytest


LANGUAGES = ["arabic", "farsi", "urdu", "german", "bahasa melayu", "french"]

ARABIC_SCRIPT_LANGUAGES = {"arabic", "farsi", "urdu"}

# General Islamic theology/history questions — not fiqh rulings — so these
# route through the normal hadith/Quran agent path rather than the fiqh
# sub-graph, keeping the harness focused on generation-language correctness.
IMAMATE_QUESTION = "What is the concept of Imamate in Twelver Shia Islam?"
ASHURA_QUESTION = "What is the significance of Ashura?"

FATWA_SELF_ATTRIBUTION_PHRASES = [
    "i hereby issue a fatwa",
    "this is my fatwa",
]


def _arabic_script_ratio(text: str) -> float:
    """Fraction of alphabetic characters in `text` that fall within the
    Arabic Unicode script block (U+0600-U+06FF). Returns 0.0 if there are
    no alphabetic characters (avoids division by zero)."""
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return 0.0
    arabic_count = sum(1 for c in alpha_chars if 0x0600 <= ord(c) <= 0x06FF)
    return arabic_count / len(alpha_chars)


@pytest.mark.real_llm
class TestMultilingualQuality:
    """Live end-to-end multilingual generation quality tests.

    Run with: pytest -m real_llm tests/test_dee68_multilingual_quality.py
    Requires ANTHROPIC_API_KEY and other env vars to be set.
    """

    def _make_agent(self):
        from agents.core.chat_agent import ChatAgent
        from agents.config.agent_config import DEFAULT_AGENT_CONFIG
        return ChatAgent(DEFAULT_AGENT_CONFIG)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("lang", LANGUAGES)
    async def test_response_is_substantive_and_in_language(self, lang):
        agent = self._make_agent()
        result = await agent.ainvoke(
            user_query=IMAMATE_QUESTION,
            session_id=f"dee68-{lang.replace(' ', '')}-{uuid.uuid4().hex}",
            target_language=lang,
        )

        final_response = result.get("final_response") or ""
        assert len(final_response) > 50, (
            f"Response for '{lang}' too short or empty: '{final_response}'"
        )

        # Routing correctness: general Islamic question must not be
        # misclassified as non-Islamic or casual.
        assert result.get("is_non_islamic") is not True, (
            f"Question misclassified as non_islamic for lang='{lang}'"
        )
        assert result.get("is_casual") is not True, (
            f"Question misclassified as casual for lang='{lang}'"
        )

        # Religious-sensitivity guard: no self-attributed fatwa language.
        lowered = final_response.lower()
        for phrase in FATWA_SELF_ATTRIBUTION_PHRASES:
            assert phrase not in lowered, (
                f"Response for '{lang}' contains self-attributed fatwa language: '{phrase}'"
            )

        # Language-correctness check.
        if lang in ARABIC_SCRIPT_LANGUAGES:
            ratio = _arabic_script_ratio(final_response)
            assert ratio > 0.15, (
                f"Response for '{lang}' does not appear to be in Arabic script "
                f"(ratio={ratio:.2f}): '{final_response[:200]}'"
            )
        else:
            from core.chat_models import get_classifier_model
            from langchain_core.messages import HumanMessage

            model = get_classifier_model()
            judge_prompt = (
                f"Is the following text written in {lang}? "
                "Respond with only 'yes' or 'no'.\n\n"
                f"Text:\n{final_response}"
            )
            judge_response = await model.ainvoke([HumanMessage(content=judge_prompt)])
            judge_text = (judge_response.content or "").strip().lower()
            assert judge_text.startswith("yes"), (
                f"LLM judge did not confirm response for '{lang}' is in that language: "
                f"judge said '{judge_text}', response was '{final_response[:200]}'"
            )
