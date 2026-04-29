---
phase: 15-pipeline-and-tools-instrumentation
plan: "02"
subsystem: agents
tags: [logging, sentry, structured-logging, langgraph, print-removal]
dependency_graph:
  requires:
    - 13-sentry-infrastructure
    - core/context.py (correlation_id ContextVar)
    - core/logging_config.py (ExtraFormatter, setup_logging)
  provides:
    - agents/core/chat_agent.py structured logging (zero print() calls)
  affects:
    - Sentry error capture via LoggingIntegration on all 7 ChatAgent node exception paths
tech_stack:
  added: []
  patterns:
    - "logger.debug() for all node traversal, routing, iteration events"
    - "logger.error(exc_info=True) for all exception paths — LoggingIntegration fires automatically"
    - "correlation_id_ctx.get() in every extra={} dict"
    - "D-04: LLM response content print dropped entirely — no replacement"
    - "D-05: user_query/working_query excluded from all extra={} dicts"
    - "D-07: tool result payload dropped — tool_name only in debug log"
key_files:
  modified:
    - agents/core/chat_agent.py
decisions:
  - "D-04 applied: agent response content print (lines 172-175) deleted entirely — LLM content must not appear in logs"
  - "D-05 applied: fiqh subgraph node previously logged state['user_query'][:80] — replacement has no user content in extra={}"
  - "D-07 applied: tool result payload (str(result_data)[:200]) replaced with tool_name only"
  - "D-02 applied: all 7 error sites use logger.error(exc_info=True) only — no capture_exception() — prevents duplicate Sentry events"
  - "import logging placed after existing local imports per CLAUDE.md import ordering convention"
metrics:
  duration: "~8 minutes"
  completed: "2026-04-28T02:01:57Z"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 1
requirements_completed:
  - TOOL-02
---

# Phase 15 Plan 02: ChatAgent Structured Logging Summary

Zero print() calls in agents/core/chat_agent.py — all 20 print sites converted to structured logger.debug() or logger.error(exc_info=True) with correlation_id in every extra={} dict.

## What Was Built

Replaced all ~20 `print()` calls in `agents/core/chat_agent.py` with structured `logger.*` calls following the Phase 14 established pattern. Added the standard module-level logger declaration (`import logging`, `from core.context import correlation_id as correlation_id_ctx`, `logger = logging.getLogger(__name__)`).

The file now has:
- **25 `logger.debug()` calls** — covering all node traversal events (`_fiqh_classification_node`, `_agent_node`, `_tool_node`, `_generate_response_node`, `_check_early_exit_node`, `_call_fiqh_subgraph_node`, `_generate_fiqh_response_node`) and all routing decisions in `_route_after_fiqh_check` and `_should_continue`
- **7 `logger.error(exc_info=True)` calls** — one per exception site: fiqh classification, agent node, response generation, LLM rejection (check_early_exit), fiqh sub-graph, fiqh response generation, load_runtime_messages
- **Zero `capture_exception()` calls** — LoggingIntegration auto-captures ERROR-level logs, preventing duplicate Sentry events

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| D-04: Drop agent response content print (lines 172-175) entirely | LLM response content may paraphrase user's original query — must not appear in logs at any level |
| D-05: No user_query in fiqh_subgraph node log | Previously `state['user_query'][:80]` was logged — replaced with doc_count and status_event_count only |
| D-07: Tool result payload dropped from tool_node log | `str(result_data)[:200]` may contain retrieved document text — tool_name only is logged |
| D-02: logger.error(exc_info=True) only | LoggingIntegration fires on ERROR — adding capture_exception() would create duplicate Sentry events |

## Verification Results

| Check | Result |
|-------|--------|
| `print()` count | 0 (PASS) |
| `capture_exception` count | 0 (PASS) |
| `import logging` | 1 (PASS) |
| `from core.context import correlation_id as correlation_id_ctx` | 1 (PASS) |
| `logger = logging.getLogger(__name__)` | 1 (PASS) |
| `logger.debug()` count | 25 (PASS — >= 15) |
| `logger.error()` count | 7 (PASS) |
| `exc_info=True` count | 7 == 7 (PASS — every error log uses exc_info=True) |
| `bind_sentry_scope` count | 0 (PASS) |
| `user_query`/`working_query` in any extra={} | 0 (PASS) |
| Python AST syntax check | OK (PASS) |

## Deviations from Plan

None — plan executed exactly as written. All 20 print sites converted per the method-by-method mapping in PLAN.md. D-04 deletion confirmed (the 3-line multi-line print block at former lines 172-175 removed, except clause now follows immediately).

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, or file access patterns introduced. The four threat mitigations from the plan's threat model are all applied:
- T-15-05: user_query dropped from fiqh_subgraph log extra — only doc_count and status_event_count logged
- T-15-06: agent response content print deleted entirely (D-04)
- T-15-07: all 7 error sites use logger.error(exc_info=True) only — zero capture_exception() calls
- T-15-08: tool result payload dropped from tool_node log — tool_name only

## Self-Check: PASSED

- `/Users/shawn.n/Desktop/Deen/deen-backend/.claude/worktrees/agent-a20d0a8b926bdd802/agents/core/chat_agent.py` — exists, verified 0 print() calls, syntax OK
- Commit `6a16eb6` — verified in git log
