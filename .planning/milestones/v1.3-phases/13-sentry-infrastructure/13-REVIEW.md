---
phase: 13-sentry-infrastructure
reviewed: 2026-04-26T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - core/context.py
  - core/middleware.py
  - core/sentry.py
  - main.py
findings:
  critical: 2
  warning: 3
  info: 3
  total: 8
status: issues_found
---

# Phase 13: Code Review Report

**Reviewed:** 2026-04-26
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

This phase introduces Sentry error-monitoring infrastructure: a `ContextVar`-based correlation ID (`core/context.py`), a `BaseHTTPMiddleware` that stamps each request with a fresh UUID (`core/middleware.py`), Sentry SDK initialisation with PII scrubbing (`core/sentry.py`), and wiring into `main.py`.

The Sentry initialisation logic and PII-scrubbing callback are sound in isolation. However, two bugs combine to make Sentry's error capture non-functional in the most common failure scenario: `catch_exceptions_mw` swallows every unhandled exception without calling `sentry_sdk.capture_exception`, so Sentry's own ASGI middleware never sees those exceptions. A second, distinct security issue is that the same middleware leaks the raw exception string to callers when `SENTRY_ENABLED` is false — which includes any production deployment that omits the env var.

Three quality/robustness warnings round out the findings: a `BaseHTTPMiddleware` ContextVar propagation caveat, a divergent error-response schema that varies by `SENTRY_ENABLED`, and a duplicate `engine` import. Three informational items cover an unauthenticated database-ping debug endpoint, commented-out auth dependencies, and scattered mid-file imports.

---

## Critical Issues

### CR-01: `catch_exceptions_mw` swallows exceptions — Sentry never captures them

**File:** `main.py:92-106`

**Issue:** `catch_exceptions_mw` catches every unhandled exception and returns a `JSONResponse`, but never calls `sentry_sdk.capture_exception()`. Because the exception is consumed rather than re-raised, Sentry's ASGI middleware (`SentryAsgiMiddleware._run_app`, line 258 in the installed SDK) only triggers its `_capture_exception` path when an exception propagates out of the app — which no longer happens. This means the primary failure mode the entire Sentry integration is intended to surface (unhandled 500 errors) is silently invisible in Sentry.

The comment in `main.py` ("Unhandled exception") and the `SENTRY_ENABLED` branch (lines 101-106) both assume Sentry is somehow notified, but nothing in this code path produces a Sentry event.

**Fix:**
```python
import sentry_sdk

@app.middleware("http")
async def catch_exceptions_mw(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logger.error(
            "Unhandled exception",
            exc_info=True,
            extra={"path": str(request.url.path)},
        )
        if SENTRY_ENABLED:
            sentry_sdk.capture_exception(e)  # <-- required: ASGI wrapper never sees this
        return JSONResponse(status_code=500, content={"detail": "internal_error"})
```

Note: After adding the explicit capture, the `SENTRY_ENABLED` branch that returns `{"detail": "internal_error", "error": str(e)}` (CR-02 below) should also be resolved.

---

### CR-02: Raw exception string exposed to callers when `SENTRY_ENABLED` is false

**File:** `main.py:101-106`

**Issue:** The error-response branch at lines 103-106 returns `{"detail": "internal_error", "error": str(e)}` — the stringified exception — whenever `SENTRY_ENABLED` is falsy. `SENTRY_ENABLED` defaults to `False` (absent env var). Any production deployment that omits `SENTRY_ENABLED=true` (or sets it to anything other than exactly `"true"`) will leak internal exception messages, stack frame text, database connection strings, file paths, and similar sensitive data to API callers.

This leakage is controlled by an observability flag, not an environment flag, which is the wrong axis. Safe vs. unsafe error disclosure should be gated on `ENV == "production"`, not on whether Sentry is configured.

**Fix:**
```python
from core.config import ENV

@app.middleware("http")
async def catch_exceptions_mw(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logger.error(
            "Unhandled exception",
            exc_info=True,
            extra={"path": str(request.url.path)},
        )
        if SENTRY_ENABLED:
            sentry_sdk.capture_exception(e)
        if ENV == "development":
            # Dev: include detail for local debugging
            return JSONResponse(
                status_code=500,
                content={"detail": "internal_error", "error": str(e)},
            )
        return JSONResponse(status_code=500, content={"detail": "internal_error"})
```

---

## Warnings

### WR-01: `BaseHTTPMiddleware` breaks `ContextVar` propagation for sync route handlers

**File:** `core/middleware.py:9-21`

**Issue:** Starlette's `BaseHTTPMiddleware` (used here for `CorrelationIdMiddleware`) copies the `contextvars.Context` from the calling task into a new task it creates for the downstream handler. In Starlette ≥ 0.20.4 (including 0.45.3 in use) this copy is made before `correlation_id.set(cid)` is called, so sync route handlers executed in a thread-pool executor via `run_in_executor` inherit a copy of the context at the moment the task was spawned — but `ContextVar.set()` on the middleware's task context is not visible across thread boundaries (only the copy is shared, and it is shallow/immutable after fork).

