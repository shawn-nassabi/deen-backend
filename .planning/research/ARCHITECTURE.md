# Architecture: Sentry Deep Integration — correlation_id and Scope Propagation

**Project:** Deen Backend v1.3 — Sentry Deep Integration
**Researched:** 2026-04-26
**Confidence:** HIGH (all claims verified against sentry-sdk 2.27.0 source, existing repo source, Python contextvar docs)

---

## Context

This document answers one question: how should `correlation_id` propagate from the FastAPI HTTP boundary down through `core/pipeline_langgraph.py`, `agents/core/chat_agent.py`, and `agents/tools/` — and where should `sentry_sdk` scope binding happen so that every Sentry event in a request carries the right context?

The existing stack has one significant constraint: the LangGraph pipeline runs synchronous LLM calls (`chain.stream()`, `self.llm.invoke()`) inside `async def` functions. This blocks the event loop but does not break contextvar propagation because Python's `contextvars.ContextVar` is copied into coroutines at creation time and is thread-safe. The design below exploits this.

---

## How sentry-sdk 2.27.0 Already Manages Scope Per Request

sentry-sdk's ASGI middleware (`sentry_sdk/integrations/asgi.py`, line 177) wraps every request in `with sentry_sdk.isolation_scope() as sentry_scope:`. This call internally uses `contextvars.ContextVar` (see `sentry_sdk/scope.py`, lines 102-106) to fork a new isolation scope per request. The fork is stored in a `ContextVar`, so it is automatically inherited by any coroutine or synchronous call that runs within that ASGI request context.

**Consequence:** When `sentry_sdk.get_isolation_scope()` is called from anywhere inside the request — including inside `pipeline_langgraph.py`, `chat_agent.py`, or a `@tool` function — it returns the same per-request forked scope. Tags set on it in middleware are visible everywhere in that request without any explicit passing.

This is the foundation the design builds on.

---

## Recommended Propagation Mechanism: Python contextvars

Use `contextvars.ContextVar` for `correlation_id`. Do not pass it through function parameters. Do not store it in `ChatState`.

**Rationale:**

Option (b) — explicit parameters — would require adding `correlation_id: str` to `chat_pipeline_streaming_agentic`, `ChatAgent.astream`, `ChatAgent.invoke`, every `_*_node` method, and every `@tool` function. That is 15+ function signatures changed for infrastructure plumbing that has nothing to do with business logic. It bleeds observability concerns into the domain model. It also fails at the `@tool` boundary: LangGraph's `ToolNode` calls `@tool` functions with only their declared Pydantic arguments. Injecting an extra `correlation_id` parameter would break tool invocation.

Option (c) — `ChatState` — has the same signature-pollution problem. `ChatState` is a domain-specific TypedDict; adding infrastructure fields couples observability to the agent protocol. It also does not help inside `@tool` functions, which receive only their declared args, not the full state.

Option (a) — `contextvars.ContextVar` — is the correct choice because:
1. It is async-safe: `asyncio` copies the current `Context` into every new task/coroutine. Any `async def` spawned during the request inherits the context automatically.
2. It is transparent to callers: no function signatures change.
3. It works across the sync/async boundary: Python's `contextvars` work in synchronous code too. When `_agent_node` calls `self.llm.invoke()` synchronously, the contextvar is still readable because we are still within the same thread and context.
4. It is the same mechanism sentry-sdk itself uses for per-request scope isolation.
5. Zero changes to `ChatState`, `@tool` signatures, or `ChatAgent` interface.

---

## Data Flow: correlation_id from HTTP Boundary to Deepest Log Call

