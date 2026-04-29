# Stack Research: v1.3 Sentry Deep Integration

**Project:** Deen Backend v1.3 — Structured Sentry Logging + Correlation ID
**Researched:** 2026-04-26
**Scope:** Four specific new capabilities on top of the already-initialized `sentry-sdk[fastapi]==2.27.0`:
1. `SENTRY_ENABLED` env var gate
2. Request-scoped `correlation_id` via middleware
3. Sentry scope binding (session_id, user_id, endpoint, correlation_id per request)
4. Python logging → Sentry structured log integration

---

## 1. SENTRY_ENABLED Env Var Gate

### What exists vs what is needed

`main.py` currently gates Sentry init on `SENTRY_DSN` presence:

```python
if SENTRY_DSN:
    sentry_sdk.init(dsn=SENTRY_DSN, ...)
```

This works — a missing DSN silences Sentry entirely. However the v1.3 goal is an explicit `SENTRY_ENABLED` boolean opt-in so local dev is never accidentally enabled even if a DSN is configured in `.env`.

### Recommended pattern

```python
# core/config.py — add alongside existing SENTRY_DSN
SENTRY_DSN = os.getenv("SENTRY_DSN")
SENTRY_ENABLED = os.getenv("SENTRY_ENABLED", "false").lower() == "true"
```

```python
# main.py — replace the current SENTRY_DSN-only guard
if SENTRY_ENABLED and SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=True,
        environment=os.getenv("ENV", "development"),
        _experiments={"enable_logs": True},
        integrations=[
            LoggingIntegration(
                level=logging.INFO,          # breadcrumbs at INFO+
                event_level=logging.ERROR,   # Sentry issues at ERROR+
                sentry_logs_level=logging.INFO,  # structured logs at INFO+
            ),
        ],
    )
```

**Why explicit boolean over DSN-only check:**
- DSN can be committed by accident or inherited from CI env; `SENTRY_ENABLED=false` is a deliberate no-op signal
- Local dev `.env` can safely include the DSN for production comparison testing without activating event sending
- Avoids the ambiguity of "is Sentry broken, or just not configured?" — `SENTRY_ENABLED=true` makes intent explicit

**No new package required.** This is pure env var + conditional logic.

**Confidence:** HIGH — based on `core/config.py` code read + official Sentry docs confirming no built-in `SENTRY_ENABLED` var exists; the DSN-presence pattern is the official fallback (sources: Sentry Configuration docs).

---

## 2. Correlation ID Generation and Propagation

### Decision: Use `asgi-correlation-id` (new dependency)

**Package:** `asgi-correlation-id` — latest stable 4.3.4 (April 2026)
**PyPI:** https://pypi.org/project/asgi-correlation-id/

**Why this over raw `contextvars`:**

Raw `contextvars.ContextVar` in FastAPI/Starlette middleware has a known propagation hazard: context set inside Starlette's middleware layers is not reliably visible in outer middleware layers. The `asgi-correlation-id` package handles this correctly — it sets the ContextVar at the ASGI scope level before any middleware chain processing. Additionally, if `sentry-sdk` is installed, `asgi-correlation-id` automatically attaches the correlation ID as Sentry's `transaction_id` — eliminating manual Sentry tagging for this specific value.

**Why not `starlette-context`:**
`starlette-context` is a more general key-value store middleware, not focused on correlation IDs. For this use case, `asgi-correlation-id` is purpose-built and has the Sentry integration built in.

**Why not `threading.local`:**
FastAPI is async; `threading.local` is unsafe across coroutines sharing the same OS thread. `contextvars.ContextVar` (which `asgi-correlation-id` uses internally) is the correct async-safe choice.

### Installation

```bash
pip install asgi-correlation-id==4.3.4
```

### FastAPI middleware setup

```python
# main.py — add after CORS middleware
from asgi_correlation_id import CorrelationIdMiddleware

app.add_middleware(CorrelationIdMiddleware)
```

