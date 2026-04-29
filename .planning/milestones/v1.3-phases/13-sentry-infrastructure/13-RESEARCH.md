# Phase 13: Sentry Infrastructure - Research

**Researched:** 2026-04-26
**Domain:** sentry-sdk 2.27.0 — initialization, scope API, LoggingIntegration, ContextVar middleware, BaseHTTPMiddleware streaming
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** Use `contextvars.ContextVar[str]` — a module-level `ContextVar` named `correlation_id` (default `''`) in a new `core/context.py`. Set once in middleware; readable from anywhere in the same async task (pipeline, tools, fiqh sub-graph) without threading `request` through function signatures.

**D-02:** Middleware class `CorrelationIdMiddleware(BaseHTTPMiddleware)` lives in new `core/middleware.py`. Registered in `main.py` via `app.add_middleware(CorrelationIdMiddleware)`. Sets the ContextVar and adds `X-Correlation-ID` to the response headers.

**D-03:** Always generate a fresh UUID per request — ignore any incoming `X-Correlation-ID` header from clients.

**D-04:** New `core/sentry.py` module holds all Sentry concerns: `SENTRY_ENABLED` bool, `sentry_sdk.init()` call (fires at module import when enabled), and `bind_sentry_scope()` helper. `main.py` does `import core.sentry` to trigger initialization.

**D-05:** `SENTRY_ENABLED: bool = os.getenv("SENTRY_ENABLED", "").lower() == "true"`. Both `SENTRY_ENABLED=true` AND `SENTRY_DSN` must be set for `sentry_sdk.init()` to execute. Either missing → Sentry stays completely silent.

**D-06:** `sentry_sdk.init()` params: `integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)]`, `send_default_pii=False` (removes the current `True`), `before_send=_scrub_pii`, `environment=os.getenv("ENV", "development")`, `_experiments={"enable_logs": True}` (kept — sentry-sdk 2.27.0 requires it in `_experiments`).

**D-07:** `bind_sentry_scope(correlation_id, endpoint, session_id=None, user_id=None)` — a helper in `core/sentry.py`. Route handlers (Phases 14+) call it after extracting user_id from auth. No-op when `SENTRY_ENABLED=false`. Uses `sentry_sdk.configure_scope()` to set tags: `correlation_id`, `endpoint`, `session_id` (if present), `user_id` (if present).

**D-08:** `_scrub_pii(event, hint)` drops `event["request"]["data"]` entirely (full request body removed via `.pop("data", None)`). Simplest and most defensive approach for Article 9 special-category data (Islamic religious content). Stack traces and tags are still captured.

**D-09:** `before_send` applies to error/exception events only. Sentry Logs use `before_send_log`, which requires sentry-sdk >= 2.35.0 — out of scope at 2.27.0.

**D-10:** Remove the existing `sentry_sdk.capture_exception(e)` call from `catch_exceptions_mw`. Replace with `logger.error("Unhandled exception", exc_info=True, extra={"path": str(request.url.path)})`. `LoggingIntegration` auto-captures to Sentry — no explicit call needed, no duplicate events.

**D-11:** Error response body is gated on `SENTRY_ENABLED`: when `True`, return `{"detail": "internal_error"}` only (production — Sentry has full context); when `False`, return `{"detail": "internal_error", "error": str(e)}` (local dev convenience, no Sentry active).

### Claude's Discretion

None specified beyond the locked decisions.

### Deferred Ideas (OUT OF SCOPE)

- `before_send_log` hook for Sentry Logs PII scrubbing — requires sentry-sdk >= 2.35.0, pin stays at 2.27.0
- Upgrading `sentry-sdk` beyond 2.27.0 — out of scope for v1.3
- Sentry Performance tracing (custom spans for retrieval, LLM calls, fiqh iterations) — future milestone

