---
phase: 16-fiqh-sub-graph-instrumentation
reviewed: 2026-04-28T00:00:00Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - agents/fiqh/fiqh_graph.py
  - tests/test_fiqh_graph_logging.py
findings:
  critical: 0
  warning: 4
  info: 2
  total: 6
status: issues_found
---

# Phase 16: Code Review Report

**Reviewed:** 2026-04-28
**Depth:** standard
**Files Reviewed:** 2
**Status:** issues_found

## Summary

Two files were reviewed: the compiled FiqhAgent LangGraph sub-graph (`agents/fiqh/fiqh_graph.py`) and its associated logging unit tests (`tests/test_fiqh_graph_logging.py`). The graph structure, routing logic, and iteration cap are correctly implemented. The LangGraph `checkpointer=False` usage is valid and intentional (confirmed against LangGraph 0.2.64 source).

Four warnings were found, none of which are individually catastrophic but each represents a real defect or robustness gap. Two info-level items were also found. No critical (security or data-loss) issues were identified.

---

## Warnings

### WR-01: State mutation before returned dict causes LangGraph state divergence

**File:** `agents/fiqh/fiqh_graph.py:30-33, 63-65, 111-114, 146-149, 184-187`

**Issue:** Every node function mutates `state["status_events"]` **in-place** via `.append()` before returning a partial state dict. LangGraph nodes are expected to be pure functions that return a partial dict; the framework merges the returned dict into a copy of the state. When a node mutates the input dict first and then returns `list(state["status_events"])` (a snapshot of the now-mutated list), two things happen:

1. The in-place mutation of the passed-in TypedDict is a side effect that violates LangGraph's update contract — if the graph ever re-runs a node (e.g., on checkpointed replay or with a future `interrupt_before`), the event will be appended twice.
2. Even with `checkpointer=False`, this pattern is fragile: if any exception occurs between the `.append()` call and the `return` statement, the `status_events` list in the caller's view of state will contain the event even though the node "failed" and returned nothing.

The correct pattern is to build the event into the returned dict without touching the input:

**Fix:**
```python
# Instead of:
state["status_events"].append({"step": "fiqh_decompose", "message": "..."})
# ...
return {
    "prior_queries": prior,
    "status_events": list(state["status_events"]),  # already mutated
}

# Do:
new_event = {"step": "fiqh_decompose", "message": "Decomposing fiqh query..."}
return {
    "prior_queries": prior,
    "status_events": list(state["status_events"]) + [new_event],
}
```

Apply the same fix to `_retrieve_node` (line 63), `_filter_node` (line 111), `_assess_node` (line 146), and `_refine_node` (line 184).

---

### WR-02: `_retrieve_node` double-logs on zero docs (WARNING then INFO both fire)

**File:** `agents/fiqh/fiqh_graph.py:73-83`

**Issue:** When `retrieve_fiqh_documents` returns an empty list, the code emits a `WARNING` ("zero documents") at line 74, then **unconditionally** emits an `INFO` ("Fiqh documents retrieved", `doc_count=0`) at line 79. Both records are emitted for the same zero-doc event. This means any log aggregation or alerting that counts WARNING events will also see a spurious INFO below it with `doc_count=0`, making it appear as though a successful (but empty) retrieval occurred. It also inverts the conventional idiom: the INFO after the WARNING implies "retrieval succeeded" when the warning already signalled a degenerate result.

**Fix:** Make the INFO conditional, or only emit INFO on the non-zero path:
```python
    if len(new_docs) == 0:
        logger.warning("Fiqh retrieval returned zero documents", extra={
            "correlation_id": correlation_id_ctx.get(),
            "iteration": iteration,
            "doc_count": 0,
        })
    else:
        logger.info("Fiqh documents retrieved", extra={
            "correlation_id": correlation_id_ctx.get(),
            "iteration": iteration,
            "doc_count": len(new_docs),
        })
```

---

### WR-03: `_filter_node` double-logs on empty filter result (same pattern as WR-02)

**File:** `agents/fiqh/fiqh_graph.py:117-127`

**Issue:** Same structural defect as WR-02. When `filter_evidence` returns `[]`, a WARNING fires at line 118, then an INFO fires at line 123 with `doc_count=0`. The INFO message "Fiqh evidence filtered" at `doc_count=0` misrepresents the outcome.

