"""
Per-request LLM token-usage telemetry (token-cost initiative, Phase 0).

Collects raw Anthropic usage counts (input / output / cache read / cache
creation) per named call site into a request-scoped accumulator, so the
pipeline can report a per-stage token breakdown at the SSE `done` boundary
and `scripts/token_bench.py` can build per-stage cost tables.

Design rules:
- Read the RAW Anthropic usage dict from `response.response_metadata["usage"]`,
  never LangChain's `usage_metadata` wrapper on full messages — the wrapper
  double-counts cached tokens on streaming paths (LangChain GitHub #32818;
  see the existing note in agents/core/chat_agent.py).
- For streamed calls, langchain-anthropic 0.3.22 reports complete usage on the
  message_delta chunk's `usage_metadata`, where `input_tokens` INCLUDES cache
  read + creation tokens. `StreamUsageTracker` subtracts the details back out
  to recover the raw Anthropic split, and max-merges across chunks — never
  sums (that is exactly the #32818 double-count).
- Telemetry must never break the pipeline: every public entry point swallows
  its own exceptions and no-ops when no request accumulator is active or the
  response carries no usage (e.g. test fakes).
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any, Dict, Optional

from langchain_core.callbacks import AsyncCallbackHandler

logger = logging.getLogger(__name__)

# Raw-Anthropic field names; `input_tokens` here is the UNCACHED remainder
# (Anthropic semantics), matching response_metadata["usage"].
USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)

# Request-scoped accumulator: {site: {"calls": n, <USAGE_FIELDS>: totals}}.
# Default None => recording is a no-op outside an instrumented request scope.
_token_usage_by_site: contextvars.ContextVar[Optional[Dict[str, Dict[str, int]]]] = (
    contextvars.ContextVar("token_usage_by_site", default=None)
)


def reset_usage_accumulator() -> contextvars.Token:
    """Install a fresh accumulator for the current request context.

    Call before spawning any task that drives LLM calls (tasks copy the
    current context at creation, sharing the same dict object). Pair with
    `restore_usage_accumulator(token)` in a finally block.
    """
    return _token_usage_by_site.set({})


def restore_usage_accumulator(token: contextvars.Token) -> None:
    """Reset the accumulator contextvar; safe to call from any context."""
    try:
        _token_usage_by_site.reset(token)
    except Exception:  # noqa: BLE001 - telemetry must never raise
        pass


def snapshot_usage() -> Dict[str, Dict[str, int]]:
    """Deep-copy the current accumulator ({} when none is active)."""
    acc = _token_usage_by_site.get()
    if not acc:
        return {}
    return {site: dict(rec) for site, rec in acc.items()}


def usage_totals(per_site: Optional[Dict[str, Dict[str, int]]] = None) -> Dict[str, int]:
    """Sum a per-site snapshot into one record (calls + the four usage fields)."""
    if per_site is None:
        per_site = snapshot_usage()
    totals = {"calls": 0, **{k: 0 for k in USAGE_FIELDS}}
    for rec in per_site.values():
        totals["calls"] += int(rec.get("calls", 0) or 0)
        for k in USAGE_FIELDS:
            totals[k] += int(rec.get(k, 0) or 0)
    return totals


def _add(site: str, rec: Dict[str, int]) -> None:
    acc = _token_usage_by_site.get()
    if acc is None:
        return
    slot = acc.setdefault(site, {"calls": 0, **{k: 0 for k in USAGE_FIELDS}})
    slot["calls"] += 1
    for k in USAGE_FIELDS:
        slot[k] += int(rec.get(k, 0) or 0)


def _normalize_raw_usage(usage: Any) -> Optional[Dict[str, int]]:
    """Normalize a raw Anthropic usage dict (response_metadata["usage"])."""
    if not isinstance(usage, dict):
        return None
    rec = {k: int(usage.get(k) or 0) for k in USAGE_FIELDS}
    return rec if any(rec.values()) else None


def _normalize_usage_metadata(um: Any) -> Optional[Dict[str, int]]:
    """Normalize a LangChain UsageMetadata dict (stream chunks).

    LangChain's `input_tokens` includes cache read + creation tokens
    (langchain_anthropic._create_usage_metadata adds them); subtract the
    details back out so the record matches raw Anthropic semantics.
    """
    if not isinstance(um, dict):
        return None
    details = um.get("input_token_details") or {}
    read = int(details.get("cache_read") or 0)
    creation = int(details.get("cache_creation") or 0)
    total_in = int(um.get("input_tokens") or 0)
    rec = {
        "input_tokens": max(total_in - read - creation, 0),
        "output_tokens": int(um.get("output_tokens") or 0),
        "cache_read_input_tokens": read,
        "cache_creation_input_tokens": creation,
    }
    return rec if any(rec.values()) else None


def record_llm_usage(site: str, response: Any) -> None:
    """Record usage from a completed `ainvoke` response (AIMessage).

    Safe no-op when: no accumulator is active, the response is None or a test
    fake without response_metadata, or the usage dict is empty.
    """
    try:
        metadata = getattr(response, "response_metadata", None) or {}
        rec = _normalize_raw_usage(metadata.get("usage"))
        if rec:
            _add(site, rec)
    except Exception:  # noqa: BLE001 - telemetry must never raise
        logger.debug("record_llm_usage failed for site=%s", site, exc_info=True)


class StreamUsageTracker:
    """Collect usage from `astream` chunks; commit once after the stream ends.

    Usage arrives on the message_delta chunk's `usage_metadata` in
    langchain-anthropic 0.3.22 (message_start deliberately carries none).
    Max-merge per field across chunks — never sum (#32818).
    """

    def __init__(self, site: str):
        self.site = site
        self._best: Optional[Dict[str, int]] = None

    def feed(self, chunk: Any) -> None:
        try:
            rec = _normalize_usage_metadata(getattr(chunk, "usage_metadata", None))
            if rec is None:
                metadata = getattr(chunk, "response_metadata", None) or {}
                rec = _normalize_raw_usage(metadata.get("usage"))
            if rec is None:
                return
            if self._best is None:
                self._best = rec
            else:
                self._best = {
                    k: max(self._best.get(k, 0), rec.get(k, 0)) for k in USAGE_FIELDS
                }
        except Exception:  # noqa: BLE001
            logger.debug("StreamUsageTracker.feed failed for site=%s", self.site, exc_info=True)

    def commit(self) -> None:
        try:
            if self._best:
                _add(self.site, self._best)
                self._best = None
        except Exception:  # noqa: BLE001
            logger.debug("StreamUsageTracker.commit failed for site=%s", self.site, exc_info=True)


class UsageCallbackHandler(AsyncCallbackHandler):
    """Capture usage on call sites whose return value hides the AIMessage.

    `with_structured_output(...)` returns the parsed Pydantic object, so
    `response_metadata` is unreachable from the caller. Passing this handler
    via `config={"callbacks": [...]}` reads the raw usage off the underlying
    ChatGeneration message in on_llm_end instead. Mock-model tests simply
    never fire the callback — a safe no-op.
    """

    def __init__(self, site: str):
        self.site = site

    async def on_llm_end(self, response: Any, **kwargs: Any) -> None:  # noqa: D102
        try:
            generations = getattr(response, "generations", None) or []
            first = generations[0][0] if generations and generations[0] else None
            message = getattr(first, "message", None)
            record_llm_usage(self.site, message)
        except Exception:  # noqa: BLE001
            logger.debug("UsageCallbackHandler failed for site=%s", self.site, exc_info=True)