Default behavior:
- Checks for `X-Correlation-ID` request header; if absent, generates a UUID4
- Sets a `ContextVar` accessible via `asgi_correlation_id.correlation_id`
- If `sentry-sdk` is installed, **automatically** calls `sentry_sdk.set_tag("transaction_id", <uuid>)` — no manual Sentry wiring needed for this

### Accessing the ID anywhere in the app

```python
from asgi_correlation_id import correlation_id

# Inside any route handler, service, or tool:
cid = correlation_id.get()  # returns str UUID or "" if not in a request context
```

### Logging filter (integrates with existing `core/logging_config.py`)

```python
# core/logging_config.py — add CorrelationIdFilter to StreamHandler
from asgi_correlation_id import CorrelationIdFilter

def setup_logging(...):
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.addFilter(CorrelationIdFilter(uuid_length=32, default_value="-"))
        handler.setFormatter(ExtraFormatter(DEFAULT_FORMAT))
        root.addHandler(handler)
    ...
```

Update `DEFAULT_FORMAT` to include `%(correlation_id)s`:
```python
DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s [%(correlation_id)s] - %(message)s"
```

**Confidence:** HIGH — `asgi-correlation-id` README and PyPI page explicitly document Sentry auto-integration and ContextVar usage. Sentry auto-tagging confirmed by multiple sources including package README.

---

## 3. Sentry Scope Binding: Attaching Context Per Request

### How sentry-sdk 2.x scopes work (critical context for implementation)

sentry-sdk 2.x has three scope levels:
- **Global scope** — set at init time; applies to all events
- **Isolation scope** — one per request, created automatically by the FastAPI/Starlette integration; top-level API calls (`sentry_sdk.set_tag()`, `sentry_sdk.set_user()`) write to this scope
- **Current scope** — short-lived, for a single code block; use `with sentry_sdk.new_scope() as scope:` when you need a temporary fork

**The FastAPI integration creates an isolation scope per request automatically** — no manual middleware is needed for that lifecycle boundary. When you call `sentry_sdk.set_tag(...)` inside a route handler or middleware, it writes to that request's isolation scope and is attached to all events from that request.

### API decision matrix

| Data | API | Reason |
|------|-----|--------|
| `correlation_id` | Handled by `asgi-correlation-id` automatically as `transaction_id` | No manual call needed |
| `session_id` | `sentry_sdk.set_tag("session_id", session_id)` | Indexed/searchable; useful for filtering events by session |
| `user_id` | `sentry_sdk.set_user({"id": user_id})` | Standard Sentry user interface; shows in event detail + user impact count |
| `endpoint` | `sentry_sdk.set_tag("endpoint", "/chat/stream/agentic")` | Indexed; allows filtering Sentry issues by endpoint |
| Rich request dict | `sentry_sdk.set_context("request_context", {...})` | Non-indexed structured data for debugging detail; not searchable |

**`set_tag` vs `set_context` — the rule:**
- `set_tag(key, value)`: key/value strings, max 32/200 chars, **indexed and searchable** in Sentry UI. Use for anything you'll filter or group by (session_id, user_id-as-tag, endpoint).
- `set_context(name, dict)`: arbitrary nested object, **not indexed, not searchable**, but visible in the event detail panel. Use for a rich debugging payload (e.g., the full request body shape, retrieved doc counts).
- `set_user({"id": ..., "email": ...})`: special Sentry user interface. Shows user-facing metrics (affected users count). Always use this for the authenticated user, not a tag.

### Where to call in FastAPI

Call from inside an `@app.middleware("http")` function **after** `CorrelationIdMiddleware` has run (i.e., add the Sentry-binding middleware after `CorrelationIdMiddleware` in `app.add_middleware` calls — Starlette executes middleware in reverse registration order, so add the Sentry middleware first, `CorrelationIdMiddleware` last).

```python
# middleware/sentry_context_middleware.py (new file)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import sentry_sdk
from core.config import SENTRY_ENABLED

class SentryContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if SENTRY_ENABLED:
            sentry_sdk.set_tag("endpoint", request.url.path)
            # session_id and user_id are set inside individual route handlers
            # where they are available from request body / JWT
        return await call_next(request)
```