</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INFRA-01 | System sends zero data to Sentry when `SENTRY_ENABLED` is `false` or unset — local dev never triggers Sentry events | D-05 guard pattern verified; Python module caching ensures single init execution |
| INFRA-02 | `main.py` initializes Sentry only when both `SENTRY_ENABLED=true` AND `SENTRY_DSN` are set; `LoggingIntegration(level=INFO, event_level=ERROR, sentry_logs_level=INFO)` explicitly configured | `sentry_logs_level` confirmed present in `LoggingIntegration.__init__` at 2.27.0; `_experiments={"enable_logs": True}` required for Sentry Logs delivery |
| INFRA-03 | Every HTTP request carries a unique `correlation_id` UUID; all log events from that request include it | `ContextVar` propagation verified through async task chains including anyio task groups used by BaseHTTPMiddleware; SSE streaming compatible |
| INFRA-04 | Sentry events include `session_id`, `user_id` (when authenticated), and `endpoint` as searchable tags on per-request isolation scope | `sentry_sdk.set_tag()` and `get_isolation_scope().set_tag()` are equivalent at 2.27.0; `FastApiIntegration` auto-creates per-request `isolation_scope()` via `SentryAsgiMiddleware` |
| INFRA-05 | `send_default_pii=True` removed; `before_send` hook redacts `user_query` and request body (GDPR Article 9 compliance) | Starlette integration puts request body in `event["request"]["data"]`; `.pop("data", None)` is the correct removal path |

</phase_requirements>

---

## Summary

Phase 13 delivers four code artifacts: `core/context.py`, `core/middleware.py`, `core/sentry.py`, and a refactored `main.py`. All locked decisions (D-01 through D-11) are technically sound against the installed sentry-sdk 2.27.0 codebase — with one important correction to D-07.

**D-07 correction (critical):** `sentry_sdk.configure_scope()` is **deprecated** at 2.27.0 and emits a `DeprecationWarning` at runtime. The replacement is `sentry_sdk.get_isolation_scope().set_tag(key, value)` or the equivalent top-level `sentry_sdk.set_tag(key, value)` (which routes to `get_isolation_scope()` internally). Since `FastApiIntegration` is auto-enabled and creates a fresh `isolation_scope()` per request via `SentryAsgiMiddleware`, calling `sentry_sdk.set_tag()` inside any request handler (including from `bind_sentry_scope()`) correctly targets the per-request scope.

Two additional verified facts change the INFRA-02 requirements interpretation: `sentry_logs_level` IS a valid `LoggingIntegration` constructor parameter at 2.27.0 (not a future-only feature), and `_experiments={"enable_logs": True}` IS required for Sentry Logs delivery at 2.27.0 (the `SentryLogsHandler` checks this flag before emitting).

`BaseHTTPMiddleware` in Starlette 0.45.3 is streaming-compatible — it passes SSE responses through a `body_stream()` generator without buffering. `ContextVar` propagates correctly into anyio task groups, so `correlation_id` is visible to the SSE generator running in a spawned task.

**Primary recommendation:** Implement `core/sentry.py` using `sentry_sdk.get_isolation_scope().set_tag()` (not the deprecated `configure_scope()`), register `CorrelationIdMiddleware` after `CORSMiddleware` in `main.py` source (so it runs first due to `insert(0)` stack semantics), and include `sentry_logs_level=logging.INFO` in the `LoggingIntegration` constructor alongside `_experiments={"enable_logs": True}`.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Sentry initialization gate (SENTRY_ENABLED + DSN check) | Backend module (`core/sentry.py`) | — | Module-level singleton; must execute once at startup |
| Per-request correlation_id generation | ASGI middleware (`core/middleware.py`) | — | Earliest possible interception point before any handler runs |
| correlation_id propagation to log calls | Python ContextVar (`core/context.py`) | — | Avoids threading `request` through all pipeline layers |
| Per-request Sentry scope binding (tags) | Route handlers (Phase 14+) | `core/sentry.py` helper | Tags need auth context (user_id) extracted in route layer |
| PII scrubbing from error events | `before_send` hook in `core/sentry.py` | — | Last-chance filter before Sentry transport |
| Unhandled exception capture | `catch_exceptions_mw` via `LoggingIntegration` | — | No duplicate events: logger → integration → Sentry |
| Structured log → Sentry Logs delivery | `LoggingIntegration` + `_experiments.enable_logs` | — | Bridge between Python logging and Sentry Logs API |

---

## Standard Stack

