"""
Read-side chat-history budgets (token-cost DEE-60, Phase 2).

Up to REDIS_MAX_MESSAGES (30) verbatim messages were re-sent to the LLM
3-5 times per request (agent iterations, enhancer, generation). These
budgets bound what each call site SENDS — Redis/Postgres still store the
full history; nothing is deleted.

Kill-switch: HISTORY_BUDGETS=0 disables all budgeting (messages pass
through unchanged).
"""

from __future__ import annotations

import os
from typing import List

from langchain_core.messages import AIMessage, BaseMessage

# Per-call-site budgets: (max_messages, max_total_chars). Central so tuning
# happens in one place; validated by the token bench's multi-turn slice.
# GENERATION char cap raised 8000 -> 12000 after live testing: answers run
# 5-11k chars, so 8000 collapsed the window to ~1 message and made the
# summary carry nearly all context. 12000 keeps ~2 recent turns verbatim;
# with AGENT_CACHE_V2 the extra history reads at the 0.1x cached rate.
GENERATION_BUDGET = (10, 12000)
AGENT_BUDGET = (10, 8000)
ENHANCER_BUDGET = (6, 4000)
CLASSIFIER_MAX_MESSAGES = 4


def history_budgets_enabled() -> bool:
    return os.getenv("HISTORY_BUDGETS", "1") != "0"


def _content_len(message: BaseMessage) -> int:
    content = getattr(message, "content", "")
    return len(content) if isinstance(content, str) else len(str(content))


def budget_messages(
    messages: List[BaseMessage], max_msgs: int, max_chars: int
) -> List[BaseMessage]:
    """Return the most recent messages within the count + char budgets.

    - Never splits a message's content.
    - Always keeps at least the last two messages (the freshest turn).
    - Avoids starting the window on an orphan assistant message so the
      model always sees a user turn opening the history.
    """
    if not history_budgets_enabled() or not messages:
        return messages

    kept = list(messages)[-max_msgs:]

    total = sum(_content_len(m) for m in kept)
    while len(kept) > 2 and total > max_chars:
        total -= _content_len(kept[0])
        kept.pop(0)

    while len(kept) > 2 and isinstance(kept[0], AIMessage):
        kept.pop(0)

    return kept
