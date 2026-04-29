"""
Query enhancement tools for the LangGraph agent.
These tools improve query quality for better retrieval results.
"""

from langchain_core.tools import tool
from modules.enhancement import enhancer
from typing import Dict


@tool
async def enhance_query_tool(query: str, session_id: str) -> Dict[str, str]:
    """
    Enhance a user's query by adding context and improving it for better document retrieval.

    Use this tool to improve the quality of queries before retrieving documents from the database.
    The enhancement process:
    - Adds relevant context from chat history
    - Expands abbreviations and clarifies ambiguous terms
    - Reformulates the query to be more specific and retrieval-friendly
    - Preserves the original intent while making it more searchable

    Args:
        query: The user's original query
        session_id: The conversation session ID to access chat history for context

    Returns:
        Dictionary with:
        - enhanced_query (str): The improved, context-enriched query
        - original_query (str): The original user query

    Example:
        Original: "Tell me more about him"
        Enhanced: "Tell me more about Imam Ali, the first Imam in Shia Islam"

    When to use:
    - Before retrieving documents from the knowledge base
    - When the query is short or lacks context
    - When chat history provides relevant context

    When NOT to use:
    - For very simple, self-contained queries
    - When the query is already detailed and specific
    - After classification determines the query is non-Islamic or fiqh
    """
    try:
        enhanced = await enhancer.aenhance_query(query, session_id)

        return {
            "enhanced_query": enhanced,
            "original_query": query
        }
    except Exception as e:
        print(f"[enhance_query_tool] Error: {e}")
        return {
            "enhanced_query": query,  # Fall back to original on error
            "original_query": query,
            "error": str(e)
        }
