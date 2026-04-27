---
phase: 14-route-layer-instrumentation
plan: "01"
subsystem: api-layer
tags:
  - logging
  - sentry
  - correlation-id
  - security
  - data-leak-fix
dependency_graph:
  requires:
    - core/context.py (correlation_id ContextVar — Phase 13)
    - core/sentry.py (bind_sentry_scope — Phase 13)
  provides:
    - api/reference.py: structured logging + REF-02 data-leak fix
    - api/hikmah.py: correlation_id in all logger calls + print() removed
  affects:
    - GET /references (data-leak fix: detail="internal_error")
    - POST /hikmah/elaborate/stream (Sentry scope bound)
    - All hikmah quiz CRUD endpoints (correlation_id in error logs)
tech_stack:
  added: []
  patterns:
    - correlation_id_ctx.get() called at handler start, passed to extra={}
    - bind_sentry_scope() called after JWT extraction, before try block
    - logger.error(exc_info=True) replaces print()+traceback.print_exc()
key_files:
  created: []
  modified:
    - api/reference.py
    - api/hikmah.py
decisions:
  - "Place corr_id = correlation_id_ctx.get() before try block in elaborate/stream so it is in scope in the except handler"
  - "bind_sentry_scope in elaborate/stream passes user_id from request; /references has no user_id so omits it"
  - "detail='Internal Server Error' preserved in hikmah handlers (pre-existing behavior, not a REF-02 target); only reference.py had the data-leak detail=f'...{str(e)}' pattern"
requirements_completed:
  - REF-01
  - REF-02
  - REF-03
  - HIK-01
  - HIK-02
metrics:
  duration_seconds: 174
  completed_date: "2026-04-26"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
---

# Phase 14 Plan 01: Reference and Hikmah Route Instrumentation Summary

**One-liner:** Structured logging with correlation_id added to /references and all hikmah handlers; REF-02 data-leak (raw exception in HTTP 500 detail) closed; print()+traceback.print_exc() replaced with logger.error(exc_info=True).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Instrument api/reference.py — add logger, fix REF-02, remove print() | 204c3f8 | api/reference.py |
| 2 | Instrument api/hikmah.py — inject correlation_id, replace print()+traceback | 7c4aa81 | api/hikmah.py |

## Changes Made

### api/reference.py

- Added `import logging` and `logger = logging.getLogger(__name__)`
- Imported `correlation_id as correlation_id_ctx` from `core.context`
- Imported `bind_sentry_scope` from `core.sentry`
- Added `corr_id = correlation_id_ctx.get()` + `bind_sentry_scope(corr_id, "/references")` before the validation guard
- Added `logger.info("References request received", extra={...})` with correlation_id
- Added `logger.info("References request completed", extra={...})` on success path
- Fixed REF-02: replaced `detail=f"Internal Server Error: {str(e)}"` with `detail="internal_error"`
- Replaced `print(f"{str(e)}")` with `logger.error("References pipeline error", exc_info=True, extra={...})`

### api/hikmah.py

- Removed `import traceback`
- Added `from core.context import correlation_id as correlation_id_ctx`
- Added `from core.sentry import bind_sentry_scope`
- In `chat_pipeline_stream_ep`: added `corr_id = correlation_id_ctx.get()` + `bind_sentry_scope(corr_id, "/hikmah/elaborate/stream", user_id=request.user_id)` before the try block
- Added `"correlation_id": corr_id` to the logger.info() extra dict in `chat_pipeline_stream_ep`
- Replaced `print("UNHANDLED ERROR...")+traceback.print_exc()` with `logger.error("Unhandled error in /hikmah/elaborate/stream", exc_info=True, extra={...})`
- Added `corr_id = correlation_id_ctx.get()` + `"correlation_id": corr_id` to extra dicts in all 7 quiz CRUD handlers: `get_page_quiz_questions`, `create_page_quiz_question`, `list_page_quiz_questions_admin`, `get_page_quiz_question`, `replace_page_quiz_question`, `patch_page_quiz_question`, `delete_page_quiz_question`

## Deviations from Plan

None — plan executed exactly as written.

## Threat Model Verification

| Threat ID | Status |
|-----------|--------|
| T-14-01 (REF-02 data leak) | CLOSED — detail="internal_error" in api/reference.py |
| T-14-02 (extra={} field safety) | ACCEPTED — no user_query in any extra={} field |
| T-14-03 (correlation_id tampering) | ACCEPTED — server-side ContextVar, not client-controlled |

## Known Stubs

None.

## Self-Check: PASSED

Files created/modified:
- FOUND: api/reference.py
- FOUND: api/hikmah.py

Commits verified:
- FOUND: 204c3f8 (feat(14-01): instrument api/reference.py)
- FOUND: 7c4aa81 (feat(14-01): instrument api/hikmah.py)
