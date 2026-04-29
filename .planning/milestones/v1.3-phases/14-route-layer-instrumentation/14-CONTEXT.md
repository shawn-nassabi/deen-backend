# Phase 14: Route Layer Instrumentation - Context

**Gathered:** 2026-04-26
**Status:** Ready for planning

<domain>
## Phase Boundary

All four main API route handlers (`api/chat.py`, `api/reference.py`, `api/hikmah.py`, `api/primers.py`) emit structured INFO/WARNING/ERROR logs with `correlation_id` in every `extra={}` call. The 500-leaking data bug in `/references` is fixed. All `print()` calls across all four files are replaced with `logger.*`. This phase wires the Phase 13 infrastructure (ContextVar, `bind_sentry_scope`) into the route layer — no pipeline or tool changes (Phase 15), no fiqh sub-graph changes (Phase 16).

**Scope:** `api/chat.py`, `api/reference.py`, `api/hikmah.py`, `api/primers.py` only.

</domain>

<decisions>
## Implementation Decisions

### Streaming completion log (/chat/stream/agentic)

- **D-01:** Log "request accepted, returning stream" INFO at the outer handler's return point — when the `StreamingResponse` is assembled and about to be returned. The outer handler completing setup successfully is the "completion" event for observability purposes.
- **D-02:** Both `/chat/stream/agentic` (streaming) and `/chat/agentic` (non-streaming) use the same log field set at start and completion: `correlation_id`, `session_id`, `endpoint`, `user_id`. No additional fields differ between the two endpoints at completion.

### Sentry scope binding

