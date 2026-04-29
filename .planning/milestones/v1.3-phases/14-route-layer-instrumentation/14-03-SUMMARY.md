---
phase: 14-route-layer-instrumentation
plan: "03"
subsystem: api/chat
tags:
  - logging
  - sentry
  - correlation-id
  - structured-logging
  - instrumentation
dependency_graph:
  requires:
    - core/context.py (correlation_id ContextVar — Phase 13)
    - core/sentry.py (bind_sentry_scope — Phase 13)
    - 14-01 (reference.py/hikmah.py pattern precedent)
    - 14-02 (primers.py pattern precedent)
  provides:
    - api/chat.py: structured logging for /chat/stream/agentic and /chat/agentic
    - api/chat.py: bind_sentry_scope wired in both agentic handlers
    - api/chat.py: all print() and import traceback removed
  affects:
    - POST /chat/stream/agentic (start + completion INFO logs with full context)
    - POST /chat/agentic (start + completion INFO logs with full context)
    - POST /chat/stream (except block uses logger.error(exc_info=True))
    - Sentry Logs — correlation_id, session_id, user_id, query_length now searchable
tech_stack:
  added: []
  patterns:
    - "corr_id = correlation_id_ctx.get() at handler start (before try block for except scope)"
    - "bind_sentry_scope(corr_id, endpoint, session_id=..., user_id=...) after JWT extraction"
    - "logger.info start log with {correlation_id, session_id, endpoint, user_id, query_length}"
    - "logger.info completion log with {correlation_id, session_id, endpoint, user_id}"
    - "logger.warning for config parse errors per D-09 (not ERROR)"
    - "logger.error(exc_info=True) in except blocks — no print() or traceback.print_exc()"
    - "user_id extracted before try block in /chat/agentic so it is available in except handler"
key_files:
  created: []
  modified:
    - api/chat.py
decisions:
  - "corr_id captured at handler function scope (before try block) so it is in scope inside the except handler — same pattern as 14-01/14-02"
  - "user_id extracted before try block in /chat/agentic non-streaming handler — plan required this so bind_sentry_scope and start log can include user_id before the pipeline runs"
  - "Config parse errors logged at WARNING (not ERROR) per D-09 — malformed config falls back to default AgentConfig, handler continues, no re-raise"
  - "query_length (int) logged instead of user_query (string) per T-14-07 — prevents Islamic query text reaching Sentry Logs"
metrics:
  duration_seconds: 696
  completed_date: "2026-04-27"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 1
requirements_completed:
  - CHAT-01
  - CHAT-02
  - CHAT-03
---

# Phase 14 Plan 03: Chat Route Structured Logging Summary

**One-liner:** Structured logging with correlation_id and bind_sentry_scope added to both agentic chat handlers (/chat/stream/agentic and /chat/agentic); all print()/traceback.print_exc() replaced with logger.*; import traceback removed — completing Phase 14's full api/ instrumentation.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add logger + imports; instrument /chat/stream and /chat/stream/agentic | f6c8772 | api/chat.py |
| 2 | Instrument /chat/agentic; eliminate all remaining print() from api/chat.py | be1f4b9 | api/chat.py |

## Changes Made

### api/chat.py

**Imports added / removed:**
- Added `import logging`
- Added `from core.context import correlation_id as correlation_id_ctx`
- Added `from core.sentry import bind_sentry_scope`
- Added `logger = logging.getLogger(__name__)`
- Removed `import traceback`

**`/chat/stream` handler:**
- Except block: replaced `print("UNHANDLED ERROR in /chat/stream:", e) + traceback.print_exc()` with `logger.error("Unhandled error in /chat/stream", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "endpoint": "/chat/stream"})`

