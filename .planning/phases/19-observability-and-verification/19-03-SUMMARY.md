---
phase: 19-observability-and-verification
plan: "03"
subsystem: observability
tags: [sentry, cache-metrics, testing, oss-02, checklist]
dependency_graph:
  requires: [19-01, 19-02]
  provides: [OBS-01-tests, OBS-02-checklist]
  affects: [tests/test_cache_metrics_breadcrumb.py]
tech_stack:
  added: []
  patterns: [monkeypatch-both-module-namespaces, FakeAgent-pipeline-control]
key_files:
  created:
    - tests/test_cache_metrics_breadcrumb.py
    - .planning/phases/19-observability-and-verification/DEE-50-POST-DEPLOY-CHECKLIST.md
  modified: []
decisions:
  - "Used FakeAgent (not _FakeLLM) pattern: patching pipeline_langgraph.ChatAgent with a controlled astream yields final_state directly — avoids driving real LangGraph graph through fiqh classifier and all other nodes"
  - "Patched both core.sentry.record_cache_metrics_breadcrumb AND core.pipeline_langgraph.record_cache_metrics_breadcrumb to handle Python import-bound names (T-19-10)"
  - "9 tests (5 pipeline-level, 4 unit-direct) instead of 5 minimum — added multi-iteration aggregation, early-exit path, _emit_cache_metrics_breadcrumb direct unit tests for comprehensive coverage"
  - "Phase 17/18/19-01/19-02 code forward-ported to worktree via git show from feature/release-llm-cache-cost-reduction — worktree was on older base missing those commits"
  - "Task 3 (OBS-02 closure) surfaced as pending checkpoint:human-action per D-12 — not attempted autonomously"
metrics:
  duration: "~30 minutes"
  completed_date: "2026-05-04"
  tasks_completed: 2
  tasks_pending: 1
  files_created: 2
  files_modified: 7
---

# Phase 19 Plan 03: OBS-01 Tests + OBS-02 Checklist Summary

**One-liner:** Hermetic unit-seam tests for the per-turn cache efficiency breadcrumb (9 passing, 2.56s) and a copy-paste Linear comment template for OBS-02 post-deploy closure.

## Tasks Completed

### Task 1: Hermetic unit-seam tests for OBS-01 (COMPLETE)
**Commit:** `33cd5ab` — `DEE-50: test(19-03): hermetic unit-seam tests for OBS-01 cache breadcrumb`

Created `tests/test_cache_metrics_breadcrumb.py` with 9 hermetic tests:

| Test | Coverage |
|------|----------|
| `test_cold_cache_ratio_is_zero` | D-06 + ROADMAP criterion 2: zero tokens → ratio 0.0, no ZeroDivisionError |
| `test_warm_cache_ratio_matches_sum_then_divide` | D-05: pure read turn → ratio 1.0 |
| `test_multi_iteration_aggregation_is_token_weighted` | D-05: equal creation+read → ratio 0.5 |
| `test_breadcrumb_payload_shape_locked_to_d08` | D-08: exactly 4 canonical keys |
| `test_breadcrumb_fires_on_early_exit_path` | D-02: breadcrumb fires on early-exit path |
| `test_breadcrumb_no_op_when_sentry_disabled` | D-09: SENTRY_ENABLED=false → no SDK call |
| `test_breadcrumb_helper_emits_when_sentry_enabled` | D-08+D-09: correct category/level/message/data |
| `test_emit_helper_direct_cold_cache` | Unit: _emit_cache_metrics_breadcrumb with zero tokens |
| `test_emit_helper_handles_none_final_state` | Defensive: None final_state handled |

All tests run in 2.56s (well under 10s requirement). Both `core.sentry.record_cache_metrics_breadcrumb` AND `core.pipeline_langgraph.record_cache_metrics_breadcrumb` are patched (T-19-10 mitigation).

**Verification:** `pytest tests/test_cache_metrics_breadcrumb.py -q` — 9 passed, 3 warnings, 2.56s

### Task 2: DEE-50 post-deploy checklist (COMPLETE)
**Commit:** `f779323` — `DEE-50: docs(19-03): create post-deploy checklist for OBS-02 closure`

