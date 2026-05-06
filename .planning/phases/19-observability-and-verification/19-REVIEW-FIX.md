---
phase: 19-observability-and-verification
fixed_at: 2026-05-04T00:00:00Z
review_path: .planning/phases/19-observability-and-verification/19-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 19: Code Review Fix Report

**Fixed at:** 2026-05-04T00:00:00Z
**Source review:** `.planning/phases/19-observability-and-verification/19-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (CR-01, WR-01, WR-02, WR-03)
- Fixed: 4
- Skipped: 0

## Fixed Issues

### CR-01: Internal exception messages leaked to SSE clients via `error` event

**Files modified:** `core/pipeline_langgraph.py`
**Commit:** e047480
**Applied fix:** Replaced `str(e)` with the generic string `"An error occurred. Please try again."` in the outer `except` handler's SSE error event yield (line 434). The exception continues to be logged with `exc_info=True` for server-side diagnostics.

---

### WR-01: Cache token accumulation silently drops metrics when `response_metadata` is None

**Files modified:** `agents/core/chat_agent.py`
**Commit:** e838228
**Applied fix:** Changed `response.response_metadata.get("usage", {})` to `(response.response_metadata or {}).get("usage", {})` at line 188 in `_agent_node`. This prevents an `AttributeError` when `response_metadata` is `None` (possible with mocks or older serialized messages) from silently aborting the turn via the enclosing `except` block and losing cache metrics.

---

### WR-02: Cache metrics not accumulated for generator nodes — undocumented design intent

**Files modified:** `core/pipeline_langgraph.py`
**Commit:** d67f121
**Applied fix:** Added a NOTE paragraph to the `_emit_cache_metrics_breadcrumb` docstring explicitly stating that `_generate_response_node` and `_generate_fiqh_response_node` LLM calls are excluded from cache token accumulation by design, because they run outside the iterative tool-calling loop where prompt cache warm-up occurs.

---

### WR-03: No test covers the fiqh FAIR-RAG streaming path for breadcrumb emission

**Files modified:** `tests/test_cache_metrics_breadcrumb.py`
**Commit:** a4f6511
**Applied fix:** Added `test_breadcrumb_fires_on_fiqh_streaming_path` which drives the pipeline via `_drive_pipeline` with `fiqh_category="VALID_OBVIOUS"` and empty `fiqh_filtered_docs` (avoids any LLM call via the no-docs fallback branch). The test asserts the breadcrumb fires with correct `cache_creation_tokens=100`, `cache_read_tokens=400`, `iterations=2`, and `cache_efficiency_ratio=0.8`, and verifies the fiqh fallback SSE message contains `"sistani.org"`. All 17 tests pass (9 pre-existing + 1 new breadcrumb test + 7 agentic streaming tests).

---

_Fixed: 2026-05-04T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
