"""
Classification tools for the LangGraph agent.
These tools help determine if a query is relevant and answerable.
"""

import logging
from typing import Dict

from langchain_core.tools import tool
from core.context import correlation_id as correlation_id_ctx
from modules.classification import classifier

logger = logging.getLogger(__name__)


@tool
async def check_if_non_islamic_tool(query: str, session_id: str) -> Dict[str, any]:
    """
    Check if the user's query is related to Islamic education (specifically Twelver Shia Islam).

    Use this tool when you need to determine if a query is within the domain of Islamic education.
    This includes questions about theology, history, practices, interpretations, beliefs, scholars,
    hadith, Quran, fiqh preview, rituals, and any other aspects of Twelver Shia Islam.

    Args:
        query: The user's question or query
        session_id: The conversation session ID for context

    Returns:
        Dictionary with:
        - is_non_islamic (bool): True if query is NOT about Islamic education, False if it is
        - explanation (str): Brief explanation of the classification

    Examples of ISLAMIC queries (should return is_non_islamic=False):
    - "What is Imamate?"
    - "Tell me about Imam Ali"
    - "How should I perform wudu?"
    - "What does the Quran say about justice?"

    Examples of NON-ISLAMIC queries (should return is_non_islamic=True):
    - "What's the weather today?"
    - "How do I bake a cake?"
    - "Tell me a joke"
    - "Who won the World Cup?"
    """
    try:
        is_non_islamic = await classifier.aclassify_non_islamic_query(query, session_id)

        if is_non_islamic:
            explanation = "Query is not related to Islamic education domain"
        else:
            explanation = "Query is relevant to Islamic education"

        return {
            "is_non_islamic": is_non_islamic,
            "explanation": explanation
        }
    except Exception as e:
        logger.error(
            "check_if_non_islamic_tool error",
            exc_info=True,
            extra={"correlation_id": correlation_id_ctx.get()},
        )
        return {
            "is_non_islamic": False,  # Default to allowing the query
            "explanation": f"Classification error: {str(e)}"
        }


@tool
async def check_if_fiqh_tool(query: str, session_id: str) -> Dict[str, any]:
    """
    Check if the user's query is asking for a fiqh (Islamic jurisprudence) ruling.

    Use this tool when you need to determine if a query is asking for a specific fiqh ruling
    or legal religious verdict. Fiqh questions ask "what should I do" or "is X permissible".

    Args:
        query: The user's question or query
        session_id: The conversation session ID for context

    Returns:
        Dictionary with:
        - is_fiqh (bool): True if query asks for a fiqh ruling, False otherwise
        - explanation (str): Brief explanation of the classification

    Examples of FIQH queries (should return is_fiqh=True):
    - "Is it halal to eat shrimp?"
    - "Can I pray without wudu in an emergency?"
    - "What's the ruling on temporary marriage?"
    - "Am I allowed to fast while traveling?"

    Examples of NON-FIQH queries (should return is_fiqh=False):
    - "What is the concept of Tawhid?"
    - "Tell me about the life of Imam Hussain"
    - "What does the Quran say about patience?"
    - "Who were the 12 Imams?"
    """
    try:
        is_fiqh = await classifier.aclassify_fiqh_query(query, session_id)

        if is_fiqh:
            explanation = "Query appears to be asking for a fiqh ruling or legal verdict"
        else:
            explanation = "Query is not asking for a fiqh ruling"

        return {
            "is_fiqh": is_fiqh,
            "explanation": explanation
        }
    except Exception as e:
        logger.error(
            "check_if_fiqh_tool error",
            exc_info=True,
            extra={"correlation_id": correlation_id_ctx.get()},
        )
        return {
            "is_fiqh": False,  # Default to allowing the query
            "explanation": f"Classification error: {str(e)}"
        }