```
HTTP Request arrives
    |
    v
[sentry ASGI middleware]
    sentry_sdk.isolation_scope() forks per-request Sentry scope into ContextVar
    |
    v
[CorrelationIdMiddleware]  (NEW: core/middleware.py)
    correlation_id = str(uuid4())
    _correlation_id_ctx.set(correlation_id)       # ContextVar write
    |
    v
[FastAPI @app.middleware("http") — catch_exceptions_mw]  (MODIFIED: main.py)
    (runs after CorrelationIdMiddleware; correlation_id already in context)
    |
    v
[api/chat.py — chat_pipeline_agentic_ep]  (MODIFIED)
    cid = get_correlation_id()               # ContextVar read
    scope = sentry_sdk.get_isolation_scope() # same per-request scope
    scope.set_tag("correlation_id", cid)
    scope.set_tag("session_id", session_id)
    scope.set_tag("user_id", user_id or "anonymous")
    scope.set_tag("endpoint", "/chat/stream/agentic")
    logger.info("...", extra={"correlation_id": cid, "session_id": session_id})
    |
    v
[core/pipeline_langgraph.py — chat_pipeline_streaming_agentic]  (MODIFIED)
    cid = get_correlation_id()               # ContextVar read — no parameter needed
    logger.info("...", extra={"correlation_id": cid})
    |
    v
[agents/core/chat_agent.py — _fiqh_classification_node / _agent_node / etc.]  (MODIFIED)
    cid = get_correlation_id()
    logger.info("...", extra={"correlation_id": cid})
    |
    v
[agents/tools/retrieval_tools.py — @tool functions]  (MODIFIED)
    cid = get_correlation_id()
    logger.warning("...", extra={"correlation_id": cid})
```

At every layer, the call is identical: `get_correlation_id()` reads the `ContextVar`. No arguments are threaded. The Sentry scope carries the same tags because it was set once in the route handler.

---

## New and Modified Files

### New Files

**`core/correlation.py`**
Single responsibility: define the `ContextVar` and the two accessor functions.

```python
import uuid
from contextvars import ContextVar
from typing import Optional

_correlation_id_ctx: ContextVar[Optional[str]] = ContextVar(
    "correlation_id", default=None
)

def set_correlation_id(value: str) -> None:
    _correlation_id_ctx.set(value)

def get_correlation_id() -> str:
    return _correlation_id_ctx.get() or "no-correlation-id"
```

No other module should touch `_correlation_id_ctx` directly — always go through these two functions.

**`core/middleware.py`**
FastAPI `BaseHTTPMiddleware` subclass that generates and sets the `correlation_id` for every request. Also sets Sentry context for the request-level scope.

```python
import uuid
import sentry_sdk
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from core.correlation import set_correlation_id, get_correlation_id

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        set_correlation_id(cid)
        # Tag the already-forked per-request Sentry isolation scope
        scope = sentry_sdk.get_isolation_scope()
        scope.set_tag("correlation_id", cid)
        scope.set_tag("http.path", request.url.path)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response
```

**Why `BaseHTTPMiddleware` and not `@app.middleware("http")`:**
`BaseHTTPMiddleware` runs before route handlers and before FastAPI's dependency injection. The sentry ASGI integration wraps the entire ASGI app, so by the time `CorrelationIdMiddleware.dispatch` runs, the Sentry per-request isolation scope is already in the context. This ordering is safe. `@app.middleware("http")` decorators run in reverse registration order; `BaseHTTPMiddleware` added via `app.add_middleware()` runs before all `@app.middleware("http")` decorators, which is what we want (correlation_id must be available when `catch_exceptions_mw` fires).

---

### Modified Files

**`main.py`**
- Register `CorrelationIdMiddleware` via `app.add_middleware(CorrelationIdMiddleware)` before the CORS middleware registration (so it runs in the outermost position after Sentry ASGI).
- Update `catch_exceptions_mw` to log via `logger.error` instead of `print`, including `correlation_id` in `extra={}`.