Created `.planning/phases/19-observability-and-verification/DEE-50-POST-DEPLOY-CHECKLIST.md` with:
- Explicit D-12 language: "Required manual action — OBS-02 cannot be closed by automated tasks"
- 4-step procedure: verify deploy → trigger 2 turns within 5 minutes → observe Sentry breadcrumbs → post Linear comment
- Copy-paste Linear comment template with all 3 D-11 sections pre-filled from Phase 17/18 sources:
  1. Eligible call sites (ChatAgent path + 6 fiqh modules + explicit exclusions)
  2. Approach taken (content-block format, cache_control on last tool, response_metadata["usage"], SENTRY_ENABLED guard)
  3. Measured hit rate (placeholder table for developer to fill post-deploy)

## Task 3: OBS-02 Closure — PENDING (checkpoint:human-action)

**Status:** Pending — developer must perform this after production deployment.
**Resume artifact:** `.planning/phases/19-observability-and-verification/DEE-50-POST-DEPLOY-CHECKLIST.md`
**Resume signal:** Type `obs-02-closed` after posting the Linear comment with measured hit rates.

Per D-12: OBS-02 requires production traffic to measure a non-zero `cache_efficiency_ratio` in Sentry. This cannot be automated. The developer must:

1. Deploy Phase 19 (Plans 01 + 02 + 03 Task 1) to production
2. Send two identical queries to `/chat/stream/agentic` within 5 minutes
3. Observe the Sentry breadcrumbs (cold turn → ratio 0.0, warm turn → ratio > 0.0)
4. Post the Linear comment on DEE-50 (using the template in the checklist)
5. Update STATE.md to mark OBS-02 verified, ROADMAP.md Phase 19 criterion 3 met

## Deviations from Plan

### Auto-applied (worktree base)
**[Rule 3 - Blocking] Forward-ported Phase 17/18/19-01/19-02 code to worktree**
- **Found during:** Task 1 setup
- **Issue:** Worktree branch `worktree-agent-ab585f1dcca9ceee9` was created from commit `8fa93ef` (DEE-44 async migration), which predates Phase 17/18/19 feature work on `feature/release-llm-cache-cost-reduction`. The test file imports `core.sentry.record_cache_metrics_breadcrumb`, `core.pipeline_langgraph._emit_cache_metrics_breadcrumb`, etc. — none of which existed in the worktree.
- **Fix:** Used `git show feature/release-llm-cache-cost-reduction:<file>` to copy 7 files into the worktree: `core/sentry.py`, `agents/state/chat_state.py`, `agents/core/chat_agent.py`, `core/pipeline_langgraph.py`, `agents/tools/retrieval_tools.py`, `core/chat_models.py`, `core/prompt_templates.py`
- **Files modified:** 7 files (all feature-branch commits, not new code)
- **Commit:** `7e16d2a`

### Design choice
**Used FakeAgent not _FakeLLM for pipeline tests**
- The plan's action text showed a `_FakeLLM` skeleton, but using `_FakeLLM` would require driving the full LangGraph graph through the fiqh classifier (which calls the real LLM) before reaching `_agent_node`. The `FakeAgent` pattern (from `test_agentic_streaming_pipeline.py:test_streaming_pipeline_uses_runtime_history_and_appends_once`) patches `pipeline_langgraph.ChatAgent` directly, giving full control over `final_state` including the `cache_creation_tokens_total`/`cache_read_tokens_total` fields — which is the actual data source for `_emit_cache_metrics_breadcrumb`. This is cleaner, faster, and more hermetic.

## Test Results

```
pytest tests/test_cache_metrics_breadcrumb.py -q
9 passed, 3 warnings in 2.56s
```

Pre-existing test failures (not caused by this plan): 12 failures in `test_agentic_streaming_pipeline.py`, `test_agentic_streaming_sse.py`, `test_chat_agent_async.py`, `test_concurrency_baseline.py`, `test_fiqh_graph_logging.py`, `test_fiqh_integration.py` — confirmed pre-existing by stash test (present on worktree before any of this plan's changes).

## Known Stubs

None — the test file asserts real behavior, not stubs. The checklist file has `<...>` placeholders intentionally (they are meant for the developer to fill in post-deploy).

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced. The test file is hermetic (no external network calls). The checklist file is a documentation artifact.

## Self-Check

Checking created files exist and commits are present:
- `tests/test_cache_metrics_breadcrumb.py`: FOUND
- `.planning/phases/19-observability-and-verification/DEE-50-POST-DEPLOY-CHECKLIST.md`: FOUND
- Commit `33cd5ab`: FOUND (test(19-03) commit)
- Commit `f779323`: FOUND (docs(19-03) commit)

## Self-Check: PASSED
