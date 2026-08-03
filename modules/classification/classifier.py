from modules.context import context
from core import chat_models
from core import prompt_templates
from core.resilience import anthropic_retry
from core.token_telemetry import record_llm_usage


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
    record_llm_usage("non_islamic_classifier_tool", response)
    return "true" in response.content.strip().lower()


@anthropic_retry
async def _aclassify_intent_call(messages):
    chat_model = chat_models.get_classifier_model()
    return await chat_model.ainvoke(messages)


async def aclassify_intent(query: str, session_id: str = None) -> str:
    """3-label intent classifier for the agentic path.

    Returns one of: 'islamic', 'non_islamic', 'casual'.
    Does NOT replace the bool aclassify_non_islamic_query (still used by core/pipeline.py).
    Uses recent conversation context if session_id is provided.
    """
    chatContext = ""
    if session_id:
        chatContext = context.get_recent_context(session_id)

    messages = prompt_templates.intent_classifier_messages(query=query, chatContext=chatContext)
    response = await _aclassify_intent_call(messages)
    record_llm_usage("intent_classifier", response)
    label = response.content.strip().lower()
    if label in ("islamic", "non_islamic", "casual"):
        return label
    # Fallback: if LLM returns unexpected output, treat as islamic to avoid over-refusal
    return "islamic"
