---
phase: 17-chatagent-caching-foundation
plan: "02"
subsystem: agents-core
tags: [caching, anthropic, langchain, system-message, metrics, logging]
requirements-completed: [CACHE-02, CACHE-04]

dependency-graph:
  requires:
    - core/chat_models.py (make_cached_system_message — delivered by plan 17-01)
    - agents/tools/retrieval_tools.py (retrieve_quran_tafsir_tool_cached — delivered by plan 17-01)
  provides:
    - Cached system prompt injection in _agent_node and _generate_response_node
    - Cache metrics logging (cache_hit, cache_creation_tokens, cache_read_tokens) in _agent_node
  affects:
    - agents/core/chat_agent.py (modified)
    - /chat/stream/agentic and /chat/agentic endpoints (runtime behavior)

tech-stack:
  added: []
  patterns:
    - make_cached_system_message() helper call replacing inline SystemMessage construction
    - response.response_metadata["usage"] for cache metrics (not usage_metadata)

key-files:
  created: []
  modified:
    - agents/core/chat_agent.py

decisions:
  - "Replaced inline SystemMessage(content=AGENT_SYSTEM_PROMPT) in both _agent_node and _generate_response_node with make_cached_system_message(AGENT_SYSTEM_PROMPT)"
  - "Cache metrics sourced from response.response_metadata['usage'] (raw Anthropic dict) — not response.usage_metadata which double-counts in streaming paths (GitHub #32818)"
  - "Comment phrasing avoids literal 'usage_metadata' string to satisfy grep-based acceptance test while still communicating the prohibition"

metrics:
  duration: "2 minutes"
  completed: "2026-05-03T21:03:54Z"
  tasks-completed: 2
  tasks-total: 2
  files-modified: 1
---

# Phase 17 Plan 02: ChatAgent Caching Foundation — Wire + Metrics Summary

Wired `make_cached_system_message` into both SystemMessage construction sites in `agents/core/chat_agent.py` and added cache metrics structured logging in `_agent_node`.

## What Was Built

### Task 1: Import and replace both SystemMessage sites

Three changes to `agents/core/chat_agent.py`:

1. **Import added** (line 35): `from core.chat_models import make_cached_system_message`

2. **_agent_node replacement** (line 167): The `SystemMessage(content=AGENT_SYSTEM_PROMPT)` inserted at iteration 1 is now `make_cached_system_message(AGENT_SYSTEM_PROMPT)`. This is where cache hits will actually occur — the full prefix (tool definitions + system prompt) exceeds the 2048-token threshold for claude-sonnet-4-6.

3. **_generate_response_node replacement** (line 245): The `SystemMessage(content=AGENT_SYSTEM_PROMPT)` at the start of `generation_messages` is now `make_cached_system_message(AGENT_SYSTEM_PROMPT)`. This node uses `get_generator_model()` without bound tools, so the system prompt alone is below the 2048-token threshold — Anthropic silently ignores `cache_control` when the threshold is not met, so there is zero cost impact. Replaced for structural consistency per LANGGRAPH-2 (prevents split cache entries from different SystemMessage formats).

Zero plain-string `SystemMessage(content=AGENT_SYSTEM_PROMPT)` patterns remain.

### Task 2: Cache metrics logging in _agent_node

Added a metrics extraction and logging block immediately after `response = self.llm.invoke(messages)` in the `_agent_node` try block:

```python
_usage = response.response_metadata.get("usage", {})
_cache_creation = _usage.get("cache_creation_input_tokens", 0) or 0
_cache_read = _usage.get("cache_read_input_tokens", 0) or 0
logger.debug(
    "Agent LLM cache metrics",
    extra={
        "correlation_id": correlation_id_ctx.get(),
        "cache_hit": _cache_read > 0,
        "cache_creation_tokens": _cache_creation,
        "cache_read_tokens": _cache_read,
    },
)
```

Key implementation decisions:
- `.get("usage", {})` with empty-dict fallback prevents KeyError if the Anthropic API response shape changes (T-17-04 mitigation)
- `or 0` guards on individual keys handle the case where a key exists but its value is None
- Source is `response_metadata["usage"]` (raw Anthropic dict) — avoids the LangChain wrapper double-counting bug (GitHub #32818)
- `_generate_response_node` does NOT get metrics logging — metrics would always be zero there (below threshold, no bound tools), adding noise without signal per D-05

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | 8080c6f | feat(17-02): wire make_cached_system_message into both SystemMessage sites |
| Task 2 | fddd4ad | feat(17-02): add cache metrics logging in _agent_node after llm.invoke |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Comment text contained the literal string 'usage_metadata' violating grep-based acceptance test**

- **Found during:** Task 2 verification
- **Issue:** The plan's acceptance criteria requires `grep -c "usage_metadata" agents/core/chat_agent.py` to return 0. The initial comment text "Do NOT use response.usage_metadata" contained the exact prohibited string.
- **Fix:** Rephrased the comment to "Do NOT use the LangChain usage wrapper" — communicates the same prohibition without the literal string that would fail the grep test.
- **Files modified:** `agents/core/chat_agent.py`
- **Commit:** fddd4ad (included in Task 2 commit)

## Must-Have Truths vs Delivered

| Truth | Status | Notes |
|-------|--------|-------|
| No inline `SystemMessage(content=AGENT_SYSTEM_PROMPT)` remains in chat_agent.py | DELIVERED | grep returns 0 |
| `_agent_node` calls `make_cached_system_message(AGENT_SYSTEM_PROMPT)` | DELIVERED | line 167 |
| `_generate_response_node` calls `make_cached_system_message(AGENT_SYSTEM_PROMPT)` | DELIVERED | line 245 |
| `_agent_node` emits logger.debug with cache_hit, cache_creation_tokens, cache_read_tokens, correlation_id | DELIVERED | after self.llm.invoke(messages) |
| Cache metrics sourced from response.response_metadata["usage"], not usage_metadata | DELIVERED | grep confirms 0 usage_metadata occurrences |

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. Cache metrics are logged at DEBUG level and contain only billing integers (no PII). T-17-04 mitigation (empty-dict fallback + or-0 guards) applied.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| agents/core/chat_agent.py exists | PASS |
| AST parse succeeds | PASS |
| make_cached_system_message import present (1 occurrence) | PASS |
| make_cached_system_message(AGENT_SYSTEM_PROMPT) calls = 2 | PASS |
| SystemMessage(content=AGENT_SYSTEM_PROMPT) occurrences = 0 | PASS |
| "Agent LLM cache metrics" occurrences = 1 | PASS |
| usage_metadata occurrences = 0 | PASS |
| cache_creation_input_tokens occurrences = 1 | PASS |
| cache_read_input_tokens occurrences = 1 | PASS |
| Commit 8080c6f (Task 1) exists | PASS |
| Commit fddd4ad (Task 2) exists | PASS |
