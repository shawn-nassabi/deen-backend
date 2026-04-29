---
phase: 13-sentry-infrastructure
fixed_at: 2026-04-26T00:00:00Z
review_path: .planning/phases/13-sentry-infrastructure/13-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 13: Code Review Fix Report

**Fixed at:** 2026-04-26
**Source review:** .planning/phases/13-sentry-infrastructure/13-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (CR-01, CR-02, WR-01, WR-02, WR-03)
- Fixed: 5
- Skipped: 0

## Fixed Issues

### CR-01: `catch_exceptions_mw` swallows exceptions — Sentry never captures them

**Files modified:** `main.py`
**Commit:** 348d345
**Applied fix:** Added `sentry_sdk.capture_exception(e)` inside the `catch_exceptions_mw` exception handler, guarded by `if SENTRY_ENABLED`. Also imported `sentry_sdk` at the mid-file block where the middleware is defined. CR-01, CR-02, and WR-02 were fixed together in one atomic commit as they all affected the same function body.

---

### CR-02: Raw exception string exposed to callers when `SENTRY_ENABLED` is false

**Files modified:** `main.py`
**Commit:** 348d345
**Applied fix:** Replaced the `SENTRY_ENABLED`-gated error disclosure with an `ENV == "development"` gate. Imported `ENV` from `core.config` at the mid-file import block. The detailed `{"detail": "internal_error", "error": str(e)}` response is now returned only in the development environment; production always returns the safe `{"detail": "internal_error"}` schema.

---

### WR-01: `BaseHTTPMiddleware` breaks `ContextVar` propagation for sync route handlers

**Files modified:** `core/middleware.py`
**Commit:** 39ac0ae
**Applied fix:** Replaced the `BaseHTTPMiddleware`-based `CorrelationIdMiddleware` with a pure ASGI middleware class. The new class implements `__init__(self, app: ASGIApp)` and `async __call__(self, scope, receive, send)`, sets `correlation_id` before the downstream app is called, and injects the `x-correlation-id` response header via a `send_with_header` wrapper. The `app.add_middleware(CorrelationIdMiddleware)` registration in `main.py` required no change.

---

### WR-02: Divergent error response schema depending on `SENTRY_ENABLED`

**Files modified:** `main.py`
**Commit:** 348d345
**Applied fix:** Resolved as part of the CR-02 fix. The two-branch `SENTRY_ENABLED` conditional that produced inconsistent JSON schemas was replaced with a single `ENV == "development"` gate, giving all callers a uniform response schema in each environment.

---

### WR-03: Duplicate `engine` import

**Files modified:** `main.py`
**Commit:** b2781cd
**Applied fix:** Moved `from sqlalchemy import text` to the top-level import block immediately after `from db.session import engine, Base`. Removed the redundant mid-file block (`from sqlalchemy import text` + `from db.session import engine` at the original lines 108-109). The `engine` and `text` names are now available from a single top-level import, eliminating the shadowing.

---

_Fixed: 2026-04-26_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
