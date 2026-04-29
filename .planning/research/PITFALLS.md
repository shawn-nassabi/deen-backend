# Pitfalls Research: v1.3 Sentry Deep Integration

**Project:** Deen Backend — v1.3 Sentry Deep Integration
**Researched:** 2026-04-26
**Scope:** Adding structured Sentry logging with correlation_id, SENTRY_ENABLED gate, Sentry scope binding per request, and converting print() to logger.* across 4 files in an existing FastAPI + LangGraph + SSE streaming system
**Confidence:** HIGH (code inspection + sentry-sdk changelog + official Sentry docs + GitHub issues)

---

## Critical Pitfalls

Mistakes that cause incorrect behavior, data leaks, or silent failures at production time.

---

### CRITICAL-1: `_experiments.enable_logs` will become a deprecation warning in sentry-sdk >=2.35.0

**What goes wrong:**
The current `main.py` initializes Sentry with:
```python
sentry_sdk.init(
    dsn=SENTRY_DSN,
    send_default_pii=True,
    _experiments={"enable_logs": True},
)
```
In sentry-sdk 2.27.0 (pinned in `requirements.txt`), placing `enable_logs` inside `_experiments` is the correct location — the option was still experimental. However, `enable_logs` was promoted to a stable top-level option in sentry-sdk 2.35.0 and using `_experiments` for it now emits a `DeprecationWarning`. In a future major version, `_experiments.enable_logs` will be removed entirely.

**Consequence at current version (2.27.0):**
The `_experiments` form works correctly at 2.27.0. No immediate breakage. The pitfall is version drift: if `requirements.txt` is bumped past 2.35.0 without updating the init call, logs will continue to function but with deprecation noise in stderr, and eventually stop working when the experimental API is removed.

**Prevention:**
- At 2.27.0, leave `_experiments={"enable_logs": True}` as-is — it is the correct form for this version.
- Add a comment in `main.py` at the `_experiments` call: `# TODO: move to top-level enable_logs=True when sentry-sdk >= 2.35.0`.
- When bumping sentry-sdk past 2.35.0 in a future PR, migrate to `sentry_sdk.init(dsn=..., enable_logs=True)`.
- Do NOT proactively move it to top-level now — that will break at 2.27.0 where `enable_logs` is not a recognized top-level kwarg.

**Confidence:** HIGH — confirmed via sentry-sdk changelog and PyPI release notes.

---

### CRITICAL-2: Dual capture — INFO logs become both Sentry log entries AND breadcrumbs when `enable_logs=True`

**What goes wrong:**
With `enable_logs=True` active, any `logger.info(...)` call is captured by the Sentry logging integration via three separate handlers:
- `BreadcrumbHandler` — attaches the log as a breadcrumb on the current request event (INFO+ threshold, default behavior)
- `SentryLogsHandler` — sends the log as a discrete Sentry Log entry counted against the logs quota

This means converting the `print()` calls in `core/pipeline_langgraph.py` (which fires for every SSE chunk iteration) and `agents/tools/retrieval_tools.py` to `logger.info(...)` will double-count: every INFO log entry is both a breadcrumb and a billable Sentry log item. High-volume INFO logs (e.g., `[AGENTIC PIPELINE] Node: agent` emitted on each graph node traversal — 5-8 times per request) will rapidly consume the 5GB logs quota included in Sentry plans.

**The specific hot paths in this codebase:**
- `core/pipeline_langgraph.py` line 91: `print(f"[AGENTIC PIPELINE] Starting for query: {user_query[:100]}")` — once per request, acceptable.
- `core/pipeline_langgraph.py` line 123: `print(f"[AGENTIC PIPELINE] Node: {node_name}")` — fires 5-8 times per request for every LangGraph node traversal. Converting this to `logger.info()` means 5-8 Sentry log entries per chat request.
- Tool error `print()` calls in `retrieval_tools.py` — these are exception paths, appropriate for `logger.warning()` or `logger.error()`, not `logger.info()`.

