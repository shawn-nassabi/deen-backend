"""
Translation tools for the LangGraph agent.
These tools handle translation between English and other languages.
"""

import asyncio

from langchain_core.tools import tool
from modules.translation import translator
from typing import Dict


@tool
async def translate_to_english_tool(text: str, source_language: str) -> Dict[str, str]:
    """
    Translate text from another language to English.

    Use this tool when the user's query appears to be in a language other than English.
    The system needs queries in English for retrieval and processing.

    Args:
        text: The text to translate
        source_language: The source language (e.g., "arabic", "urdu", "french", etc.)

    Returns:
        Dictionary with:
        - translated_text (str): The English translation
        - original_text (str): The original text
        - source_language (str): The detected/provided source language

    Note: If translation fails, returns the original text. If source_language is "english",
    returns the text unchanged.
    """
    try:
        if source_language.lower().strip() == "english":
            return {
                "translated_text": text,
                "original_text": text,
                "source_language": "english"
            }

        # Phase 3 (DEE-42) introduces native `atranslate_to_english`; until
        # then, run the sync translator off the event loop.
        translated = await asyncio.to_thread(
            translator.translate_to_english, text, source_language
        )

        return {
            "translated_text": translated,
            "original_text": text,
            "source_language": source_language
        }
    except Exception as e:
        print(f"[translate_to_english_tool] Error: {e}")
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
        print(f"[translate_response_tool] Error: {e}")
        return {
            "translated_text": text,  # Return original on error
            "original_text": text,
            "target_language": target_language,
            "error": str(e)
        }
