---
phase: 13-sentry-infrastructure
plan: "01"
subsystem: core-infrastructure
tags: [sentry, observability, middleware, correlation-id, pii-scrubbing]
dependency_graph:
  requires: []
  provides:
    - core.context.correlation_id
    - core.middleware.CorrelationIdMiddleware
    - core.sentry.SENTRY_ENABLED
    - core.sentry.bind_sentry_scope
  affects:
    - main.py (side-effect import core.sentry in Phase 14)
    - api/chat.py (bind_sentry_scope calls in Phase 14)
tech_stack:
  added:
    - sentry-sdk==2.27.0 (already in requirements.txt)
  patterns:
    - ContextVar per-request correlation ID propagation
    - BaseHTTPMiddleware for UUID generation and header injection
    - SENTRY_ENABLED + SENTRY_DSN dual-gate for conditional SDK initialization
    - before_send PII scrubbing hook
key_files:
  created:
    - core/context.py
    - core/middleware.py
    - core/sentry.py
  modified: []
decisions:
  - "configure_scope mention removed from docstring to meet strict acceptance criteria (no configure_scope in any form)"
  - "sentry_logs_level=logging.INFO included in LoggingIntegration — valid at sentry-sdk 2.27.0"
  - "FastApiIntegration excluded from integrations list — auto-enabled by sentry-sdk[fastapi]"
  - "_experiments={'enable_logs': True} used instead of top-level param — required at 2.27.0"
metrics:
  duration: "6m"
  completed: "2026-04-26"
  tasks_completed: 3
  files_created: 3
  files_modified: 0
---

# Phase 13 Plan 01: Sentry Infrastructure Foundation Summary

**One-liner:** Three new core modules providing correlation ID propagation (ContextVar), server-side UUID middleware, and dual-gated Sentry SDK initialization with GDPR-compliant PII scrubbing.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create core/context.py | 7c550d4 | core/context.py |
| 2 | Create core/middleware.py | 90061d8 | core/middleware.py |
| 3 | Create core/sentry.py | ac2fddc | core/sentry.py |

## What Was Built

### core/context.py
Single-export module providing `correlation_id: ContextVar[str]` with default `""`. Enables per-request ID propagation through async task chains without threading request objects through function signatures.

### core/middleware.py
`CorrelationIdMiddleware(BaseHTTPMiddleware)` generates a server-side `str(uuid.uuid4())` per request, sets the `correlation_id` ContextVar before delegating to `call_next`, and adds `X-Correlation-ID` to the response headers. Never reads the incoming `X-Correlation-ID` header from clients (D-03 threat mitigation T-13-01).

### core/sentry.py
- `SENTRY_ENABLED: bool` — requires both `SENTRY_ENABLED=true` AND `SENTRY_DSN` in env; defaults to `False`
- `sentry_sdk.init()` gate with `LoggingIntegration(sentry_logs_level=logging.INFO)`, `send_default_pii=False`, `_experiments={"enable_logs": True}`, `before_send=_scrub_pii`
- `_scrub_pii()` hook removes `event["request"]["data"]` before Sentry transport (GDPR Article 9 T-13-02)
- `bind_sentry_scope()` uses `sentry_sdk.get_isolation_scope().set_tag()` — no deprecated `configure_scope()`

## Verification Results

All plan verification checks passed:
- All 3 files exist and importable with no errors when SENTRY_DSN unset
- No `configure_scope` usage anywhere in core/
- No `send_default_pii=True`
- No `request.headers` in middleware (server-side UUID only)
- `sentry_logs_level=logging.INFO` present
- `_experiments={"enable_logs": True}` present
- `before_send=_scrub_pii` present
- `get_isolation_scope()` used (non-deprecated API)
- Test suite: 196 passed, 6 pre-existing failures (unrelated to new files)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Accuracy] Removed configure_scope mention from docstring**
- **Found during:** Task 3 verification
- **Issue:** Plan acceptance criteria states "File does NOT contain `configure_scope`" — the plan's own docstring template referenced it in a comment explaining what NOT to use
- **Fix:** Replaced the `sentry_sdk.configure_scope()` reference in the `bind_sentry_scope` docstring with equivalent prose that doesn't include the string
- **Files modified:** core/sentry.py
- **Commit:** ac2fddc (same commit, fix applied before committing)

## Known Stubs

None — all three modules are complete implementations.

## Threat Flags

None — the three new files introduce no network endpoints, auth paths, or schema changes beyond what the plan's threat model already covered.

## Threat Model Compliance

| Threat ID | Status | Verification |
|-----------|--------|-------------|
| T-13-01 (Tampering - CorrelationIdMiddleware) | MITIGATED | `grep -c "request.headers" core/middleware.py` = 0 |
| T-13-02 (PII disclosure - _scrub_pii) | MITIGATED | `grep -c ".pop..data" core/sentry.py` = 1 |
| T-13-03 (SENTRY_DSN in env) | ACCEPTED | SENTRY_DSN loaded from core.config, not hardcoded |
| T-13-04 (Sentry Logs PII path) | ACCEPTED | No log calls added in this plan; deferred to Phases 14-16 |
| T-13-05 (DoS - duplicate init) | MITIGATED | Python sys.modules caching guarantees single init |
| T-13-06 (SENTRY_ENABLED in dev) | MITIGATED | `SENTRY_ENABLED` defaults to `False` |

## Self-Check: PASSED
