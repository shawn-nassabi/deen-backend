# Phase 13: Sentry Infrastructure - Pattern Map

**Mapped:** 2026-04-26
**Files analyzed:** 5 (2 new, 2 new in core/, 1 modified main.py + 1 optional config.py check)
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `core/context.py` | utility | request-response | `modules/context/context.py` | role-match (different mechanism; stdlib ContextVar vs Redis/in-memory) |
| `core/middleware.py` | middleware | request-response | `main.py` `catch_exceptions_mw` (lines 93–101) | role-match (both are per-request ASGI interceptors) |
| `core/sentry.py` | utility/config | request-response | `core/config.py` + `main.py` lines 17–23 | role-match (module-level singleton initialization with env gate) |
| `main.py` | config | request-response | itself (modify) | exact — refactor existing `sentry_sdk.init()` and `catch_exceptions_mw` |
| `core/config.py` | config | — | itself (read-only verify) | exact — `SENTRY_DSN` already present at line 8; no edits needed |

---

## Pattern Assignments

### `core/context.py` (utility, request-response)

**Analog:** `modules/context/context.py` — same concept (shared context object imported across layers), different mechanism.

**Pattern: module-level singleton export** (`modules/context/context.py` lines 1–15):
```python
from core.memory import make_history, trim_history

def get_recent_context(session_id: str, max_messages: int = 6) -> str:
    history = make_history(session_id)
    msgs = history.messages[-max_messages:]
    ...
```
The existing `modules/context/context.py` shows the project convention: a single-purpose module in `core/` or `modules/` that exports one primary object used by callers without needing to instantiate anything. `core/context.py` follows the same convention — one exported name, no class, no constructor.

**Target pattern** (copy this exactly):
```python
from contextvars import ContextVar

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
```

**Imports pattern:** single stdlib import only. No third-party dependencies. Type annotation on the module-level variable (`ContextVar[str]`) follows the fully-annotated convention established in `services/` layer and `agents/core/chat_agent.py`.

---

### `core/middleware.py` (middleware, request-response)

**Analog:** `main.py` `catch_exceptions_mw` (lines 93–101) — the only existing per-request ASGI interceptor in the codebase. Both intercept every HTTP request before route handlers run.

**Imports pattern** from `main.py` (lines 89–92):
```python
from fastapi.responses import JSONResponse
from fastapi.requests import Request
import traceback
```
`core/middleware.py` imports will be narrower — use `starlette.middleware.base.BaseHTTPMiddleware` and `starlette.requests.Request` directly (same underlying package, more specific import path for middleware classes).

**Core middleware pattern** from `main.py` (lines 93–101):
```python
@app.middleware("http")
async def catch_exceptions_mw(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        tb = traceback.format_exc()
        print("\n===== SERVER EXCEPTION =====\n", tb, "\n============================\n")
        sentry_sdk.capture_exception(e)
        return JSONResponse(status_code=500, content={"detail": "internal_error", "error": str(e)})
```
`CorrelationIdMiddleware` uses the same `async def dispatch(self, request, call_next)` contract and `await call_next(request)` pass-through. The key difference: it sets a ContextVar and mutates `response.headers` rather than catching exceptions.

**Target pattern** (copy this exactly):
```python
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

**Naming convention:** `PascalCase` for the class (`CorrelationIdMiddleware`) per project convention; `snake_case` for the module file (`middleware.py`).

---

### `core/sentry.py` (utility, request-response)

**Analog:** `core/config.py` (env-gated module-level initialization) + `main.py` lines 17–23 (existing `sentry_sdk.init()` call being replaced).

**Env-gate pattern** from `core/config.py` (lines 7–8, 44–46):
```python
ENV = os.getenv("ENV", "development")
SENTRY_DSN = os.getenv("SENTRY_DSN")  # Optional — absence disables Sentry silently

# Startup guard: fail fast if any required API key is absent
if not ANTHROPIC_API_KEY or not PINECONE_API_KEY:
    raise ValueError("Missing API keys! Ensure ANTHROPIC_API_KEY and PINECONE_API_KEY are set in the .env file.")