- **D-03:** `bind_sentry_scope()` is called in **all four** route files — `api/chat.py`, `api/reference.py`, `api/hikmah.py`, `api/primers.py`. Not just chat.py. Every endpoint gets Sentry scope set for consistent observability.
- **D-04:** In the agentic endpoint, `bind_sentry_scope()` is called **after** JWT extraction so `user_id` can be included. Aligns with Phase 13 D-07 intent. (Errors before JWT extraction won't have full scope — accepted tradeoff for cleaner single call.)

### Log field design

- **D-05:** Request start log includes: `correlation_id`, `session_id`, `endpoint`, `user_id`, `query_length`. `query_length` gives query size context without leaking the query text itself — safe for Sentry Logs. `user_id` is `None` for unauthenticated requests.
- **D-06:** Completion log includes: `correlation_id`, `session_id`, `endpoint`, `user_id`. No `latency_ms` — timing can be derived from Sentry or middleware if needed. Keeps completion log consistent with start log fields.
- **D-07:** For `api/hikmah.py` and `api/primers.py`: add `correlation_id` to every existing `extra={}` call. Keep existing domain fields (`lesson_id`, `user_id`, etc.) in place — do not restructure what's already there, only inject `correlation_id`.

### print() replacement

- **D-08:** All `print()` and `traceback.print_exc()` calls replaced with `logger.*`. Use `logger.error("message", exc_info=True)` (not `logger.exception()`) for consistency with Phase 13 D-10 pattern. Remove `import traceback` once all uses are eliminated.
- **D-09:** Config parse errors in `api/chat.py` (currently `print(f"[AGENTIC ENDPOINT] Config parse error: {e}")`) are logged at WARNING — not ERROR. Aligns with CHAT-02: "Config parse errors logged at WARNING."

### REF-02 data-leak fix

- **D-10:** `api/reference.py` currently returns `{"detail": f"Internal Server Error: {str(e)}"}` — exposes raw exception message. Fix: `raise HTTPException(status_code=500, detail="internal_error")`. Log the exception via `logger.error("References pipeline error", exc_info=True, extra={...})` before raising.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements and roadmap
- `.planning/REQUIREMENTS.md` — Phase 14 requirements: CHAT-01, CHAT-02, CHAT-03, REF-01, REF-02, REF-03, HIK-01, HIK-02, PRIM-01 (full acceptance criteria)
- `.planning/ROADMAP.md` §Phase 14 — Success criteria (5 acceptance tests), depends-on Phase 13

### Phase 13 infrastructure (built, must be used as-is)
- `core/context.py` — `correlation_id: ContextVar[str]` — import and call `.get()` in route handlers to read the current request's correlation ID
- `core/sentry.py` — `bind_sentry_scope(correlation_id, endpoint, session_id=None, user_id=None)` and `SENTRY_ENABLED` flag
- `core/middleware.py` — `CorrelationIdMiddleware` (already registered in `main.py`) — sets the ContextVar per request

### Files being modified in this phase
- `api/chat.py` — primary target; no logger exists yet; 3 `print()` blocks + `traceback.print_exc()` to replace; `bind_sentry_scope()` to add
- `api/reference.py` — no logger exists; 1 `print()` + REF-02 data-leak bug to fix; `bind_sentry_scope()` to add
- `api/hikmah.py` — logger exists (`logging.getLogger("api.hikmah")`); add `correlation_id` to all `extra={}` calls; replace 1 `print()` + `traceback.print_exc()`
- `api/primers.py` — logger exists (`logging.getLogger(__name__)`); convert f-string log messages to `extra={}`; add `correlation_id`; replace `traceback.print_exc()`

### Logging infrastructure
- `core/logging_config.py` — `ExtraFormatter` (appends `extra={}` keys as `key=value` pairs), `setup_logging()` (idempotent, safe to call at module level)
- `main.py` — does NOT call `setup_logging()` at module level (uses bare `logging.getLogger(__name__)`). Route files that already call `setup_logging()` (hikmah.py) can keep it; new files (chat.py, reference.py) should follow the `logging.getLogger(__name__)` pattern without `setup_logging()` since `main.py` owns app initialization.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/logging_config.py` `ExtraFormatter`: already in use — the structured `extra={}` pattern is established. New log calls follow the same shape.
- `api/hikmah.py` logger pattern: `logging.getLogger("api.hikmah")` with `logger.info/error(..., extra={...})` — the reference implementation for what chat.py and reference.py should look like after this phase.
- `core/sentry.py` `bind_sentry_scope()`: ready to call; no-op when `SENTRY_ENABLED=false`. No guards needed in route handlers.

### Current state per file
- `api/chat.py`: no `import logging`, no logger, 3 `print()` + `traceback.print_exc()` blocks (lines 117–118, 208–209, 254–255), 2 config parse `print()` calls (lines 186, 242)
- `api/reference.py`: no logger, 1 `print()` (line 33), REF-02 leak at line 34 (`detail=f"Internal Server Error: {str(e)}"`)
- `api/hikmah.py`: logger exists, 1 `print()` + `traceback.print_exc()` at lines 81–82
- `api/primers.py`: logger exists, f-string interpolation throughout (lines 38, 42, 45, 57, 93, 182), `traceback.print_exc()` at lines 58, 119, 220

### Established Patterns
- `extra={}` structured logging: `logger.info("message", extra={"correlation_id": corr_id, "session_id": session_id, ...})` — the ExtraFormatter appends each key as `key=value` in the log line and Sentry Logs captures them as searchable fields.
- Error logging: `logger.error("message", exc_info=True, extra={...})` — `LoggingIntegration` auto-captures to Sentry; no explicit `capture_exception()` needed.
- No duplicate Sentry events: use `logger.error(exc_info=True)` only, never alongside `sentry_sdk.capture_exception()`.

### Integration Points
- Route handlers import `from core.context import correlation_id as correlation_id_ctx` then call `corr_id = correlation_id_ctx.get()` at the start of each handler to read the ContextVar set by `CorrelationIdMiddleware`.
- `bind_sentry_scope(corr_id, endpoint, session_id=session_id, user_id=user_id)` called after JWT extraction in each handler.

</code_context>

<specifics>
## Specific Ideas

- The `/sentry-debug` dev endpoint in `main.py` can remain as-is — dev-only, useful for verifying Sentry capture.
- `traceback.print_exc()` removal: once all `traceback` usages are replaced with `logger.error(exc_info=True)`, the `import traceback` line should be removed from the file entirely.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 14-Route Layer Instrumentation*
*Context gathered: 2026-04-26*
