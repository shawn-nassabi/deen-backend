---
phase: 14-route-layer-instrumentation
plan: "02"
subsystem: api/primers
tags: [logging, sentry, structured-logging, correlation-id, instrumentation]
requirements-completed: [PRIM-01]
dependency-graph:
  requires:
    - core/context.py (correlation_id ContextVar — Phase 13)
    - core/sentry.py (bind_sentry_scope — Phase 13)
  provides:
    - api/primers.py with structured extra={} logging and correlation_id per request
  affects:
    - Sentry Logs — lesson_id, user_id, filter, from_cache, personalized_available now searchable
tech-stack:
  added: []
  patterns:
    - "corr_id = correlation_id_ctx.get() at handler entry point"
    - "bind_sentry_scope(corr_id, endpoint, user_id=...) immediately after corr_id"
    - "logger.*(message, extra={correlation_id: corr_id, ...}) — no f-string interpolation"
    - "logger.error(message, exc_info=True, extra={...}) replacing traceback.print_exc()"
key-files:
  modified:
    - api/primers.py
decisions:
  - "corr_id captured at outer handler scope for stream_personalized_primer so inner event_generator() async generator can close over it — avoids ContextVar access issues inside nested async generators"
metrics:
  duration: "2m"
  completed: "2026-04-27T01:03:55Z"
  tasks-completed: 1
  tasks-total: 1
  files-modified: 1
---

# Phase 14 Plan 02: Primers Route Structured Logging Summary

**One-liner:** Converted all `api/primers.py` logger calls from f-string interpolation to structured `extra={}` with `correlation_id`, removed `traceback.print_exc()`, added `bind_sentry_scope()` in all three handlers — enabling Sentry Logs queries like `lesson_id:42` and `user_id:<sub>`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Convert api/primers.py — f-string logs to extra={}, inject correlation_id, remove traceback | cf42a32 | api/primers.py |

## What Was Built

Instrumented `api/primers.py` (3 route handlers) with Phase 13's Sentry infrastructure:

1. **`get_baseline_primer` (`GET /{lesson_id}/baseline`):** Added `corr_id` extraction and `bind_sentry_scope()` call. Converted 3 logger calls to `extra={}` form. Replaced `logger.error + traceback.print_exc()` with `logger.error(exc_info=True, extra={...})`.

2. **`get_personalized_primer` (`POST /personalized`):** Added `corr_id` extraction and `bind_sentry_scope()` call with `user_id`. Converted 3 logger calls to `extra={}` form with richer fields (`force_refresh`, `filter`, `from_cache`, `personalized_available`). Replaced `logger.error + traceback.print_exc()` with `logger.error(exc_info=True, extra={...})`.

3. **`stream_personalized_primer` (`POST /personalized/stream`):** Added `corr_id` extraction and `bind_sentry_scope()` in the outer handler. The inner `event_generator()` async generator closes over `corr_id`. Converted 3 logger calls to `extra={}` form. Replaced `logger.error + traceback.print_exc()` with `logger.error(exc_info=True, extra={...})` for both exception branches.

Removed `import traceback` entirely once all `traceback.print_exc()` calls were replaced.

## Verification Results

| Check | Result | Expected |
|-------|--------|----------|
| `import traceback` count | 0 | 0 |
| `traceback.print_exc` count | 0 | 0 |
| `print()` calls | 0 | 0 |
| `correlation_id_ctx` occurrences | 4 | >= 4 |
| `bind_sentry_scope` occurrences | 4 | >= 4 |
| `"correlation_id"` key count | 13 | >= 8 |
| `exc_info=True` count | 4 | >= 3 |
| f-string logger calls | 0 | 0 |

## Deviations from Plan

None - plan executed exactly as written.

The `corr_id` variable is correctly captured in the outer `stream_personalized_primer` function scope before the `event_generator()` inner function is defined, so the inner generator closes over the already-resolved value. This is consistent with the plan's note: "The inner function closes over `corr_id` from the outer scope."

## Known Stubs

None. The fallback `PersonalizedPrimerResponse(personalized_bullets=[], ...)` in the exception handler of `get_personalized_primer` is an intentional graceful degradation pattern (pre-existing behavior), not a stub.

## Threat Flags

None. No new endpoints introduced. All extra={} fields are per the plan's threat model (T-14-04, T-14-05, T-14-06): no user_query content, no PII beyond opaque user_id sub claim. Exception detail flows to Sentry only via LoggingIntegration, not to client response (T-14-04 mitigated). correlation_id is server-side ContextVar — client cannot inject (T-14-06 accepted).

## Self-Check: PASSED

- api/primers.py exists and is modified: confirmed
- Commit cf42a32 exists: confirmed
- All acceptance criteria met: confirmed (see Verification Results table)