### Core (all already installed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sentry-sdk[fastapi] | 2.27.0 [VERIFIED: pip show] | Error capture, Sentry Logs, scope management | Installed, pinned in requirements.txt |
| FastAPI / Starlette | 0.115.8 / 0.45.3 [VERIFIED: pip show] | BaseHTTPMiddleware, Request/Response types | Project framework |
| Python contextvars | stdlib | Per-request ContextVar propagation | Zero dependencies, async-native |

### No New Installations Required

All dependencies for this phase are already present. Phase 13 is pure code addition/refactoring.

---

## Architecture Patterns

### System Architecture Diagram

```
HTTP Request
     │
     ▼
CorrelationIdMiddleware (core/middleware.py)
  - uuid4() → correlation_id ContextVar
  - X-Correlation-ID: <uuid> added to response
     │
     ▼
catch_exceptions_mw (@app.middleware in main.py)
  - try/except → logger.error(exc_info=True) → LoggingIntegration → Sentry
  - SENTRY_ENABLED-gated response body
     │
     ▼
CORSMiddleware
     │
     ▼
Route Handler (Phase 14+)
  - reads correlation_id.get()
  - calls bind_sentry_scope() → sentry_sdk.get_isolation_scope().set_tag(...)
     │
     ▼
Pipeline / Tools / Fiqh subgraph
  - reads correlation_id.get() from ContextVar (same async task context)
     │
     ▼
Python logging.Logger calls
     │
     ▼
LoggingIntegration (sentry_sdk)
  - breadcrumbs at INFO+
  - error events at ERROR+
  - Sentry Logs at INFO+ (when _experiments.enable_logs=True)
     │
     ▼
Sentry (remote) OR /dev/null (when SENTRY_ENABLED=false)
```

### Recommended New File Structure

```
core/
├── context.py       # ContextVar[str] correlation_id = ContextVar("correlation_id", default="")
├── middleware.py    # CorrelationIdMiddleware(BaseHTTPMiddleware)
├── sentry.py        # SENTRY_ENABLED, sentry_sdk.init(), bind_sentry_scope(), _scrub_pii()
├── config.py        # (existing — SENTRY_DSN already here, no changes needed)
└── logging_config.py  # (existing — no changes needed in Phase 13)
```

### Pattern 1: core/context.py — ContextVar Module

```python
# Source: Python stdlib contextvars docs + verified propagation behavior
from contextvars import ContextVar

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
```

**Why this works:** Python's `asyncio` event loop copies ContextVar state into any new coroutine/task spawned from a parent context. Since FastAPI + uvicorn run each request in a coroutine (not a new OS thread), the ContextVar set in middleware propagates to all `await`-ed calls downstream — including LangGraph `astream()`, SSE generator, and any anyio task groups spawned by `BaseHTTPMiddleware.call_next()`. `[VERIFIED: asyncio.run() test + anyio task group test confirmed propagation]`

### Pattern 2: core/middleware.py — CorrelationIdMiddleware

```python
# Source: Starlette BaseHTTPMiddleware docs + verified streaming behavior at 0.45.3
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from core.context import correlation_id


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cid = str(uuid.uuid4())
        correlation_id.set(cid)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response
```

**Streaming note:** `BaseHTTPMiddleware` in Starlette 0.45.3 passes SSE `StreamingResponse` through a `body_stream()` async generator — it does NOT buffer the full body. The known request-body-buffering issue (fixed in Starlette ~0.20.x) does not affect response streaming. `[VERIFIED: source inspection of Starlette 0.45.3 BaseHTTPMiddleware.__call__]`

### Pattern 3: core/sentry.py — Sentry Initialization and Scope Helper

```python
# Source: verified against sentry_sdk 2.27.0 source (pip show + inspect)
import logging
import os
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from core.config import SENTRY_DSN

SENTRY_ENABLED: bool = os.getenv("SENTRY_ENABLED", "").lower() == "true"


def _scrub_pii(event, hint):
    """Remove request body from Sentry events (GDPR Article 9 — Islamic religious content)."""
    if "request" in event:
        event["request"].pop("data", None)
    return event


if SENTRY_ENABLED and SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=False,
        environment=os.getenv("ENV", "development"),
        integrations=[
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR,
                sentry_logs_level=logging.INFO,
            )
        ],
        before_send=_scrub_pii,
        _experiments={"enable_logs": True},
    )


def bind_sentry_scope(
    cid: str,
    endpoint: str,
    session_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Set per-request Sentry tags on the current isolation scope. No-op when disabled."""
    if not SENTRY_ENABLED:
        return
    scope = sentry_sdk.get_isolation_scope()   # per-request scope (auto-created by FastApiIntegration)
    scope.set_tag("correlation_id", cid)
    scope.set_tag("endpoint", endpoint)
    if session_id:
        scope.set_tag("session_id", session_id)
    if user_id:
        scope.set_tag("user_id", user_id)
```

