# Phase 16: Fiqh Sub-graph Instrumentation - Context

**Gathered:** 2026-04-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Instrument `agents/fiqh/fiqh_graph.py` — convert all existing `%s` format-string log calls to `extra={}` structured logs, and add three new WARNING events at specific failure boundaries (FIQH-02, FIQH-03, FIQH-04). Single file, no API surface changes, no LangGraph topology changes.

**Out of scope:** Any other file in `agents/fiqh/` or `modules/fiqh/`. No behavior changes to the FAIR-RAG loop itself.

</domain>

<decisions>
## Implementation Decisions

### extra={} Field Composition

- **D-01:** Only include fields that are meaningfully available in each node — omit absent fields entirely (do not use `None` or `0` as placeholders). Prevents misleading Sentry search results.
- **D-02:** Every log call includes `correlation_id` from `correlation_id_ctx.get()` — consistent with Phase 13–15 pattern.
- **D-03:** Field set per node:
  - `_decompose_node` → `extra={"correlation_id": ...}` only (no iteration/verdict/doc_count available at decompose time)
  - `_retrieve_node` → `extra={"correlation_id": ..., "iteration": iteration, "doc_count": len(new_docs)}` where `doc_count` = new docs returned this iteration (not accumulated total)
  - `_filter_node` → `extra={"correlation_id": ..., "iteration": state["iteration"], "doc_count": len(filtered)}` where `doc_count` = post-filter count
  - `_assess_node` → `extra={"correlation_id": ..., "iteration": state["iteration"], "verdict": verdict, "doc_count": len(state["accumulated_docs"])}`
  - `_route_after_assess` → `extra={"correlation_id": ..., "iteration": state["iteration"], "verdict": state["verdict"], "doc_count": len(state["accumulated_docs"])}`