Concretely: any sync `def` route handler (e.g., `db_ping`, `home`, `health`, `_routes`) that reads `correlation_id.get()` will see the empty-string default, not the UUID set by the middleware. If `bind_sentry_scope` is eventually called from a sync context it would tag events with an empty `correlation_id`.

**Fix:** Replace `BaseHTTPMiddleware` with a pure ASGI middleware that sets the ContextVar before yielding:

```python
from starlette.types import ASGIApp, Receive, Scope, Send
import uuid
from core.context import correlation_id

class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        cid = str(uuid.uuid4())
        correlation_id.set(cid)

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[b"x-correlation-id"] = cid.encode()
                message = {**message, "headers": list(headers.items())}
            await send(message)

        await self.app(scope, receive, send_with_header)
```

Then register it as `app.add_middleware(CorrelationIdMiddleware)` unchanged.

---

### WR-02: Divergent error response schema depending on `SENTRY_ENABLED`

**File:** `main.py:100-106`

**Issue:** The two branches of `catch_exceptions_mw` return different JSON shapes: `{"detail": "internal_error"}` vs. `{"detail": "internal_error", "error": str(e)}`. Clients that parse the 500 response body will behave differently depending on whether the server has Sentry enabled — an operational flag is changing the API contract. This makes consistent client error handling impossible and is also the mechanism through which CR-02's information disclosure occurs.

**Fix:** Unify to a single response schema. Add the `"error"` field only in the development environment (see CR-02 fix above), completely decoupled from `SENTRY_ENABLED`.

---

### WR-03: Duplicate `engine` import

**File:** `main.py:18` and `main.py:109`

**Issue:** `engine` is imported twice from `db.session`: once at line 18 (`from db.session import engine, Base`) and again at line 109 (`from db.session import engine`). The second import is redundant and shadowing the first. It also signals that imports are scattered throughout the file rather than consolidated at the top, which is contrary to the project's stated convention (CLAUDE.md: "Standard library imports first, then third-party, then local").

**Fix:** Remove line 109 (`from db.session import engine`) and move the `from sqlalchemy import text` import to the top-level import block alongside the other db imports.

---

## Info

### IN-01: `/_debug/db` and `/_routes` endpoints exposed in production with no authentication

**File:** `main.py:111-115`, `main.py:129-131`

**Issue:** `/_debug/db` executes a live database query (`SELECT version()`) and returns the full PostgreSQL version string. `/_routes` exposes all registered route paths and HTTP methods. Neither endpoint has an authentication dependency, and neither is guarded by an `ENV == "development"` conditional. Any unauthenticated caller can probe the database connectivity status and enumerate all API routes in production.

**Fix:** Either restrict to development only (same pattern as `/sentry-debug` at line 133) or add `dependencies=[Depends(auth)]`:

```python
if os.getenv("ENV", "development") == "development":
    @app.get("/_debug/db")
    def db_ping():
        ...

    @app.get("/_routes")
    def _routes():
        ...
```

---

### IN-02: All primary API router auth dependencies are commented out

**File:** `main.py:65-68`

**Issue:** Lines 65-68 show that `chat_router`, `ref_router`, `hikmah_router`, and `account.router` originally had `dependencies=[Depends(auth)]` applied at the router level. These are now commented out. The routes are included without authentication at lines 70-73. If the individual route handlers themselves do not enforce auth via `Depends(optional_auth)` or equivalent, these endpoints are unauthenticated in production.

This is noted as an existing condition rather than a new regression introduced by this phase, but it is worth flagging since the Sentry scope-binding work in `bind_sentry_scope` tags `user_id` — which implies authenticated calls are expected.

**Fix:** Audit each router to confirm per-route `optional_auth` or `auth` dependencies are applied where required. If router-level auth is intentionally removed, delete the commented-out lines rather than leaving them as dead code.

---

### IN-03: Scattered mid-file imports violate project conventions

**File:** `main.py:61`, `main.py:85-87`, `main.py:108-109`, `main.py:128`

**Issue:** Multiple import statements appear in the middle of `main.py` rather than at the top of the file: `CorrelationIdMiddleware` (line 61), `logging`/`JSONResponse`/`Request` (lines 85-87), `sqlalchemy.text` + second `engine` (lines 108-109), and `APIRoute` (line 128). CLAUDE.md explicitly calls out consolidated top-of-file imports as the project convention.

**Fix:** Move all imports to the top of the file in standard-library → third-party → local order. Eliminate the duplicate `engine` import (see WR-03).

---

_Reviewed: 2026-04-26_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