**Fix:** Mirror the fix from WR-02:
```python
    if len(filtered) == 0:
        logger.warning("Fiqh evidence filter removed all documents", extra={
            "correlation_id": correlation_id_ctx.get(),
            "iteration": state["iteration"],
            "doc_count": 0,
        })
    else:
        logger.info("Fiqh evidence filtered", extra={
            "correlation_id": correlation_id_ctx.get(),
            "iteration": state["iteration"],
            "doc_count": len(filtered),
        })
```

---

### WR-04: Test patch targets are wrong — tests will always pass regardless of production code

**File:** `tests/test_fiqh_graph_logging.py:36, 52, 72, 89`

**Issue:** The tests patch `"modules.fiqh.retriever.retrieve_fiqh_documents"` and `"modules.fiqh.filter.filter_evidence"`, but both functions are imported **inside the node body** using deferred imports:

```python
# _retrieve_node:
def _retrieve_node(state: FiqhState) -> dict:
    from modules.fiqh.retriever import retrieve_fiqh_documents
    ...
    new_docs = retrieve_fiqh_documents(current_query)
```

When `unittest.mock.patch` is given `"modules.fiqh.retriever.retrieve_fiqh_documents"`, it patches the `retrieve_fiqh_documents` name **in the `modules.fiqh.retriever` namespace**. Because the deferred `from ... import retrieve_fiqh_documents` inside the node body re-executes on each call, it re-binds the local name to the patched object — which means the patch **does** happen to work here. However, this only works by coincidence of execution order; the test file's own comment ("Patch targets use source modules... because all imports are deferred inside function bodies") is correct reasoning but the implication is fragile.

The real defect is that if any developer converts the deferred imports to module-level imports (which is the standard pattern in this codebase), all four tests will silently break — they will stop mocking the function and will attempt real network calls to Pinecone/LLM, causing test failures for environmental reasons rather than logic reasons. The patch target for deferred imports should be verified to work and a comment must be present explaining why this non-standard target is correct, which it is not currently.

More critically: `test_fiqh02_warning_on_zero_docs` patches at the source module but the retriever itself calls `decompose_query` internally (line 157 in `retriever.py`) — meaning even in the mocked path the actual `retrieve_fiqh_documents` production code is not being called at all (the mock replaces it entirely), which is the intent. This is fine. But the comment on line 8–9 of the test file actually incorrectly describes the reason: the real reason you patch the source module is that the name lookup inside the deferred import goes to the source namespace.

**Fix:** Either document the patch target fragility explicitly with a comment, or patch at the fiqh_graph module level which is more robust for deferred-import functions and conventional in the codebase:
```python
# Patch where the name is looked up, not where it is defined:
with patch("agents.fiqh.fiqh_graph._retrieve_node.__globals__[...]"):
    ...
# -or- simpler: mock at source (current approach) but add explicit comment:
# NOTE: patch target is the source module namespace because retrieve_node
# uses a deferred `from modules.fiqh.retriever import ...` on every call.
# If that import is ever hoisted to module level, this patch target must
# change to "agents.fiqh.fiqh_graph.retrieve_fiqh_documents".
```

---

## Info

### IN-01: `_retrieve_node` increments iteration before use, skewing log records for iteration 1

**File:** `agents/fiqh/fiqh_graph.py:62`

**Issue:** `iteration = state["iteration"] + 1` is computed at the top of `_retrieve_node`, and then used in all log records within the same node. However, `state["iteration"]` is still `0` when the first call arrives — the increment is a local variable that is also returned and written back to state. This means the first retrieval is logged as `iteration=1`, the second as `iteration=2`, the third as `iteration=3`, which is semantically correct (you are on the 1st retrieval pass). But the `_filter_node` and `_assess_node` read `state["iteration"]` after the retrieve node has already returned and updated state, so their log records also reflect the already-incremented value. This is consistent but worth noting: iteration values in logs are `{1, 2, 3}`, not `{0, 1, 2}`. No bug — but future maintainers may be confused when they see `"iteration": 3` at the max cap (not `"iteration": 2`). The docstring should clarify.

**Fix:** Add a comment to the top of `_retrieve_node`:
```python
# iteration is 1-based in logs: retrieve increments before logging so that
# the first retrieval pass shows iteration=1 and the max cap shows iteration=3.
iteration = state["iteration"] + 1
```

---

### IN-02: `MagicMock` imported but never used in test file

**File:** `tests/test_fiqh_graph_logging.py:14`

**Issue:** `from unittest.mock import patch, MagicMock` — `MagicMock` is imported but not referenced anywhere in the test file.

**Fix:** Remove `MagicMock` from the import:
```python
from unittest.mock import patch
```

---

_Reviewed: 2026-04-28_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
