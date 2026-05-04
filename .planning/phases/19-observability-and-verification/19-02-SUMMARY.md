---
phase: 19-observability-and-verification
plan: "02"
subsystem: observability
tags: [sentry, cache-metrics, chatstate, langgraph, breadcrumb, pipeline]
requirements-completed: [OBS-01]

dependency-graph:
  requires:
    - "19-01 (record_cache_metrics_breadcrumb helper in core/sentry.py)"
    - "19-01 (cache_creation_tokens_total / cache_read_tokens_total fields on ChatState)"
    - "17-chatagent-caching-foundation (_cache_creation / _cache_read extraction in _agent_node)"
  provides:
    - "_agent_node accumulates per-iteration cache tokens into ChatState fields (writer)"
    - "_emit_cache_metrics_breadcrumb helper in pipeline_langgraph.py (computes ratio, fires breadcrumb at all 4 SSE done sites)"
    - "OBS-01 success criterion 1: warm-cache breadcrumb visible per session via Sentry"
    - "OBS-01 success criterion 2: cold-cache turn produces cache_efficiency_ratio: 0.0 (explicit guard)"
  affects:
    - "core/pipeline_langgraph.py (4 SSE done sites each preceded by breadcrumb call)"
    - "agents/core/chat_agent.py (_agent_node now accumulates into ChatState on every iteration)"

tech-stack:
  added: []
  patterns:
    - "State accumulation: state.get(key, 0) + value form (defensive against absent TypedDict keys)"
    - "Private helper (_emit_cache_metrics_breadcrumb) at module level near SSE generator — callable at all done sites without duplication"
    - "Cold-cache guard: (sum_read / total) if total > 0 else 0.0 — explicit ZeroDivisionError prevention"
    - "Accumulation inside try: block only — no partial token credit on failed llm.invoke"

key-files:
  created: []
  modified:
    - "agents/core/chat_agent.py (added 4 lines: Phase 19 accumulation comment + 2 state.get lines inside _agent_node)"
    - "core/pipeline_langgraph.py (added 36 lines: import, _emit_cache_metrics_breadcrumb helper, 4 breadcrumb call sites)"

decisions:
  - "D-07 option (b) confirmed: ChatState fields used (as established by Plan 19-01); plan confirmed accumulation at _agent_node writer site using state.get(key,0)+value form"
  - "state.get(key, 0) over state[key] += value: defensive against TypedDict absent keys in test-constructed states; += would KeyError on missing key"
  - "Non-streaming chat_pipeline_agentic path deliberately left without breadcrumb: OBS-01 success criterion 1 satisfied via streaming path which is the production path"
  - "6 pre-existing test failures in test_fiqh_integration.py and test_primer_service.py confirmed unrelated to plan changes (same failures present on base branch before edits)"

metrics:
  duration: "~9 minutes"
  completed: "2026-05-04"
  tasks-completed: 2
  tasks-total: 2
  files-changed: 2
---

# Phase 19 Plan 02: Wire Cache Token Accumulation and SSE Done Breadcrumb

Wires the writer (`_agent_node` per-iteration accumulation) and the reader (SSE `done` ratio computation + breadcrumb emission) onto the foundation built in Plan 01. Delivers OBS-01 success criteria 1 and 2: warm-cache breadcrumb visible per session via Sentry, cold-cache produces `cache_efficiency_ratio: 0.0`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Accumulate cache tokens into ChatState inside _agent_node | 064bd75 | agents/core/chat_agent.py (+4 lines) |
| 2 | Compute ratio and fire breadcrumb at every SSE done site in pipeline_langgraph.py | 2c9e364 | core/pipeline_langgraph.py (+36 lines) |

## What Was Built

**Task 1 — `agents/core/chat_agent.py:_agent_node` accumulation**