**For session_id and user_id** — these come from the request body and JWT, not the URL, so they must be set inside the route handler after extraction:

```python
# api/chat.py — inside the agentic chat handler
import sentry_sdk
from core.config import SENTRY_ENABLED

async def chat_pipeline_streaming_agentic(request, credentials, ...):
    user_id = _extract_user_id(credentials)
    session_id = request.session_id

    if SENTRY_ENABLED:
        if user_id:
            sentry_sdk.set_user({"id": user_id})
        sentry_sdk.set_tag("session_id", session_id)

    ...
```

**Important:** Do NOT use `with sentry_sdk.new_scope() as scope:` for per-request context. The isolation scope is already request-scoped by the FastAPI integration. Using `new_scope()` creates a temporary fork that is discarded after the `with` block — not what you want for request-lifetime context. Call top-level `sentry_sdk.set_tag()` / `sentry_sdk.set_user()` directly.

**Confidence:** HIGH — Sentry SDK 2.x migration docs and scope documentation explicitly state that top-level API calls write to the isolation scope, which is request-scoped. FastAPI integration docs confirm per-request isolation scope creation.

---

## 4. Python Logging → Sentry Integration

### What is already wired

`main.py` initializes with `_experiments={"enable_logs": True}`. This is the correct flag for sentry-sdk 2.27.0 (the stable `enable_logs` parameter moved out of `_experiments` in later versions, but `_experiments={"enable_logs": True}` is the correct form for 2.27.0 — already confirmed by the prior milestone).

### What is missing

The `LoggingIntegration` is not explicitly configured in the current `sentry_sdk.init()` call. Without it, the defaults apply:
- `level=logging.INFO` → breadcrumbs from INFO+
- `event_level=logging.ERROR` → Sentry issues from ERROR+
- `sentry_logs_level` defaults are unclear in 2.27.0 without explicit config

**Recommendation:** Explicitly pass `LoggingIntegration` to make the behavior contract visible and intentional:

```python
from sentry_sdk.integrations.logging import LoggingIntegration
import logging

sentry_sdk.init(
    dsn=SENTRY_DSN,
    send_default_pii=True,
    environment=os.getenv("ENV", "development"),
    _experiments={"enable_logs": True},
    integrations=[
        LoggingIntegration(
            level=logging.INFO,           # INFO+ as breadcrumbs (trail of what happened)
            event_level=logging.ERROR,    # ERROR+ as Sentry issues (creates issue in dashboard)
            sentry_logs_level=logging.INFO,  # INFO+ as structured Sentry logs (Explore > Logs)
        ),
    ],
)
```

### How the two log channels work

| Channel | Trigger | What it does |
|---------|---------|--------------|
| Breadcrumbs | `logger.info(...)` / `logger.warning(...)` | Appended to the breadcrumb trail of the next error event. Breadcrumbs appear in the event detail. Not searchable independently. |
| Sentry Issues | `logger.error(...)` / `logger.critical(...)` | Creates a new Sentry issue. Good for unexpected errors. Do NOT call for expected/handled errors — it creates noise. |
| Structured Logs | Any `logger.*` call when `enable_logs=True` + `sentry_logs_level` set | Sent to Sentry Logs (Explore > Logs). Searchable by level, message, and extra fields. |

### How `extra` dict fields flow to Sentry structured logs

With `enable_logs=True` and `LoggingIntegration(sentry_logs_level=logging.INFO)`, any `extra={}` dict passed to a log call becomes top-level searchable attributes in Sentry Logs:

```python
logger.info(
    "Agentic chat request received",
    extra={
        "session_id": session_id,
        "user_id": user_id,
        "endpoint": "/chat/stream/agentic",
    }
)
```

This is the pattern to use for structured context on individual log calls. It complements the per-request Sentry scope tags (which apply to all events from the request) with per-log-call structured data.