```
`core/sentry.py` uses the same `os.getenv()` pattern for `SENTRY_ENABLED`, but the guard is a silent no-op (not a `ValueError`) — absence means "disabled", not "misconfigured".

**Optional config pattern** from `core/config.py` (line 8):
```python
SENTRY_DSN = os.getenv("SENTRY_DSN")  # Optional — absence disables Sentry silently
```
Import `SENTRY_DSN` from `core.config` — do not re-read from `os.getenv()` in `core/sentry.py`. The value is already loaded.

**Current sentry init to replace** (`main.py` lines 14–23):
```python
from core.config import validate_supabase_config, SENTRY_DSN
import os
import sentry_sdk

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=True,
        environment=os.getenv("ENV", "development"),
        _experiments={"enable_logs": True},
    )
```
This block moves entirely out of `main.py` into `core/sentry.py`. The replacement in `main.py` is `import core.sentry` (no `from` — side-effect import to trigger `sentry_sdk.init()` at module load).

**Target pattern for `core/sentry.py`** (verified against sentry-sdk 2.27.0 source):
```python
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
    scope = sentry_sdk.get_isolation_scope()
    scope.set_tag("correlation_id", cid)
    scope.set_tag("endpoint", endpoint)
    if session_id:
        scope.set_tag("session_id", session_id)
    if user_id:
        scope.set_tag("user_id", user_id)
```

**Critical API note:** Do NOT use `sentry_sdk.configure_scope()` — it emits `DeprecationWarning` on every call at sentry-sdk 2.27.0. Use `sentry_sdk.get_isolation_scope().set_tag()` as shown above.

**Logging conventions** from `core/logging_config.py` (lines 1–2) and `api/hikmah.py` (lines 1, 29):
```python
import logging
# ...
logger = logging.getLogger("api.hikmah")
```
`core/sentry.py` does not emit its own log calls, but `bind_sentry_scope` is a no-op helper — consistent with the project's pattern of thin utility functions that perform one task without side effects.

---

### `main.py` (config, request-response) — MODIFY

**Analog:** itself. Three surgical changes to the existing file.

**Change 1 — Remove old sentry init block and replace with side-effect import.**

Current block to remove (`main.py` lines 14–23):
```python
from core.config import validate_supabase_config, SENTRY_DSN
import os
import sentry_sdk

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=True,
        environment=os.getenv("ENV", "development"),
        _experiments={"enable_logs": True},
    )
```
Replacement (two import lines in the existing import block):
```python
from core.config import validate_supabase_config  # remove SENTRY_DSN from this import
import core.sentry                                 # side-effect: triggers sentry_sdk.init() when enabled
from core.sentry import SENTRY_ENABLED            # needed by catch_exceptions_mw
```

**Change 2 — Add CorrelationIdMiddleware registration.**

Existing middleware block (`main.py` lines 60–66):
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
Addition after the CORS block (registration order is critical — `add_middleware` uses `insert(0)`, so last-registered runs first on request):
```python
from core.middleware import CorrelationIdMiddleware
app.add_middleware(CorrelationIdMiddleware)   # registered after CORS → runs before CORS on request
```

**Change 3 — Refactor `catch_exceptions_mw`.**

Current implementation (`main.py` lines 89–101):
```python
from fastapi.responses import JSONResponse
from fastapi.requests import Request
import traceback

