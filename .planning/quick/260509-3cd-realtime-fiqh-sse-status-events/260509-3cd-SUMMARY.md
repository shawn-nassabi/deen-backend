---
phase: 260509-3cd
plan: 01
status: complete
subsystem: sse-streaming
tags: [sse, fiqh-subgraph, real-time-status, langgraph, contextvar, asyncio-queue]
requires:
  - core/context.py::correlation_id (existing contextvar pattern)
  - agents/fiqh/fiqh_graph.py::status_events (still populated for retrospective fallback)
provides:
  - core.context.fiqh_status_queue contextvar (per-request asyncio.Queue)
  - core.context._push_fiqh_status helper (silent no-op when queue unset)
  - Real-time SSE status events emitted from fiqh sub-graph nodes during the 10-15s window
  - Iteration-aware filtering (per-stage labels first pass; "Searching deeper..." on retries)
  - Producer/consumer multiplex in core.pipeline_langgraph.response_generator
affects:
  - core/context.py
  - agents/fiqh/fiqh_graph.py
  - agents/core/chat_agent.py
  - core/pipeline_langgraph.py
  - tests/test_pipeline_realtime_fiqh_sse.py (new)
tech_stack:
  added: []
  patterns:
    - "Contextvar-bound asyncio.Queue: fiqh sub-graph nodes call _push_fiqh_status at entry; pipeline producer/consumer drains the queue alongside agent.astream events."
    - "Producer/consumer split: an inner _agent_producer task drives agent.astream and pushes SSE strings into a single output queue; the outer generator yields based on item type (str=SSE, dict=fiqh status)."
key_files:
  created:
    - .planning/quick/260509-3cd-realtime-fiqh-sse-status-events/260509-3cd-PLAN.md
    - .planning/quick/260509-3cd-realtime-fiqh-sse-status-events/260509-3cd-SUMMARY.md
    - tests/test_pipeline_realtime_fiqh_sse.py
  modified:
    - core/context.py
    - agents/fiqh/fiqh_graph.py
    - agents/core/chat_agent.py
    - core/pipeline_langgraph.py
decisions:
  - "Use a contextvar-bound asyncio.Queue rather than LangGraph's native custom-stream mechanism (get_stream_writer requires LG 0.3.x; project is on 0.2.64)."
  - "Single multiplexed output queue: producer puts SSE strings, fiqh nodes put dicts; consumer dispatches by item type. Avoids two-source merge complexity."
  - "Iteration UX: first pass emits per-stage labels (decompose/retrieve/filter/assess); iteration >= 2 collapses to a single 'Searching deeper for evidence...' from _refine_node entry. (Per user decision.)"
  - "Keep retrospective fiqh_status_events replay path as a fallback gated on fiqh_realtime_count == 0 — fires only when the real-time queue produced nothing (e.g. sub-graph raised before any node ran)."
  - "Skip emitting NODE_STATUS_MESSAGES['fiqh_subgraph'] from the producer loop — the keep-alive 'Processing fiqh query...' message is now pushed via the queue from _call_fiqh_subgraph_node entry. Emitting it again from astream would duplicate."
  - "The keep-alive 'Processing fiqh query (this may take 10-15 seconds)...' is retained as a brief intro before the first real-time stage event. (Per user decision.)"
  - "Errors inside _push_fiqh_status are swallowed (DEBUG-logged) — a transient queue issue must never abort the sub-graph."
metrics:
  duration: "~50 minutes"
  completed: "2026-05-10"
  tasks: 5
  files_modified: 4
  files_created: 3
  commits: 5
---

# Quick Task 260509-3cd: Real-Time Fiqh SSE Status Events — Summary

Real-time SSE status emission from fiqh sub-graph nodes — eliminates the
10-15 second silent gap between "Fiqh query detected..." and the streamed
answer that prior task `260420-t2v` explicitly deferred.

## Problem

`260420-t2v` accumulated fiqh sub-graph status events in
`FiqhState["status_events"]` and replayed them all at once after the
sub-graph finished — the user saw "Fiqh query detected..." → ~10-15s of
silence → a rapid-fire trail (`Decomposing... Retrieving... Filtering...
Assessing...`) right before the answer streamed. From the parent graph's
perspective the sub-graph is a single atomic node (`agent.astream` only
yields after the node completes), so node-arrival statuses for fiqh stages
could not flow during the wait.

## Fix

A contextvar-bound `asyncio.Queue` lets fiqh sub-graph nodes push status
events the moment each stage starts. `pipeline_langgraph.response_generator`
runs an inner `_agent_producer` task that drives `agent.astream` and pushes
its translated SSE strings into the same queue; the outer generator yields
items as they arrive, so fiqh stage progress is interleaved with agent
events in real time.

## Files Changed

### `core/context.py` (modified)

