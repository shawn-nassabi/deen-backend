---
phase: 17-chatagent-caching-foundation
verified: 2026-05-03T23:30:00Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 4/5
  gaps_closed:
    - "The 6 ChatAgent tool definitions are passed to bind_tools() with cache_control on the last tool dict only"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Make two identical chat requests to /chat/agentic (or run agent_tests/test_prompt_cache.py) and inspect structured DEBUG logs or test output"
    expected: "Call 1: cache_creation_input_tokens > 0 (cache WRITE). Call 2: cache_read_input_tokens > 0 (cache HIT)"
    why_human: "Requires live Anthropic API call with ANTHROPIC_API_KEY; cannot verify token counts programmatically without network access"
---

# Phase 17: ChatAgent Caching Foundation — Verification Report

**Phase Goal:** The ChatAgent delivers confirmed Anthropic prompt cache hits on every `/chat/stream/agentic` request — tool definitions and system prompt are cached together as a single prefix, and cache metrics are observable in structured logs.
**Verified:** 2026-05-03T23:30:00Z
**Status:** HUMAN NEEDED (all structural checks pass; live cache hit requires human test)
**Re-verification:** Yes — after gap closure fix applied to `_create_llm_with_tools()`

---

## Gap Closure Confirmation

The single blocking gap from the initial verification has been resolved:

**Previous gap:** `retrieve_quran_tafsir_tool_cached` was defined in `retrieval_tools.py` but never imported or used in `chat_agent.py`. `bind_tools()` received bare `@tool` objects with no `cache_control`.

**Fix verified:**
- `chat_agent.py` line 31: `from agents.tools.retrieval_tools import retrieve_quran_tafsir_tool_cached` — import present
- `chat_agent.py` lines 61-78: `_create_llm_with_tools()` builds a separate `bind_tools_list` with `retrieve_quran_tafsir_tool_cached` as the last element, then calls `llm.bind_tools(bind_tools_list)`
- `chat_agent.py` line 219: `ToolNode(self.tools)` unchanged — still uses the callable `@tool` objects; the `bind_tools_list` is only for LLM tool schema registration

The fix exactly matches the recommended Option 1 from the initial verification's gap closure plan.

---

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | After first request, DEBUG log appears with `cache_creation_input_tokens > 0` and `cache_hit: false` | UNCERTAIN | Logging code is correct (chat_agent.py:185-198). Tool prefix now has `cache_control` via `retrieve_quran_tafsir_tool_cached` at bind_tools position 6; system message has `cache_control` via `make_cached_system_message`. Whether combined prefix meets Anthropic's 2048-token minimum requires live test. |
| 2 | After second identical request within 5 minutes, DEBUG log contains `cache_read_input_tokens > 0` and `cache_hit: true` | UNCERTAIN | Depends on SC1 producing a cache write. All structural prerequisites are now met. Requires live test. |
| 3 | `response.response_metadata["usage"]` is the source for cache metrics, `usage_metadata` is NOT used | VERIFIED | chat_agent.py:188 reads `response.response_metadata.get("usage", {})`. Zero occurrences of `usage_metadata` in chat_agent.py or test_prompt_cache.py (grep confirmed). Comment at lines 185-187 documents the prohibition with GitHub issue reference. |
| 4 | `make_cached_system_message` is used at both SystemMessage sites in `chat_agent.py`; no inline `SystemMessage(content=AGENT_SYSTEM_PROMPT)` remains | VERIFIED | chat_agent.py:36 imports `make_cached_system_message`. Lines 178 and 271 both call `make_cached_system_message(AGENT_SYSTEM_PROMPT)`. Zero occurrences of `SystemMessage(content=AGENT_SYSTEM_PROMPT)` in chat_agent.py (grep returned empty). |
| 5 | The 6 ChatAgent tool definitions are passed to `bind_tools()` with `cache_control: {"type": "ephemeral"}` on the last tool dict only | VERIFIED | chat_agent.py:70-78: `bind_tools_list` ends with `retrieve_quran_tafsir_tool_cached` (line 76). `retrieve_quran_tafsir_tool_cached` is the Anthropic dict built at retrieval_tools.py:273-277 via `convert_to_anthropic_tool()` with `cache_control: {"type": "ephemeral"}` applied at line 276. `self.tools` (callable `@tool` objects) is kept separate and used only by `ToolNode(self.tools)` at line 219. |