**Prevention:**
- Reserve `logger.info()` for request-level events: request start, request end, early exits. NOT for per-node LangGraph traversal.
- Convert the node traversal print to `logger.debug()` — debug level is NOT captured by Sentry's logging integration (threshold is INFO by default), so it logs locally but does not create Sentry entries.
- Add a `before_send_log` hook (available as stable in sentry-sdk 2.35.0, experimental earlier) or configure `LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR)` to raise the Sentry capture threshold above INFO.
- Rule: Sentry logs should answer "did this request succeed and why not?" — not "what did every node do?".

**Confidence:** HIGH — confirmed from Sentry logs billing docs and logging integration source.

---

### CRITICAL-3: `send_default_pii=True` in production sends full request bodies — user queries are PII

**What goes wrong:**
`main.py` currently initializes with `send_default_pii=True`. This flag instructs the Sentry FastAPI/Starlette integration to capture:
- The full HTTP request body (which for `/chat/stream/agentic` includes `user_query`, `session_id`, `target_language`, and the `config` object)
- User IP addresses
- Authentication headers (the Supabase JWT Bearer token)

For this application, `user_query` contains the user's Islamic religious questions. Under GDPR Article 9, religious beliefs and practices are **special category personal data** with stricter processing requirements. Sending these queries to a third-party service (Sentry's US-hosted infrastructure) without explicit user consent for that specific processing purpose creates a GDPR compliance risk.

Additionally, if a user asks a sensitive fiqh question about personal religious matters (inheritance, purity, personal circumstances), that exact text will appear in Sentry event payloads, Sentry issue titles, and Sentry log entries — visible to all Sentry project members.

**Prevention:**
1. Remove `send_default_pii=True` from `sentry_sdk.init()` for the default path. The FastAPI integration will then omit IP addresses, auth headers, and full request bodies.
2. Add a `before_send` hook that explicitly truncates or omits `user_query` from the event body:
   ```python
   def scrub_pii(event, hint):
       # Remove user query from request body in Sentry events
       req = event.get("request", {})
       body = req.get("data", {})
       if isinstance(body, dict) and "user_query" in body:
           body["user_query"] = "[REDACTED]"
       return event
   ```
3. If correlation_id and session_id are attached to scope as tags (acceptable — they are pseudonymous identifiers, not PII), ensure `user_id` (the actual Supabase user UUID) is treated carefully: set it on the Sentry user context as `id` only, never `email` or `username`.
4. Do not log `user_query` content in any `logger.info()` call that would flow to Sentry. Log only a truncated hash or the first 20 characters max if needed for debugging.

**Confidence:** HIGH — `send_default_pii` behavior confirmed from official Sentry docs; GDPR Article 9 classification of religious data is established law.

---

### CRITICAL-4: Exceptions inside `response_generator()` async generator are NOT captured by the global catch-all middleware

**What goes wrong:**
`main.py` has a catch-all middleware:
```python
@app.middleware("http")
async def catch_exceptions_mw(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return JSONResponse(status_code=500, ...)
```

The `/chat/stream/agentic` route returns a `StreamingResponse`. FastAPI's `call_next` returns the `StreamingResponse` object immediately — **before** the `response_generator()` async generator runs. The middleware's `try/except` exits successfully when the `StreamingResponse` is constructed. The actual generator body runs later, when the client reads bytes from the stream, outside the middleware's exception scope.

An exception thrown inside `response_generator()` — after the middleware has already returned — is NOT caught by `catch_exceptions_mw`. The existing Sentry `capture_exception(e)` call in the middleware never fires for SSE generator errors.

This is confirmed: the existing `core/pipeline_langgraph.py` already has an explicit `except Exception` block inside `response_generator()` that calls `print(f"[AGENTIC PIPELINE] Error: {e}")`. That print-based approach was the only capture mechanism before Sentry was added.

