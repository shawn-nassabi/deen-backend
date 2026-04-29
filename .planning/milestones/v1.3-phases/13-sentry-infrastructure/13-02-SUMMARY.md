---
phase: 13-sentry-infrastructure
plan: "02"
subsystem: main-entrypoint
tags: [sentry, observability, middleware, correlation-id, structured-logging]
dependency_graph:
  requires:
    - core.context.correlation_id
    - core.middleware.CorrelationIdMiddleware
    - core.sentry.SENTRY_ENABLED
    - core.sentry.bind_sentry_scope
  provides:
    - main.py Sentry wiring (import core.sentry side-effect init)
    - main.py CorrelationIdMiddleware registered
    - main.py catch_exceptions_mw structured logging
  affects:
    - main.py
tech_stack:
  added: []
  patterns:
    - Side-effect import pattern for module-level initialization (import core.sentry)
    - logger.error(exc_info=True) → LoggingIntegration auto-capture (no duplicate Sentry events)
    - SENTRY_ENABLED-gated response body (production vs dev exception detail)
    - Module-level logger = logging.getLogger(__name__) convention
key_files:
  created: []
  modified:
    - main.py
decisions:
  - "Comment on core.sentry import avoids literal 'sentry_sdk.init(' string — plan's own verification script matches that literal; adjusted comment to 'initializes Sentry SDK' instead"
  - "import sentry_sdk removed from main.py entirely — all SDK access now goes through core/sentry.py"
metrics:
  duration: "7m"
  completed: "2026-04-26"
  tasks_completed: 2
  files_created: 0
  files_modified: 1
requirements_completed:
  - INFRA-01
  - INFRA-02
  - INFRA-03
---

# Phase 13 Plan 02: Wire Sentry Infrastructure into main.py Summary

**One-liner:** Three surgical changes to main.py completing Phase 13 — side-effect sentry import, CorrelationIdMiddleware registration with correct insert(0) order, and catch_exceptions_mw refactored to structured logger.error(exc_info=True) with SENTRY_ENABLED-gated response body.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Replace sentry init block and add CorrelationIdMiddleware | 068d8a8 | main.py |
| 2 | Refactor catch_exceptions_mw | f714e3c | main.py |

## What Was Built

### Task 1 — Sentry Init Block Replacement

**Removed:**
- `from core.config import validate_supabase_config, SENTRY_DSN` (SENTRY_DSN import dropped — no longer used in main.py)
- `import sentry_sdk` top-level import
- `if SENTRY_DSN: sentry_sdk.init(dsn=..., send_default_pii=True, ...)` block

**Added:**
- `import core.sentry` — side-effect import that triggers `sentry_sdk.init()` via core/sentry.py when both `SENTRY_ENABLED=true` AND `SENTRY_DSN` are set
- `from core.sentry import SENTRY_ENABLED` — explicit export for use in catch_exceptions_mw

### Task 1 — CorrelationIdMiddleware Registration

Added after the `app.add_middleware(CORSMiddleware, ...)` block:
```python
from core.middleware import CorrelationIdMiddleware
app.add_middleware(CorrelationIdMiddleware)  # registered after CORS → runs first (insert(0) semantics)
```

Starlette's `add_middleware` uses `list.insert(0)` — last-registered middleware is outermost (runs first on incoming requests). Registering CorrelationIdMiddleware after CORSMiddleware in source ensures it runs before CORSMiddleware, so `correlation_id` ContextVar is set for all downstream code including route handlers.

### Task 2 — catch_exceptions_mw Refactoring

**Removed:**
- `import traceback` — `exc_info=True` on logger handles stack trace capture
- `traceback.format_exc()` and the `print("\n===== SERVER EXCEPTION =====\n", ...)` call
- `sentry_sdk.capture_exception(e)` — LoggingIntegration auto-captures ERROR log events, one Sentry event per exception

**Added:**
- `import logging` at module level
- `logger = logging.getLogger(__name__)` above the middleware decorator (project convention)
- `logger.error("Unhandled exception", exc_info=True, extra={"path": str(request.url.path)})` replaces the print+capture pattern
- SENTRY_ENABLED-gated response: production returns `{"detail": "internal_error"}` only; dev includes `"error": str(e)` for debugging convenience

## Verification Results

All plan acceptance criteria and overall verification passed:
- `grep -c "sentry_sdk.init(" main.py` = 0
- `grep -c "send_default_pii" main.py` = 0
- `grep -c "import core.sentry" main.py` = 1
- `grep -c "from core.sentry import SENTRY_ENABLED" main.py` = 1
- `grep -c "CorrelationIdMiddleware" main.py` = 2 (import + add_middleware call)
- `grep -c "capture_exception" main.py` = 0
- `grep -c "import traceback" main.py` = 0
- `grep -c "exc_info=True" main.py` = 1
- `grep -c "SENTRY_ENABLED" main.py` = 3 (import + usage in catch_exceptions_mw x2 branches)
- `grep -c "internal_error" main.py` = 2 (two branches)
- `grep -c "print(" main.py` = 0
- `CorrelationIdMiddleware` position > `CORSMiddleware` position in source: PASS
- `python -m py_compile main.py` exits 0
- Test suite: 189 passed, 6 pre-existing failures (same as Plan 01), 0 regressions

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Accuracy] Adjusted comment on core.sentry import to avoid literal pattern collision**
- **Found during:** Task 1 verification
- **Issue:** The plan specified comment text `# side-effect: triggers sentry_sdk.init() when SENTRY_ENABLED=true AND SENTRY_DSN set` — this contains the literal string `sentry_sdk.init(` which the plan's own verification script checks for: `assert 'sentry_sdk.init(' not in src`. The comment would cause the check to FAIL.
- **Fix:** Changed comment to `# side-effect: initializes Sentry SDK when SENTRY_ENABLED=true AND SENTRY_DSN set` — preserves meaning without the literal pattern that triggers the assertion.
- **Files modified:** main.py (comment only)
- **Commit:** 068d8a8 (applied before committing)

## Known Stubs

None — all changes are complete implementations with no placeholder values.

## Threat Model Compliance

| Threat ID | Status | Verification |
|-----------|--------|-------------|
| T-13-07 (Info Disclosure - response body) | MITIGATED | `grep -c "internal_error" main.py` = 2 (two branches: SENTRY_ENABLED true/false) |
| T-13-08 (Duplicate Sentry events) | MITIGATED | `grep -c "capture_exception" main.py` = 0; `logger.error(exc_info=True)` used |
| T-13-09 (sentry_sdk import in main.py) | MITIGATED | `grep -c "import sentry_sdk" main.py` = 0 — all SDK access via core/sentry.py |
| T-13-10 (Middleware registration order) | MITIGATED | CorrelationIdMiddleware index > CORSMiddleware index in source; runs first at request time |

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced.

## Self-Check: PASSED