@app.middleware("http")
async def catch_exceptions_mw(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        tb = traceback.format_exc()
        print("\n===== SERVER EXCEPTION =====\n", tb, "\n============================\n")
        sentry_sdk.capture_exception(e)
        return JSONResponse(status_code=500, content={"detail": "internal_error", "error": str(e)})
```
Replacement — replace `print()` + `sentry_sdk.capture_exception(e)` with `logger.error()` using the `extra={}` structured logging pattern from `api/hikmah.py` (lines 56–68):
```python
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
The `extra={"path": ...}` pattern is the established structured logging convention from `api/hikmah.py` lines 56–68 and `api/primers.py`. The `traceback` import can be removed entirely — `exc_info=True` on the logger call handles stack trace capture.

**Logger instantiation pattern** from `api/hikmah.py` (lines 1, 9, 28–29):
```python
import logging
from core.logging_config import setup_logging

setup_logging()
logger = logging.getLogger("api.hikmah")
```
In `main.py`, `setup_logging()` is already called elsewhere (or called via `core/logging_config.py` import). Use `logging.getLogger(__name__)` since `main.py` is the app entry point — `__name__` resolves to `"__main__"` which is a clear identifier.

---

### `core/config.py` (config) — READ-ONLY VERIFY

**No changes needed.** `SENTRY_DSN = os.getenv("SENTRY_DSN")` is already present at line 8. `SENTRY_ENABLED` belongs in `core/sentry.py` per D-05 — not in `core/config.py`. The existing optional-value pattern (no `ValueError` guard, comment explaining absence = disabled) is the correct model.

**Relevant lines to confirm no duplication** (`core/config.py` lines 7–8):
```python
ENV = os.getenv("ENV", "development")
SENTRY_DSN = os.getenv("SENTRY_DSN")  # Optional — absence disables Sentry silently
```

---

## Shared Patterns

### Structured Logging with `extra={}`
**Source:** `api/hikmah.py` lines 56–68; `api/primers.py` lines 85–92
**Apply to:** `main.py` `catch_exceptions_mw` refactor (Change 3 above)
```python
logger.error(
    "Unhandled exception",
    exc_info=True,
    extra={"path": str(request.url.path)},
)
```
Convention: structured fields go in `extra={}` dict, not f-string interpolation. `ExtraFormatter` in `core/logging_config.py` appends them as `key=value` pairs automatically.

### Module-Level Logger Instantiation
**Source:** `api/hikmah.py` lines 28–29
**Apply to:** `main.py` (add logger), any new module that emits log calls
```python
setup_logging()
logger = logging.getLogger("api.hikmah")  # or logging.getLogger(__name__)
```

### Optional Env Var Pattern
**Source:** `core/config.py` lines 7–8
**Apply to:** `core/sentry.py` `SENTRY_ENABLED` declaration
```python
SENTRY_DSN = os.getenv("SENTRY_DSN")  # Optional — absence disables silently
```
`SENTRY_ENABLED` follows the same convention: `os.getenv("SENTRY_ENABLED", "").lower() == "true"` — absence defaults to `False` without raising.

### Module-Level Singleton Initialization Guard
**Source:** `core/config.py` lines 44–46, `main.py` lines 17–19
**Apply to:** `core/sentry.py` init block
```python
if not ANTHROPIC_API_KEY or not PINECONE_API_KEY:
    raise ValueError(...)

# sentry.py equivalent (silent, not raising):
if SENTRY_ENABLED and SENTRY_DSN:
    sentry_sdk.init(...)
```
Python module caching (`sys.modules`) guarantees the `if` block runs exactly once per process. No additional `is_initialized()` guard needed.

---

## No Analog Found

No files in this phase lack a reasonable analog. All four new/modified artifacts have direct parallels in the codebase:

| File | Closest Mapping |
|------|-----------------|
| `core/context.py` | `modules/context/context.py` (same single-export module convention) |
| `core/middleware.py` | `main.py` `catch_exceptions_mw` (same ASGI interceptor contract) |
| `core/sentry.py` | `core/config.py` env-gate pattern + `main.py` init block being replaced |
| `main.py` changes | itself (surgical refactor of lines 17–23 and 93–101) |

---

## Anti-Patterns Flagged (avoid in implementation)

| Anti-Pattern | Found In | Replacement |
|---|---|---|
| `sentry_sdk.capture_exception(e)` alongside `logger.error(exc_info=True)` | `main.py` line 100 | Remove `capture_exception` call; `LoggingIntegration` auto-captures from `logger.error` |
| `print()` for exception logging | `main.py` line 99 | `logger.error("Unhandled exception", exc_info=True, extra={...})` |
| `send_default_pii=True` | `main.py` line 20 | `send_default_pii=False` — GDPR Article 9 compliance |
| `sentry_sdk.configure_scope()` | CONTEXT.md D-07 (outdated API spec) | `sentry_sdk.get_isolation_scope().set_tag()` — D-07 corrected in RESEARCH.md |
| f-string interpolation in log messages | `api/primers.py` lines 38, 42, 57 (legacy) | `extra={}` dict for structured fields; new code in Phase 13 uses `extra={}` only |

---

## Metadata

**Analog search scope:** `main.py`, `core/`, `api/`, `modules/context/`, `tests/`
**Files scanned:** 7 (`main.py`, `core/config.py`, `core/logging_config.py`, `modules/context/context.py`, `api/hikmah.py`, `api/primers.py`, `tests/test_primer_service.py`)
**Pattern extraction date:** 2026-04-26
