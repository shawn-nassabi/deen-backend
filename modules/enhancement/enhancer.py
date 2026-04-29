import asyncio
from typing import Optional

from core import chat_models
from core import prompt_templates
from core.memory import make_history


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
        except Exception as e:
            print(f"[enhance_query] failed loading history: {e}")
            history_messages = []

    prompt = prompt_templates.enhancer_prompt_template.invoke(
        {"text": query, "chat_history": history_messages}
    )
    response = chat_model.invoke(prompt.to_messages())

    print("Generated enhanced query:", response.content)
    return response.content.strip()


async def aenhance_query(query: str, session_id: Optional[str] = None) -> str:
    """Native async variant of `enhance_query`. The history fetch hits sync
    redis-py so it's offloaded to a thread until DEE-43 ships
    AsyncRedisChatMessageHistory; the LLM invocation uses ainvoke directly."""
    chat_model = chat_models.get_enhancer_model()

    history_messages = []
    if session_id:
        try:
            history_messages = await asyncio.to_thread(
                lambda: make_history(session_id).messages
            )
        except Exception as e:
            print(f"[aenhance_query] failed loading history: {e}")
            history_messages = []

    prompt = prompt_templates.enhancer_prompt_template.invoke(
        {"text": query, "chat_history": history_messages}
    )
    response = await chat_model.ainvoke(prompt.to_messages())
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


async def aenhance_elaboration_query(
    selected_text: str,
    context_text: str,
    hikmah_tree_name: str,
    lesson_name: str,
    lesson_summary: str,
) -> str:
    """Native async variant of `enhance_elaboration_query`. Used by the
    /hikmah/elaborate route once Phase 5 (DEE-44) lands."""
    chat_model = chat_models.get_enhancer_model()
    prompt = prompt_templates.elaboration_enhancer_prompt_template.invoke({
        "selected_text": selected_text,
        "context_text": context_text,
        "hikmah_tree_name": hikmah_tree_name,
        "lesson_name": lesson_name,
        "lesson_summary": lesson_summary,
    })
    response = await chat_model.ainvoke(prompt.to_messages())
    return response.content.strip()