### Pattern 4: main.py Changes

**Registration order (critical):**

```python
# add_middleware uses insert(0): LAST registered = runs FIRST on request
# CorrelationIdMiddleware must be the outermost (first to run) — register it last

app.add_middleware(CORSMiddleware, ...)        # registered first → runs second
app.add_middleware(CorrelationIdMiddleware)    # registered last → runs first
```

**catch_exceptions_mw refactor:**

```python
# Source: D-10, D-11
import logging
logger = logging.getLogger(__name__)

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
            return JSONResponse(status_code=500, content={"detail": "internal_error"})
        return JSONResponse(
            status_code=500,
            content={"detail": "internal_error", "error": str(e)},
        )
```

`SENTRY_ENABLED` must be imported from `core.sentry`, which is imported before the middleware decorator is evaluated.

### Anti-Patterns to Avoid

- **Using `sentry_sdk.configure_scope()`:** Emits `DeprecationWarning` at every call in sentry-sdk 2.27.0. Use `sentry_sdk.get_isolation_scope().set_tag()` instead. `[VERIFIED: source inspection shows DeprecationWarning in configure_scope body]`
- **Using `sentry_sdk.push_scope()`:** Also deprecated at 2.27.0; replaced by `sentry_sdk.new_scope()` or `sentry_sdk.isolation_scope()` context managers.
- **Calling `sentry_sdk.capture_exception(e)` alongside `logger.error(exc_info=True)`:** Creates duplicate Sentry events. `LoggingIntegration` at `event_level=ERROR` already captures the exception from the `logger.error()` call — no explicit `capture_exception()` needed.
- **Registering `CorrelationIdMiddleware` before `CORSMiddleware` in source:** `add_middleware()` uses `insert(0)`, so first-registered runs last. Register `CorrelationIdMiddleware` after `CORSMiddleware` to ensure it runs first on incoming requests.
- **Setting `send_default_pii=True`:** Sends user data (IP, email, cookies) to Sentry. Must be `False` per D-06 and GDPR Article 9 compliance.
- **Putting `_experiments={"enable_logs": True}` at top level of `sentry_sdk.init()`:** Not a valid top-level parameter at 2.27.0 — must remain in `_experiments` dict. Top-level `enable_logs` is only valid at sentry-sdk >= 2.35.0 (per REQUIREMENTS.md Future Requirements). `[VERIFIED: sentry_sdk.consts Experiments TypedDict source]`

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-request Sentry scope isolation | Manual scope dict per request | `FastApiIntegration` + `SentryAsgiMiddleware` (auto-enabled) | Already creates `isolation_scope()` per request via ContextVar — no extra wiring needed |
| Log → Sentry capture bridge | `sentry_sdk.capture_exception()` everywhere | `LoggingIntegration(event_level=ERROR)` | Auto-captures every `logger.error(exc_info=True)` — single event, no duplication |
| Sentry Logs delivery | Direct Sentry Logs API calls | `LoggingIntegration(sentry_logs_level=INFO)` + `_experiments.enable_logs` | `SentryLogsHandler` converts `logger.*` calls to Sentry Log entries automatically |
| ContextVar propagation | Manual `extra={}` threading through every function signature | `ContextVar` set in middleware | Python async runtime copies ContextVar state to all child coroutines |

**Key insight:** `sentry-sdk[fastapi]` auto-enables `FastApiIntegration` and `StarletteIntegration` — verified via `_AUTO_ENABLING_INTEGRATIONS` list in `sentry_sdk.integrations`. No explicit listing in `sentry_sdk.init(integrations=[])` required for the ASGI scope setup, but `LoggingIntegration` must be listed explicitly because it is not auto-enabled.

---

## Common Pitfalls

### Pitfall 1: `configure_scope()` DeprecationWarning Spam

