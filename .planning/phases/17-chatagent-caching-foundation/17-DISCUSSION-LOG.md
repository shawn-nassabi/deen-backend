# Phase 17: ChatAgent Caching Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-03
**Phase:** 17-ChatAgent Caching Foundation
**Areas discussed:** Tool cache_control site, Response node scope, CACHE-03 test format, Metrics logging scope

---

## Tool cache_control site

| Option | Description | Selected |
|--------|-------------|----------|
| Decorator on tool file | `@tool(extras={"cache_control": {"type": "ephemeral"}})` on `retrieve_quran_tafsir_tool` in `agents/tools/retrieval_tools.py` — caching intent co-located with tool definition | ✓ |
| Dict construction at bind time | Convert last tool to dict and inject `cache_control` inside `_create_llm_with_tools()` — caching concern stays inside ChatAgent, tool file untouched | |

**User's choice:** Decorator on tool file
**Notes:** Cleaner co-location; tool file is the natural place to express that this tool marks the cache breakpoint.

---

## Response node scope

| Option | Description | Selected |
|--------|-------------|----------|
| Apply everywhere — CACHE-02 compliant | Use `make_cached_system_message()` in both `_agent_node` and `_generate_response_node`. Below-threshold nodes silently ignored by Anthropic — zero negative effects. | ✓ |
| Agent node only | Apply helper only where cache hits are confirmed (`_agent_node`). `_generate_response_node` keeps plain `SystemMessage`. Partially violates CACHE-02. | |

**User's choice:** Apply everywhere — CACHE-02 compliant
**Notes:** User asked whether applying `cache_control` below threshold causes latency or cost issues. Clarified: Anthropic silently ignores the marker when below threshold — no latency increase, no 1.25× write cost, no behavioral change. User confirmed safe to apply everywhere.

---

## CACHE-03 test format

| Option | Description | Selected |
|--------|-------------|----------|
| agent_tests/ script | `agent_tests/test_prompt_cache.py` — two identical ChatAgent calls, assert cache metrics from `response_metadata["usage"]`. One-time manual tool. | ✓ |
| Skip script — console + DEBUG logs | No verification script. Verify via Anthropic console + DEBUG log lines from CACHE-04 after deploy. Zero overhead. | |

**User's choice:** agent_tests/ script
**Notes:** User initially asked whether the script would add production latency (it does not — it's a standalone one-time tool). User also noted that the Anthropic console shows cache metrics directly and considered skipping the script entirely. Ultimately chose the script for explicit, reusable verification artifact.

---

## Metrics logging scope

| Option | Description | Selected |
|--------|-------------|----------|
| _agent_node only | Log only from the primary LLM call where cache hits. Clean signal, no noise from below-threshold nodes. | ✓ |
| All LLM-calling nodes | Log from `_agent_node` + `_generate_response_node`. More complete but `_generate_response_node` produces all-zero metrics today. | |

**User's choice:** _agent_node only
**Notes:** `_generate_response_node` uses a toolless model likely below 2048-token threshold today; logging zeros there adds noise without signal. Deferred to future if system prompt grows.

---

## Claude's Discretion

- Exact `logger.debug` message string for the cache metrics log line (e.g., `"Agent LLM cache metrics"`) — follow existing patterns in `chat_agent.py`

## Deferred Ideas

- Console-only CACHE-03 verification (no script) — user considered, decided script is more explicit
- 1-hour TTL via `cache_control` — not user-configurable in the standard Anthropic API; TTL is model-determined
- Fiqh module system prompt caching — out of scope for Phase 17; addressed in Phase 18 (STRUCT-02)
- `_generate_response_node` cache metrics logging — deferred until system prompt clears 2048-token threshold
