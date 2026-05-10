---
phase: 17-chatagent-caching-foundation
plan: "01"
subsystem: core-cache-helpers
tags: [caching, anthropic, langchain, tools, system-message]
requirements-completed: [STRUCT-01, CACHE-01]

dependency-graph:
  requires: []
  provides:
    - make_cached_system_message helper in core/chat_models.py
    - retrieve_quran_tafsir_tool_cached dict in agents/tools/retrieval_tools.py
  affects:
    - agents/core/chat_agent.py (consumer of both artifacts, plan 17-02)

tech-stack:
  added: []
  patterns:
    - Anthropic content-block format (list of dicts) for SystemMessage with cache_control
    - convert_to_anthropic_tool() + dict mutation for tool-level cache_control injection

key-files:
  created: []
  modified:
    - core/chat_models.py
    - agents/tools/retrieval_tools.py

decisions:
  - "Used Anthropic dict format instead of @tool(extras=) — langchain-core==0.3.84 does not support extras parameter on @tool decorator; the correct approach per langchain-anthropic docs is convert_to_anthropic_tool() + dict cache_control mutation"
  - "Exported retrieve_quran_tafsir_tool_cached from retrieval_tools.py to keep the cache_control declaration co-located with the tool definition"

metrics:
  duration: "6 minutes"
  completed: "2026-05-03T20:59:00Z"
  tasks-completed: 2
  tasks-total: 2
  files-modified: 2
---

# Phase 17 Plan 01: ChatAgent Caching Foundation — Infrastructure Summary

Delivered `make_cached_system_message()` helper and `retrieve_quran_tafsir_tool_cached` dict as the two caching infrastructure primitives for Phase 17.

## What Was Built

### Task 1: make_cached_system_message helper (core/chat_models.py)

Added `make_cached_system_message(text: str) -> SystemMessage` after the imports block. The function returns a `SystemMessage` with content as a list-of-dicts format (required by Anthropic's prompt caching API). Plain-string content causes `ChatPromptTemplate.format_messages()` to strip `cache_control` silently (GitHub #26701). The list format preserves `cache_control` through the LangChain-Anthropic integration.

```python
def make_cached_system_message(text: str) -> SystemMessage:
    return SystemMessage(content=[
        {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}
    ])
```

### Task 2: Tool cache_control breakpoint (agents/tools/retrieval_tools.py)

Added `retrieve_quran_tafsir_tool_cached` — a pre-built Anthropic tool dict for `retrieve_quran_tafsir_tool` with `cache_control: {type: ephemeral}` applied. This is the cache breakpoint for the tools prefix: Anthropic caches all tool definitions up to and including the last tool (INTEGRATION-3). Plan 17-02 uses this dict in `_create_llm_with_tools` when building the tools list for `bind_tools`.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | d7829f2 | feat(17-01): add make_cached_system_message helper to core/chat_models.py |
| Task 2 | 9d27c3a | feat(17-01): add cache_control breakpoint dict to retrieval_tools.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] @tool(extras=...) is not a valid API in langchain-core==0.3.84**

- **Found during:** Task 2 execution
- **Issue:** The plan specified `@tool(extras={"cache_control": {"type": "ephemeral"}})` on `retrieve_quran_tafsir_tool`. The `@tool` decorator in `langchain-core==0.3.84` does not accept an `extras` keyword argument — this causes `TypeError: tool() got an unexpected keyword argument 'extras'` at import time.
- **Fix:** Used the correct approach per the `langchain-anthropic.bind_tools` documentation: called `convert_to_anthropic_tool(retrieve_quran_tafsir_tool)` to get an Anthropic dict, set `cache_control` on that dict, and exported `retrieve_quran_tafsir_tool_cached` for use by plan 17-02.
- **Impact:** Plan 17-02 must import `retrieve_quran_tafsir_tool_cached` from `retrieval_tools` instead of using `retrieve_quran_tafsir_tool` directly in the tools list passed to `bind_tools`.
- **Files modified:** `agents/tools/retrieval_tools.py`
- **Commit:** 9d27c3a

## Must-Have Truths vs Delivered

| Truth | Status | Notes |
|-------|--------|-------|
| `make_cached_system_message(text: str) -> SystemMessage` exported from `core/chat_models.py` | DELIVERED | Exact signature and return structure as specified |
| Returns `SystemMessage(content=[{type, text, cache_control}])` | DELIVERED | Verified via import test |
| `retrieve_quran_tafsir_tool` has `extras={cache_control}` on its `@tool` decorator | NOT DELIVERED — INVALID API | `extras` is not a valid `@tool` parameter in langchain-core==0.3.84. Equivalent functionality delivered via `retrieve_quran_tafsir_tool_cached` dict |
| No other tool has `cache_control` on its decorator | DELIVERED (N/A) | All 4 tools retain bare `@tool` decorators; cache_control is on the exported dict only |

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. Static configuration data only.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| core/chat_models.py exists | PASS |
| agents/tools/retrieval_tools.py exists | PASS |
| 17-01-SUMMARY.md exists | PASS |
| make_cached_system_message defined in core/chat_models.py | PASS |
| cache_control present in core/chat_models.py | PASS |
| retrieve_quran_tafsir_tool_cached in agents/tools/retrieval_tools.py | PASS |
| cache_control present in agents/tools/retrieval_tools.py | PASS |
| Commit d7829f2 (Task 1) exists | PASS |
| Commit 9d27c3a (Task 2) exists | PASS |
