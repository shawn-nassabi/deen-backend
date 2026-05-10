import logging

from core import chat_models
from core import prompt_templates
from core.resilience import anthropic_retry

logger = logging.getLogger(__name__)


def translate_to_english(text: str, source_language: str | None = None) -> str:
    """
    Sync variant kept for legacy callers. Prefer `atranslate_to_english` from
    inside an event loop (DEE-42).

    Translate `text` from `source_language` to English using a LangChain chat
    model. Returns the original `text` on error.
    """
    if not text:
        return ""

    if (source_language or "").strip().lower() == "english":
        return text

    try:
        chat_model = chat_models.get_translator_model()
        messages = prompt_templates.translation_messages(source_language=source_language or "unknown", text=text)
        response = chat_model.invoke(messages)
        out = (getattr(response, "content", None) or "").strip()
        return out or text
    except Exception:
        logger.error("translate_to_english error", exc_info=True)
        return text


@anthropic_retry
async def _atranslate_to_english_call(text: str, source_language: str | None):
    chat_model = chat_models.get_translator_model()
    prompt = prompt_templates.translation_prompt_template.invoke(
        {"source_language": source_language or "unknown", "text": text}
    )
    return await chat_model.ainvoke(prompt.to_messages())


async def atranslate_to_english(text: str, source_language: str | None = None) -> str:
    """Native async variant of `translate_to_english`."""
    if not text:
        return ""

    if (source_language or "").strip().lower() == "english":
        return text

    try:
        response = await _atranslate_to_english_call(text, source_language)
        out = (getattr(response, "content", None) or "").strip()
        return out or text
    except Exception:
        logger.error("atranslate_to_english failed after retries", exc_info=True)
        return text