**`api/chat.py`**
- Import `get_correlation_id` from `core.correlation`.
- Import `sentry_sdk`.
- In `chat_pipeline_agentic_ep`: after extracting `user_id` and `session_id`, call `sentry_sdk.get_isolation_scope().set_tag(...)` for `session_id`, `user_id`, and `endpoint`. Log entry/error with `correlation_id` in `extra`.
- Replace `print("UNHANDLED ERROR ...")` and `traceback.print_exc()` with `logger.error(...)`.
- Apply same pattern to `chat_pipeline_stream_ep` and `chat_pipeline_agentic_non_stream_ep`.

**`api/reference.py`**, **`api/hikmah.py`**, **`api/primers.py`**
- Same treatment: replace `print` with `logger.*`; add Sentry scope tags; include `correlation_id` in `extra`.

**`core/pipeline_langgraph.py`**
- Import `logging` and `get_correlation_id`.
- Replace all `print(f"[AGENTIC PIPELINE] ...")` calls with `logger.info/warning/error(...)`.
- Add `correlation_id=get_correlation_id()` to every `extra={}` dict.
- No signature changes.

**`agents/core/chat_agent.py`**
- Import `logging` and `get_correlation_id`.
- Replace all `print(f"[FIQH CLASSIFICATION NODE] ...")`, `print(f"[AGENT NODE] ...")`, etc. with `logger.*`.
- Add `correlation_id=get_correlation_id()` to `extra={}` on every log call.
- No signature changes to `invoke`, `astream`, or any node method.

**`agents/tools/retrieval_tools.py`**
- Replace all `print(f"[retrieve_*_tool] Error: {e}")` with `logger.error(...)`.
- Add `correlation_id=get_correlation_id()` to `extra={}`.
- No change to `@tool` signatures.

**`agents/tools/classification_tools.py`**, **`agents/tools/enhancement_tools.py`**, **`agents/tools/translation_tools.py`**
- Same treatment: replace `print` with `logger.*`; add `correlation_id` to `extra`.

---

## Where sentry_sdk Scope Binding Happens

There are three layers of scope binding. Each serves a distinct purpose.

**Layer 1: Sentry ASGI integration (automatic, no code needed)**
`sentry_sdk.init(integrations=[FastApiIntegration()])` — which the `sentry-sdk[fastapi]` extra auto-configures — wraps the entire ASGI app. It forks a new isolation scope per request and attaches HTTP method, URL, and request headers. This happens before any application code runs. No action required.

**Layer 2: CorrelationIdMiddleware (NEW)**
After the Sentry isolation scope is forked, `CorrelationIdMiddleware.dispatch` calls `sentry_sdk.get_isolation_scope().set_tag(...)` to attach `correlation_id` and `http.path`. These tags appear on every Sentry event generated anywhere in the request, because they are on the isolation scope.

**Layer 3: Route handler (MODIFIED)**
In each route handler (e.g., `chat_pipeline_agentic_ep`), after extracting `session_id` and `user_id`, call:

```python
scope = sentry_sdk.get_isolation_scope()
scope.set_tag("session_id", session_id)
scope.set_tag("user_id", user_id or "anonymous")
scope.set_tag("endpoint", "/chat/stream/agentic")
```

This adds domain-level context that the middleware does not have (it runs before request body parsing and JWT extraction). Do not use `sentry_sdk.set_tag()` (top-level function) — that writes to the isolation scope of the current request anyway (see `sentry_sdk/api.py`, line 295: `return get_isolation_scope().set_tag(...)`), so either form works, but `get_isolation_scope().set_tag(...)` is more explicit about what it is doing.

Do not use `sentry_sdk.push_scope()` or `sentry_sdk.configure_scope()`. These are deprecated in sentry-sdk 2.x. `push_scope()` creates a nested current scope (not isolation scope) and is designed for temporary, locally-scoped overrides. For request-level context that should propagate to all events in a request, `get_isolation_scope().set_tag()` is the correct API.

---

## Async Boundary: Does contextvars Work Through LangGraph's astream?

Yes, with one caveat.

