"""
Query decomposer for the FAIR-RAG pipeline.

Decomposes a user's fiqh question into 1-4 independent, keyword-rich sub-queries
optimised for retrieval from Ayatollah Sistani's "Islamic Laws" (4th edition).
"""

from __future__ import annotations
import json

from langchain_core.messages import HumanMessage
from core import chat_models
from core.chat_models import make_cached_system_message


SYSTEM_PROMPT = """You decompose a user's Islamic fiqh question into 1-4 independent, keyword-rich sub-queries for retrieval from Ayatollah Sistani's "Islamic Laws" (4th edition).

Rules:
- Return ONLY a JSON array of strings — no markdown, no explanation, no preamble
- Simple questions → array of length 1 (the original question enriched with terminology)
- Complex multi-part questions → 2-4 independent sub-queries
- Each sub-query MUST include relevant Arabic/Persian fiqh terminology in transliteration
  where appropriate (e.g., wudu, ghusl, salah, tahara, najis, halal, haram, khums,
  zakat, nikah, talaq, iddah, tawaf, sawm, hajj, istinja, istibra)
- Each sub-query must be self-contained for standalone retrieval
- Do NOT include overlap between sub-queries
- Do NOT repeat or rephrase the same concept across sub-queries

Examples:
Q: "Is my wudu broken if I sleep?"
A: ["wudu nullifiers sleep validity istinja"]

Q: "Can I pray with wet socks and do I need to remove my ring for wudu?"
A: ["khuffayn wet socks prayer validity wudu", "ring jewelry obstruction wudu ghusl tahara ruling"]

Q: "What are the rulings on fasting if I am ill, travelling, or pregnant?"
A: ["sawm fasting illness exemption qada ruling", "sawm fasting travel exemption musafir ruling", "sawm fasting pregnant breastfeeding ruling fidya"]

Q: "Is pork haram?"
A: ["pork haram prohibition halal food rulings"]"""

def _build_messages(query: str) -> list:
    return [
        make_cached_system_message(SYSTEM_PROMPT),
        HumanMessage(content=f"Query: {query}"),
    ]


def decompose_query(query: str) -> list[str]:
    """
    Decomposes a fiqh query into 1-4 keyword-rich sub-queries using the configured LLM (SMALL_LLM).
    Falls back to [query] on any parse error or unexpected output.

    Returns:
        list[str]: 1-4 sub-query strings. Never empty, never raises.
    """
    try:
        model = chat_models.get_classifier_model()
        response = model.invoke(_build_messages(query))
        content = response.content.strip()
        # Strip markdown code fences if LLM wraps output
        if content.startswith("```"):
            parts = content.split("```")
            content = parts[1] if len(parts) > 1 else content
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        sub_queries = json.loads(content)
        if not isinstance(sub_queries, list) or not sub_queries:
            return [query]
        return [str(q).strip() for q in sub_queries[:4] if str(q).strip()]
    except Exception:
        return [query]