Added two lines immediately after `state["messages"].append(response)`, inside the `try:` block, before the `ready_to_answer` check. Uses `state.get(key, 0) + value` form (not `+=`) for defensive TypedDict safety — `+=` on an absent TypedDict key would raise `KeyError` inside `_agent_node` and pollute `state["errors"]`. The existing Phase 17 D-05 `logger.debug("Agent LLM cache metrics", ...)` call at lines 191-199 is preserved byte-for-byte. Accumulation only in `_agent_node` per D-03; no other node writes to these fields.

**Task 2 — `core/pipeline_langgraph.py` breadcrumb and helper**

Added:
1. Import: `from core.sentry import record_cache_metrics_breadcrumb` — inserted after the existing `correlation_id_ctx` import.
2. `_emit_cache_metrics_breadcrumb(final_state)` private helper — defined at module level before `chat_pipeline_streaming_agentic`. Reads `cache_creation_tokens_total` and `cache_read_tokens_total` from `final_state.get(...)` (defensive against `None` and missing keys), computes ratio with explicit `(sum_read / total) if total > 0 else 0.0` guard (D-06), then calls `record_cache_metrics_breadcrumb(...)`.
3. Breadcrumb call inserted before `yield sse_event("done", {})` at all 4 sites:
   - (a) `final_state is None` error short-circuit path (line ~233)
   - (b) early-exit success path for non-Islamic/unethical (line ~252)
   - (c) main streaming success path — fiqh and hadith/non-fiqh converge (line ~413)
   - (d) outer `except Exception as e:` error path (line ~435)

The non-streaming `chat_pipeline_agentic` path was deliberately left without a breadcrumb — OBS-01 success criterion 1 is satisfied via the streaming path which is the production path.

## Verification

- `grep -c "_emit_cache_metrics_breadcrumb(final_state)" core/pipeline_langgraph.py` returns 5 (4 call sites + 1 function definition that matches the pattern — all 4 call sites confirmed via `grep -n`)
- `grep -c 'yield sse_event("done", {})' core/pipeline_langgraph.py` returns exactly 4 — no done sites added or removed
- `grep -c "if total > 0 else 0.0" core/pipeline_langgraph.py` returns 1 — D-06 cold-cache guard present
- `grep -c "ZeroDivisionError" core/pipeline_langgraph.py` returns 0 — guarding, not catching
- `awk` ordering check confirms breadcrumb immediately precedes every done yield (gap = 1 at all 4 sites)
- `python -c "import core.pipeline_langgraph; print('imports_ok')"` prints `imports_ok` — no circular import
- `pytest tests/test_agentic_streaming_pipeline.py -q` — 7 passed (both before and after Task 2 changes)
- `pytest tests --ignore=tests/db -q` — 203 passed, 6 failed (same 6 pre-existing failures confirmed on base branch)

## Deviations from Plan

None — plan executed exactly as written. The note about `grep -c "_emit_cache_metrics_breadcrumb(final_state)"` returning 5 (not 4) is because the function definition `def _emit_cache_metrics_breadcrumb(final_state) -> None:` also contains the substring `_emit_cache_metrics_breadcrumb(final_state)`. There are exactly 4 call sites as required.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. All changes are purely in-process:
- `_agent_node` mutation of two int fields already on `ChatState` — in-process LangGraph state.
- `_emit_cache_metrics_breadcrumb` calls `sentry_sdk.add_breadcrumb` (server-side only, no new SSE event to client). Consistent with T-19-06, T-19-07, T-19-09 from the plan's threat register.

## Known Stubs

None. Both accumulation and breadcrumb emission are fully wired. Plan 19-03 will add unit tests asserting the ratio math at the seam.

## Self-Check: PASSED

- `agents/core/chat_agent.py` contains `state["cache_creation_tokens_total"] = state.get` at line 203 — FOUND
- `core/pipeline_langgraph.py` contains `def _emit_cache_metrics_breadcrumb` — FOUND
- `core/pipeline_langgraph.py` contains `from core.sentry import record_cache_metrics_breadcrumb` — FOUND
- Commit `064bd75` exists in git log — FOUND
- Commit `2c9e364` exists in git log — FOUND