`ChatAgent.astream()` is called with `async for event in self.compiled_graph.astream(...)`. LangGraph's `compiled_graph.astream()` is an async generator. Python copies the current `Context` when a coroutine or async generator is started. The `_correlation_id_ctx` ContextVar set in the middleware is part of that context copy. So `get_correlation_id()` called inside `_fiqh_classification_node` (a regular sync function called from within an async context) reads the correct value.

The sync LLM calls inside async nodes (`self.llm.invoke(messages)`, `chain.stream(...)`) run on the same thread and within the same `Context` — they are blocking calls, not new threads or tasks. ContextVars are thread-local by design and do not move across threads. Since these blocking calls do not spawn new threads, they inherit the same context. ContextVar reads inside them return the correct `correlation_id`.

The only exception would be if LangGraph used `asyncio.run_in_executor()` to offload work to a `ThreadPoolExecutor`. LangGraph does not do this for node execution — nodes are called directly within the async event loop. This is confirmed by the existing code pattern: `_agent_node` is a synchronous method called from an async graph; the graph calls it via its internal node execution, not via `run_in_executor`. So no cross-thread context loss occurs.

The `fiqh_subgraph.invoke(...)` call inside `_call_fiqh_subgraph_node` is a blocking synchronous call to a LangGraph sub-graph. It runs on the same thread. ContextVar reads inside the sub-graph nodes also work correctly.

---

## Async Boundary: StreamingResponse and the response_generator AsyncGenerator

`chat_pipeline_streaming_agentic` returns a `StreamingResponse` wrapping `response_generator()`. `response_generator` is an `async def` generator. It is awaited by Starlette as a separate async iteration — but crucially, it is created within the scope of the route handler's `async def`, which means Python copies the current `Context` at creation time (when `response_generator()` is called, not when it is iterated). The `correlation_id` ContextVar is already set by the time the route handler runs, so the generator inherits it.

The `extra={"correlation_id": get_correlation_id()}` in `response_generator`'s log calls will resolve to the correct UUID for the lifetime of the streaming response.

---

## Logging Pattern for All Modified Call Sites

All logging in `api/`, `core/`, `agents/` should follow this pattern:

```python
import logging
from core.correlation import get_correlation_id

logger = logging.getLogger(__name__)

# In a function body:
logger.info(
    "Starting agentic pipeline",
    extra={
        "correlation_id": get_correlation_id(),
        "session_id": session_id,
    }
)

logger.error(
    "Pipeline error: %s",
    str(e),
    extra={"correlation_id": get_correlation_id()},
    exc_info=True,
)
```

The `ExtraFormatter` in `core/logging_config.py` already handles `extra` dict keys by appending them as `key=value` pairs to the log line. No changes to `ExtraFormatter` or `setup_logging` are needed.

Because `enable_logs=True` is set in `sentry_sdk.init()`, Sentry's logging integration captures `logger.error()` and `logger.warning()` calls as Sentry log events. The `correlation_id` from `extra={}` appears as a structured field on the Sentry event if the log handler is configured to forward it — but more importantly, the Sentry isolation scope tags (`correlation_id`, `session_id`) set at Layers 1-3 above are automatically attached to all Sentry events (including captured exceptions and log events) for the request.

---

## Build Order

The dependency graph requires this sequence:

**Step 1 — `core/correlation.py` (new file)**
No dependencies. Every subsequent step imports from it. Build first.

**Step 2 — `core/middleware.py` (new file)**
Depends on `core/correlation.py`. Does not depend on any route or pipeline code.

**Step 3 — `main.py` (register middleware)**
Depends on `core/middleware.py`. After this step, all requests have `correlation_id` set in ContextVar and Sentry scope.

**Step 4 — `api/chat.py`, `api/reference.py`, `api/hikmah.py`, `api/primers.py` (route layer)**
Depends on Step 1 (for `get_correlation_id`). Scope binding at the route layer requires Step 3 to be complete so that scope tags set here augment the already-tagged scope, rather than potentially racing with scope initialization.

