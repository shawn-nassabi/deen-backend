from modules.context import context
from core import chat_models
from core import prompt_templates

def classify_fiqh_query(query: str, session_id: str = None) -> bool:
    """
    Uses 4o-mini to determine if a query is fiqh-related or not.
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



def classify_non_islamic_query(query: str, session_id: str = None) -> bool:
    """
    Uses 4o mini to classify whether the user query is relevant to shia islam or not.
    Uses recent conversation context if session_id is provided.
    """
    chatContext = ""
    if session_id:
        chatContext = context.get_recent_context(session_id)

    chat_model = chat_models.get_classifier_model()
    messages = prompt_templates.nonislamic_classifier_messages(query=query, chatContext=chatContext)
    response = chat_model.invoke(messages)
    response = response.content.strip()
    return "true" in response.lower()