- Added `fiqh_status_queue: ContextVar[Optional[asyncio.Queue]]` (default None).
- Added `_push_fiqh_status(step, message)` helper that `put_nowait`s a status
  dict if the queue is set; silent no-op otherwise. Errors swallowed and
  logged at DEBUG.
- Imports `asyncio`, `logging`, `Optional`.

### `agents/fiqh/fiqh_graph.py` (modified)

- Imports `_push_fiqh_status` from `core.context`.
- `_decompose_node`: pushes `("fiqh_decompose", "Decomposing fiqh query...")` always.
- `_retrieve_node`: pushes `("fiqh_retrieve", "Retrieving fiqh documents...")`
  ONLY when `state["iteration"] == 0` (first pass, before increment).
- `_filter_node`: pushes `("fiqh_filter", "Filtering evidence...")` ONLY
  when `state["iteration"] == 1`.
- `_assess_node`: pushes `("fiqh_assess", "Assessing evidence sufficiency...")`
  ONLY when `state["iteration"] == 1`.
- `_refine_node`: pushes `("fiqh_searching_deeper", "Searching deeper for
  evidence...")` always (refine only runs on retries).
- The accumulated `status_events` list is unchanged — retrospective replay
  in `pipeline_langgraph.py` still consumes it as the fallback.

### `agents/core/chat_agent.py` (modified)

- `_call_fiqh_subgraph_node` now pushes the keep-alive intro
  `"Processing fiqh query (this may take 10-15 seconds)..."` via
  `_push_fiqh_status` BEFORE awaiting `fiqh_subgraph.ainvoke(...)`. This
  emits the latency-expectation message at sub-graph start instead of the
  prior post-completion arrival.

### `core/pipeline_langgraph.py` (modified — largest change)

- Imports `fiqh_status_queue` from `core.context`.
- `response_generator()` refactored to a producer/consumer pattern:
  - Creates `output_queue: asyncio.Queue` and binds it to the contextvar
    via `set()` (released in `finally`).
  - Inner `_agent_producer()` coroutine drives `agent.astream` and pushes
    translated SSE strings into the queue. Mutable state (`final_state`,
    `emitted_tool_call_ids`, `fiqh_trail_emitted`) is captured via closure
    boxes so the post-loop body can read it.
  - Skips emitting `NODE_STATUS_MESSAGES["fiqh_subgraph"]` from the
    producer (keep-alive is pushed via queue from `_call_fiqh_subgraph_node`
    entry — emitting again would duplicate).
  - Retrospective `fiqh_status_events` replay path is gated on
    `fiqh_realtime_count == 0`. When the real-time queue emitted at least
    one fiqh status, retrospective replay is suppressed and
    `fiqh_trail_emitted_box["v"]` is set to True.
  - Producer runs as `asyncio.create_task(...)`. The outer body becomes a
    `while True: await output_queue.get()` consumer that yields based on
    item type:
    - `_AGENT_DONE` sentinel → break.
    - `dict` (fiqh status from contextvar) → wrap as `status` SSE,
      increment `fiqh_realtime_count`, yield.
    - `str` (SSE event from producer) → yield as-is.
  - After consumer loop: `await producer_task` to propagate exceptions.
- The post-loop body (early-exit, fiqh streaming, hadith streaming, done,
  error handler) is unchanged. The canned-stages fallback remains gated on
  `fiqh_trail_emitted is False` as a deepest safety net.
- `finally` clause resets the contextvar so a later request on the same
  task chain cannot inherit a closed queue.

### `tests/test_pipeline_realtime_fiqh_sse.py` (new)

- `test_push_fiqh_status_writes_to_queue` — happy path.
- `test_push_fiqh_status_noop_when_unset` — default contextvar None is silent no-op.
- `test_push_fiqh_status_swallows_full_queue_errors` — bounded queue at
  capacity does not raise out of the helper.

## Before / After Order

### Fiqh query (first iteration sufficient)

**Before (260420-t2v):**

```
status starting              "Checking query classification..."   <-- pre-flight
status fiqh_classification   "Fiqh query detected..."
... ~10-15s silence (sub-graph running) ...
status fiqh_subgraph         "Processing fiqh query (10-15s)..."  <-- post-completion
status fiqh_decompose        "Decomposing fiqh query..."          <-- retrospective
status fiqh_retrieve         "Retrieving fiqh documents..."       <-- retrospective
status fiqh_filter           "Filtering evidence..."              <-- retrospective
status fiqh_assess           "Assessing evidence sufficiency..."  <-- retrospective
status generate_fiqh_response "Preparing fiqh answer..."
response_chunk * N
...
```

**After (260509-3cd):**