**`/chat/stream/agentic` handler:**
- `corr_id = correlation_id_ctx.get()` at start of handler body (before try block)
- `bind_sentry_scope(corr_id, "/chat/stream/agentic", session_id=session_id, user_id=user_id)` after JWT extraction
- Start INFO log: `"Agentic stream request accepted"` with `{correlation_id, session_id, endpoint, user_id, query_length}`
- Config parse: replaced `print(f"[AGENTIC ENDPOINT] Config parse error: {e}")` with `logger.warning("Config parse error, using default config", extra={...})`
- Completion INFO log: `"Agentic stream response assembled, returning stream"` with `{correlation_id, session_id, endpoint, user_id}` at StreamingResponse assembly
- Except block: replaced `print("UNHANDLED ERROR...")+traceback.print_exc()` with `logger.error(exc_info=True, extra={...})`

**`/chat/agentic` handler:**
- `corr_id = correlation_id_ctx.get()` and `user_id = _extract_user_id(credentials)` extracted at handler start (before try block)
- `bind_sentry_scope(corr_id, "/chat/agentic", session_id=session_id, user_id=user_id)` before try block
- Start INFO log: `"Agentic request accepted"` with `{correlation_id, session_id, endpoint, user_id, query_length}`
- Config parse: replaced `print(f"[AGENTIC ENDPOINT] Config parse error: {e}")` with `logger.warning("Config parse error, using default config", extra={...})`
- Completion INFO log: `"Agentic request completed"` with `{correlation_id, session_id, endpoint, user_id}` before `return result`
- Except block: replaced `print("UNHANDLED ERROR...")+traceback.print_exc()` with `logger.error(exc_info=True, extra={...})`

## Verification Results

| Check | Result | Expected |
|-------|--------|----------|
| `print(` count in api/chat.py | 0 | 0 |
| `traceback.print_exc` count | 0 | 0 |
| `import traceback` | absent | absent |
| `logger.info` count | 4 | >= 4 |
| `logger.warning` count | 2 | >= 2 |
| `logger.error` count | 3 | >= 3 |
| `"correlation_id"` key count | 12 | >= 8 |
| `exc_info=True` count | 3 | >= 3 |
| `print(` count in api/reference.py | 0 | 0 (Phase 14-01) |
| `print(` count in api/hikmah.py | 0 | 0 (Phase 14-01) |
| `print(` count in api/primers.py | 0 | 0 (Phase 14-02) |
| pytest tests (excl. DB tests) | 190 passed, 6 pre-existing failures | 0 new failures |

## Deviations from Plan

None — plan executed exactly as written.

Note: The `/chat/agentic` handler extracted `user_id` before the try block exactly as the plan specified in Task 2. The 6 failing tests (`test_fiqh_integration.py::test_out_of_scope_routes_to_exit` and 5 from `test_primer_service.py`) are pre-existing failures in `core.pipeline_langgraph` and primer service logic — not caused by changes to `api/chat.py`.

## Threat Model Verification

| Threat ID | Status |
|-----------|--------|
| T-14-07 (query text in Sentry Logs) | MITIGATED — `query_length` (int) logged, never `user_query` string |
| T-14-08 (exception details to client) | MITIGATED — `exc_info=True` sends to Sentry only; HTTP response is generic "Internal Server Error" |
| T-14-09 (correlation_id tampering) | ACCEPTED — server-side ContextVar from CorrelationIdMiddleware, not client-controlled |
| T-14-10 (DoS via config parse) | ACCEPTED — malformed config falls back to default, WARNING logged, handler continues |
| T-14-11 (user_id PII in Sentry) | ACCEPTED — user_id is Cognito sub (opaque UUID), not username/email |

## Known Stubs

None.

## Threat Flags

None. No new endpoints introduced. All extra={} fields are within the plan's threat model. Exception detail flows to Sentry only via LoggingIntegration, not to client response.

## Self-Check: PASSED

Files created/modified:
- FOUND: api/chat.py

Commits verified:
- FOUND: f6c8772 (feat(14-03): add logger + imports; instrument /chat/stream and /chat/stream/agentic)
- FOUND: be1f4b9 (feat(14-03): instrument /chat/agentic; eliminate all remaining print() from api/chat.py)
