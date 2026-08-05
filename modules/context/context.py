from core.history_budget import CLASSIFIER_MAX_MESSAGES
from core.memory import make_history, trim_history

def get_recent_context(session_id: str, max_messages: int = CLASSIFIER_MAX_MESSAGES) -> str:
    """
    Pulls the last N turns from Redis (or ephemeral fallback) and returns
    them as a compact string for classifier context.

    Token-cost DEE-60 Phase 2: default window 6 -> 4 messages (the intent
    classifier only needs enough context to label islamic/casual/off-topic).
    """
    history = make_history(session_id)
    msgs = history.messages[-max_messages:]  # last N messages

    parts = []
    for m in msgs:
        role = getattr(m, "type", getattr(m, "role", "user"))
        parts.append(f"{role}: {m.content}")
    return "\n".join(parts)