**What goes wrong:** Every call to `bind_sentry_scope()` emits a `DeprecationWarning: sentry_sdk.configure_scope is deprecated...` to stderr. In production, this pollutes logs on every request.

**Why it happens:** D-07 in CONTEXT.md specified `configure_scope()` as the implementation, but sentry-sdk 2.27.0 deprecated it in the 2.x migration.

**How to avoid:** Use `sentry_sdk.get_isolation_scope().set_tag(key, value)` directly. This is the documented 2.x replacement per the migration guide URL in the deprecation message.

**Warning signs:** `DeprecationWarning` lines in `uvicorn` stderr output on every request containing `sentry_sdk.configure_scope`.

### Pitfall 2: Middleware Registration Order Confusion

**What goes wrong:** `CorrelationIdMiddleware` runs after route handlers (or after `catch_exceptions_mw`), so `correlation_id` ContextVar is empty when log calls are made.

**Why it happens:** `app.add_middleware()` uses `list.insert(0)` — last-registered middleware ends up at index 0 (outermost = runs first on request). "Register before CORS" means "add to source code before CORS" but `insert(0)` reverses that, making it the innermost. The intended meaning in D-02 is "run before CORS in execution order," which requires registering it last in source.

**How to avoid:** In `main.py`, call `app.add_middleware(CorrelationIdMiddleware)` AFTER `app.add_middleware(CORSMiddleware, ...)`.

**Warning signs:** `correlation_id.get()` returns `''` inside route handlers; `X-Correlation-ID` header absent from responses when Correlation middleware was added in wrong position.

### Pitfall 3: Missing `_experiments={"enable_logs": True}` Causes Silent Log Drop

**What goes wrong:** `LoggingIntegration(sentry_logs_level=INFO)` is configured, but no logs appear in Sentry Logs UI despite reaching the handler.

**Why it happens:** `SentryLogsHandler.emit()` checks `client.options["_experiments"].get("enable_logs", False)` before doing anything. If `_experiments` is absent or missing the key, the handler silently returns without delivering the log. `[VERIFIED: sentry_sdk/integrations/logging.py line 348]`

**How to avoid:** Always include `_experiments={"enable_logs": True}` in `sentry_sdk.init()` when using `sentry_logs_level`.

**Warning signs:** Python logs appear locally (`uvicorn` output) but Sentry Logs tab in dashboard is empty despite `SENTRY_ENABLED=true`.

### Pitfall 4: `sentry_logs_level` Not a Future-Only Parameter

**What goes wrong:** Planner or implementer omits `sentry_logs_level` from `LoggingIntegration` assuming it only exists in sentry-sdk >= 2.35.0 (based on REQUIREMENTS.md Future Requirements note about `before_send_log`).

**Why it happens:** REQUIREMENTS.md Future Requirements section mentions `before_send_log` hook as requiring >= 2.35.0. This is a different thing from `sentry_logs_level`. The parameter name is similar, causing confusion.

**How to avoid:** `sentry_logs_level` is a valid constructor parameter at 2.27.0 — confirmed by `inspect.signature(LoggingIntegration.__init__)`. INFRA-02 explicitly requires it. Include it in the integration constructor.

**Warning signs:** INFRA-02 acceptance test fails (LoggingIntegration not configured with `sentry_logs_level`).

### Pitfall 5: `before_send` Only Covers Error Events, Not Sentry Logs

**What goes wrong:** Assuming `before_send` scrubs all Sentry data including Sentry Logs entries, leading to false confidence that `user_query` in log `extra={}` is protected.

**Why it happens:** `before_send` is called only for error/exception events. Sentry Logs use a separate delivery path (`_capture_experimental_log` → `LogBatcher`). Scrubbing Sentry Logs requires `before_send_log`, which needs sentry-sdk >= 2.35.0.

**How to avoid (D-09):** Phases 14–16 are responsible for not putting `user_query` content into `extra={}`. The `before_send` scrubber in Phase 13 handles error events only. This is a documented scope limitation, not a bug.

**Warning signs:** None at Phase 13 level — this only becomes a risk when Phase 14+ routes add logging. The planner should note this constraint in Phase 14 research.

---

## Code Examples

### Verified `LoggingIntegration` Constructor at sentry-sdk 2.27.0

