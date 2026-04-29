# Phase 13: Sentry Infrastructure - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-26
**Phase:** 13-Sentry Infrastructure
**Areas discussed:** correlation_id propagation, Sentry scope binding, before_send PII scrubbing, catch_exceptions_mw capture

---

## correlation_id propagation

### Q1: How should correlation_id be propagated to deep pipeline/tool log calls?

| Option | Description | Selected |
|--------|-------------|----------|
| contextvars.ContextVar | Set once in middleware, readable from anywhere in the same async context — pipeline, tools, sub-graphs — without passing request around. Standard async Python pattern. | ✓ |
| request.state only | Store in request.state, thread request object through every pipeline function signature. Works but invasive. | |
| You decide | Defer to downstream agents. | |

**User's choice:** contextvars.ContextVar in `core/context.py`
**Notes:** Chosen for clean propagation without modifying every function signature. Critical for phases 14–16 which need correlation_id deep in pipeline and tool log calls.

---

### Q2: Where should the correlation_id middleware live?

| Option | Description | Selected |
|--------|-------------|----------|
| New core/middleware.py | Dedicated file for CorrelationIdMiddleware class. Clean separation, importable for tests. | ✓ |
| Inline in main.py | Add middleware directly alongside catch_exceptions_mw. Simpler, no new file. | |
| You decide | Defer to downstream agents. | |

**User's choice:** New `core/middleware.py`
**Notes:** Keeps main.py slim. CorrelationIdMiddleware extends BaseHTTPMiddleware.

---

### Q3: Should the middleware respect an incoming X-Correlation-ID header?

| Option | Description | Selected |
|--------|-------------|----------|
| Respect incoming if present | Use client-supplied header if present; generate fresh UUID otherwise. Enables end-to-end tracing from frontend/gateway. | |
| Always generate fresh | Ignore client headers — always generate a new UUID. Simpler, avoids accepting untrusted IDs. | ✓ |

**User's choice:** Always generate fresh
**Notes:** Simplicity preferred. Frontend/gateway tracing not a current need.

---

## Sentry scope binding

### Q1: How should session_id, user_id, endpoint, correlation_id be attached per request?

| Option | Description | Selected |
|--------|-------------|----------|
| bind_sentry_scope() helper | Helper function called by route handlers after auth extraction. Consistent pattern across phases 14–16. No-op when SENTRY_ENABLED=false. | ✓ |
| Inline sentry_sdk.set_tag() calls | Each route handler calls set_tag() directly. More verbose, no abstraction. | |
| You decide | Defer to downstream agents. | |

**User's choice:** `bind_sentry_scope()` helper function
**Notes:** Explicit, consistent, reusable by all route handlers in phases 14–16.

---

### Q2: Where should bind_sentry_scope() and SENTRY_ENABLED live?

| Option | Description | Selected |
|--------|-------------|----------|
| core/sentry.py | Dedicated module for all Sentry concerns. Clean isolation, importable everywhere. | ✓ |
| core/middleware.py | Co-locate with correlation middleware. Fewer files but mixes concerns. | |
| core/config.py | Add to existing config module. No new file, but config.py has no Sentry logic today. | |

**User's choice:** New `core/sentry.py`
**Notes:** All Sentry concerns isolated in one file: SENTRY_ENABLED flag, sentry_sdk.init(), bind_sentry_scope(), _scrub_pii.

---

### Q3: Where should sentry_sdk.init() be called?

| Option | Description | Selected |
|--------|-------------|----------|
| Move to core/sentry.py | Fires at module import. main.py does `import core.sentry`. All Sentry initialization in one place. | ✓ |
| Stay in main.py | Keep init in main.py, just import helpers from core/sentry.py. | |

**User's choice:** Move to `core/sentry.py`
**Notes:** `main.py` just does `import core.sentry` — single line, clean.

---

## before_send PII scrubbing

### Q1: What should the before_send hook scrub?

| Option | Description | Selected |
|--------|-------------|----------|
| Drop request.data entirely | Remove full request body from every Sentry error event. Simple, most defensive for Article 9 data. Stack traces and tags still captured. | ✓ |
| Targeted field removal | Recursively scan and remove known fields (user_query, message, query, content). More complex, easier to miss a field path. | |

**User's choice:** Drop `request.data` entirely
**Notes:** Islamic religious content is GDPR Article 9 special-category data. Most defensive approach chosen. Debugging context comes from Sentry tags and stack traces, not request body.

---

### Q2: Should before_send also scrub Sentry log payloads?

| Option | Description | Selected |
|--------|-------------|----------|
| Error events only | before_send only fires on error events. Sentry Logs need before_send_log, unavailable at sentry-sdk 2.27.0. Phases 14–16 control log PII by not logging user_query in extra={}. | ✓ |
| Handle both if possible | Attempt both hooks, document gap at 2.27.0. | |

**User's choice:** Error events only
**Notes:** before_send_log deferred to future milestone (requires sentry-sdk >= 2.35.0, per REQUIREMENTS.md).

---

## catch_exceptions_mw capture

### Q1: How should catch_exceptions_mw handle Sentry capture?

| Option | Description | Selected |
|--------|-------------|----------|
| Replace with logger.error(exc_info=True) | Remove capture_exception(). LoggingIntegration auto-captures via logger.error(). No duplicate events. | ✓ |
| Keep capture_exception() with SENTRY_ENABLED guard | Keep explicit call, add guard, set event_level=CRITICAL to suppress LoggingIntegration duplication. | |

**User's choice:** Replace with `logger.error("Unhandled exception", exc_info=True, extra={"path": ...})`
**Notes:** Cleanest solution. LoggingIntegration handles capture automatically.

---

### Q2: Should catch_exceptions_mw expose raw exception string in response?

**User raised:** Including the error message in the response is useful for development.

**Resolution (free-form discussion):** Gate on SENTRY_ENABLED:
- `SENTRY_ENABLED=true` (production): return `{"detail": "internal_error"}` only — Sentry has full context
- `SENTRY_ENABLED=false` (local dev): return `{"detail": "internal_error", "error": str(e)}` — no Sentry active, dev needs the string

**Notes:** User's reasoning: `SENTRY_ENABLED` is already the "are we in production observability mode" signal, so using it to gate response verbosity is natural and clean.

---

## Claude's Discretion

None — all areas had clear user direction.

## Deferred Ideas

- `before_send_log` for Sentry Logs PII scrubbing — requires sentry-sdk >= 2.35.0
- Sentry Performance tracing (custom spans per retrieval/LLM call)
- Upgrading sentry-sdk beyond 2.27.0
