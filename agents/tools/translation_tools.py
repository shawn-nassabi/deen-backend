"""
Translation tools for the LangGraph agent.
These tools handle translation between English and other languages.
"""

import logging
from typing import Dict

from langchain_core.tools import tool
from core.context import correlation_id as correlation_id_ctx
from modules.translation import translator

logger = logging.getLogger(__name__)


@tool
async def translate_to_english_tool(text: str, source_language: str) -> Dict[str, str]:
    """
    Translate the user's query to English (retrieval runs on English text).

    Only use when the query is in a language other than English.

    Args:
        text: The text to translate.
        source_language: The source language (e.g. "arabic", "urdu").
    """
    try:
        if source_language.lower().strip() == "english":
            return {
                "translated_text": text,
                "original_text": text,
                "source_language": "english"
            }

        translated = await translator.atranslate_to_english(text, source_language)

        return {
            "translated_text": translated,
            "original_text": text,
            "source_language": source_language
        }
    except Exception as e:
        logger.error(
            "translate_to_english_tool error",
            exc_info=True,
            extra={"correlation_id": correlation_id_ctx.get()},
        )
        return {
            "translated_text": text,  # Return original on error
            "original_text": text,
            "source_language": source_language,
            "error": str(e)
        }


@tool
async def translate_response_tool(text: str, target_language: str) -> Dict[str, str]:
    """
    Translate English text to the user's preferred language.

    Use this tool at the END of the conversation flow, after generating the English response,
    if the user requested a language other than English.

    Args:
        text: The English text to translate
        target_language: The target language (e.g., "arabic", "urdu", "french", etc.)

    Returns:
        Dictionary with:
        - translated_text (str): The translation in target language
        - original_text (str): The original English text
        - target_language (str): The target language

    Note: If translation fails, returns the original English text.
    If target_language is "english", returns text unchanged.
    """
    try:
        if target_language.lower().strip() == "english":
            return {
                "translated_text": text,
                "original_text": text,
                "target_language": "english"
            }

        # Reverse translation is not implemented in modules/translation/translator.py
        # yet — preserve the existing TODO behavior unchanged.
        return {
            "translated_text": text,  # TODO: Implement reverse translation
            "original_text": text,
            "target_language": target_language,
            "note": "Response translation not yet implemented, returning English"
        }
    except Exception as e:
        logger.error(
            "translate_response_tool error",
            exc_info=True,
            extra={"correlation_id": correlation_id_ctx.get()},
        )
        return {
            "translated_text": text,  # Return original on error
            "original_text": text,
            "target_language": target_language,
            "error": str(e)
        }
