---
phase: 15-pipeline-and-tools-instrumentation
plan: "01"
subsystem: pipeline-logging
tags: [logging, sentry, structured-logging, pipeline, tools]
requirements-completed: [PIPE-01, PIPE-02, TOOL-01]

dependency-graph:
  requires:
    - core/context.py (correlation_id ContextVar — Phase 13)
    - core/logging_config.py (ExtraFormatter — Phase 13)
    - core/sentry.py (LoggingIntegration — Phase 13)
    - api/chat.py (bind_sentry_scope already called upstream — Phase 14)
  provides:
    - core/pipeline_langgraph.py (structured INFO/DEBUG/ERROR/WARNING logging)
    - agents/tools/retrieval_tools.py (structured ERROR logging per tool)
  affects:
    - Sentry Logs stream (pipeline start events, node traversals at DEBUG, errors at ERROR)
    - agents/core/chat_agent.py (called by pipeline — Phase 15 plan 02 scope)

tech-stack:
  added: []
  patterns:
    - "module-level logger via logging.getLogger(__name__)"
    - "correlation_id in every log extra={} via ContextVar.get()"
    - "logger.error(exc_info=True) as sole Sentry capture mechanism — no capture_exception()"
    - "DEBUG for node traversal (not sent to Sentry Logs), INFO for pipeline boundaries"

key-files:
  created: []
  modified:
    - core/pipeline_langgraph.py
    - agents/tools/retrieval_tools.py

decisions:
  - "D-01: node traversal at DEBUG only — avoids Sentry log quota overrun at scale"
  - "D-02: logger.error(exc_info=True) is the sole Sentry capture path — no capture_exception()"
  - "D-03: secondary Redis history write failure uses WARNING (recoverable, no Sentry event)"
  - "D-05: user_query excluded from all extra={} dicts — no user content in logs"
  - "D-08: retrieval_tools.py extra={} contains correlation_id and error string only — no query param"
  - "D-09: import traceback and traceback.print_exc() removed entirely from SSE generator"

metrics:
  duration: "~8 minutes"
  completed: "2026-04-28T02:01:29Z"
  tasks-completed: 2
  tasks-total: 2
  files-modified: 2
---

# Phase 15 Plan 01: Pipeline and Tools Instrumentation Summary

**One-liner:** Replace 9 print() calls across pipeline_langgraph.py and retrieval_tools.py with structured logger.* calls using correlation_id in extra={}, zero capture_exception(), zero user content in logs.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Instrument core/pipeline_langgraph.py — replace 5 print() calls | abd87fd | core/pipeline_langgraph.py |
| 2 | Instrument agents/tools/retrieval_tools.py — replace 4 print() calls | 4146e4b | agents/tools/retrieval_tools.py |

## What Was Built

### Task 1: core/pipeline_langgraph.py

Added structured logging across both pipeline entry points:

- **Import block:** `import logging`, `from core.context import correlation_id as correlation_id_ctx`, `logger = logging.getLogger(__name__)` placed after `from core import utils`
- **5 print() calls replaced:**
  - Line 90: `[AGENTIC PIPELINE] Starting for query:` → `logger.info("Pipeline started")` with session_id, correlation_id, target_language in extra={}
  - Line 122: `[AGENTIC PIPELINE] Node: {node_name}` → `logger.debug("Node traversal")` with correlation_id and node name (DEBUG — never reaches Sentry Logs)
  - Lines 376-378: `[AGENTIC PIPELINE] Error:` + `import traceback` + `traceback.print_exc()` → `logger.error("Pipeline error", exc_info=True)` — 3 lines collapsed to 1 call (D-09)
  - Line 389: `[AGENTIC PIPELINE] Failed to append runtime history:` → `logger.warning("Failed to append runtime history after error", exc_info=True)` — WARNING level (D-03, no Sentry event)
  - Line 414: `[AGENTIC PIPELINE NON-STREAM] Starting for query:` → `logger.info("Pipeline started")` with session_id, correlation_id, target_language

### Task 2: agents/tools/retrieval_tools.py

Added structured error logging to all 4 retrieval tool exception handlers:

- **Import block:** `import logging`, `from core.context import correlation_id as correlation_id_ctx`, `logger = logging.getLogger(__name__)` placed after existing imports
- **4 print() calls replaced** — one per @tool function:
  - `retrieve_shia_documents_tool` except block
  - `retrieve_sunni_documents_tool` except block
  - `retrieve_combined_documents_tool` except block
  - `retrieve_quran_tafsir_tool` except block
  - All replaced with: `logger.error("Retrieval error", exc_info=True, extra={"correlation_id": ..., "error": str(e)})`
- The `return {"documents": [], ..., "error": str(e)}` payloads in each except block are unchanged

## Verification Results

All success criteria met:

```
grep -v "^#" core/pipeline_langgraph.py | grep -c "print("     → 0  PASS
grep -v "^#" agents/tools/retrieval_tools.py | grep -c "print(" → 0  PASS
grep -c "capture_exception" core/pipeline_langgraph.py          → 0  PASS
grep -c "capture_exception" agents/tools/retrieval_tools.py     → 0  PASS
grep -c 'logger.info("Pipeline started"' core/pipeline_langgraph.py  → 2  PASS
grep -c 'logger.debug("Node traversal"' core/pipeline_langgraph.py   → 1  PASS
grep -c 'logger.error("Retrieval error"' agents/tools/retrieval_tools.py → 4  PASS
python3 ast.parse(pipeline_langgraph.py)  → syntax OK
python3 ast.parse(retrieval_tools.py)     → syntax OK
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

No new network endpoints, auth paths, file access patterns, or schema changes introduced. Only logging calls added. Threat mitigations T-15-01 through T-15-04 verified:

| Threat | Mitigation Applied |
|--------|--------------------|
| T-15-01: user_query in log extra={} | No user_query in any extra={} dict in either file |
| T-15-02: Node traversal DEBUG at scale | logger.debug only — below Sentry LoggingIntegration INFO threshold |
| T-15-03: Duplicate Sentry events | logger.error(exc_info=True) only; no capture_exception() anywhere |
| T-15-04: query param in retrieval_tools extra={} | extra={} contains only correlation_id and error string |

## Self-Check: PASSED

- core/pipeline_langgraph.py exists and has 2x logger.info, 1x logger.debug, 1x logger.error, 1x logger.warning
- agents/tools/retrieval_tools.py exists and has 4x logger.error
- Commits abd87fd and 4146e4b exist in git log
- Both files pass ast.parse() with no syntax errors
- Zero print() calls in either file
- Zero capture_exception() calls in either file
