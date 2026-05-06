---
phase: 17-chatagent-caching-foundation
plan: "03"
subsystem: agent-tests
tags: [caching, anthropic, test-script, verification, prompt-cache]
requirements-completed: [CACHE-03]

dependency-graph:
  requires:
    - agents/core/chat_agent.py (ChatAgent.invoke() — delivered by plan 17-02)
    - core/chat_models.py (make_cached_system_message — delivered by plan 17-01)
    - agents/tools/retrieval_tools.py (retrieve_quran_tafsir_tool cache_control — delivered by plan 17-01)
  provides:
    - Standalone cache write/hit verification script for Phase 17 CACHE-03
  affects:
    - agent_tests/test_prompt_cache.py (created)

tech-stack:
  added: []
  patterns:
    - Standalone agent_tests/ script pattern (no pytest, sys.path.insert at top)
    - response_metadata["usage"] for cache metrics extraction from AIMessage final state

key-files:
  created:
    - agent_tests/test_prompt_cache.py
  modified: []

decisions:
  - "Extracts cache metrics from last AIMessage in final_state['messages'] via response_metadata['usage'] — not usage_metadata (LangChain double-counting bug, GitHub #32818)"
  - "Uses distinct session IDs (_call1 / _call2) so LangGraph MemorySaver thread state does not carry over, while Anthropic server-side cache still hits (same static tools+system prefix)"
  - "Follows test_memory_agent.py standalone script pattern — sys.path.insert(0, ...) allows running from project root or agent_tests/ directory"
  - "Exits with sys.exit(1) on assertion failure for CI/CD pipeline detection"

metrics:
  duration: "4 minutes"
  completed: "2026-05-03T21:07:32Z"
  tasks-completed: 1
  tasks-total: 1
  files-created: 1
  files-modified: 0
---

# Phase 17 Plan 03: ChatAgent Caching Foundation — Cache Verification Script Summary

Standalone two-call cache write/hit verification script confirming Anthropic prompt caching works via `cache_creation_input_tokens > 0` on first call and `cache_read_input_tokens > 0` on second call.

## What Was Built

### Task 1: Create agent_tests/test_prompt_cache.py

Created `agent_tests/test_prompt_cache.py` as a 122-line standalone script with no test runner dependency. Key characteristics:

**Design:**
- Calls `ChatAgent().invoke()` twice with identical queries but different `session_id` values (`_call1` / `_call2`). This ensures the two calls do NOT share LangGraph `MemorySaver` state (different `thread_id`s) while still sharing the Anthropic server-side prefix cache (same static tool definitions + system prompt).
- Extracts cache metrics by iterating `final_state["messages"]` in reverse and reading `msg.response_metadata.get("usage", {})` from the last `AIMessage`. This is the same source used in `_agent_node` cache metrics logging (Plan 17-02).
- Does NOT use `usage_metadata` anywhere — that LangChain wrapper double-counts cached tokens in streaming paths (GitHub #32818, CRITICAL-5 from PITFALLS.md).

**Assertions:**
- Call 1: `cache_creation_input_tokens > 0` — cache WRITE (server stores the prefix)
- Call 2: `cache_read_input_tokens > 0` — cache HIT (server serves from cache)

**Human-readable output format (per D-04):**
```
Phase 17: Prompt Cache Verification
==================================================

Call 1 (expect cache WRITE): 'What is the ruling on performing wudu with tap water?'
  cache_creation_input_tokens=<N>, cache_read_input_tokens=0 -> WRITE OK

Call 2 (expect cache HIT):   'What is the ruling on performing wudu with tap water?'
  cache_creation_input_tokens=0, cache_read_input_tokens=<N> -> HIT OK

==================================================
RESULT: PASS — prompt cache is working correctly
  Write tokens cached: <N>
  Read tokens on hit:  <N>
```

**Failure output includes diagnostic hints:**
- Call 1 failure: notes the 2048-token Sonnet minimum threshold and how to measure token count
- Call 2 failure: notes that session IDs must differ and the static prefix must be identical

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | f00ca0b | feat(17-03): add standalone prompt cache verification script |

## Deviations from Plan

None — plan executed exactly as written.

## Acceptance Criteria Verification

| Criterion | Result |
|-----------|--------|
| `agent_tests/test_prompt_cache.py` exists | PASS |
| Syntax check (`ast.parse`) exits 0 | PASS |
| `grep -c "usage_metadata"` returns 0 | PASS (0 occurrences) |
| `grep "response_metadata"` returns >= 1 | PASS (4 occurrences) |
| `grep "cache_creation_input_tokens"` returns >= 2 | PASS (10 occurrences) |
| `grep "cache_read_input_tokens"` returns >= 2 | PASS (10 occurrences) |
| `grep "sys.path.insert"` returns 1 | PASS (line 25) |
| `grep "if __name__"` returns 1 | PASS (line 121) |
| `grep "WRITE OK\|HIT OK"` returns >= 2 | PASS (lines 75, 99) |

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. `agent_tests/test_prompt_cache.py` is a dev-only test script using a hardcoded benign fiqh query with no PII. T-17-05 disposition: accept (per plan threat model).

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `agent_tests/test_prompt_cache.py` exists | PASS |
| AST parse succeeds | PASS |
| Commit f00ca0b exists | PASS |
| No unexpected file deletions in commit | PASS |