**Note:** `extra` fields in Python logging are not forwarded to Sentry Breadcrumbs or Issues — only to Sentry Logs. For breadcrumbs, the message string is the only data captured.

### The existing `ExtraFormatter` works correctly

`core/logging_config.py`'s `ExtraFormatter` appends `extra` dict keys as `key=value` pairs to the console log line. This is complementary: `extra` fields show up both in local console output (via `ExtraFormatter`) and in Sentry Logs (via `LoggingIntegration`). No changes to `ExtraFormatter` are needed.

### Converting `print()` to `logger.*`

The files requiring conversion and their recommended log levels:

| File | Current | Replace with |
|------|---------|-------------|
| `agents/tools/retrieval_tools.py` | `print(f"[retrieve_shia_documents_tool] Error: {e}")` | `logger.warning("Retrieval error", extra={"tool": "retrieve_shia_documents", "error": str(e)})` |
| `api/chat.py` | `print(...)` / `traceback.print_exc()` | `logger.error(...)` with `exc_info=True` for exceptions |
| `core/pipeline_langgraph.py` | `print(...)` calls | `logger.info(...)` for status, `logger.warning(...)` for recoverable issues, `logger.error(..., exc_info=True)` for caught exceptions |
| `api/reference.py` | `print(...)` | `logger.info(...)` / `logger.warning(...)` |