**Step 5 — `core/pipeline_langgraph.py` (pipeline layer)**
Depends on Step 1. No structural changes; print-to-logger substitution only.

**Step 6 — `agents/core/chat_agent.py` (agent layer)**
Depends on Step 1. No structural changes; print-to-logger substitution only.

**Step 7 — `agents/tools/retrieval_tools.py` and other tool files (tool layer)**
Depends on Step 1. No structural changes; print-to-logger substitution only.

Steps 5-7 have no inter-dependencies and can be done in any order after Step 4.

---

## Integration Points Summary

| File | Change Type | What Changes | Risk |
|------|-------------|--------------|------|
| `core/correlation.py` | NEW | ContextVar definition, `get_correlation_id()`, `set_correlation_id()` | NONE |
| `core/middleware.py` | NEW | `CorrelationIdMiddleware` — generates UUID, sets ContextVar, tags Sentry scope | LOW |
| `main.py` | MODIFIED | Register `CorrelationIdMiddleware`; update `catch_exceptions_mw` to use logger | LOW |
| `api/chat.py` | MODIFIED | Add Sentry scope tags per route; replace `print`/`traceback.print_exc` with `logger.*` | LOW |
| `api/reference.py` | MODIFIED | Same pattern | LOW |
| `api/hikmah.py` | MODIFIED | Same pattern | LOW |
| `api/primers.py` | MODIFIED | Same pattern | LOW |
| `core/pipeline_langgraph.py` | MODIFIED | Replace `print` with `logger.*`; add `correlation_id` to `extra={}` | LOW |
| `agents/core/chat_agent.py` | MODIFIED | Replace `print` with `logger.*`; add `correlation_id` to `extra={}` | LOW |
| `agents/tools/retrieval_tools.py` | MODIFIED | Replace `print` with `logger.error`; add `correlation_id` to `extra={}` | LOW |
| `agents/tools/classification_tools.py` | MODIFIED | Same pattern | LOW |
| `agents/tools/enhancement_tools.py` | MODIFIED | Same pattern | LOW |
| `agents/tools/translation_tools.py` | MODIFIED | Same pattern | LOW |

**No changes to:**
- `agents/state/chat_state.py` — `ChatState` is not modified
- `agents/config/agent_config.py` — no observability fields added
- `core/logging_config.py` — `ExtraFormatter` already handles `extra` keys correctly
- Any `@tool` function signatures — ContextVar reads happen inside tool body, not in signature

---

## What Does NOT Change

- `ChatState` TypedDict — no new fields
- `@tool` function signatures — LangGraph's ToolNode invokes tools with their declared Pydantic args only; adding a `correlation_id` parameter would break tool invocation
- `ChatAgent.astream` / `ChatAgent.invoke` signatures — no new parameters
- `chat_pipeline_streaming_agentic` signature — no new parameters
- Any LangGraph graph topology
- SSE event protocol

---

## Sources

- `sentry_sdk/integrations/asgi.py` line 177 — `isolation_scope()` called per request (verified in installed package)
- `sentry_sdk/scope.py` lines 102-106 — `_isolation_scope` and `_current_scope` are `ContextVar` instances (verified in installed package)
- `sentry_sdk/api.py` lines 295, 301, 307, 313, 319 — `set_tag`, `set_context`, etc. delegate to `get_isolation_scope()` (verified in installed package)
- Python docs — `contextvars.ContextVar` is copied into coroutines at creation; thread-local for synchronous code
- `agents/core/chat_agent.py` — node methods are synchronous callables invoked within LangGraph's async executor; no `run_in_executor` used (verified in repo source)
- `core/logging_config.py` — `ExtraFormatter` strips `_RESERVED` keys and appends remaining `extra` keys as `key=value` (verified in repo source)
