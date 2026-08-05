"""
Query enhancement tools for the LangGraph agent.
These tools improve query quality for better retrieval results.
"""

import logging
from typing import Dict

from langchain_core.tools import tool
from core.context import correlation_id as correlation_id_ctx
from modules.enhancement import enhancer

logger = logging.getLogger(__name__)


@tool
async def enhance_query_tool(query: str, session_id: str) -> Dict[str, str]:
    """
    Rewrite the query into a better retrieval query using chat history
    (resolves pronouns/follow-ups, e.g. "tell me more about him" ->
    "Imam Ali, the first Imam in Shia Islam").

    Args:
        query: The user's original query.
        session_id: Conversation session ID (for chat-history context).

    When to use: follow-ups, ambiguous or pronoun-heavy queries.
    When NOT to use: direct, self-contained questions.
    """
    try:
        enhanced = await enhancer.aenhance_query(query, session_id)

        return {
            "enhanced_query": enhanced,
            "original_query": query
        }
    except Exception as e:
        logger.error(
            "enhance_query_tool error",
            exc_info=True,
            extra={"correlation_id": correlation_id_ctx.get()},
        )
        return {
            "enhanced_query": query,  # Fall back to original on error
            "original_query": query,
            "error": str(e)
        }