**Current state after `fb7286d` commit:** The commit message says "explicitly capture exceptions swallowed by catch_exceptions_mw" — implying an explicit `sentry_sdk.capture_exception(e)` was likely added inside the `except` block in `response_generator()`. Verify this is present.

**Prevention:**
- The existing `except Exception` block in `response_generator()` (lines 375-391 of `pipeline_langgraph.py`) must call `sentry_sdk.capture_exception(e)` explicitly. Do not rely on the middleware for SSE exceptions.
- When converting `print(f"[AGENTIC PIPELINE] Error: {e}")` to `logger.error(...)`, confirm that the `logger.error()` call with `exc_info=True` will correctly propagate the error to Sentry via the logging integration OR add an explicit `sentry_sdk.capture_exception()` alongside it. Using `logger.error("msg", exc_info=True)` with the Sentry logging integration active WILL create a Sentry error event — but only if `event_level=logging.ERROR` (the default). Confirm this is not overridden by a custom `LoggingIntegration` configuration.
- Apply the same pattern to the inner `except Exception as memory_exc` at line 388 — this exception is currently only printed and not captured.

**Confidence:** HIGH — FastAPI StreamingResponse lifecycle is well-documented; the middleware scope vs. generator execution timing is confirmed behavior.

---

## High Pitfalls

Mistakes that cause subtle incorrect behavior or data quality problems.

---

### HIGH-1: ContextVar correlation_id is NOT automatically propagated into sync LangGraph nodes that run in a thread executor

**What goes wrong:**
Python's `contextvars.ContextVar` propagates automatically across `await` chains within the same async context. However, `asyncio.to_thread()` and `loop.run_in_executor()` do copy the context (as of Python 3.7), so a value set before the `await asyncio.to_thread(...)` call IS visible in the thread.

The specific risk in this codebase is `chain.stream()` calls (synchronous LLM streaming) that run inside the `async def response_generator()`. These are NOT dispatched to a thread executor — they run synchronously, blocking the event loop inline. The ContextVar IS available for inline sync calls because they run in the same OS thread as the coroutine.

However, LangGraph itself may dispatch sync node functions to a thread pool internally when running via `compiled_graph.astream()`. If a LangGraph node function (e.g., a tool in `agents/tools/`) runs in a thread spawned by LangGraph's internal executor, and you try to read `correlation_id_var.get()` inside that tool function, it will return `None` rather than the request-scoped value — even though the ContextVar was set correctly in the middleware.

**Why this matters:**
If the correlation_id middleware sets `correlation_id_var.set(new_uuid)` at request entry and you then call `logger.info(f"[{correlation_id_var.get()}] Retrieved docs")` inside `retrieve_shia_documents_tool()`, you may get `None` or a stale value depending on whether LangGraph dispatched that node to a new thread.

**Prevention:**
- Do not rely on ContextVar reads inside `agents/tools/` functions for correlation_id. Instead, thread correlation_id through explicit function arguments or through LangGraph's `ChatState` dict (add a `correlation_id` field to `ChatState`).
- If ContextVar-based propagation is required, use `contextvars.copy_context().run(fn)` when dispatching to threads manually. For LangGraph-internal thread dispatch, the safest pattern is to pass correlation_id as part of the state that LangGraph carries natively.
- For the middleware and route handler level (where the ContextVar IS reliably set), ContextVar reads are safe.
- For `core/pipeline_langgraph.py`'s `response_generator()` function itself (async generator, not in a thread), ContextVar reads are safe.

**Confidence:** MEDIUM — Python's context propagation to `asyncio.to_thread` is documented. LangGraph's internal thread dispatch behavior is less documented; confirmed by community issues showing context leaks in nested graph invocations.

---

### HIGH-2: Sentry scope tags set with `sentry_sdk.set_tag()` in async middleware leak across concurrent requests