```python
# Source: inspect.getsource(LoggingIntegration.__init__) — VERIFIED in venv
from sentry_sdk.integrations.logging import LoggingIntegration
import logging

LoggingIntegration(
    level=logging.INFO,           # breadcrumbs threshold (default: INFO)
    event_level=logging.ERROR,    # error event threshold (default: ERROR)
    sentry_logs_level=logging.INFO,  # Sentry Logs threshold (default: INFO, requires _experiments.enable_logs)
)
```

### Verified Scope Tag API (replacement for deprecated `configure_scope`)

```python
# Source: inspect.getsource(sentry_sdk.api.set_tag) — VERIFIED in venv
# configure_scope() is deprecated — emits DeprecationWarning on every call at 2.27.0

# CORRECT at 2.27.0:
sentry_sdk.get_isolation_scope().set_tag("correlation_id", cid)

# Also valid (same underlying call):
sentry_sdk.set_tag("correlation_id", cid)  # routes to get_isolation_scope().set_tag()

# DEPRECATED (do not use):
# with sentry_sdk.configure_scope() as scope:
#     scope.set_tag("correlation_id", cid)  # DeprecationWarning
```

### Verified ContextVar Propagation Pattern

```python
# Source: Python stdlib + anyio task group propagation test — VERIFIED
from contextvars import ContextVar
import uuid

# core/context.py
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

# Reading from anywhere in the same async request context:
cid = correlation_id.get()  # returns the UUID set by middleware, or '' if unset
```

### Verified `before_send` Request Body Scrubber

