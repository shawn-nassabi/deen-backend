# Phase 15: Pipeline and Tools Instrumentation - Context

**Gathered:** 2026-04-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace all `print()` calls in `core/pipeline_langgraph.py`, `agents/tools/retrieval_tools.py`, and `agents/core/chat_agent.py` with structured `logger.*` calls. No remaining print() calls in these three files. Pipeline exceptions captured in Sentry exactly once — no duplicate events.

**Out of scope:** `agents/fiqh/fiqh_graph.py` instrumentation (Phase 16). No API surface changes. No LangGraph topology changes.

</domain>

<decisions>
## Implementation Decisions

### Log Level Policy

- **D-01:** All node traversal events in `chat_agent.py` and `pipeline_langgraph.py` go to **DEBUG** — this includes node-entry prints, routing decision prints (e.g., "routing to fiqh sub-graph", "not a fiqh query"), iteration counters, and tool execution starts. None of these should appear in Sentry Logs (INFO and above only).
- **D-02:** All exception paths in all three files use `logger.error(msg, exc_info=True, extra={...})` only. Never `capture_exception()` — LoggingIntegration auto-captures ERROR-level logs. This prevents duplicate Sentry events (established in Phase 13).
- **D-03:** The secondary Redis write failure in the SSE generator (pipeline_langgraph.py ~line 389: "Failed to append runtime history after error") uses `logger.warning(exc_info=True, extra={...})` — it is a recoverable secondary failure inside an already-logged error path, and WARNING does not create a Sentry event.
- **D-04:** The LLM response content snippet in `chat_agent.py` ~line 172 (prints partial LLM response text during agent node processing) is **dropped entirely** — no replacement. LLM content should not appear in logs.

### Query/Content in Logs

- **D-05:** User query is **omitted from all log messages** across all three files. `before_send` only filters Sentry error events, not the Sentry Logs stream — logging the query at any level risks leaking it to Sentry Logs in production. Clean PII stance: no user content in any log call.
- **D-06:** Pipeline start/end INFO logs (replacing the current `[AGENTIC PIPELINE] Starting for query:` print) include exactly: `session_id`, `correlation_id`, `target_language` as top-level `extra={}` keys.

### Tool Result Logging

- **D-07:** The tool result payload print in `chat_agent.py` ~line 202 (`Tool {tool_name} result: {str(result_data)[:200]}`) is replaced with a DEBUG log that includes `tool_name` only — no result payload. Tool name is already in the log record from the logger name; this can be a simple `logger.debug("Tool executed", extra={"tool_name": tool_name, "correlation_id": ...})`.
- **D-08:** Error logs in `retrieval_tools.py` include `correlation_id` and the exception string only — **no query snippet** in `extra={}`. This overrides TOOL-01's literal "query snippet" specification. Tool name comes from `logging.getLogger(__name__)` (each tool is in its own module scope). Format: `extra={"correlation_id": correlation_id_ctx.get(), "error": str(e)}`.

### SSE Generator Error Handling

- **D-09:** The SSE generator main exception handler (pipeline_langgraph.py ~line 376) becomes `logger.error(msg, exc_info=True, extra={...})` — no other changes. The existing `yield sse_event("error", ...)` call stays unchanged.
- **D-10:** No `capture_exception()` call anywhere in Phase 15 scope. LoggingIntegration handles Sentry capture for all ERROR-level logs automatically.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` §PIPE, §TOOL — PIPE-01, PIPE-02, TOOL-01, TOOL-02 (4 requirements this phase)
- `.planning/ROADMAP.md` — Phase 15 goal and success criteria (grep target file and success criteria)

### Prior Phase Infrastructure (patterns to follow)
- `.planning/phases/13-sentry-infrastructure/` — `core/sentry.py`, `core/context.py`, `core/middleware.py` created here; read to understand the infrastructure being used
- `.planning/phases/14-route-layer-instrumentation/` — established the `extra={}` structured logging pattern and `bind_sentry_scope()` call sites; read as the direct template for Phase 15 work

### Target Files (all three must be touched)
- `core/pipeline_langgraph.py` — 5 print() calls; no logger import yet; contains the async SSE generator and the sync non-streaming pipeline
- `agents/tools/retrieval_tools.py` — 4 error-path print() calls; no logger import yet
- `agents/core/chat_agent.py` — ~20 print() calls across all nodes; no logger import yet

### Infrastructure Already in Place
- `core/context.py` — `correlation_id` ContextVar; import as `from core.context import correlation_id as correlation_id_ctx`; call `.get()` per log call
- `core/sentry.py` — `bind_sentry_scope()` already called in `api/chat.py`; do NOT call again in pipeline or tools (would rebind scope)
- `core/logging_config.py` — `setup_logging()` and `ExtraFormatter`; logger setup already wired in `main.py`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core.context.correlation_id` ContextVar: set by `CorrelationIdMiddleware` on every request; accessible via `.get()` anywhere in the call stack including inside async generators and LangGraph nodes
- Phase 14 instrumented files (`api/chat.py`, `api/reference.py`, `api/hikmah.py`, `api/primers.py`) as direct pattern reference — copy the import block and `extra={}` style

### Established Patterns (from Phase 14)
- Module-level logger: `import logging; logger = logging.getLogger(__name__)`
- Import: `from core.context import correlation_id as correlation_id_ctx`
- Every log call: `extra={"correlation_id": correlation_id_ctx.get(), ...domain_fields}`
- Exception paths: `logger.error("message", exc_info=True, extra={"correlation_id": ..., "error": str(e)})`
- Never: `logger.error(...) + capture_exception()` together — duplicate Sentry events

### Integration Points
- `core/pipeline_langgraph.py` is called from `api/chat.py` — correlation_id ContextVar is already set before pipeline is invoked; no threading concerns
- `agents/core/chat_agent.py` is called from `core/pipeline_langgraph.py` synchronously inside the async generator — same ContextVar still available
- `agents/tools/retrieval_tools.py` is invoked via LangGraph's `ToolNode` inside the graph — ContextVar propagates through the async call stack

</code_context>

<specifics>
## Specific Ideas

- Pipeline start INFO log message: `"Pipeline started"` with `extra={"correlation_id": ..., "session_id": ..., "target_language": ...}`
- Pipeline end INFO log message: `"Pipeline complete"` with same fields
- For `[AGENTIC PIPELINE] Node: {node_name}` (line 122) → `logger.debug("Node traversal", extra={"correlation_id": ..., "node": node_name})`
- retrieval_tools.py error logs: use `logging.getLogger(__name__)` so Sentry/log records include the tool module name automatically (e.g., `agents.tools.retrieval_tools`)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 15-pipeline-and-tools-instrumentation*
*Context gathered: 2026-04-27*
