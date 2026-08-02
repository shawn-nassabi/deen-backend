"""
Retrieval tools for the LangGraph agent.
These tools fetch relevant documents from the knowledge base.
"""

import asyncio

from langchain_core.tools import tool
from langchain_anthropic import convert_to_anthropic_tool
from modules.retrieval import retriever
from typing import Any, Dict, List
import logging
from core.context import correlation_id as correlation_id_ctx

logger = logging.getLogger(__name__)


def _clamp(value, lo: int, hi: int) -> int:
    """Bound an LLM-supplied doc count to [lo, hi] (token-cost Phase 1)."""
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return lo


@tool
async def retrieve_shia_documents_tool(query: str, num_documents: int = 5) -> Dict[str, any]:
    """
    Retrieve hadith and narrations from the Shia Islamic knowledge base
    (hybrid dense+sparse search with reranking).

    Args:
        query: Search query, phrased for Shia hadith sources.
        num_documents: How many documents to return (1-10; default 5).

    When to use:
    - The primary retrieval tool — Shia sources are the default perspective.
    - Theology, practice, history, and hadith questions from the Twelver
      Shia viewpoint.
    """
    try:
        num_documents = _clamp(num_documents, 1, 10)
        docs = await retriever.aretrieve_shia_documents(query, num_documents)

        return {
            "documents": docs,
            "count": len(docs),
            "source": "shia",
            "query_used": query,
        }
    except Exception as e:
        logger.error("Retrieval error", exc_info=True, extra={
            "correlation_id": correlation_id_ctx.get(),
            "error": str(e),
        })
        return {
            "documents": [],
            "count": 0,
            "source": "shia",
            "query_used": query,
            "error": str(e),
        }


@tool
async def retrieve_sunni_documents_tool(query: str, num_documents: int = 2) -> Dict[str, any]:
    """
    Retrieve hadith and narrations from the Sunni Islamic knowledge base.

    Args:
        query: Search query, phrased for Sunni hadith sources.
        num_documents: How many documents to return (0-5; default 2).

    When to use:
    - Cross-tradition corroboration or comparison on shared topics.
    - When the user explicitly asks for the Sunni perspective.

    When NOT to use:
    - Purely Shia-specific topics (e.g. Imamate) or when the user asks for
      Shia sources only. Do not call this by default on every question.
    """
    try:
        num_documents = _clamp(num_documents, 0, 5)
        docs = await retriever.aretrieve_sunni_documents(query, num_documents)

        return {
            "documents": docs,
            "count": len(docs),
            "source": "sunni",
            "query_used": query,
        }
    except Exception as e:
        logger.error("Retrieval error", exc_info=True, extra={
            "correlation_id": correlation_id_ctx.get(),
            "error": str(e),
        })
        return {
            "documents": [],
            "count": 0,
            "source": "sunni",
            "query_used": query,
            "error": str(e),
        }


@tool
async def retrieve_combined_documents_tool(
    query: str,
    shia_num_documents: int = 5,
    sunni_num_documents: int = 2,
) -> Dict[str, any]:
    """
    Retrieve relevant documents from both Shia and Sunni knowledge bases in one call.

    This is a convenience tool that retrieves from both sources and combines them.
    Use this when you want a comprehensive view with both perspectives.

    Args:
        query: The search query (should be enhanced if possible)
        shia_num_documents: Number of Shia documents to retrieve (default: 5)
        sunni_num_documents: Number of Sunni documents to retrieve (default: 2)

    Returns:
        Dictionary with:
        - documents (List[Dict]): Combined documents from both sources
        - shia_count (int): Number of Shia documents retrieved
        - sunni_count (int): Number of Sunni documents retrieved
        - total_count (int): Total documents retrieved

    When to use:
    - For general Islamic topics that benefit from multiple perspectives
    - When you want to provide comprehensive coverage
    - For historical events, shared practices, or common teachings

    When to use separate tools instead:
    - When you need control over the retrieval process
    - When you want to retrieve Shia first, then conditionally retrieve Sunni
    - When query complexity requires different query formulations for each source
    """
    try:
        shia_docs, sunni_docs = await asyncio.gather(
            retriever.aretrieve_shia_documents(query, shia_num_documents),
            retriever.aretrieve_sunni_documents(query, sunni_num_documents),
        )

        combined_docs = shia_docs + sunni_docs

        return {
            "documents": combined_docs,
            "shia_count": len(shia_docs),
            "sunni_count": len(sunni_docs),
            "total_count": len(combined_docs),
            "query_used": query,
        }
    except Exception as e:
        logger.error("Retrieval error", exc_info=True, extra={
            "correlation_id": correlation_id_ctx.get(),
            "error": str(e),
        })
        return {
            "documents": [],
            "shia_count": 0,
            "sunni_count": 0,
            "total_count": 0,
            "query_used": query,
            "error": str(e),
        }


@tool
async def retrieve_quran_tafsir_tool(query: str, num_documents: int = 3) -> Dict[str, any]:
    """
    Retrieve Quran verses with Tafsir (scholarly exegesis) from the
    dedicated Quran/Tafsir knowledge base.

    Args:
        query: Search query, phrased for Quranic content.
        num_documents: How many documents to return (0-5; default 3).

    When to use:
    - Questions about Quranic verses, Surahs, themes, stories, or meanings.
    - When Quranic evidence would strengthen a hadith-based answer (use
      alongside the hadith retrieval tools).

    When NOT to use:
    - Purely hadith or history questions with no Quranic dimension.
    """
    try:
        num_documents = _clamp(num_documents, 0, 5)
        docs = await retriever.aretrieve_quran_documents(query, num_documents)

        return {
            "documents": docs,
            "count": len(docs),
            "source": "quran_tafsir",
            "query_used": query,
        }
    except Exception as e:
        logger.error("Retrieval error", exc_info=True, extra={
            "correlation_id": correlation_id_ctx.get(),
            "error": str(e),
        })
        return {
            "documents": [],
            "count": 0,
            "source": "quran_tafsir",
            "query_used": query,
            "error": str(e),
        }


# Pre-built Anthropic tool dict for retrieve_quran_tafsir_tool with cache_control applied.
#
# The langchain_core @tool decorator does not support an 'extras' parameter, so
# cache_control cannot be set at decoration time. The correct approach per the
# langchain-anthropic docs is to convert the tool to an Anthropic dict via
# convert_to_anthropic_tool() and then set cache_control on the dict directly.
#
# This dict is the cache breakpoint for the tools prefix — Anthropic caches all
# tool definitions up to and including the last tool (INTEGRATION-3: only the last
# tool needs cache_control; earlier tools are included automatically in the prefix).
#
# Usage in chat_agent.py _create_llm_with_tools():
#   from agents.tools.retrieval_tools import retrieve_quran_tafsir_tool_cached
#   # Replace the bare retrieve_quran_tafsir_tool in the tools list with this dict.
_retrieve_quran_tafsir_tool_dict: Dict[str, Any] = convert_to_anthropic_tool(
    retrieve_quran_tafsir_tool
)
_retrieve_quran_tafsir_tool_dict["cache_control"] = {"type": "ephemeral"}
retrieve_quran_tafsir_tool_cached: Dict[str, Any] = _retrieve_quran_tafsir_tool_dict
