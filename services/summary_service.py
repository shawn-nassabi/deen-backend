"""
Running conversation summaries for long chats (token-cost DEE-60, Phase 5).

Phase 2's read-side history budgets send only the most recent ~10 messages to
the LLM; this service keeps a compact SMALL_LLM (Haiku) summary of the OLDER
turns so long conversations keep their context without paying verbatim-history
prices. The summary is refreshed asynchronously after a turn is persisted
(fire-and-forget — zero user-facing latency) and prepended at prompt-build
time only when the budget actually dropped messages.

Cache note (Phase 3 interplay): the summary sits between the cached system
block and the history, so refreshing it invalidates the generation history
prefix. Refreshes therefore run only every second turn once past the trigger,
halving the cache churn for long sessions.

Kill-switch: HISTORY_SUMMARY=0 disables generation, storage, and injection.
Redis-less deployments degrade silently (no summary, budgets still apply).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional

from langchain_core.messages import BaseMessage, HumanMessage

from core import memory

logger = logging.getLogger(__name__)

# Aligned with core/history_budget.py: budgets keep ~10 recent messages.
# The summary covers everything except the freshest TURN (2 messages) —
# overlapping the kept window is benign duplication, but a gap would be a
# silent context hole when the char budget shrinks the window below 8
# messages (review finding: budget can keep as few as 2 on long turns).
SUMMARY_TRIGGER_MSGS = 10
SUMMARY_KEEP_RECENT = 2
SUMMARY_MAX_CHARS = 1000
_TRANSCRIPT_CHAR_CAP = 12000

SUMMARY_PROMPT = (
    "Summarize the EARLIER turns of this Islamic-education chat in at most 900 "
    "characters of plain prose (no preamble, no markdown). Capture: the topics "
    "discussed, key conclusions and any sources/citations mentioned, the user's "
    "stated context or goals, and open threads the user may follow up on.\n\n"
    "Earlier turns:\n{transcript}"
)

# Fire-and-forget task registry so background refreshes aren't garbage-collected.
_pending_tasks: set = set()


def summaries_enabled() -> bool:
    return os.getenv("HISTORY_SUMMARY", "1") != "0"


def _summary_key(session_id: str) -> str:
    return f"{memory.KEY_PREFIX}:{session_id}:summary"


def _turn_counter_key(session_id: str) -> str:
    return f"{memory.KEY_PREFIX}:{session_id}:summary_turns"


async def get_session_summary(session_id: str) -> Optional[str]:
    """Fetch the stored summary; None when disabled, Redis-less, or absent."""
    if not summaries_enabled() or not memory.USE_REDIS:
        return None
    try:
        raw = await memory._get_async_redis().get(_summary_key(session_id))
        if not raw:
            return None
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    except Exception:  # noqa: BLE001 - summary is best-effort
        logger.debug("get_session_summary failed", exc_info=True)
        return None


async def refresh_session_summary(session_id: str) -> None:
    """Regenerate the summary of the pre-budget-window turns (best-effort)."""
    if not summaries_enabled() or not memory.USE_REDIS:
        return
    try:
        messages = await memory.amake_history(session_id).aget_messages()
        if len(messages) <= SUMMARY_TRIGGER_MSGS:
            return
        # Refresh every SECOND persisted turn to halve generation-cache churn
        # (see module docstring). Gated on a dedicated Redis turn counter, NOT
        # on history length: once atrim_history caps the list at
        # REDIS_MAX_MESSAGES the length is constant (a length-modulo gate
        # would then fire every turn — review finding 1), and odd-length
        # histories after a failed stream would never fire (finding 2).
        client = memory._get_async_redis()
        turn_count = await client.incr(_turn_counter_key(session_id))
        await client.expire(_turn_counter_key(session_id), memory.TTL_SECONDS)
        if turn_count % 2 != 0:
            return

        older = messages[:-SUMMARY_KEEP_RECENT]
        transcript = "\n".join(
            f"{getattr(m, 'type', 'user')}: {str(getattr(m, 'content', ''))[:600]}"
            for m in older
        )[:_TRANSCRIPT_CHAR_CAP]

        from core import chat_models
        from core.token_telemetry import record_llm_usage

        model = chat_models.get_enhancer_model()  # SMALL_LLM (Haiku), max_tokens 512
        response = await model.ainvoke(
            [HumanMessage(content=SUMMARY_PROMPT.format(transcript=transcript))]
        )
        record_llm_usage("history_summarizer", response)
        text = (getattr(response, "content", "") or "").strip()[:SUMMARY_MAX_CHARS]
        if text:
            client = memory._get_async_redis()
            await client.set(
                _summary_key(session_id),
                text.encode("utf-8"),
                ex=memory.TTL_SECONDS,
            )
            logger.debug("Session summary refreshed", extra={"session_id": session_id})
    except Exception:  # noqa: BLE001 - never break persistence on summary failure
        logger.debug("refresh_session_summary failed", exc_info=True)


def maybe_schedule_summary_refresh(session_id: str) -> None:
    """Schedule a background refresh from an async context (fire-and-forget)."""
    if not summaries_enabled() or not memory.USE_REDIS:
        return
    try:
        task = asyncio.get_running_loop().create_task(refresh_session_summary(session_id))
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)
    except RuntimeError:
        # No running loop (sync/legacy caller) — skip silently.
        pass


async def prepend_summary_if_truncated(
    session_id: str,
    full_messages: List[BaseMessage],
    budgeted_messages: List[BaseMessage],
) -> List[BaseMessage]:
    """Prepend the stored summary when the history budget dropped messages.

    The summary rides a leading HumanMessage (Anthropic merges consecutive
    user turns, so a human-first history stays valid). No-op when nothing was
    dropped, the feature is off, or no summary exists yet.
    """
    if len(budgeted_messages) >= len(full_messages):
        return budgeted_messages
    summary = await get_session_summary(session_id)
    if not summary:
        return budgeted_messages
    preamble = HumanMessage(
        content=f"[Summary of the earlier conversation]\n{summary}"
    )
    return [preamble, *budgeted_messages]