```
status starting              "Checking query classification..."   <-- pre-flight
status fiqh_classification   "Fiqh query detected..."
status fiqh_subgraph         "Processing fiqh query (10-15s)..."  <-- now real-time
status fiqh_decompose        "Decomposing fiqh query..."          <-- real-time
status fiqh_retrieve         "Retrieving fiqh documents..."       <-- real-time
status fiqh_filter           "Filtering evidence..."              <-- real-time
status fiqh_assess           "Assessing evidence sufficiency..."  <-- real-time
status generate_fiqh_response "Preparing fiqh answer..."
response_chunk * N
...
```

Each stage event now arrives the moment that stage starts (1–4s apart in
practice), so the frontend sees continuous progress rather than a silent
window followed by a burst.

### Fiqh query with refinement (iteration 2)

**After:**

```
status starting              ...
status fiqh_classification   ...
status fiqh_subgraph         "Processing fiqh query (10-15s)..."
status fiqh_decompose        ...
status fiqh_retrieve         "Retrieving fiqh documents..."
status fiqh_filter           "Filtering evidence..."
status fiqh_assess           "Assessing evidence sufficiency..."
status fiqh_searching_deeper "Searching deeper for evidence..."   <-- collapses retry
... (no per-stage labels emitted on iteration 2; user already sees activity) ...
status generate_fiqh_response ...
```

## Test Evidence

```
$ pytest tests/test_pipeline_realtime_fiqh_sse.py -v
tests/test_pipeline_realtime_fiqh_sse.py::test_push_fiqh_status_writes_to_queue PASSED
tests/test_pipeline_realtime_fiqh_sse.py::test_push_fiqh_status_noop_when_unset PASSED
tests/test_pipeline_realtime_fiqh_sse.py::test_push_fiqh_status_swallows_full_queue_errors PASSED
3 passed in 0.02s

$ pytest tests/test_fiqh_integration.py -k stage_status_events -q
1 passed (canned-fallback path unchanged)
```

Full suite: 11 pre-existing failures at HEAD `6241c04` (pre-task) match 11
pre-existing failures after this plan's commits — no new regressions
introduced. Pre-existing failures cover `test_primer_service` (5),
`test_agentic_streaming_pipeline` (4 — env-bootstrap dependent),
`test_agentic_streaming_sse::test_agentic_streaming_emits_granular_status_events`
(graceful-skip path triggered by env), and
`test_fiqh_integration::TestFiqhRouting::test_out_of_scope_routes_to_exit`.

Smoke imports (all PASS):
```
$ python -c "from core.context import fiqh_status_queue, _push_fiqh_status; print('OK')"
OK
$ python -c "from agents.fiqh.fiqh_graph import fiqh_subgraph; print('OK')"
OK
$ python -c "from agents.core.chat_agent import ChatAgent; print('OK')"
OK
$ python -c "from core import pipeline_langgraph; print('OK')"
OK
```

## Commits

- `f599db6` — `feat(260509-3cd): add fiqh_status_queue contextvar + helper`
- `a0821a4` — `feat(260509-3cd): emit fiqh sub-graph status events in real-time`
- `504fec4` — `feat(260509-3cd): push fiqh keep-alive intro from wrapper node entry`
- `1e1c4e5` — `feat(260509-3cd): producer/consumer refactor for real-time fiqh SSE multiplexing`
- `94a06d4` — `test(260509-3cd): unit tests for fiqh status queue helper`

## Deviations from Plan

**None material.** Plan followed step-by-step.

## Out of Scope / Deferred

- Pre-existing `LARGE_LLM=claude-sonnet-4-6` env / `max_tokens=None`
  pipeline-bootstrap failure (carried over from `260420-t2v/deferred-items.md`).
- The 5 `test_primer_service` failures and 4 `test_agentic_streaming_pipeline`
  failures present at pre-task HEAD remain. None are touched by this plan.
- The pre-existing `TestFiqhRouting::test_out_of_scope_routes_to_exit` failure
  (router asserts "exit" but gets "continue" for `OUT_OF_SCOPE_FIQH`) — present
  before this plan, untouched.

## Self-Check: PASSED

- [x] `core/context.py` — modified (contextvar + helper)
- [x] `agents/fiqh/fiqh_graph.py` — modified (real-time push at each node entry; iteration filter)
- [x] `agents/core/chat_agent.py` — modified (keep-alive push from wrapper node)
- [x] `core/pipeline_langgraph.py` — modified (producer/consumer refactor + finally cleanup)
- [x] `tests/test_pipeline_realtime_fiqh_sse.py` — created (3 tests, all PASS)
- [x] All 5 commits exist
- [x] Existing fiqh integration test (canned-fallback path) PASSES unchanged
- [x] Full suite: no new regressions (same 11 pre-existing failures)
- [x] SSE contract preserved: `status` event payload `{step, message}` shape
      unchanged; new `step` value `fiqh_searching_deeper` is additive (clients
      already ignore unknown step values per the existing extensibility note)
- [x] `chat_persistence_service.extract_answer_text` still compatible: it reads
      only `response_chunk` token payloads, which are unchanged