**What goes wrong:**
When adding Sentry scope binding in a middleware (e.g., `sentry_sdk.set_tag("correlation_id", cid)`), the behavior depends on which scope the tag is written to. The Sentry Python SDK uses three scope layers:
- **Global scope**: Shared across all requests — modifications here leak everywhere.
- **Isolation scope**: Per-request, created by the FastAPI/Starlette integration automatically.
- **Current scope**: Per-span/per-operation.

Calling `sentry_sdk.set_tag(...)` at the top-level API writes to the **current scope**, which in an async ASGI application may be shared between concurrent requests if you call it outside of a properly isolated context.

The FastAPI integration (included via `sentry-sdk[fastapi]`) creates one isolation scope per HTTP request when the middleware is active. BUT if your custom correlation_id middleware calls `sentry_sdk.set_tag()` before the FastAPI integration's own scope setup completes, you may be writing to the wrong scope layer.

**The `new_scope` context manager (2.x recommended pattern):**
```python
with sentry_sdk.new_scope() as scope:
    scope.set_tag("correlation_id", cid)
    scope.set_tag("session_id", session_id)
    response = await call_next(request)
```
This forks the current scope for the duration of the block, ensuring tags do not bleed into other requests. However, `new_scope` only covers code within the `with` block — if you yield to an async generator (like `StreamingResponse`), the scope exits before the generator runs.

**The correct pattern for SSE streaming with Sentry scope:**
Use `sentry_sdk.get_isolation_scope()` (stable in sentry-sdk 2.x) to write to the per-request isolation scope that the FastAPI integration already created:
```python
scope = sentry_sdk.get_isolation_scope()
scope.set_tag("correlation_id", cid)
scope.set_user({"id": user_id})
```
This is safe because the isolation scope is tied to the ASGI request lifecycle, not just a context manager block, and persists through the async generator's execution.

**Prevention:**
- Use `sentry_sdk.get_isolation_scope().set_tag(...)` and `.set_user(...)` in the correlation_id middleware and route handlers.
- Never use bare `sentry_sdk.set_tag()` in async code paths that handle concurrent requests.
- Do not use the deprecated `configure_scope()` context manager (removed in sentry-sdk 2.x).

**Confidence:** HIGH — confirmed from sentry-sdk 2.x migration guide and scope architecture documentation.

---

### HIGH-3: `logger.error()` inside the `except` block AND `sentry_sdk.capture_exception()` in the same block creates duplicate Sentry error events

**What goes wrong:**
When `enable_logs=True` and the Sentry logging integration is active, calling `logger.error("msg", exc_info=True)` inside an `except` block creates a **Sentry error event** (because `event_level=logging.ERROR` is the default threshold for creating events, not just log entries). If you then also call `sentry_sdk.capture_exception(e)` in the same `except` block, the error is sent to Sentry twice — consuming two error events against your quota.

