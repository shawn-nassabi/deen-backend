import logging
from typing import Optional

from core import chat_models
from core import prompt_templates
from core.memory import amake_history, make_history
from core.resilience import anthropic_retry

logger = logging.getLogger(__name__)


def enhance_query(query: str, session_id: Optional[str] = None) -> str:
    """
    Sync variant kept for legacy callers. Prefer `aenhance_query` from inside
    an event loop (DEE-42).

    Enhances the user query by adding more context to improve retrieval. If
    session_id is provided, recent chat history from Redis is injected via
    the `chat_history` MessagesPlaceholder.
    """
    print("INSIDE enhance_query")

    chat_model = chat_models.get_enhancer_model()

    history_messages = []
    if session_id:
        try:
            history = make_history(session_id)
            history_messages = history.messages
        except Exception:
            logger.error("[enhance_query] failed loading history", exc_info=True)
            history_messages = []

    prompt = prompt_templates.enhancer_prompt_template.invoke(
        {"text": query, "chat_history": history_messages}
    )
    response = chat_model.invoke(prompt.to_messages())

    return response.content.strip()


@anthropic_retry
async def _aenhance_query_call(query: str, history_messages: list):
    chat_model = chat_models.get_enhancer_model()
    prompt = prompt_templates.enhancer_prompt_template.invoke(
        {"text": query, "chat_history": history_messages}
    )
    return await chat_model.ainvoke(prompt.to_messages())


async def aenhance_query(query: str, session_id: Optional[str] = None) -> str:
    """Native async variant of `enhance_query`. The history fetch hits sync
    redis-py so it's offloaded to a thread until DEE-43 ships
    AsyncRedisChatMessageHistory; the LLM invocation uses ainvoke directly."""
    history_messages = []
    if session_id:
        try:
            history_messages = await amake_history(session_id).aget_messages()
        except Exception:
            logger.error("[aenhance_query] failed loading history", exc_info=True)
            history_messages = []

    response = await _aenhance_query_call(query, history_messages)
    from core.token_telemetry import record_llm_usage

    record_llm_usage("enhancer", response)
    return response.content.strip()


def enhance_elaboration_query(selected_text: str, context_text: str, hikmah_tree_name: str, lesson_name: str, lesson_summary: str) -> str:
    """
    Enhances user query by adding more context to improve retrieval.
    """
    print("INSIDE enhance_query")

    chat_model = chat_models.get_enhancer_model()

    prompt = prompt_templates.elaboration_enhancer_prompt_template.invoke({"selected_text": selected_text, "context_text": context_text, "hikmah_tree_name": hikmah_tree_name, "lesson_name": lesson_name, "lesson_summary": lesson_summary})

    response = chat_model.invoke(prompt.to_messages())

    print("Generated enhanced query:", response.content)

    return response.content.strip()


@anthropic_retry
async def _aenhance_elaboration_query_call(
    selected_text: str,
    context_text: str,
    hikmah_tree_name: str,
    lesson_name: str,
    lesson_summary: str,
):
    chat_model = chat_models.get_enhancer_model()
    prompt = prompt_templates.elaboration_enhancer_prompt_template.invoke({
        "selected_text": selected_text,
        "context_text": context_text,
        "hikmah_tree_name": hikmah_tree_name,
        "lesson_name": lesson_name,
        "lesson_summary": lesson_summary,
    })
    return await chat_model.ainvoke(prompt.to_messages())


async def aenhance_elaboration_query(
    selected_text: str,
    context_text: str,
    hikmah_tree_name: str,
    lesson_name: str,
    lesson_summary: str,
) -> str:
    """Native async variant of `enhance_elaboration_query`. Used by the
    /hikmah/elaborate route once Phase 5 (DEE-44) lands."""
    response = await _aenhance_elaboration_query_call(
        selected_text, context_text, hikmah_tree_name, lesson_name, lesson_summary,
    )
    return response.content.strip()
