from modules.context import context
from core import chat_models
from core import prompt_templates
from core.resilience import anthropic_retry


def classify_fiqh_query(query: str, session_id: str = None) -> bool:
    """
    Sync variant kept for legacy callers. Prefer `aclassify_fiqh_query` from
    inside an event loop (DEE-42).

    Uses the small LLM to determine if a query is fiqh-related or not.
    Returns True if fiqh-related, False otherwise.
    Uses recent conversation context if session_id is provided.
    """
    chatContext = ""
    if session_id:
        chatContext = context.get_recent_context(session_id, 2)

    chat_model = chat_models.get_classifier_model()
    messages = prompt_templates.fiqh_classifier_messages(query=query, chatContext=chatContext)
    response = chat_model.invoke(messages)
    response = response.content.strip()
    return "true" in response.lower()


@anthropic_retry
async def _aclassify_fiqh_query_call(messages):
    chat_model = chat_models.get_classifier_model()
    return await chat_model.ainvoke(messages)


async def aclassify_fiqh_query(query: str, session_id: str = None) -> bool:
    """Native async variant — uses chat_model.ainvoke so the event loop
    yields while waiting on the LLM response.

    Functional behavior matches `classify_fiqh_query`.
    """
    chatContext = ""
    if session_id:
        chatContext = context.get_recent_context(session_id, 2)

    messages = prompt_templates.fiqh_classifier_messages(query=query, chatContext=chatContext)
    response = await _aclassify_fiqh_query_call(messages)
    return "true" in response.content.strip().lower()


def classify_non_islamic_query(query: str, session_id: str = None) -> bool:
    """
    Sync variant kept for legacy callers. Prefer `aclassify_non_islamic_query`
    from inside an event loop (DEE-42).

    Uses the small LLM to classify whether the user query is relevant to Shia
    Islam or not. Uses recent conversation context if session_id is provided.
    """
    chatContext = ""
    if session_id:
        chatContext = context.get_recent_context(session_id)

    chat_model = chat_models.get_classifier_model()
    messages = prompt_templates.nonislamic_classifier_messages(query=query, chatContext=chatContext)
    response = chat_model.invoke(messages)
    response = response.content.strip()
    return "true" in response.lower()


@anthropic_retry
async def _aclassify_non_islamic_query_call(messages):
    chat_model = chat_models.get_classifier_model()
    return await chat_model.ainvoke(messages)


async def aclassify_non_islamic_query(query: str, session_id: str = None) -> bool:
    """Native async variant of `classify_non_islamic_query`."""
    chatContext = ""
    if session_id:
        chatContext = context.get_recent_context(session_id)

    messages = prompt_templates.nonislamic_classifier_messages(query=query, chatContext=chatContext)
    response = await _aclassify_non_islamic_query_call(messages)
    return "true" in response.content.strip().lower()