**Score:** 5/5 structural truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `core/chat_models.py` | `make_cached_system_message(text: str) -> SystemMessage` | VERIFIED | Lines 6-24. Returns `SystemMessage(content=[{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}])`. |
| `agents/core/chat_agent.py` | No inline SystemMessage; cache metrics logging; make_cached_system_message calls; retrieve_quran_tafsir_tool_cached in bind_tools | VERIFIED | All four conditions met: no inline SystemMessage (grep clean), metrics at lines 185-198, make_cached_system_message at lines 178 and 271, cached dict at line 76 in bind_tools_list. |
| `agents/tools/retrieval_tools.py` | `retrieve_quran_tafsir_tool_cached` dict with `cache_control` | VERIFIED (wired) | Lines 273-277: dict built via `convert_to_anthropic_tool()`, `cache_control` set at line 276. Imported by chat_agent.py:31. Used at chat_agent.py:76. No longer orphaned. |
| `agent_tests/test_prompt_cache.py` | Standalone two-call cache write/hit verification script | VERIFIED | 122 lines. Two calls with distinct session IDs (`_call1`, `_call2`). Reads `msg.response_metadata.get("usage", {})` at line 45. `sys.exit(1)` on failure at line 118. Zero `usage_metadata` occurrences. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `agents/core/chat_agent.py` | `core/chat_models.py` | `from core.chat_models import make_cached_system_message` | WIRED | chat_agent.py:36 |
| `_agent_node` | `response.response_metadata["usage"]` | cache metrics extraction after `self.llm.invoke(messages)` | WIRED | chat_agent.py:185-198 |
| `_create_llm_with_tools()` | `retrieve_quran_tafsir_tool_cached` | separate `bind_tools_list` with cached dict as last element | WIRED | chat_agent.py:31 (import), 70-78 (bind_tools_list construction), 76 (cached dict as last element) |
| `_tool_node` | `self.tools` (callable @tool objects) | `ToolNode(self.tools)` at line 219 | WIRED | `self.tools` unchanged: bare callables for execution; `bind_tools_list` is separate and used only in `_create_llm_with_tools()` |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `make_cached_system_message` defined in core/chat_models.py | `grep -n "def make_cached_system_message" core/chat_models.py` | Line 6: match | PASS |
| No inline SystemMessage in chat_agent.py | `grep -c "SystemMessage(content=AGENT_SYSTEM_PROMPT" chat_agent.py` | 0 | PASS |
| `retrieve_quran_tafsir_tool_cached` imported in chat_agent.py | `grep -n "retrieve_quran_tafsir_tool_cached" agents/core/chat_agent.py` | Lines 31, 76 | PASS |
| `retrieve_quran_tafsir_tool_cached` is last item in bind_tools_list | `grep -A8 "bind_tools_list = \[" agents/core/chat_agent.py` | Line 76 is last element before `]` | PASS |
| `cache_control` set on the cached dict | `grep -n "cache_control" agents/tools/retrieval_tools.py` | Line 276: `_retrieve_quran_tafsir_tool_dict["cache_control"] = {"type": "ephemeral"}` | PASS |
| `ToolNode(self.tools)` still uses callable list | `grep -n "ToolNode(self.tools)" agents/core/chat_agent.py` | Line 219: match | PASS |
| `usage_metadata` absent from chat_agent.py | `grep -c "usage_metadata" agents/core/chat_agent.py` | 0 | PASS |
| `usage_metadata` absent from test_prompt_cache.py | `grep -c "usage_metadata" agent_tests/test_prompt_cache.py` | 0 | PASS |
| test_prompt_cache.py uses `response_metadata["usage"]` | `grep -n "response_metadata" agent_tests/test_prompt_cache.py` | Lines 44-45: `msg.response_metadata.get("usage", {})` | PASS |

---

## Human Verification Required

### 1. Live Cache Write/Hit Confirmation

**Test:** From project root with all env vars set (`ANTHROPIC_API_KEY`, `PINECONE_API_KEY`, `REDIS_URL`, `DATABASE_URL`), run:
```
python agent_tests/test_prompt_cache.py
```
**Expected:** Output shows `RESULT: PASS` with `cache_creation_input_tokens > 0` on Call 1 and `cache_read_input_tokens > 0` on Call 2.

**Why human:** Requires live Anthropic API call. Also requires that the combined tools+system prefix reaches Anthropic's 2048-token minimum for Claude Sonnet 4.6 (claude-sonnet-4-6). If the test fails with `cache_creation_input_tokens=0`, the prefix is below the token threshold — diagnose with `python -c "import tiktoken; ..."` per the test script's failure message.

---

## Gaps Summary

No gaps remain. All five success criteria are structurally verified. The single item requiring human action is a live-call confirmation that the token threshold is met in production — this is an operational gate, not a code gap.

---

_Verified: 2026-05-03T23:30:00Z_
_Verifier: Claude (gsd-verifier)_
