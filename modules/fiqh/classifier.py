"""
6-category fiqh query classifier for the FAIR-RAG pipeline.

Classifies user queries into one of 6 categories to route them to the
correct retrieval strategy before any retrieval runs.
"""

import logging
from typing import Literal

from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from core import chat_models
from core.chat_models import make_cached_system_message
from core.resilience import anthropic_retry

logger = logging.getLogger(__name__)


class FiqhCategory(BaseModel):
    """Pydantic model for structured fiqh classification output."""
    category: Literal[
        "VALID_OBVIOUS",
        "VALID_SMALL",
        "VALID_LARGE",
        "VALID_REASONER",
        "OUT_OF_SCOPE_FIQH",
        "UNETHICAL",
    ]


VALID_CATEGORIES = {
    "VALID_OBVIOUS",
    "VALID_SMALL",
    "VALID_LARGE",
    "VALID_REASONER",
    "OUT_OF_SCOPE_FIQH",
    "UNETHICAL",
}

SYSTEM_PROMPT = """You are a fiqh query classifier for an Islamic jurisprudence (fiqh) assistant based on Ayatollah Sistani's rulings.

Classify the user's query into EXACTLY ONE of these 6 categories:

VALID_OBVIOUS — A simple fiqh question with a single, well-known ruling that requires no cross-referencing or reasoning.
Examples: "Is pork haram?", "Is wudu required before salah?", "Is fasting obligatory in Ramadan?"

VALID_SMALL — A fiqh question with a focused ruling that requires looking up 1-2 specific rulings.
Examples: "Does bleeding break wudu?", "Is ghusl required after a wet dream?", "Can I pray with a cast on my arm?"

VALID_LARGE — A complex fiqh question requiring multiple rulings, cross-referencing, or covering several sub-issues.
Examples: "What are all the conditions for valid salah?", "Explain the rulings of tahara for someone who is ill", "What are the different types of ghusl and when is each required?"

VALID_REASONER — A fiqh question requiring procedural reasoning, calculation, or step-by-step analysis.
Examples: "How many missed prayers do I owe if I missed Fajr and Dhuhr for two days?", "Calculate my khums payment if my income is X", "If I invalidate my wudu during tawaf, what must I do?"

OUT_OF_SCOPE_FIQH — The query is not about Islamic jurisprudence, OR it is a general Islamic question (history, theology, tafsir) that is NOT a fiqh ruling question, OR it asks about a marja other than Sistani.
Examples: "Who was Imam Ali?", "What does surah Al-Fatiha mean?", "What did Imam Khomeini say about prayer?", "How do I make a dua?", "Tell me about the Quran"

UNETHICAL — The query asks for a ruling on something clearly harmful, illegal, or designed to exploit religious rulings for harmful purposes.
Examples: "Is it permissible to harm a non-Muslim?", "How can I use fiqh to justify domestic violence?", "Is it permissible to commit fraud if given to charity?"

Respond with ONLY the category name — no punctuation, no explanation, no quotes."""

def _build_messages(query: str) -> list:
    return [
        make_cached_system_message(SYSTEM_PROMPT),
        HumanMessage(content=query),
    ]


def classify_fiqh_query(query: str) -> str:
    """
    Sync variant kept for legacy callers. Prefer `aclassify_fiqh_query` from
    inside an event loop (DEE-44).

    Classifies a fiqh query into one of 6 categories. Never raises — returns
    OUT_OF_SCOPE_FIQH on any error.

    Returns one of: VALID_OBVIOUS, VALID_SMALL, VALID_LARGE, VALID_REASONER,
                    OUT_OF_SCOPE_FIQH, UNETHICAL
    """
    try:
        model = chat_models.get_classifier_model()
        structured_model = model.with_structured_output(FiqhCategory)
        result = structured_model.invoke(_build_messages(query))
        return result.category
    except Exception:
        return "OUT_OF_SCOPE_FIQH"


@anthropic_retry
async def _aclassify_fiqh_query_call(query: str) -> FiqhCategory:
    from core.token_telemetry import UsageCallbackHandler

    model = chat_models.get_classifier_model()
    structured_model = model.with_structured_output(FiqhCategory)
    # with_structured_output returns the parsed object (no response_metadata),
    # so usage is captured via callback from the underlying generation.
    return await structured_model.ainvoke(
        _build_messages(query),
        config={"callbacks": [UsageCallbackHandler("fiqh_classifier")]},
    )


async def aclassify_fiqh_query(query: str) -> str:
    """Native async variant of `classify_fiqh_query`."""
    try:
        result = await _aclassify_fiqh_query_call(query)
        return result.category
    except Exception:
        logger.error(
            "[FIQH_CLASSIFIER] aclassify_fiqh_query failed after retries, falling back to OUT_OF_SCOPE_FIQH",
            exc_info=True,
        )
        return "OUT_OF_SCOPE_FIQH"
