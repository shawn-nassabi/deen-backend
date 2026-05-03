# Phase 17: ChatAgent Caching Foundation - Context

**Gathered:** 2026-05-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Add Anthropic prompt caching to the ChatAgent LLM calls — tool definitions and system prompt cached together as a single prefix, a `make_cached_system_message()` helper centralizes construction, and cache metrics are observable in structured DEBUG logs. No changes to the fiqh sub-graph modules or any module outside `agents/core/chat_agent.py`, `core/chat_models.py`, and `agents/tools/retrieval_tools.py`. Verification via a standalone `agent_tests/` script.

</domain>

<decisions>
## Implementation Decisions

### Tool cache_control Injection
- **D-01:** Apply `cache_control` via the `@tool(extras={"cache_control": {"type": "ephemeral"}})` decorator on `retrieve_quran_tafsir_tool` in `agents/tools/retrieval_tools.py` — it is the last tool in `self.tools` and is the cache breakpoint per Anthropic's tools-prefix model. No changes to `_create_llm_with_tools()` in `chat_agent.py`; `bind_tools(self.tools)` call is unchanged.

### System Prompt Helper Scope
- **D-02:** `make_cached_system_message(text: str) -> SystemMessage` is added to `core/chat_models.py`. It returns `SystemMessage(content=[{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}])`.
- **D-03:** Apply `make_cached_system_message()` in **both** `_agent_node` (line 166) and `_generate_response_node` (line 243). If the system prompt is below the 2048-token Sonnet threshold in `_generate_response_node` (no bound tools prefix), Anthropic silently ignores `cache_control` — zero negative effects, zero extra cost. This satisfies CACHE-02 and STRUCT-01 exactly and future-proofs the node if the prompt grows.

### CACHE-03 Verification
- **D-04:** Write `agent_tests/test_prompt_cache.py` as a standalone script (matches the `test_memory_agent.py` pattern). It makes two identical ChatAgent calls back-to-back and asserts from `response.response_metadata["usage"]`:
  - Call 1: `cache_creation_input_tokens > 0` and `cache_hit == False`
  - Call 2: `cache_read_input_tokens > 0` and `cache_hit == True`
  - Uses `response.response_metadata["usage"]` directly — NOT `usage_metadata` (known LangChain double-counting bug, CRITICAL-5 in PITFALLS.md).

### Cache Metrics Logging
- **D-05:** Log cache metrics from `_agent_node` only — this is the only node where cache will reliably hit (tools + system prompt clears the 2048-token threshold). Emit a single `logger.debug(...)` after `self.llm.invoke(messages)` with:
  ```python
  extra={
      "correlation_id": correlation_id_ctx.get(),
      "cache_hit": cache_read > 0,
      "cache_creation_tokens": cache_creation,
      "cache_read_tokens": cache_read,
  }
  ```
  Source: `response.response_metadata["usage"]` (raw Anthropic dict). Do NOT use `usage_metadata`.

### Claude's Discretion
- Exact field names for the `logger.debug` message string (e.g., "Agent LLM cache metrics") — follow existing `logger.debug` patterns in `chat_agent.py`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements and Goals
- `.planning/ROADMAP.md` §Phase 17 — Goal, requirements (CACHE-01–04, STRUCT-01), and all 5 success criteria (locked)
- `.planning/REQUIREMENTS.md` — v1.4 requirements table with CACHE-01 through STRUCT-01

### Critical Pitfalls (MUST READ before implementing)
- `.planning/research/PITFALLS.md` — Comprehensive implementation pitfalls for Anthropic prompt caching with LangGraph + `bind_tools()`. Key ones for Phase 17:
  - CRITICAL-1: minimum token thresholds (Sonnet ≥ 2048, Haiku ≥ 4096)
  - CRITICAL-3: `AnthropicPromptCachingMiddleware` incompatible with `bind_tools()` — do NOT use
  - CRITICAL-5: `usage_metadata` double-counts cache tokens in streaming — always use `response_metadata["usage"]`
  - INTEGRATION-3: tool `cache_control` goes on LAST tool only
  - LANGGRAPH-2: `SystemMessage` must be structurally identical across all nodes — single helper enforces this

