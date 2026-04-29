---
phase: 16-fiqh-sub-graph-instrumentation
plan: "01"
subsystem: infra
tags: [logging, sentry, langgraph, fiqh, structured-logging, correlation-id]

# Dependency graph
requires:
  - phase: 13-sentry-infrastructure
    provides: core/context.py (correlation_id ContextVar), core/sentry.py (LoggingIntegration), core/logging_config.py (ExtraFormatter)
  - phase: 15-pipeline-and-tools-instrumentation
    provides: extra={} structured logging pattern established in agents/tools/retrieval_tools.py

provides:
  - Fully instrumented FAIR-RAG sub-graph with structured extra={} logging in all 5 nodes and 1 routing function
  - Three Sentry-searchable WARNING boundaries: zero-doc retrieval (FIQH-02), filter drops all docs (FIQH-03), max iterations exhausted INSUFFICIENT (FIQH-04)
  - Unit test suite proving all three WARNING events fire at the correct code paths

affects: [sentry-dashboard, fiqh-monitoring, 17-any-future-fiqh-phase]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "extra={} structured logging with correlation_id_ctx.get() in every log call"
    - "WARNING-on-failure-boundary pattern: log WARNING before continuing on silent failure path"
    - "Deferred-import patch target: patch source module (modules.fiqh.xxx) not fiqh_graph.py module level"
    - "TDD RED/GREEN for instrumentation: write failing tests for new WARNING calls, then implement"

key-files:
  created:
    - tests/test_fiqh_graph_logging.py
  modified:
    - agents/fiqh/fiqh_graph.py

key-decisions:
  - "D-01 through D-11 from 16-CONTEXT.md applied: only available fields in extra={}, correlation_id in every call, no query content, no capture_exception()"
  - "D-06: current_query[:60] dropped from _retrieve_node log — PII risk (sub-queries derive from user query)"
  - "D-07: FIQH-02 WARNING fires inside try block before dedup loop; INFO log fires unconditionally"
  - "D-08: FIQH-03 WARNING inside try block only — except-clause fail-open path gets ERROR only, not WARNING"
  - "D-09: FIQH-04 WARNING guarded by state['verdict'] != 'SUFFICIENT' to prevent false-positive on SUFFICIENT+iteration>=3 exits"
  - "D-10/D-11: logger.error(exc_info=True) only — no capture_exception() to avoid duplicate Sentry events"
  - "Local variable 'iteration' used in _retrieve_node log calls (not state['iteration'] which is pre-increment)"

patterns-established:
  - "WARNING-on-boundary: log.warning() BEFORE continuing on a silent failure, not instead of continuing"
  - "Patch deferred imports at source module for unit tests (Pitfall 6 from research)"

requirements-completed: [FIQH-01, FIQH-02, FIQH-03, FIQH-04]

# Metrics
duration: 7min
completed: 2026-04-29
---

# Phase 16 Plan 01: Fiqh Sub-graph Instrumentation Summary

**Structured extra={} logging added to all FAIR-RAG nodes in fiqh_graph.py, with three new Sentry-searchable WARNING boundaries for zero-doc retrieval, evidence filter loss, and iteration exhaustion**

## Performance

- **Duration:** 7 min
- **Started:** 2026-04-29T00:29:18Z
- **Completed:** 2026-04-29T00:36:46Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- FIQH-01: All 10 existing `%s` format-string log calls converted to `extra={}` style — zero format strings remain, every call has `correlation_id` and domain fields (`iteration`, `verdict`, `doc_count` where available per node)
- FIQH-02/03/04: Three new `logger.warning()` calls added at the three FAIR-RAG silent failure boundaries, producing Sentry-searchable events with `iteration:N`, `verdict:V`, and `doc_count:0` as top-level attributes
- 7 unit tests in `tests/test_fiqh_graph_logging.py` prove all three WARNING boundaries fire exactly when expected and do not fire on success paths

## Task Commits

Each task was committed atomically following TDD flow:

