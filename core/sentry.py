import logging
import os

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from core.config import SENTRY_DSN

# D-05: Both SENTRY_ENABLED=true AND SENTRY_DSN must be set for Sentry to activate.
# Absence of either leaves Sentry completely silent — safe for local dev.
SENTRY_ENABLED: bool = os.getenv("SENTRY_ENABLED", "").lower() == "true"


def _scrub_pii(event: dict, hint: dict) -> dict:
    """Remove request body from Sentry error events.

    D-08: Drops event["request"]["data"] entirely — the most defensive
    approach for GDPR Article 9 special-category data (Islamic religious content).
    Stack traces and tags are preserved; only the request body is removed.

    Note (D-09): before_send applies to error/exception events only.
    Sentry Logs use a separate delivery path — Phases 14-16 control
    log PII by not including user_query in extra={} fields.
    """
    if "request" in event:
        event["request"].pop("data", None)
    return event


if SENTRY_ENABLED and SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=False,
        environment=os.getenv("ENV", "development"),
        integrations=[
            # FastApiIntegration and StarletteIntegration are auto-enabled by sentry-sdk[fastapi].
            # LoggingIntegration must be listed explicitly — it is NOT auto-enabled.
            LoggingIntegration(
                level=logging.INFO,           # breadcrumbs threshold
                event_level=logging.ERROR,    # error event threshold
                sentry_logs_level=logging.INFO,  # Sentry Logs threshold
            )
        ],
        before_send=_scrub_pii,
        enable_logs=True,
    )


def bind_sentry_scope(
    cid: str,
    endpoint: str,
    session_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Set per-request Sentry tags on the current isolation scope.

    No-op when SENTRY_ENABLED is False. Route handlers in Phase 14+ call
    this after extracting session_id and user_id from the request context.

    D-07 CORRECTED: Uses get_isolation_scope().set_tag() — the non-deprecated API
    at sentry-sdk 2.27.0 that does not emit DeprecationWarning on every call.
    FastApiIntegration (auto-enabled) creates a fresh isolation_scope per request
    via SentryAsgiMiddleware, so set_tag() correctly targets the per-request scope.
    """
    if not SENTRY_ENABLED:
        return
    scope = sentry_sdk.get_isolation_scope()
    scope.set_tag("correlation_id", cid)
    scope.set_tag("endpoint", endpoint)
    if session_id:
        scope.set_tag("session_id", session_id)
    if user_id:
        scope.set_tag("user_id", user_id)


def record_cache_metrics_breadcrumb(
    *,
    cache_efficiency_ratio: float,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    iterations: int,
) -> None:
    """Emit a per-turn cache-efficiency breadcrumb on the current Sentry scope.

    No-op when SENTRY_ENABLED is False (D-09) — local dev / unit tests must not
    require Sentry. Called once per /chat/stream/agentic (or /chat/agentic) turn
    at the SSE `done` boundary (D-01, D-02). Caller pre-computes the ratio and
    handles the cold-cache (denominator 0) case as 0.0 (D-06).

    Note: correlation_id is auto-attached via the request's isolation scope
    (set by bind_sentry_scope in api/chat.py); the data dict carries diagnostic
    counts only.

    Args:
        cache_efficiency_ratio: cache_read / (cache_read + cache_creation), 0.0..1.0
        cache_read_tokens: sum across all _agent_node iterations this turn
        cache_creation_tokens: sum across all _agent_node iterations this turn
        iterations: number of _agent_node calls this turn
    """
    if not SENTRY_ENABLED:
        return
    sentry_sdk.add_breadcrumb(
        category="cache_metrics",
        level="info",
        message="cache_efficiency",
        data={
            "cache_efficiency_ratio": cache_efficiency_ratio,
            "cache_read_tokens": cache_read_tokens,
            "cache_creation_tokens": cache_creation_tokens,
            "iterations": iterations,
        },
    )