### Primary Change Files
- `agents/core/chat_agent.py` — `_agent_node` (line 166, SystemMessage insertion), `_generate_response_node` (line 243, second SystemMessage site), `_create_llm_with_tools` (line 59, `bind_tools` call — no change needed)
- `core/chat_models.py` — add `make_cached_system_message()` here (alongside existing `get_generator_model()` etc.)
- `agents/tools/retrieval_tools.py` — add `extras={"cache_control": ...}` to `@tool` decorator on `retrieve_quran_tafsir_tool` (line ~197)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/chat_models.py`: existing `get_generator_model()`, `get_classifier_model()` etc. are the pattern to follow for `make_cached_system_message()` — simple module-level function, no class
- `agents/tools/retrieval_tools.py:14` — `@tool` decorator from `langchain_core.tools` already imported; adding `extras=` is a one-line change
- `core/context.py` `correlation_id_ctx` — already imported in `chat_agent.py`; use in the `extra={}` dict for CACHE-04 logging

### Established Patterns
- Cache metrics logging must use `extra={}` style (v1.3 Sentry instrumentation convention) — no f-string interpolation of structured fields
- All `logger.debug` calls in `chat_agent.py` include `correlation_id: correlation_id_ctx.get()` in `extra={}` — follow this convention
- `agent_tests/` scripts use `sys.path.insert(0, ...)` at the top to run standalone — follow `test_memory_agent.py` structure
- Tool list order in `ChatAgent.__init__` is a fixed, static constant — `retrieve_quran_tafsir_tool` is always last (index 5); never reorder

### Integration Points
- `self.llm.invoke(messages)` in `_agent_node` returns an `AIMessage`; `response.response_metadata["usage"]` is the raw Anthropic usage dict — `cache_creation_input_tokens` and `cache_read_input_tokens` are keys in that dict (0 if not present)
- `_generate_response_node` uses `llm = get_generator_model()` (a separate `ChatAnthropic` instance without bound tools) — `make_cached_system_message()` is applied here for structural consistency, not expected cache hits today

</code_context>

<specifics>
## Specific Ideas

- The `agent_tests/test_prompt_cache.py` script should print human-readable output like: `"Call 1: cache_creation_input_tokens=1842, cache_read_input_tokens=0 → WRITE ✓"` and `"Call 2: cache_creation_input_tokens=0, cache_read_input_tokens=1842 → HIT ✓"` — easy to read during manual verification.
- Additional visibility via Anthropic console (cache metrics visible per API call) — user confirmed this is available as a secondary verification path.

</specifics>

<deferred>
## Deferred Ideas

- **Console-only verification (no script)**: User considered relying solely on the Anthropic console for CACHE-03 verification. Deferred — the script provides a reusable artifact and explicit assertion.
- **Fiqh module system prompt caching**: `modules/fiqh/` decomposer, filter, SEA, generator system prompts. Out of scope for Phase 17 — those are below the 4096-token Haiku minimum and require `ChatPromptTemplate` refactoring. Addressed in Phase 18 (STRUCT-02).
- **1-hour TTL**: Using `"ttl": "1h"` for the `AGENT_SYSTEM_PROMPT` (high-traffic, called on every non-fiqh request). Not available as a user-configurable option in `cache_control` via the standard API — TTL is model-determined. Not applicable.
- **`_generate_response_node` metrics logging**: Logging cache metrics from `_generate_response_node` too. Deferred — metrics will be all-zero today (below threshold); adds noise without signal. Revisit if system prompt grows.

</deferred>

---

*Phase: 17-ChatAgent Caching Foundation*
*Context gathered: 2026-05-03*
