# Phase 13: Sentry Infrastructure - Context

**Gathered:** 2026-04-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Sentry is initialized safely — active only when `SENTRY_ENABLED=true` AND `SENTRY_DSN` is set, with PII scrubbed from error events, and every HTTP request carrying a traceable `correlation_id` UUID propagated via `contextvars.ContextVar` so all downstream log calls (pipeline, tools, sub-graphs) can include it. This phase delivers the infrastructure foundation all other v1.3 phases depend on.

**Scope:** `main.py`, `core/config.py`, new `core/sentry.py`, new `core/middleware.py`. No route handler instrumentation yet (Phase 14), no pipeline/tool logging (Phase 15), no fiqh sub-graph (Phase 16).

</domain>

<decisions>
## Implementation Decisions

### correlation_id propagation

- **D-01:** Use `contextvars.ContextVar[str]` — a module-level `ContextVar` named `correlation_id` (default `''`) in a new `core/context.py`. Set once in middleware; readable from anywhere in the same async task (pipeline, tools, fiqh sub-graph) without threading `request` through function signatures.
- **D-02:** Middleware class `CorrelationIdMiddleware(BaseHTTPMiddleware)` lives in new `core/middleware.py`. Registered in `main.py` via `app.add_middleware(CorrelationIdMiddleware)`. Sets the ContextVar and adds `X-Correlation-ID` to the response headers.
- **D-03:** Always generate a fresh UUID per request — ignore any incoming `X-Correlation-ID` header from clients.

### Sentry initialization and scope binding

- **D-04:** New `core/sentry.py` module holds all Sentry concerns: `SENTRY_ENABLED` bool, `sentry_sdk.init()` call (fires at module import when enabled), and `bind_sentry_scope()` helper. `main.py` does `import core.sentry` to trigger initialization.
- **D-05:** `SENTRY_ENABLED: bool = os.getenv("SENTRY_ENABLED", "").lower() == "true"`. Both `SENTRY_ENABLED=true` AND `SENTRY_DSN` must be set for `sentry_sdk.init()` to execute. Either missing → Sentry stays completely silent.
- **D-06:** `sentry_sdk.init()` params: `integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)]`, `send_default_pii=False` (removes the current `True`), `before_send=_scrub_pii`, `environment=os.getenv("ENV", "development")`, `_experiments={"enable_logs": True}` (kept — sentry-sdk 2.27.0 requires it in `_experiments`).
- **D-07:** `bind_sentry_scope(correlation_id, endpoint, session_id=None, user_id=None)` — a helper in `core/sentry.py`. Route handlers (Phases 14+) call it after extracting user_id from auth. No-op when `SENTRY_ENABLED=false`. Uses `sentry_sdk.configure_scope()` to set tags: `correlation_id`, `endpoint`, `session_id` (if present), `user_id` (if present).

### before_send PII scrubbing

- **D-08:** `_scrub_pii(event, hint)` drops `event["request"]["data"]` entirely (full request body removed via `.pop("data", None)`). Simplest and most defensive approach for Article 9 special-category data (Islamic religious content). Stack traces and tags are still captured.
- **D-09:** `before_send` applies to error/exception events only. Sentry Logs use `before_send_log`, which requires sentry-sdk >= 2.35.0 — out of scope at 2.27.0 (per REQUIREMENTS.md Future Requirements). Phases 14–16 control log PII by not putting `user_query` in `extra={}`.

### catch_exceptions_mw refactor

- **D-10:** Remove the existing `sentry_sdk.capture_exception(e)` call from `catch_exceptions_mw`. Replace with `logger.error("Unhandled exception", exc_info=True, extra={"path": str(request.url.path)})`. `LoggingIntegration` auto-captures to Sentry — no explicit call needed, no duplicate events.
- **D-11:** Error response body is gated on `SENTRY_ENABLED`: when `True`, return `{"detail": "internal_error"}` only (production — Sentry has full context); when `False`, return `{"detail": "internal_error", "error": str(e)}` (local dev convenience, no Sentry active).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements and Roadmap
- `.planning/REQUIREMENTS.md` — Full v1.3 requirements, especially INFRA-01 through INFRA-05 (this phase) and the Out of Scope / Future Requirements sections (sentry-sdk upgrade, `before_send_log`)
- `.planning/ROADMAP.md` §Phase 13 — Success criteria (5 acceptance tests), depends-on chain

### Existing Sentry setup (starting point)
- `main.py` — Current `sentry_sdk.init()` call (lines 17–23), `catch_exceptions_mw` (lines 93–101), `/sentry-debug` dev endpoint. Phase 13 refactors both.
- `core/config.py` — `SENTRY_DSN = os.getenv("SENTRY_DSN")` (line 8). `SENTRY_ENABLED` will live in `core/sentry.py`, not here.

### Logging infrastructure
- `core/logging_config.py` — `ExtraFormatter`, `setup_logging()`, `get_memory_logger()`. The `extra={}` structured logging pattern established here is what phases 14–16 extend. Phase 13 does not modify this file.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/logging_config.py`: `ExtraFormatter` already appends `extra={}` dict keys as `key=value` pairs — the structured logging convention is established. Phases 14–16 follow it.
- `main.py` `catch_exceptions_mw`: The existing try/except structure is the right shell — Phase 13 replaces `capture_exception()` + error body with `logger.error()` + `SENTRY_ENABLED`-gated response.

### Established Patterns
- `extra={}` structured logging: already used in `api/hikmah.py` and `api/primers.py`. All new log calls in v1.3 follow this pattern (no f-string interpolation for structured fields).
- Optional config pattern: `core/config.py` uses `os.getenv()` with sensible defaults. `SENTRY_ENABLED` follows the same convention.

### Integration Points
- `main.py` imports `core.sentry` → triggers `sentry_sdk.init()` at startup if enabled.
- `main.py` registers `CorrelationIdMiddleware` from `core/middleware.py` — must be added before CORS middleware so `X-Correlation-ID` header is set on all responses.
- `core/context.py` exports `correlation_id: ContextVar[str]` — imported by `core/middleware.py` (to set it) and by any log call site in phases 14–16 (to read it).
- `core/sentry.py` exports `SENTRY_ENABLED` and `bind_sentry_scope()` — imported by route handlers in Phase 14.

</code_context>

<specifics>
## Specific Ideas

- The `/sentry-debug` dev endpoint in `main.py` (lines 128–132) can stay as-is — it's dev-only and useful for verifying Sentry capture works.
- `sentry_sdk.configure_scope()` (used in `bind_sentry_scope`) is the sentry-sdk 1.x/2.x API for setting tags on the current scope. Confirm this is still valid at sentry-sdk 2.27.0 before implementing — may need `sentry_sdk.set_tag()` (standalone function form) depending on version.

</specifics>

<deferred>
## Deferred Ideas

- `before_send_log` hook for Sentry Logs PII scrubbing — requires sentry-sdk >= 2.35.0, pin stays at 2.27.0 (explicitly deferred in REQUIREMENTS.md)
- Upgrading `sentry-sdk` beyond 2.27.0 — out of scope for v1.3
- Sentry Performance tracing (custom spans for retrieval, LLM calls, fiqh iterations) — future milestone

</deferred>

---

*Phase: 13-Sentry Infrastructure*
*Context gathered: 2026-04-26*
