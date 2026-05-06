---
phase: 19-observability-and-verification
plan: "01"
subsystem: observability
tags: [sentry, cache-metrics, chatstate, langgraph, breadcrumb]
requirements-completed: [OBS-01]

dependency-graph:
  requires:
    - "17-chatagent-caching-foundation (ChatAgent cache metrics extraction in _agent_node)"
    - "13-sentry-deep-integration (core/sentry.py SENTRY_ENABLED guard pattern)"
  provides:
    - "record_cache_metrics_breadcrumb helper (core/sentry.py) — callable by Plan 19-02"
    - "cache_creation_tokens_total / cache_read_tokens_total fields on ChatState — writable by Plan 19-02, readable by Plan 19-02 at SSE done"
  affects:
    - "agents/core/chat_agent.py (_agent_node must accumulate into new ChatState fields — Plan 19-02)"
    - "core/pipeline_langgraph.py (must fire breadcrumb at done sites — Plan 19-02)"

tech-stack:
  added: []
  patterns:
    - "SENTRY_ENABLED no-op guard on new sentry helper (mirrors bind_sentry_scope pattern)"
    - "TypedDict int field + create_initial_state factory default (mirrors iterations field pattern)"
    - "Keyword-only function signature (*,) for four homogeneous numeric args"

key-files:
  created: []
  modified:
    - "core/sentry.py (appended record_cache_metrics_breadcrumb, lines 76-112)"
    - "agents/state/chat_state.py (added cache_creation_tokens_total and cache_read_tokens_total fields + initializers)"

decisions:
  - "D-07 option (b) chosen: ChatState fields over ContextVar — matches existing final_state.get(...) read pattern in pipeline_langgraph.py; less invasive than adding ContextVar + middleware reset"
  - "Helper is a pure observability sink: caller computes ratio, handles ZeroDivisionError (D-06); helper only emits breadcrumb"
  - "Keyword-only args (*,) prevent positional drift across four homogeneous numeric parameters"
  - "Data dict keys locked by D-08: cache_efficiency_ratio, cache_read_tokens, cache_creation_tokens, iterations"

metrics:
  duration: "~7 minutes"
  completed: "2026-05-04"
  tasks-completed: 2
  tasks-total: 2
  files-changed: 2
---

# Phase 19 Plan 01: Foundation — Sentry Breadcrumb Helper and ChatState Accumulator Fields

Additive foundation delivering the Sentry breadcrumb helper (`record_cache_metrics_breadcrumb`) and two per-turn int accumulator fields (`cache_creation_tokens_total`, `cache_read_tokens_total`) on `ChatState`. Zero behavior change — no call site is wired; Plan 19-02 wires `_agent_node` as writer and `pipeline_langgraph.py` as reader.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add record_cache_metrics_breadcrumb helper to core/sentry.py | eddad24 | core/sentry.py (+39 lines) |
| 2 | Add cache_creation_tokens_total and cache_read_tokens_total to ChatState | 3d69a2d | agents/state/chat_state.py (+9 lines) |

## What Was Built

**Task 1 — `core/sentry.py:record_cache_metrics_breadcrumb`**

New function appended after `bind_sentry_scope`. Mirrors the existing helper's SENTRY_ENABLED no-op guard pattern exactly: first statement after docstring is `if not SENTRY_ENABLED: return`. Uses keyword-only args (`*,`) to prevent positional drift. Emits `sentry_sdk.add_breadcrumb` with locked D-08 shape: `category="cache_metrics"`, `level="info"`, `message="cache_efficiency"`, `data={cache_efficiency_ratio, cache_read_tokens, cache_creation_tokens, iterations}`. Caller pre-computes the ratio and handles the cold-cache edge case — helper is a pure sink.

**Task 2 — `agents/state/chat_state.py` accumulator fields**

Two new `int` fields inserted under a new `# Cache metrics (Phase 19, D-07 option b)` section immediately after the existing `# Metadata` section and its `iterations` field. Both fields carry one-line docstrings per the existing TypedDict convention. Both initialized to `0` in `create_initial_state` immediately after `iterations=0,`. No existing field reordered, renamed, or retyped.

## Verification

- `from core.sentry import record_cache_metrics_breadcrumb` — import succeeds
- `record_cache_metrics_breadcrumb(cache_efficiency_ratio=0.0, ..., iterations=0)` with `SENTRY_ENABLED` unset — returns `None`, no exception, no Sentry call
- `create_initial_state(user_query="q", session_id="s")` — `cache_creation_tokens_total == 0`, `cache_read_tokens_total == 0`, `iterations == 0`
- `tests/test_agentic_streaming_pipeline.py` — 7/7 pass
- `git diff` shows only additions on both files — no deletions, no reordering

## Deviations from Plan

None — plan executed exactly as written. Both tasks are purely additive; no existing function body was modified.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. The `record_cache_metrics_breadcrumb` helper touches the Sentry SDK only when `SENTRY_ENABLED=true` — consistent with the existing threat analysis in the plan's `<threat_model>` (T-19-01 through T-19-04). No new threat surface beyond what the plan already addressed.

## Known Stubs

None. This plan delivers infrastructure surfaces only (helper + state fields). No data flows to UI. Plan 19-02 wires the accumulation and breadcrumb emission.

## Self-Check: PASSED

- `core/sentry.py` exists and contains `def record_cache_metrics_breadcrumb` at line 76 — FOUND
- `agents/state/chat_state.py` exists and contains `cache_creation_tokens_total: int` at line 124 — FOUND
- Commit `eddad24` exists in git log — FOUND
- Commit `3d69a2d` exists in git log — FOUND