Use `logger = logging.getLogger(__name__)` at module level in each file — do not call `setup_logging()` from within individual modules (that is `main.py`'s responsibility).

**Confidence:** HIGH — LoggingIntegration parameters confirmed via Sentry official logging docs and sentry-python source on GitHub. `extra` field forwarding confirmed via Sentry structured logs discussion (#4220 getsentry/sentry-python).

---

## New Dependency to Add

| Package | Version | Why |
|---------|---------|-----|
| `asgi-correlation-id` | `4.3.4` | Correlation ID generation, ContextVar propagation, automatic Sentry `transaction_id` tagging, logging filter |

No other new packages are required. All Sentry scope and logging APIs are part of the already-installed `sentry-sdk[fastapi]==2.27.0`.

```bash
# Add to requirements.txt
asgi-correlation-id==4.3.4
```

---

## New Env Vars Required

| Variable | Default | Description |
|----------|---------|-------------|
| `SENTRY_ENABLED` | `false` | Set to `true` in production only. Must be `true` AND `SENTRY_DSN` must be set for Sentry to activate. |

`SENTRY_DSN` already exists in `core/config.py`. `SENTRY_ENABLED` is a new addition.

---

## Files Requiring Changes

| File | Change |
|------|--------|
| `core/config.py` | Add `SENTRY_ENABLED = os.getenv("SENTRY_ENABLED", "false").lower() == "true"` |
| `main.py` | Gate on `SENTRY_ENABLED and SENTRY_DSN`; add explicit `LoggingIntegration`; add `CorrelationIdMiddleware`; add `SentryContextMiddleware` |
| `core/logging_config.py` | Add `CorrelationIdFilter` to `StreamHandler`; update `DEFAULT_FORMAT` to include `%(correlation_id)s` |
| `api/chat.py` | Replace `print()` with `logger.*`; call `sentry_sdk.set_user` + `sentry_sdk.set_tag("session_id", ...)` after user/session extraction |
| `api/reference.py` | Replace `print()` with `logger.*` |
| `core/pipeline_langgraph.py` | Replace `print()` with `logger.*` |
| `agents/tools/retrieval_tools.py` | Replace `print()` with `logger.warning(...)` in except blocks |
| `middleware/sentry_context_middleware.py` (new) | `SentryContextMiddleware` — sets `endpoint` tag per request |
| `requirements.txt` | Add `asgi-correlation-id==4.3.4` |
| `.env.example` | Add `SENTRY_ENABLED=false` |

---

## What Does NOT Change

| Component | Reason |
|-----------|--------|
| `sentry-sdk[fastapi]==2.27.0` | No version upgrade needed; all required APIs present |
| `sentry_sdk.init()` call site location | Stays in `main.py` at module level, before app construction |
| `sentry_sdk.capture_exception(e)` in `catch_exceptions_mw` | Already correct; keep as-is |
| `/sentry-debug` dev endpoint | Keep; useful for manual verification |
| Redis, Pinecone, PostgreSQL, LangGraph | Unaffected |
| SSE protocol and all response formats | Zero behavioral changes from frontend's perspective |

---

## Middleware Registration Order

Starlette processes `add_middleware` calls in **reverse** order. The intended execution order for a request is:

1. CORS (already first)
2. `CorrelationIdMiddleware` — generates/reads UUID, sets ContextVar, auto-tags Sentry
3. `SentryContextMiddleware` — reads `request.url.path`, calls `sentry_sdk.set_tag("endpoint", ...)`
4. `catch_exceptions_mw` (already registered via `@app.middleware("http")`)

To achieve this order with `add_middleware` (reverse registration), register as:

```python
app.add_middleware(SentryContextMiddleware)   # registered 2nd → runs 3rd
app.add_middleware(CorrelationIdMiddleware)   # registered 1st → runs 2nd after CORS
```

The existing `@app.middleware("http")` catch-all runs innermost (last) regardless of `add_middleware` order.

---

## Sources

- [Sentry Python Migration 1.x → 2.x](https://docs.sentry.io/platforms/python/migration/1.x-to-2.x) — `configure_scope`/`push_scope` deprecated; top-level API writes to isolation scope (HIGH confidence — official docs)
- [Sentry Python Scopes](https://docs.sentry.io/platforms/python/guides/fastapi/enriching-events/scopes/) — `new_scope` vs `isolation_scope`; top-level `set_tag` uses isolation scope; per-request isolation (HIGH confidence — official docs)
- [Sentry Python Tags](https://docs.sentry.io/platforms/python/enriching-events/tags/) — `set_tag` is indexed/searchable; max 32-char key / 200-char value (HIGH confidence — official docs)
- [Sentry Python Context](https://docs.sentry.io/platforms/python/enriching-events/context/) — `set_context` is not indexed; use for rich structured debugging data (HIGH confidence — official docs)
- [Sentry Python Logging Integration](https://docs.sentry.io/platforms/python/integrations/logging/) — `LoggingIntegration` parameters: `level`, `event_level`, `sentry_logs_level` (HIGH confidence — official docs)
- [Sentry Python Structured Logs Setup](https://docs.sentry.io/platforms/python/logs/) — `enable_logs` in `_experiments` for 2.27.0; `sentry_logs_level` for threshold (HIGH confidence — official docs)
- [Sentry Structured Logging Discussion #4220](https://github.com/getsentry/sentry-python/discussions/4220) — `extra` fields forwarded to Sentry Logs as attributes (MEDIUM confidence — GitHub discussion, not official docs)
- [asgi-correlation-id PyPI](https://pypi.org/project/asgi-correlation-id/) — 4.3.4 latest; `CorrelationIdMiddleware`, `CorrelationIdFilter`, `correlation_id.get()` API (HIGH confidence — official PyPI page)
- [asgi-correlation-id GitHub README](https://github.com/snok/asgi-correlation-id) — Sentry auto-tagging as `transaction_id` when `sentry-sdk` installed; ContextVar usage; logging filter pattern (HIGH confidence — official README)
- [FastAPI contextvars propagation issue #4696](https://github.com/fastapi/fastapi/issues/4696) — raw ContextVar in Starlette middleware has propagation hazards; motivates using `asgi-correlation-id` (MEDIUM confidence — GitHub issue)
- [Sentry FastAPI Integration](https://docs.sentry.io/platforms/python/integrations/fastapi/) — per-request isolation scope created automatically; `set_tag` in handlers applies to current request (HIGH confidence — official docs)
- [sentry_sdk.set_user Issue #2108](https://github.com/getsentry/sentry-python/issues/2108) — `set_user` in FastAPI dependencies may not apply to exception handlers; call in route handler body (MEDIUM confidence — GitHub issue, confirmed as known limitation)