This is a documented known issue (sentry-python issue #1468): when `logging.exception()` is called before `sentry_sdk.capture_exception()` in the same except block, the second call is silently ignored in some versions. In other configurations, both fire.

**The existing `catch_exceptions_mw` is already vulnerable:**
```python
except Exception as e:
    print("\n===== SERVER EXCEPTION =====\n", tb, "\n============================\n")
    sentry_sdk.capture_exception(e)  # explicit capture
    return JSONResponse(...)
```
If this `print()` is converted to `logger.error(..., exc_info=True)`, and the logging integration creates an error event, the explicit `sentry_sdk.capture_exception(e)` may duplicate it.

**Prevention:**
- In `catch_exceptions_mw`: convert `print()` to `logger.error()` but WITHOUT `exc_info=True`, and keep the explicit `sentry_sdk.capture_exception(e)`. The logger call provides the breadcrumb trail; `capture_exception` provides the event. This avoids duplication.
- In `response_generator()`'s `except` block: use `logger.error("Pipeline error: %s", e)` (no `exc_info`) + `sentry_sdk.capture_exception(e)` explicitly — consistent pattern.
- Alternatively, use ONLY `logger.error("msg", exc_info=True)` and REMOVE explicit `capture_exception()` calls, relying on the logging integration to create events. But not both.
- Pick one pattern and apply it consistently across all exception handlers.

**Confidence:** HIGH — confirmed from sentry-python issue #1468 and logging integration documentation.

---

### HIGH-4: SENTRY_ENABLED env var gate vs. SENTRY_DSN absence — two different gate mechanisms create confusion

**What goes wrong:**
The current `main.py` already uses `SENTRY_DSN` as the gate:
```python
if SENTRY_DSN:
    sentry_sdk.init(...)
```
The v1.3 plan adds a separate `SENTRY_ENABLED` env var as an explicit opt-in. Having two mechanisms (`SENTRY_DSN` presence AND `SENTRY_ENABLED=true`) creates ambiguity:
- What if `SENTRY_DSN` is set in `.env` but `SENTRY_ENABLED=false`? Should Sentry be active?
- What if `SENTRY_ENABLED=true` but `SENTRY_DSN` is absent? Silent failure or loud error?
- In Docker Compose, a variable may be set to an empty string vs. unset — both evaluate differently.

The more dangerous failure mode: a developer sets `SENTRY_DSN` in their local `.env` for testing but forgets to set `SENTRY_ENABLED=false`, causing local development queries (including test queries with real user data patterns) to be sent to the production Sentry project.

**Prevention:**
- Collapse to a single gate: `SENTRY_ENABLED=true` is required AND `SENTRY_DSN` must be set. If either is absent, Sentry does not initialize.
- Explicitly require `SENTRY_ENABLED=true` (not just truthy `SENTRY_DSN`) so the behavior is opt-in and obvious.
- Add a startup log: `logger.info("Sentry initialized for environment: %s", ENV)` when Sentry is active, and `logger.info("Sentry disabled (SENTRY_ENABLED not set)")` when it is not.
- Add `SENTRY_ENABLED=false` as the default in `.env.example` to protect local development.

**Confidence:** HIGH — derived from code inspection of `main.py` and `core/config.py`.

---

## Moderate Pitfalls

Mistakes that degrade observability quality or create operational friction.

---

### MODERATE-1: Converting `print()` in tool `except` blocks to `logger.info()` silently swallows error context

**What goes wrong:**
`agents/tools/retrieval_tools.py` uses this pattern in every tool's except block:
```python
except Exception as e:
    print(f"[retrieve_shia_documents_tool] Error: {e}")
    return {"documents": [], "count": 0, "error": str(e)}
```

Tool errors are intentionally non-fatal: the graph continues running and the tool returns an error dict. This is by design — LangGraph tools should not raise. The risk when converting to `logger.*` is choosing the wrong level:

- `logger.info(f"Tool error: {e}")` — error is captured as a Sentry log entry at INFO level, but does NOT create a Sentry error event. A tool failing silently is difficult to detect in Sentry.
- `logger.error(f"Tool error: {e}")` — creates a Sentry error event. But if retrieval tools fail on every request due to a Pinecone outage, this spams the Sentry error quota.
- `logger.warning(f"Tool error: {e}")` — creates a Sentry breadcrumb and (with `enable_logs=True`) a log entry, but not an error event. Most appropriate for recoverable tool failures.

**Prevention:**
- Use `logger.warning("retrieve_shia_documents_tool error: %s", e)` for recoverable tool failures (Pinecone timeout, empty result). This avoids creating Sentry error events for expected transient failures.
- Use `logger.error("retrieve_shia_documents_tool unexpected error: %s", e, exc_info=True)` only for truly unexpected errors (e.g., import errors, type errors) — and pair with explicit `sentry_sdk.capture_exception(e)`.
- Add a `retrieval_error` tag to the Sentry scope when a tool fails, so errors are filterable: `sentry_sdk.get_isolation_scope().set_tag("retrieval_failed", "true")`.

**Confidence:** HIGH — derived from code inspection of all tool error paths.

---

### MODERATE-2: Correlation_id set in middleware is not visible in LangGraph sub-graph invocations

**What goes wrong:**
The FAIR-RAG fiqh sub-graph (`agents/fiqh/fiqh_graph.py`) is invoked as `fiqh_subgraph.invoke(fiqh_state)` inside the main LangGraph agent. When the sub-graph runs, it creates its own execution context. Any logs emitted inside fiqh sub-graph nodes (e.g., `fiqh_decompose`, `fiqh_retrieve`, `fiqh_assess`) will not carry the correlation_id from the parent request's ContextVar if those nodes run in a different thread context.

This means: for fiqh requests (the most complex and error-prone path), the correlation_id that links all log entries across the request may be absent from the most important diagnostic logs.

**Prevention:**
- Pass `correlation_id` as a field in `FiqhState` (add it to the TypedDict) so it is threaded explicitly through sub-graph nodes.
- In fiqh sub-graph node functions, read `state["correlation_id"]` and include it as a `extra` kwarg in logger calls: `logger.info("...", extra={"correlation_id": state["correlation_id"]})`.
- The `ExtraFormatter` in `core/logging_config.py` already appends extra dict keys as `key=value` pairs to log messages — this pattern works with the existing formatter.

**Confidence:** MEDIUM — based on LangGraph context isolation behavior and code inspection of FiqhState structure.

---

### MODERATE-3: `ExtraFormatter` in `core/logging_config.py` exposes ALL extra dict keys — easy to accidentally log PII

**What goes wrong:**
`core/logging_config.py`'s `ExtraFormatter.format()` appends every key from `record.__dict__` that is not in `_RESERVED` to the log line as `key=value`. This means any `extra={"user_query": "..."}` kwarg passed to a logger call will appear verbatim in the formatted log output — and, if Sentry is active, in Sentry log entries.

The danger: a developer adding a log statement for debugging adds `extra={"query": user_query}` to get richer context locally. This goes to production, logs full user queries to Sentry, and violates PII handling rules.

**Prevention:**
- Establish a policy: `extra` dict keys that may contain user-generated content must be truncated or hashed before logging. Example: `extra={"query_preview": user_query[:30]}` rather than the full query.
- Document the allowed set of `extra` fields in a comment near `ExtraFormatter` — e.g., `correlation_id`, `session_id`, `endpoint`, `user_id` (UUID only), `duration_ms`, `doc_count`, `tool_name`. Flag anything with free-form text as PII risk.
- Consider overriding `ExtraFormatter` to apply a denylist of field names that are scrubbed before formatting: `if k in {"query", "user_query", "message_content"}: v = "[REDACTED]"`.

**Confidence:** HIGH — derived from `ExtraFormatter` code inspection.

---

### MODERATE-4: Per-node LangGraph status prints are high-cardinality — converting to INFO creates quota pressure

**What goes wrong:**
`core/pipeline_langgraph.py` line 123:
```python
print(f"[AGENTIC PIPELINE] Node: {node_name}")
```
This fires for every LangGraph node traversal. A typical non-fiqh request traverses: `fiqh_classification` → `agent` → `tools` → `agent` (possibly twice) → `generate_response` → `check_early_exit` = 6 nodes. A fiqh request adds `fiqh_subgraph` with its internal nodes. That is 6-10 log entries per request at INFO level, directly to Sentry.

At 1,000 daily active users × 5 requests each × 7 nodes = 35,000 INFO log entries per day. The free Sentry tier includes 5GB of logs, but at scale this will trigger quota alerts and PAYG overages.

**Prevention:**
- Convert node traversal logging to `logger.debug()`, not `logger.info()`. Debug is below the Sentry logging integration's default threshold (INFO) and will NOT be sent to Sentry — but still appears in local terminal output.
- Only log meaningful state transitions at INFO: request start, early exit triggered, fiqh path selected, final response generated, error encountered.
- The `[AGENTIC PIPELINE] Starting for query:` print (line 91) is appropriate at INFO — once per request, actionable.

**Confidence:** HIGH — derived from code inspection and Sentry quota documentation.

---

## Minor Pitfalls

Low severity but worth avoiding to prevent confusion or tech debt.

---

### MINOR-1: `sentry_sdk.init()` must execute before any logger is constructed that will send to Sentry

**What goes wrong:**
`main.py` calls `sentry_sdk.init()` near the top of the file, but other modules (e.g., `core/logging_config.py`) may be imported before `sentry_sdk.init()` runs if those modules are referenced at module import time in `main.py`. The Sentry logging integration patches the `logging.Logger` class at init time. Any logger constructed before `init()` runs may not have the Sentry handler attached.

In practice, `core/logging_config.py` is only called via `setup_logging()` (called explicitly from route handlers or on first use), so this is not currently a problem. But if `setup_logging()` is ever moved to module-level (e.g., `setup_logging()` at the top of `core/logging_config.py`), loggers created before `sentry_sdk.init()` will not send to Sentry.

**Prevention:**
- Keep `sentry_sdk.init()` as the first non-import statement in `main.py` — before any route module imports.
- The current `main.py` structure already does this correctly. Preserve this ordering in all future changes.

**Confidence:** MEDIUM — based on sentry-sdk documentation about integration registration timing.

---

### MINOR-2: `logger.warning()` on tool errors creates Sentry log entries even when Sentry disabled — no-op overhead

**What goes wrong:**
When `SENTRY_ENABLED=false` (local dev), calling `logger.warning(...)` still invokes the Python logging framework, which if `setup_logging()` has been called, iterates over handlers. Since `sentry_sdk.init()` was not called, the Sentry logging integration handler is not attached — so no Sentry event is created. This is harmless.

However, if a developer accidentally installs `sentry-sdk` and calls `sentry_sdk.init()` with a test DSN in their local `.env`, all tool error warnings will go to Sentry even in "dev mode". This conflates local testing noise with production signal.

**Prevention:**
- The `SENTRY_ENABLED` guard in `main.py` must be evaluated before `sentry_sdk.init()` is called, not just before DSN usage. Current code gates on `if SENTRY_DSN:` — sufficient if the developer's local `.env` does not have `SENTRY_DSN`.
- Add `SENTRY_DSN=` (empty) to `.env.example` with a comment: "Leave empty for local development — Sentry disabled when blank".

**Confidence:** MEDIUM — operational hygiene rather than a technical bug.

---

### MINOR-3: `ExtraFormatter` colorization in logs conflicts with JSON log parsers in production

**What goes wrong:**
`core/logging_config.py`'s `ExtraFormatter` prepends ANSI escape codes (`\033[92m`, `\033[93m`, etc.) to the log level name. This makes local terminal output readable but breaks structured log parsers in production (e.g., Datadog, CloudWatch Logs Insights, any grep-based log query) because the level field contains `\033[92mINFO\033[0m` rather than `INFO`.

When Sentry's logging integration reads the log record, it reads `record.levelname` after `ExtraFormatter.format()` has been called — meaning Sentry receives the colorized string as the log level, not the plain level name. This corrupts Sentry log level filtering.

**What to check:** In `ExtraFormatter.format()`, the colorization modifies `record.levelname` in place (`record.levelname = f"{color}{level}{reset}"`). The Sentry logging integration reads `record.levelname` after the formatter runs. Confirm whether Sentry uses `record.levelno` (the integer, unaffected) or `record.levelname` (the string, corrupted) for level filtering.

**Prevention:**
- Restore `record.levelname` after formatting: save the original level before colorizing, colorize for the display string, then restore: `record.levelname = level` before returning.
- Alternatively, only colorize the output string, not the record field: format the base string first, then return `f"{color}{base}{reset}"` without touching `record.levelname`.
- Add a `ENV=production` guard: skip colorization when not in a TTY or when `ENV != "development"`.

**Confidence:** MEDIUM — based on code inspection of `ExtraFormatter`; Sentry's exact field usage in the logging handler requires verification.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| SENTRY_ENABLED gate | Two-gate confusion (SENTRY_DSN vs. SENTRY_ENABLED) | Collapse to single AND-gate; document clearly in `.env.example` |
| Correlation_id middleware | Scope pollution across concurrent async requests | Use `get_isolation_scope()` not bare `set_tag()` |
| Sentry scope binding (session_id, user_id) | `send_default_pii=True` leaks full request bodies | Remove `send_default_pii=True`; add `before_send` scrubber |
| print() → logger.* in `pipeline_langgraph.py` | Node traversal prints at INFO create quota pressure | Use `logger.debug()` for per-node traversal; INFO only for request-level events |
| print() → logger.* in `retrieval_tools.py` | Tool errors at INFO don't create Sentry events; tool errors at ERROR spam quota | Use `logger.warning()` for recoverable tool errors |
| print() → logger.* in exception handlers | Double-capture: logger.error(exc_info=True) + capture_exception() duplicates events | Pick one pattern; do not use both in the same except block |
| `_experiments.enable_logs` at 2.27.0 | It is correct at this version; do NOT move to top-level yet | Add TODO comment for migration when sdk is bumped past 2.35.0 |
| Fiqh sub-graph logging | ContextVar correlation_id not propagated into sub-graph threads | Thread correlation_id through FiqhState explicitly |
| `ExtraFormatter` colorization | ANSI codes corrupt Sentry log level field | Restore `record.levelname` after formatting; skip colorization in production |

---

## Sources

- [sentry-sdk Python — Set Up Logs](https://docs.sentry.io/platforms/python/logs/) — enable_logs stable API in 2.35.0
- [sentry-sdk Logging Integration](https://docs.sentry.io/platforms/python/integrations/logging/) — BreadcrumbHandler + SentryLogsHandler dual capture
- [Manage Your Logs Quota](https://docs.sentry.io/pricing/quotas/manage-logs-quota/) — log_item data category, quota billing
- [Scrubbing Sensitive Data — Python](https://docs.sentry.io/platforms/python/data-management/sensitive-data/) — before_send, send_default_pii, PII scrubbing
- [Data Collected — FastAPI](https://docs.sentry.io/platforms/python/guides/fastapi/data-collected/) — what send_default_pii=True captures
- [Scopes and Hubs for FastAPI](https://docs.sentry.io/platforms/python/guides/fastapi/enriching-events/scopes/) — get_isolation_scope(), isolation scope per request
- [Sentry Python Scopes — async safety](https://github.com/getsentry/sentry-python/issues/147) — historical async scope issue, contextvars resolution
- [sentry-python Issue #1468 — duplicate capture from logger + capture_exception](https://github.com/getsentry/sentry-python/issues/1468)
- [sentry-python Issue #2328 — asyncio integration and init() timing](https://github.com/getsentry/sentry-python/issues/2328)
- [Migrate 1.x to 2.x — configure_scope deprecated](https://docs.sentry.io/platforms/python/migration/1.x-to-2.x)
- [LangGraph context streaming leaks across nested graphs — issue #4826](https://github.com/langchain-ai/langgraph/issues/4826)
- [Python contextvars — asyncio task context copying](https://docs.python.org/3/library/contextvars.html)
- [send_default_pii docs discussion](https://github.com/getsentry/sentry-docs/issues/1240)
- [sentry-sdk CHANGELOG.md](https://github.com/getsentry/sentry-python/blob/master/CHANGELOG.md) — 2.27.0 vs 2.35.0 enable_logs promotion