- **D-04:** For `_retrieve_node`, `doc_count` = `len(new_docs)` (this iteration's new docs) — not the accumulated total after dedup. This makes FIQH-02 detection direct: `doc_count:0` in Sentry = zero docs retrieved this iteration.
- **D-05:** For `_filter_node`, `doc_count` = `len(filtered)` (post-filter count) — not the pre-filter count. Makes FIQH-03 detection direct: `doc_count:0` = filter dropped everything.

### Query Content in Logs

- **D-06:** Drop `current_query[:60]` from `_retrieve_node` log (line 67). Replace with `doc_count` in `extra={}` only. Sub-queries are derived from user input and carry the same PII risk as the original query. Per Phase 15 D-05: no query content in any log call.

### FIQH-02: Zero-Doc Retrieval WARNING

- **D-07:** After `retrieve_fiqh_documents()` returns, if `len(new_docs) == 0`, log `logger.warning("Fiqh retrieval returned zero documents", extra={"correlation_id": ..., "iteration": iteration, "doc_count": 0})`. Log before the dedup loop. The existing INFO log fires regardless (FIQH-01 conversion) — the WARNING is an additional call on the zero-doc path only.

### FIQH-03: Filter Drops All Docs WARNING

- **D-08:** After `filter_evidence()` succeeds, if `len(filtered) == 0`, log `logger.warning("Fiqh evidence filter removed all documents", extra={"correlation_id": ..., "iteration": state["iteration"], "doc_count": 0})`. **No behavior change** — the empty list still propagates to `accumulated_docs`. The graph continues to `_assess_node` with zero docs → INSUFFICIENT verdict → refine or exit. The except-clause fail-open (line 104) stays unchanged.

### FIQH-04: Max Iterations + INSUFFICIENT WARNING

- **D-09:** In `_route_after_assess`, when `state["iteration"] >= 3 and state["verdict"] != "SUFFICIENT"` (i.e., the exit condition is hit due to iteration exhaustion, not a SUFFICIENT verdict), log `logger.warning("Fiqh FAIR-RAG exhausted max iterations with insufficient evidence", extra={"correlation_id": ..., "iteration": state["iteration"], "verdict": state["verdict"], "doc_count": len(state["accumulated_docs"])})`. This fires before `return "exit"`.

### Log Level Policy (inherited from Phase 15)

- **D-10:** Exception paths in all nodes use `logger.error(msg, exc_info=True, extra={...})` — never `capture_exception()`. LoggingIntegration auto-captures ERROR-level logs. No duplicate Sentry events.
- **D-11:** No `capture_exception()` anywhere in Phase 16 scope.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` §FIQH — FIQH-01, FIQH-02, FIQH-03, FIQH-04 (4 requirements this phase)
- `.planning/ROADMAP.md` — Phase 16 goal and success criteria (grep "Phase 16" for target file and success criteria)

### Prior Phase Infrastructure (patterns to follow)
- `.planning/phases/13-sentry-infrastructure/` — `core/sentry.py`, `core/context.py`, `core/middleware.py`; source of the `correlation_id` ContextVar infrastructure
- `.planning/phases/14-route-layer-instrumentation/` — established the `extra={}` structured logging pattern; read as the direct pattern template
- `.planning/phases/15-pipeline-and-tools-instrumentation/15-CONTEXT.md` — decisions D-01 through D-10 that Phase 16 inherits (especially D-05: no query content, D-02: error-only via logger.error(exc_info=True))

### Target File (only file touched)
- `agents/fiqh/fiqh_graph.py` — 214 lines; logger already imported (line 12–19); all log calls use `%s` format strings; no `correlation_id` import yet

### Infrastructure Already in Place
- `core/context.py` — `correlation_id` ContextVar; import as `from core.context import correlation_id as correlation_id_ctx`; call `.get()` per log call
- `core/logging_config.py` — `setup_logging()` and `ExtraFormatter`; already wired in `main.py`
- `core/sentry.py` — `bind_sentry_scope()` already called upstream in `api/chat.py`; do NOT call again in fiqh_graph.py

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core.context.correlation_id` ContextVar: set by `CorrelationIdMiddleware` on every request; accessible via `.get()` anywhere in the call stack, including inside LangGraph nodes (fiqh_subgraph is invoked synchronously from within the agentic pipeline which runs inside the async SSE generator — ContextVar propagates through the call stack)
- Phase 14 instrumented files (`api/chat.py`, etc.) and Phase 15 instrumented files (`core/pipeline_langgraph.py`, `agents/tools/retrieval_tools.py`, `agents/core/chat_agent.py`) as direct pattern reference

### Established Patterns (from Phases 14–15)
- Module-level logger already exists: `logger = logging.getLogger(__name__)` (line 19) — no new logger setup needed
- Add import: `from core.context import correlation_id as correlation_id_ctx`
- Every log call: `extra={"correlation_id": correlation_id_ctx.get(), ...domain_fields}`
- Exception paths: `logger.error("message", exc_info=True, extra={"correlation_id": ..., "error": str(e)})` — never both `logger.error` and `capture_exception()`

### Log Calls to Convert (FIQH-01)
All existing log calls use `%s` format strings — convert all to `extra={}` style:
- `_decompose_node` lines 35, 37 (INFO + ERROR)
- `_retrieve_node` lines 67, 69 (INFO + ERROR) — drop query snippet from line 67
- `_filter_node` lines 97–100, 103 (INFO + ERROR)
- `_assess_node` lines 123, 125 (INFO + ERROR)
- `_refine_node` lines 155, 157 (INFO + ERROR)
- `_route_after_assess` lines 181–186 (INFO)

### New WARNING Calls to Add
- `_retrieve_node`: after `new_docs = retrieve_fiqh_documents(...)`, if `len(new_docs) == 0` → WARNING (FIQH-02)
- `_filter_node`: after `filtered = filter_evidence(...)`, if `len(filtered) == 0` → WARNING (FIQH-03), then continue (no behavior change)
- `_route_after_assess`: when `state["iteration"] >= 3 and state["verdict"] != "SUFFICIENT"` → WARNING before `return "exit"` (FIQH-04)

</code_context>

<specifics>
## Specific Ideas

- FIQH-02 WARNING message: `"Fiqh retrieval returned zero documents"` with `extra={"correlation_id": ..., "iteration": iteration, "doc_count": 0}`
- FIQH-03 WARNING message: `"Fiqh evidence filter removed all documents"` with `extra={"correlation_id": ..., "iteration": state["iteration"], "doc_count": 0}`
- FIQH-04 WARNING message: `"Fiqh FAIR-RAG exhausted max iterations with insufficient evidence"` with `extra={"correlation_id": ..., "iteration": state["iteration"], "verdict": state["verdict"], "doc_count": len(state["accumulated_docs"])}`
- Existing INFO log in `_route_after_assess` (lines 181–186) should be converted to `extra={}` and kept — it fires on both SUFFICIENT exits and iteration-exhaustion exits. The new WARNING only fires on the iteration-exhaustion path.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 16-fiqh-sub-graph-instrumentation*
*Context gathered: 2026-04-28*