```python
# Source: Starlette integration source + sentry-sdk before_send docs — VERIFIED
# Starlette integration puts request body in event["request"]["data"] when:
# - Content-Type is application/json AND json() returns non-empty value
# - Content-Type is form data AND form() returns non-empty value
# .pop("data", None) safely removes it whether or not it is present

def _scrub_pii(event, hint):
    if "request" in event:
        event["request"].pop("data", None)
    return event
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `sentry_sdk.configure_scope()` | `sentry_sdk.get_isolation_scope().set_tag()` | sentry-sdk 2.0.0 | `configure_scope` still works but emits DeprecationWarning |
| `sentry_sdk.push_scope()` | `sentry_sdk.new_scope()` or `sentry_sdk.isolation_scope()` | sentry-sdk 2.0.0 | `push_scope` still works but deprecated |
| `Hub` API (`sentry_sdk.Hub.current`) | Scope API (`get_current_scope()`, `get_isolation_scope()`) | sentry-sdk 2.0.0 | Hub is deprecated; Scope API is the 2.x standard |
| `sentry_sdk.init()` as context manager | Direct call, no context manager pattern | sentry-sdk 2.0.0 | Context manager return value deprecated; call once at module level |
| `_experiments={"enable_logs": True}` | `enable_logs=True` top-level param (future) | sentry-sdk >= 2.35.0 | `_experiments` dict required at 2.27.0 pin |

**Deprecated/outdated in current codebase (`main.py`):**
- `send_default_pii=True` in current `sentry_sdk.init()` — must be replaced with `False`
- `sentry_sdk.capture_exception(e)` in `catch_exceptions_mw` — must be removed (replaced by `LoggingIntegration`)
- `print()` in `catch_exceptions_mw` — must be replaced by `logger.error()`

---

## Open Questions

1. **`sentry_sdk.is_initialized()` guard vs module-level boolean**
   - What we know: Python module caching (`sys.modules`) ensures `core/sentry.py` executes its module body exactly once per process, regardless of how many times it is imported.
   - What's unclear: Whether adding an explicit `if not sentry_sdk.is_initialized():` guard before `sentry_sdk.init()` is desirable as extra safety.
   - Recommendation: The `SENTRY_ENABLED and SENTRY_DSN` condition is sufficient — module caching prevents double-init. The `is_initialized()` guard is redundant but harmless. The planner should not add it unless there is a known test-isolation requirement.

2. **`bind_sentry_scope()` call timing vs `FastApiIntegration` isolation scope**
   - What we know: `FastApiIntegration` (auto-enabled) creates a fresh `isolation_scope()` per request via `SentryAsgiMiddleware._run_app()`. This scope is set as a ContextVar at the ASGI level, before any middleware in `app.user_middleware` runs.
   - What's unclear: Whether `bind_sentry_scope()` calling `get_isolation_scope().set_tag()` from inside `CorrelationIdMiddleware.dispatch()` (middleware level) vs from route handlers (later) matters.
   - Recommendation: Phase 13 middleware only sets the `correlation_id` ContextVar. The `bind_sentry_scope()` call is reserved for route handlers in Phase 14 where `session_id` and `user_id` are available. No issue.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| sentry-sdk[fastapi] | core/sentry.py, LoggingIntegration | ✓ | 2.27.0 | — |
| FastAPI | BaseHTTPMiddleware host | ✓ | 0.115.8 | — |
| Starlette | BaseHTTPMiddleware implementation | ✓ | 0.45.3 | — |
| Python contextvars | core/context.py | ✓ | stdlib (3.11) | — |
| anyio | BaseHTTPMiddleware task groups | ✓ | bundled with Starlette | — |

No missing dependencies. All required libraries are installed and version-confirmed.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — (no auth changes in Phase 13) |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | no | — (correlation_id is server-generated UUID, not user input) |
| V6 Cryptography | no | — |
| V8 Data Protection | **yes** | `before_send` hook strips request body; `send_default_pii=False` prevents PII leakage to Sentry |

### Known Threat Patterns for Sentry Integration

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| PII leakage in error reports | Information Disclosure | `send_default_pii=False` + `before_send` body scrubber (D-06, D-08) |
| Client-controlled correlation_id | Tampering | D-03: always generate server-side UUID, ignore incoming header |
| Sentry DSN exposure in logs | Information Disclosure | `SENTRY_DSN` loaded from env, not hardcoded; `core/config.py` pattern preserved |
| Sentry events in dev environment | Information Disclosure | D-05: `SENTRY_ENABLED=true` explicit opt-in; local dev defaults to disabled |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `ContextVar` set in `CorrelationIdMiddleware.dispatch()` is visible to LangGraph `astream()` calls downstream (same asyncio task chain) | Architecture Patterns — Pattern 1 | correlation_id would be empty in pipeline logs; verified for direct async calls and anyio task groups, not verified for LangGraph's internal task spawning |

**Note on A1:** The LangGraph graph executor may spawn internal asyncio tasks (e.g., for parallel tool execution). If it creates tasks without inheriting the parent context, `correlation_id.get()` would return `''` in those tasks. This is acceptable for Phase 13 — Phase 13 does not add any log calls inside the graph. Phases 14–16 will discover this empirically when adding log calls inside pipeline nodes and tools.

---

## Sources

### Primary (HIGH confidence)
- `sentry_sdk 2.27.0` installed at `/Users/shawn.n/Desktop/Deen/deen-backend/venv/lib/python3.11/site-packages/sentry_sdk` — `configure_scope` deprecation, `LoggingIntegration.__init__` signature, `_AUTO_ENABLING_INTEGRATIONS`, `SentryAsgiMiddleware._run_app` isolation_scope setup, `SentryLogsHandler.emit` enable_logs guard, `sentry_sdk.set_tag` routing to `get_isolation_scope()`
- `Starlette 0.45.3` at `venv/lib/python3.11/site-packages/starlette` — `BaseHTTPMiddleware.__call__` body_stream generator, `add_middleware` insert(0) semantics
- Python stdlib `contextvars` — propagation behavior verified via `asyncio.run()` and anyio task group tests

### Secondary (MEDIUM confidence)
- REQUIREMENTS.md — INFRA-01 through INFRA-05 requirement text
- CONTEXT.md — D-01 through D-11 locked decisions
- ROADMAP.md §Phase 13 — 5 acceptance test criteria

### Tertiary (LOW confidence)
- A1 (LangGraph internal task ContextVar propagation) — not tested; marked as assumption

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages installed, API verified from source
- Architecture: HIGH — middleware order, scope API, LoggingIntegration all verified from source
- Pitfalls: HIGH — all identified from direct source inspection of installed packages
- A1 (LangGraph ContextVar): LOW — not tested; low risk for Phase 13 scope

**Research date:** 2026-04-26
**Valid until:** 2026-05-26 (stable library versions — sentry-sdk pinned, Starlette pinned)
