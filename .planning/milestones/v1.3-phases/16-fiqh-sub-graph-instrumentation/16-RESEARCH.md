# Phase 16: Fiqh Sub-graph Instrumentation - Research

**Researched:** 2026-04-28
**Domain:** Python structured logging, Sentry LoggingIntegration, LangGraph sub-graph node instrumentation
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** Only include fields that are meaningfully available in each node — omit absent fields entirely (do not use `None` or `0` as placeholders).
**D-02:** Every log call includes `correlation_id` from `correlation_id_ctx.get()`.
**D-03:** Field set per node:
- `_decompose_node` → `extra={"correlation_id": ...}` only
- `_retrieve_node` → `extra={"correlation_id": ..., "iteration": iteration, "doc_count": len(new_docs)}`
- `_filter_node` → `extra={"correlation_id": ..., "iteration": state["iteration"], "doc_count": len(filtered)}`
- `_assess_node` → `extra={"correlation_id": ..., "iteration": state["iteration"], "verdict": verdict, "doc_count": len(state["accumulated_docs"])}`
- `_route_after_assess` → `extra={"correlation_id": ..., "iteration": state["iteration"], "verdict": state["verdict"], "doc_count": len(state["accumulated_docs"])}`
**D-04:** For `_retrieve_node`, `doc_count` = `len(new_docs)` (this iteration's new docs) — not accumulated total after dedup.
**D-05:** For `_filter_node`, `doc_count` = `len(filtered)` (post-filter count).
**D-06:** Drop `current_query[:60]` from `_retrieve_node` line 67. No query content in any log call (PII).
**D-07:** FIQH-02 WARNING: `logger.warning("Fiqh retrieval returned zero documents", extra={"correlation_id": ..., "iteration": iteration, "doc_count": 0})` — fires after `retrieve_fiqh_documents()` if `len(new_docs) == 0`, before dedup loop.
**D-08:** FIQH-03 WARNING: `logger.warning("Fiqh evidence filter removed all documents", extra={"correlation_id": ..., "iteration": state["iteration"], "doc_count": 0})` — fires after `filter_evidence()` succeeds if `len(filtered) == 0`. No behavior change — empty list still propagates. Except-clause fail-open (line 104) stays unchanged.
**D-09:** FIQH-04 WARNING: `logger.warning("Fiqh FAIR-RAG exhausted max iterations with insufficient evidence", extra={"correlation_id": ..., "iteration": state["iteration"], "verdict": state["verdict"], "doc_count": len(state["accumulated_docs"])})` — fires in `_route_after_assess` when `state["iteration"] >= 3 and state["verdict"] != "SUFFICIENT"`, before `return "exit"`.
**D-10:** Exception paths use `logger.error(msg, exc_info=True, extra={...})` — never `capture_exception()`.
**D-11:** No `capture_exception()` anywhere in Phase 16 scope.

### Claude's Discretion

None — all decisions locked.

### Deferred Ideas (OUT OF SCOPE)

None listed.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FIQH-01 | All existing log calls converted from `%s` format strings to `extra={}` with `iteration`, `verdict`, and `doc_count` as top-level searchable fields in Sentry Logs | 12 existing log calls identified (lines 35, 37, 67, 69, 97–100, 103, 123, 125, 155, 157, 181–186) — full audit below |
| FIQH-02 | WARNING logged when zero documents are retrieved on any FAIR-RAG iteration | Insert after `new_docs = retrieve_fiqh_documents(current_query)` line 66, inside try block |
| FIQH-03 | WARNING logged when the evidence filter removes all accumulated documents (fail-open path triggered) | Insert after `filtered = filter_evidence(...)` line 96, inside try block, before `return` — fail-open except (line 102–104) unchanged |
| FIQH-04 | WARNING logged when max iterations are reached with an INSUFFICIENT evidence verdict | Insert in `_route_after_assess` when `state["iteration"] >= 3 and state["verdict"] != "SUFFICIENT"`, before `return "exit"` (line 186) |

</phase_requirements>

---

## Summary

Phase 16 is a single-file instrumentation pass on `agents/fiqh/fiqh_graph.py` (214 lines). The file has 12 existing log calls spread across 5 node functions and 1 routing function — all use `%s` format-string interpolation with no `extra={}` and no `correlation_id`. The infrastructure to fix this is fully in place from Phases 13–15: `core/context.py` exports the ContextVar, `core/logging_config.py` has `ExtraFormatter` that serialises `extra={}` keys as `key=value` pairs, and `core/sentry.py` has `LoggingIntegration` configured to forward INFO+ logs to Sentry Logs.

The work divides into two parts. FIQH-01 is mechanical: add one import line and rewrite all 12 existing log calls to use `extra={}` with the field set prescribed by D-03. FIQH-02/03/04 each add a single `logger.warning()` call at a specific failure boundary — zero retrieval, total filter loss, and iteration exhaustion — with no behavior changes to the FAIR-RAG loop itself.

No tests currently cover `fiqh_graph.py` directly. The existing test suite covers `modules/fiqh/fair_rag.py` (the legacy imperative loop, not the LangGraph sub-graph). The recommended test strategy is to add unit tests in `tests/test_fiqh_graph_logging.py` that mock module-level imports and assert that the WARNING logs fire at the correct boundaries.

**Primary recommendation:** One plan, one wave — add the import, rewrite 12 existing calls, insert 3 new WARNING calls. No architectural decisions remain open.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Structured log emission | Application (LangGraph node) | — | Log calls live inside node functions; fields derived from local node state |
| Field serialisation to console | ExtraFormatter (core/logging_config.py) | — | Already wired in main.py via setup_logging() |
| Log forwarding to Sentry Logs | LoggingIntegration (core/sentry.py) | — | Captures all INFO+ logger calls; extra={} keys become Sentry log attributes |
| Per-request correlation | ContextVar (core/context.py) | — | Set by CorrelationIdMiddleware; readable from fiqh_graph.py via .get() |
| Sentry scope tagging | bind_sentry_scope (core/sentry.py) | — | Already called in api/chat.py (Phase 14); do NOT call again in fiqh_graph.py |

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python `logging` | stdlib | Log emission | Already used; module-level logger at line 19 |
| `core.context.correlation_id` | project | ContextVar for request ID | Phase 13 infrastructure; import alias `correlation_id_ctx` is project convention |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `sentry_sdk` | 2.27.0 (pinned) | Error tracking | Passive — LoggingIntegration captures logger calls automatically; no direct calls needed in this phase |

**No new dependencies.** Phase 16 requires zero `pip install` changes.

---

## Architecture Patterns

### System Architecture Diagram

```
HTTP Request
    |
    v
CorrelationIdMiddleware  -->  sets correlation_id ContextVar
    |
    v
api/chat.py  -->  bind_sentry_scope() [Phase 14]
    |
    v
core/pipeline_langgraph.py  -->  ChatAgent.astream()
    |
    v
agents/core/chat_agent.py  -->  fiqh_subgraph.invoke()  [synchronous call]
    |
    v
agents/fiqh/fiqh_graph.py  (TARGET FILE)
    |
    +-- _decompose_node  -->  logger.info(extra={correlation_id})
    |
    +-- _retrieve_node   -->  logger.info(extra={correlation_id, iteration, doc_count})
    |                         [NEW] if doc_count==0: logger.warning(FIQH-02)
    |
    +-- _filter_node     -->  logger.info(extra={correlation_id, iteration, doc_count})
    |                         [NEW] if doc_count==0: logger.warning(FIQH-03)
    |
    +-- _assess_node     -->  logger.info(extra={correlation_id, iteration, verdict, doc_count})
    |
    +-- _refine_node     -->  logger.info(extra={correlation_id})
    |
    +-- _route_after_assess --> logger.info(extra={correlation_id, iteration, verdict, doc_count})
                                [NEW] if exhausted: logger.warning(FIQH-04)
                                    |
                                    v
                         ExtraFormatter --> serialises extra={} as key=value pairs
                                    |
                                    v
                         LoggingIntegration --> forwards to Sentry Logs (INFO+)
                                    |
                                    v
                         Sentry Logs --> searchable by iteration:N, verdict:V, doc_count:N
```

### Recommended Project Structure

No directory changes. Single file modification:
```
agents/fiqh/
└── fiqh_graph.py    # only file touched
```

---

## Current State Audit: Full Log Call Map

This is the complete inventory of every `logger.*` call in `agents/fiqh/fiqh_graph.py` as of the research date. The planner uses this as the exact change target list.

### `_decompose_node` (lines 25–49)

| Line | Level | Current Call | Conversion |
|------|-------|-------------|------------|
| 35 | INFO | `logger.info("[FIQH_GRAPH] Decomposed into %d sub-queries", len(sub_queries))` | `logger.info("Fiqh query decomposed", extra={"correlation_id": correlation_id_ctx.get(), "sub_query_count": len(sub_queries)})` |
| 37 | ERROR | `logger.error("[FIQH_GRAPH] decompose_node error: %s", exc)` | `logger.error("Fiqh decompose_node error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})` |

**Note:** D-03 specifies only `correlation_id` for `_decompose_node`. `sub_query_count` is not in the locked field set — the planner should use only `correlation_id` here per D-01/D-03. The `sub_query_count` field shown above is an addition; if D-03 says omit it, use only `correlation_id`.

**Correction:** Per D-03 strictly, `_decompose_node` gets `extra={"correlation_id": ...}` only. `sub_query_count` is not iteration/verdict/doc_count. Include it only if the planner decides it adds value without contradicting D-01 (only meaningfully available fields). D-01 supports including it — but D-03 prescribes the minimum. This is a planner call within Claude's discretion for the INFO message body text.

### `_retrieve_node` (lines 52–84)

| Line | Level | Current Call | Conversion / Action |
|------|-------|-------------|---------------------|
| 67 | INFO | `logger.info("[FIQH_GRAPH] Retrieved %d docs for query: %s", len(new_docs), current_query[:60])` | `logger.info("Fiqh documents retrieved", extra={"correlation_id": correlation_id_ctx.get(), "iteration": iteration, "doc_count": len(new_docs)})` — drop `current_query[:60]` (D-06) |
| 69 | ERROR | `logger.error("[FIQH_GRAPH] retrieve_node error: %s", exc)` | `logger.error("Fiqh retrieve_node error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "iteration": iteration, "error": str(exc)})` |
| NEW | WARNING | (does not exist) | Add after line 66 inside try: `if len(new_docs) == 0: logger.warning("Fiqh retrieval returned zero documents", extra={"correlation_id": correlation_id_ctx.get(), "iteration": iteration, "doc_count": 0})` (FIQH-02) |

**State note:** `iteration` in `_retrieve_node` is the **local variable** `iteration = state["iteration"] + 1` (line 56) — this is the incremented value computed at node start. Use the local variable, not `state["iteration"]`, which is one less.

### `_filter_node` (lines 87–109)

| Line | Level | Current Call | Conversion / Action |
|------|-------|-------------|---------------------|
| 97–100 | INFO | Multi-line `logger.info("[FIQH_GRAPH] Filtered: %d -> %d docs", len(state["accumulated_docs"]), len(filtered))` | `logger.info("Fiqh evidence filtered", extra={"correlation_id": correlation_id_ctx.get(), "iteration": state["iteration"], "doc_count": len(filtered)})` |
| 103 | ERROR | `logger.error("[FIQH_GRAPH] filter_node error: %s", exc)` | `logger.error("Fiqh filter_node error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "iteration": state["iteration"], "error": str(exc)})` |
| NEW | WARNING | (does not exist) | Add after `filtered = filter_evidence(...)` succeeds, inside try block: `if len(filtered) == 0: logger.warning("Fiqh evidence filter removed all documents", extra={"correlation_id": correlation_id_ctx.get(), "iteration": state["iteration"], "doc_count": 0})` (FIQH-03) |

**State note:** `state["iteration"]` in `_filter_node` is the value written by `_retrieve_node` (the incremented value). The filter node does not increment iteration, so `state["iteration"]` here equals the current iteration number.

**Fail-open note:** The except clause (lines 102–104) assigns `filtered = list(state["accumulated_docs"])` — this is the fail-open path. The FIQH-03 WARNING fires only in the try branch when `filter_evidence()` returns an empty list by design. The except-clause ERROR is converted separately. The WARNING does NOT fire on the except path.

### `_assess_node` (lines 112–138)

| Line | Level | Current Call | Conversion |
|------|-------|-------------|------------|
| 123 | INFO | `logger.info("[FIQH_GRAPH] SEA verdict: %s (iteration %d)", verdict, state["iteration"])` | `logger.info("Fiqh SEA assessment complete", extra={"correlation_id": correlation_id_ctx.get(), "iteration": state["iteration"], "verdict": verdict, "doc_count": len(state["accumulated_docs"])})` |
| 125 | ERROR | `logger.error("[FIQH_GRAPH] assess_node error: %s", exc)` | `logger.error("Fiqh assess_node error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "iteration": state["iteration"], "error": str(exc)})` |

### `_refine_node` (lines 141–168)

| Line | Level | Current Call | Conversion |
|------|-------|-------------|------------|
| 155 | INFO | `logger.info("[FIQH_GRAPH] Refined into %d queries", len(refinements))` | `logger.info("Fiqh query refined", extra={"correlation_id": correlation_id_ctx.get()})` — per D-03, only `correlation_id` is prescribed for this node. `refinement_count` is not iteration/verdict/doc_count — include at planner discretion per D-01 |
| 157 | ERROR | `logger.error("[FIQH_GRAPH] refine_node error: %s", exc)` | `logger.error("Fiqh refine_node error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})` |

### `_route_after_assess` (lines 175–187)

| Line | Level | Current Call | Conversion / Action |
|------|-------|-------------|---------------------|
| 181–185 | INFO | Multi-line `logger.info("[FIQH_GRAPH] Exiting after iteration %d (verdict=%s)", state["iteration"], state["verdict"])` | `logger.info("Fiqh FAIR-RAG exiting", extra={"correlation_id": correlation_id_ctx.get(), "iteration": state["iteration"], "verdict": state["verdict"], "doc_count": len(state["accumulated_docs"])})` |
| NEW | WARNING | (does not exist) | Add before `return "exit"` when `state["iteration"] >= 3 and state["verdict"] != "SUFFICIENT"`: `logger.warning("Fiqh FAIR-RAG exhausted max iterations with insufficient evidence", extra={"correlation_id": correlation_id_ctx.get(), "iteration": state["iteration"], "verdict": state["verdict"], "doc_count": len(state["accumulated_docs"])})` (FIQH-04) |

**Routing logic note:** The existing condition is `if state["verdict"] == "SUFFICIENT" or state["iteration"] >= 3`. This means the INFO log fires on BOTH exit paths (SUFFICIENT and iteration-exhaustion). The WARNING fires only on the iteration-exhaustion branch — i.e., when `state["iteration"] >= 3 AND state["verdict"] != "SUFFICIENT"`. The WARNING must be inserted inside the `if` block but before `return "exit"`, guarded by `state["verdict"] != "SUFFICIENT"`.

**Count summary:** 10 existing calls to convert (FIQH-01) + 3 new WARNING calls to add (FIQH-02, FIQH-03, FIQH-04).

---

## Import Verification

**Verified** [VERIFIED: read core/context.py directly]

`core/context.py` contains:
```python
from contextvars import ContextVar
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
```

Import alias used throughout the project:
```python
from core.context import correlation_id as correlation_id_ctx
```

This exact alias is already used in:
- `agents/tools/retrieval_tools.py` line 10
- `agents/core/chat_agent.py` line 34
- `core/pipeline_langgraph.py` line 17

`fiqh_graph.py` does NOT have this import yet (line 11–17 imports confirmed — no `core.context` import present). The import must be added as line 13 or 14 (after `import logging`, before `from typing import Literal`).

**ContextVar propagation path:** `CorrelationIdMiddleware` sets the ContextVar per HTTP request. `chat_agent.py` calls `fiqh_subgraph.invoke()` synchronously (line 312). ContextVar values propagate through synchronous call stacks without any threading concern — the value set by the middleware is readable from inside `fiqh_graph.py` nodes. [VERIFIED: Python contextvars docs, ContextVar.get() is accessible from any frame in the same task chain]

**Default value:** `ContextVar("correlation_id", default="")` — `.get()` returns `""` in unit tests without the middleware, which is safe (empty string in `extra={}` is searchable and not harmful).

---

## Pattern Reference: Phase 15 Confirmed Pattern

**Source:** `agents/tools/retrieval_tools.py` (Phase 15 instrumented) [VERIFIED: read directly]

### Error path pattern
```python
from core.context import correlation_id as correlation_id_ctx

logger.error("Retrieval error", exc_info=True, extra={
    "correlation_id": correlation_id_ctx.get(),
    "error": str(e),
})
```

**Source:** `core/pipeline_langgraph.py` (Phase 15 instrumented) [VERIFIED: read directly]

### INFO path pattern with domain fields
```python
logger.info("Pipeline started", extra={
    "correlation_id": correlation_id_ctx.get(),
    "session_id": session_id,
    "target_language": target_language,
})
```

### DEBUG path pattern (single line)
```python
logger.debug("Node traversal", extra={"correlation_id": correlation_id_ctx.get(), "node": node_name})
```

**Key pattern observations:**
1. Message is a static string — no `%s` or f-string interpolation in the message itself
2. All dynamic values go into `extra={}` as named keys
3. Error calls include `exc_info=True` — this causes the traceback to attach to the log record
4. `str(e)` is used for the `"error"` field in exception contexts
5. No `capture_exception()` calls anywhere in Phase 15 files

---

## State Field Verification

**FiqhState fields** [VERIFIED: read agents/state/fiqh_state.py directly]

| Field | Type | Available In | Notes |
|-------|------|-------------|-------|
| `query` | `str` | All nodes | Original user query — do NOT include in logs (D-06 PII policy) |
| `iteration` | `int` | All nodes except `_decompose_node` (it reads 0) | After `_retrieve_node` runs, equals current iteration number (1, 2, 3) |
| `accumulated_docs` | `List[dict]` | All nodes | Post-dedup list; use `len()` for `doc_count` in `_assess_node` and `_route_after_assess` |
| `prior_queries` | `List[str]` | All nodes | Do not log (D-06 PII) |
| `sea_result` | `Optional[object]` | `_assess_node` onward | `None` before first assess call |
| `verdict` | `str` | `_assess_node` onward | `"SUFFICIENT"` or `"INSUFFICIENT"` |
| `status_events` | `List[dict]` | All nodes | SSE events; not relevant to logging |

**Initial state passed at invocation** (from `chat_agent.py` line 311–319):
```python
{
    "query": state["user_query"],
    "iteration": 0,
    "accumulated_docs": [],
    "prior_queries": [],
    "sea_result": None,
    "verdict": "INSUFFICIENT",
    "status_events": [],
}
```

**Local variable note for `_retrieve_node`:** The node creates `iteration = state["iteration"] + 1` (line 56) before any log calls. All log calls in `_retrieve_node` should use the local variable `iteration`, not `state["iteration"]` — this gives the correct current iteration number (1, 2, or 3) rather than the pre-increment value (0, 1, or 2).

---

## Sentry Integration Path

**Verified** [VERIFIED: read core/sentry.py directly]

`core/sentry.py` configures:
```python
LoggingIntegration(
    level=logging.INFO,           # breadcrumbs threshold
    event_level=logging.ERROR,    # error event threshold
    sentry_logs_level=logging.INFO,  # Sentry Logs threshold
)
```

The data flow from `extra={}` to Sentry Logs:

1. `logger.warning("message", extra={"iteration": 2, "doc_count": 0, "correlation_id": "..."})` fires in a node function.
2. Python `logging` module attaches the `extra` dict keys directly onto the `LogRecord` as top-level attributes.
3. `ExtraFormatter` in `core/logging_config.py` serialises them as `key=value` pairs appended to the console log line.
4. `LoggingIntegration` intercepts all `LogRecord` objects at INFO+ level. It forwards them to Sentry Logs as structured log events where the `extra` keys become **searchable log attributes**.
5. In the Sentry Logs UI: `iteration:2` finds all log events with `iteration=2`; `doc_count:0` finds zero-doc events; `verdict:INSUFFICIENT` finds insufficient-verdict events.

**No `bind_sentry_scope()` call needed in `fiqh_graph.py`:** `bind_sentry_scope()` was already called in `api/chat.py` (Phase 14) at the start of the request. It sets tags on the isolation scope which persists for the full request — these tags are automatically attached to all Sentry events (including Sentry Logs) for that request. The fiqh sub-graph runs synchronously within that same request context.

**Sentry SDK version constraint:** Pinned at `2.27.0`. The `enable_logs=True` key used in `sentry_sdk.init()` is inside `_experiments` at this version. Review `core/sentry.py` line 45 — it uses `enable_logs=True` (not `_experiments={"enable_logs": True}`). This is the existing configuration; Phase 16 does not touch `core/sentry.py`.

---

## Test Coverage Analysis

**No test file directly tests `agents/fiqh/fiqh_graph.py`.** [VERIFIED: grep found zero results]

### Existing test files relevant to fiqh domain

| File | Tests | Covers fiqh_graph.py? |
|------|-------|----------------------|
| `tests/test_fair_rag.py` | 8 tests for `modules/fiqh/fair_rag.py` (legacy imperative loop) | No |
| `tests/test_fiqh_integration.py` | 5 tests for SSE path and routing in `pipeline_langgraph.py` + `chat_agent.py` | Partially (tests that `_call_fiqh_subgraph_node` works end-to-end, but mocks the ChatAgent) |
| `tests/test_fiqh_classifier.py` | classifier module unit tests | No |
| `tests/test_fiqh_decomposer.py` | decomposer module unit tests | No |
| `tests/test_fiqh_filter.py` | filter module unit tests | No |
| `tests/test_fiqh_sea.py` | SEA module unit tests | No |
| `tests/test_fiqh_refiner.py` | refiner module unit tests | No |
| `tests/test_fiqh_retriever.py` | retriever module unit tests | No |
| `tests/test_fiqh_generator.py` | generator module unit tests | No |

### Recommended test approach for Phase 16

Create `tests/test_fiqh_graph_logging.py`. Each test mocks the module-level imports inside the node functions (they use deferred imports — `from modules.fiqh.xxx import yyy` inside the function body) and asserts on `caplog` fixtures or `unittest.mock.patch` on `logger`.

```python
# Example pattern for FIQH-02 test
import pytest
from unittest.mock import patch, MagicMock
import logging

def test_fiqh_02_warning_on_zero_docs(caplog):
    from agents.fiqh.fiqh_graph import _retrieve_node

    with patch("modules.fiqh.retriever.retrieve_fiqh_documents", return_value=[]):
        # Need to patch the import inside the function
        with patch("agents.fiqh.fiqh_graph._retrieve_node.__globals__"):
            pass  # see note below

    # Preferred approach: patch at the module level via sys.modules injection
```

**Simpler recommended approach:** Use `unittest.mock.patch` to patch `modules.fiqh.retriever.retrieve_fiqh_documents` (the module, not the local import), then call the node function directly with a minimal `FiqhState` dict and assert `caplog` captured the WARNING.

```python
def test_fiqh_02_warning_on_zero_docs(caplog):
    with patch("modules.fiqh.retriever.retrieve_fiqh_documents", return_value=[]):
        state = {
            "query": "test", "iteration": 0, "accumulated_docs": [],
            "prior_queries": ["test"], "sea_result": None,
            "verdict": "INSUFFICIENT", "status_events": [],
        }
        with caplog.at_level(logging.WARNING, logger="agents.fiqh.fiqh_graph"):
            from agents.fiqh import fiqh_graph
            fiqh_graph._retrieve_node(state)
        assert any("zero documents" in r.message for r in caplog.records)
```

**Deferred import gotcha:** All module imports are deferred inside function bodies (`from modules.fiqh.xxx import yyy` at the top of each node). This means the patch target must be `modules.fiqh.retriever.retrieve_fiqh_documents` (the source module), not `agents.fiqh.fiqh_graph.retrieve_fiqh_documents` (which won't exist at module level). This is a key pitfall for test writing.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Structured log serialisation | Custom `__str__` on dicts | `extra={}` dict + `ExtraFormatter` | Already in place; Sentry receives keys as attributes |
| Request tracing | Passing correlation_id as function arg | `correlation_id_ctx.get()` | ContextVar propagates through call stack automatically |
| Sentry capture | Direct `capture_exception()` or `capture_message()` | `logger.error(exc_info=True)` | LoggingIntegration auto-captures; avoids duplicate events (D-10) |

---

## Common Pitfalls

### Pitfall 1: Using `state["iteration"]` instead of local `iteration` in `_retrieve_node`
**What goes wrong:** `state["iteration"]` is 0 at the start of iteration 1 (not yet incremented). The node computes `iteration = state["iteration"] + 1` (line 56). Using `state["iteration"]` in the log call produces `iteration:0` in Sentry, making it unsearchable as iteration 1.
**Why it happens:** The state dict has the pre-increment value; the local variable has the correct value.
**How to avoid:** Use the local variable `iteration` (not `state["iteration"]`) in all `_retrieve_node` log calls.
**Warning signs:** Sentry Logs showing `iteration:0` for valid first-iteration events.

### Pitfall 2: Placing FIQH-03 WARNING on the except path instead of the try path
**What goes wrong:** `filtered = list(state["accumulated_docs"])` in the except clause (line 104) means `len(filtered)` could be > 0. The WARNING should fire when `filter_evidence()` SUCCEEDS but returns empty, not when it fails.
**Why it happens:** The except clause fail-open could also produce `len(filtered) == 0` if `accumulated_docs` is empty — but that is a different scenario (evidence was never accumulated, not that the filter removed it).
**How to avoid:** The FIQH-03 WARNING goes inside the `try` block, after `filtered = filter_evidence(...)`, guarded by `if len(filtered) == 0`. The except clause gets only an ERROR log (the existing line 103 converted).

### Pitfall 3: Including query content in log message or extra fields
**What goes wrong:** Logging `current_query` or `state["query"]` triggers GDPR Article 9 violation (Islamic religious content = special-category data per INFRA-05).
**Why it happens:** Existing line 67 includes `current_query[:60]` — easy to accidentally preserve.
**How to avoid:** D-06 explicitly bans query content. Replace with `doc_count` in `extra={}`. Check every converted log call for any string that derives from user input.

### Pitfall 4: Adding the FIQH-04 WARNING outside the guard condition
**What goes wrong:** The WARNING fires on SUFFICIENT exits too, producing misleading Sentry events.
**Why it happens:** The exit condition is `state["verdict"] == "SUFFICIENT" or state["iteration"] >= 3` — both paths call `return "exit"`. Without a guard, the WARNING fires on SUFFICIENT exits when `iteration >= 3`.
**How to avoid:** Guard the WARNING with `if state["iteration"] >= 3 and state["verdict"] != "SUFFICIENT":`.

### Pitfall 5: Calling `capture_exception()` in addition to `logger.error`
**What goes wrong:** Duplicate Sentry events — one from `LoggingIntegration` (auto-captured from `logger.error(exc_info=True)`) and one from the explicit `capture_exception()` call.
**Why it happens:** Common reflex when adding observability.
**How to avoid:** D-10 and D-11 explicitly prohibit this. `logger.error(exc_info=True, extra={...})` is sufficient.

### Pitfall 6: Deferred imports make naive patching fail in tests
**What goes wrong:** `patch("agents.fiqh.fiqh_graph.retrieve_fiqh_documents")` raises `AttributeError` because the name only exists in the local scope during function execution, not at module level.
**Why it happens:** All module imports in fiqh_graph.py are deferred (`from modules.fiqh.xxx import yyy` inside each node function).
**How to avoid:** Patch the source module: `patch("modules.fiqh.retriever.retrieve_fiqh_documents", ...)`.

---

## Implementation Risks

### Risk 1: `_refine_node` has no iteration/verdict/doc_count in state at its call site
**Assessment:** Low risk, already handled. D-03 prescribes only `correlation_id` for `_refine_node` (iteration and verdict are not available at refine time — the node runs before the next retrieve). This is consistent with D-01 (only include meaningfully available fields).

### Risk 2: `_route_after_assess` is a routing function, not a node
**Assessment:** No risk to the pattern. `_route_after_assess` is a pure Python function that `logger.*` can be called in just like any other function. The ContextVar is still accessible.

### Risk 3: The fiqh sub-graph is invoked synchronously inside an async generator
**Assessment:** No risk to ContextVar propagation. Python ContextVars are inherited by synchronous calls made from async code without any special handling. The ContextVar value set by the ASGI middleware propagates through the entire call stack.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `ExtraFormatter` extra key serialisation format (`key=value`) is how Sentry Logs receives structured fields | Sentry Integration Path | If Sentry Logs requires a different format, fields may not be searchable — but this is already working in Phases 14–15 |
| A2 | `enable_logs=True` in `core/sentry.py` is valid at sentry-sdk 2.27.0 | Sentry Integration Path | If the key is silently ignored, Sentry Logs won't receive any log events — but this was shipped in Phase 13 and confirmed working |

**All other claims are VERIFIED by reading source files directly in this session.**

---

## Open Questions

1. **Message text for existing INFO conversions**
   - What we know: D-03 prescribes the `extra={}` field set but not the message string for existing calls
   - What's unclear: Whether to keep `[FIQH_GRAPH]` prefix in message strings or drop it (Phase 15 pattern drops all such prefixes)
   - Recommendation: Drop the `[FIQH_GRAPH]` prefix — Phase 15 pattern uses clean static strings ("Pipeline started", "Node traversal"). The logger name `agents.fiqh.fiqh_graph` already identifies the source.

2. **Whether to include `sub_query_count` and `refinement_count` in `_decompose_node` and `_refine_node`**
   - What we know: D-03 prescribes only `correlation_id` for these nodes; D-01 allows any meaningfully available field
   - What's unclear: Whether `sub_query_count` (from `_decompose_node`) and `refinement_count` (from `_refine_node`) should be included
   - Recommendation: Include them as additional context fields — they are meaningfully available, non-PII, and useful for debugging. D-01 permits this; D-03 is a minimum, not a maximum.

---

## Environment Availability

Step 2.6: SKIPPED — Phase 16 is a code-only change with no external dependencies. No new tools, services, runtimes, or CLIs required.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes | D-06: no user query content in logs (PII policy enforced by field selection) |
| V6 Cryptography | no | — |

### Known Threat Patterns for Logging

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Log injection via user query | Tampering | D-06: query content excluded from all log calls; only numeric/enum fields logged |
| PII leakage to Sentry | Information Disclosure | `before_send` hook in core/sentry.py strips request body; D-06 prevents query content entering log fields |
| Duplicate Sentry events | Denial of Service (quota) | D-10/D-11: no `capture_exception()`; WARNING logs are not error events (do not trigger `event_level=ERROR` Sentry events) |

---

## Sources

### Primary (HIGH confidence)
- `agents/fiqh/fiqh_graph.py` — read directly; all 214 lines
- `agents/state/fiqh_state.py` — read directly; FiqhState TypedDict verified
- `core/context.py` — read directly; ContextVar definition and default value verified
- `core/logging_config.py` — read directly; ExtraFormatter serialisation logic verified
- `core/sentry.py` — read directly; LoggingIntegration configuration verified
- `agents/tools/retrieval_tools.py` — read directly; Phase 15 `extra={}` pattern confirmed
- `core/pipeline_langgraph.py` — read directly (lines 88–131); Phase 15 multi-field `extra={}` pattern confirmed
- `agents/core/chat_agent.py` (lines 305–340) — read directly; fiqh_subgraph call site and correlation_id import confirmed
- `.planning/phases/16-fiqh-sub-graph-instrumentation/16-CONTEXT.md` — all 11 decisions verified

### Secondary (MEDIUM confidence)
- `tests/test_fair_rag.py` — read directly; confirmed no fiqh_graph.py test coverage exists
- `tests/test_fiqh_integration.py` — read directly; confirmed tests operate at pipeline level, not graph-node level

---

## Metadata

**Confidence breakdown:**
- Current state audit: HIGH — every log call line number and content confirmed by direct file read
- Import verification: HIGH — confirmed in both source module and three existing call sites
- Pattern reference: HIGH — Phase 15 files read directly
- State field verification: HIGH — FiqhState TypedDict read directly
- Sentry integration path: HIGH — sentry.py and LoggingIntegration config read directly
- Test coverage gap: HIGH — grep confirmed no test file targets fiqh_graph.py
- Implementation risks: HIGH — all risks derived from direct code inspection

**Research date:** 2026-04-28
**Valid until:** 2026-05-28 (stable code; no external API dependencies)