1. **RED: test(16-01)** — `e9c1c33` (test) — failing tests for FIQH-02/03/04 WARNING boundaries (3 failing, 4 passing vacuously)
2. **GREEN: feat(16-01)** — `fa35e6b` (feat) — instrumented fiqh_graph.py; all 7 tests now pass

_TDD gate compliance: RED commit `e9c1c33` precedes GREEN commit `fa35e6b`._

## Files Created/Modified

- `agents/fiqh/fiqh_graph.py` — Added `correlation_id_ctx` import; converted 10 log calls to `extra={}` style; added 3 new WARNING calls at FIQH-02/03/04 boundaries; no behavior changes to FAIR-RAG loop
- `tests/test_fiqh_graph_logging.py` — 7 unit tests covering all 3 WARNING boundaries and their negative cases; uses deferred-import patch pattern (source module, not fiqh_graph.py module level)

## Decisions Made

All decisions were pre-locked in `16-CONTEXT.md` (D-01 through D-11). No discretionary choices were needed during execution. Key decisions applied:

- **D-06 (PII):** `current_query[:60]` dropped from `_retrieve_node` INFO log — sub-queries carry same Islamic content PII risk as original user query
- **D-08 (scope):** FIQH-03 WARNING only inside `try` block — the `except`-clause fail-open path (`filtered = list(state["accumulated_docs"])`) gets an ERROR log, not the WARNING (different failure scenario)
- **D-09 (guard):** FIQH-04 WARNING guarded by `state["verdict"] != "SUFFICIENT"` — prevents false-positive when a SUFFICIENT verdict is reached on the 3rd iteration exactly
- **D-10/D-11 (no duplication):** `logger.error(exc_info=True)` only; `capture_exception()` absent — `LoggingIntegration` auto-captures ERROR-level logs; calling both creates duplicate Sentry events
- **Local variable `iteration`:** All `_retrieve_node` log calls use the local `iteration = state["iteration"] + 1` variable (not `state["iteration"]` which is one less at that point)

## Deviations from Plan

None — plan executed exactly as written. All decisions were pre-locked. The TDD structure (RED commit then GREEN commit) was followed as prescribed.

## Issues Encountered

**Pre-existing test failures (6 unrelated tests):** The full test suite has 6 pre-existing failures in `tests/test_fiqh_integration.py` and `tests/test_primer_service.py` that existed before this plan's changes. Confirmed by `git stash` baseline check. These are out of scope for Phase 16.

## Known Stubs

None — no stubs introduced. Phase 16 is observability-only with no data flow changes.

## Threat Flags

No new threat surface introduced. All threat model items from the plan's `<threat_model>` were addressed:
- T-16-01/T-16-02 (query content in logs): mitigated — `grep` confirms zero query content in any log call
- T-16-03/T-16-04 (correlation_id/doc_count disclosure): accepted per plan design
- T-16-05 (WARNING volume): accepted — WARNINGs fire only on failure paths
- T-16-06 (exc_info leakage): mitigated — `before_send` hook in `core/sentry.py` provides second layer

## TDD Gate Compliance

- RED gate: `e9c1c33` — `test(16-01): add failing tests for FIQH-02/03/04 WARNING boundaries` (3 tests fail, 4 pass)
- GREEN gate: `fa35e6b` — `feat(16-01): instrument fiqh_graph.py with structured logging` (7/7 tests pass)
- No REFACTOR commit needed — no cleanup required after GREEN.

## Next Phase Readiness

- All four FIQH requirements (FIQH-01 through FIQH-04) complete
- Phase 16 is the final phase of v1.3 Sentry Deep Integration milestone
- `agents/fiqh/fiqh_graph.py` is fully instrumented and ready for production Sentry observability when `SENTRY_ENABLED=true`

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `agents/fiqh/fiqh_graph.py` exists | FOUND |
| `tests/test_fiqh_graph_logging.py` exists | FOUND |
| `16-01-SUMMARY.md` exists | FOUND |
| Commit e9c1c33 (RED test) | FOUND |
| Commit fa35e6b (GREEN feat) | FOUND |

---
*Phase: 16-fiqh-sub-graph-instrumentation*
*Completed: 2026-04-29*
