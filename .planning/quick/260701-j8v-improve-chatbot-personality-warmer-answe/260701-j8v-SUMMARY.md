---
phase: 260701-j8v
plan: "01"
subsystem: agentic-chat
tags: [personality, intent-routing, classification, casual-handling, tone]
dependency_graph:
  requires: []
  provides:
    - intentClassifierSystemTemplate + intent_classifier_messages() in core/prompt_templates.py
    - aclassify_intent() returning 'islamic'|'non_islamic'|'casual' in modules/classification/classifier.py
    - is_casual field in ChatState + create_initial_state
    - check_if_non_islamic_tool returns is_non_islamic + is_casual
    - _check_early_exit_node: casual → non_islamic → UNETHICAL (3-branch)
    - EARLY_EXIT_CASUAL constant in agents/prompts/agent_prompts.py
    - Voice & Personality directive in generatorSystemTemplate and AGENT_SYSTEM_PROMPT
    - DEE-12 test suite in tests/test_dee12_personality.py
  affects:
    - POST /chat/stream/agentic (SSE streaming path)
    - POST /chat/agentic (non-streaming path)
tech_stack:
  added: []
  patterns:
    - 3-label intent classification (islamic/non_islamic/casual)
    - LLM-generated dynamic refusals with hardcoded fallback constants
    - Casual short-circuit routing via is_casual flag in ChatState
key_files:
  created:
    - tests/test_dee12_personality.py
  modified:
    - core/prompt_templates.py
    - modules/classification/classifier.py
    - agents/prompts/agent_prompts.py
    - agents/state/chat_state.py
    - agents/tools/classification_tools.py
    - agents/core/chat_agent.py
decisions:
  - "aclassify_intent is additive; aclassify_non_islamic_query and classify_non_islamic_query remain bool-returning for legacy core/pipeline.py callers (DEE-12 constraint)"
  - "Casual branch precedes non-Islamic branch in _check_early_exit_node to prevent accidental misrouting when both flags are True"
  - "Fallback on unexpected LLM output from intent classifier is 'islamic' (avoids over-refusal)"
  - "Voice & Personality added to both generatorSystemTemplate (streaming path) and AGENT_SYSTEM_PROMPT (non-streaming /chat/agentic path) for full tone coverage"
metrics:
  duration: "~15 minutes"
  completed: "2026-07-01T21:13:01Z"
  tasks_completed: 3
  files_modified: 6
  files_created: 1
---

# Phase 260701-j8v Plan 01: Improve Chatbot Personality (DEE-12) Summary

**One-liner:** 3-label intent classifier (islamic/non_islamic/casual) with LLM-generated dynamic refusals, casual short-circuit routing, and warmer tone directives across both agentic endpoints.

## What Was Built

### Task 1: Intent classifier + warmer tone prompts (commit 6aa87c9)

**core/prompt_templates.py:**
- Added `intentClassifierSystemTemplate` with 3-label classification (islamic/non_islamic/casual), 5+ labelled examples per class, and single-token output enforcement
- Added `intent_classifier_messages(query, chatContext) -> list` using `make_cached_system_message`
- Added "Voice & Personality" section to `generatorSystemTemplate` immediately after the opening paragraph — additive only; no citation rules, Twelver Shia framing, or refusal constraints altered

**modules/classification/classifier.py:**
- Added `_aclassify_intent_call` with `@anthropic_retry` decorator
- Added `aclassify_intent(query, session_id) -> str` returning one of: 'islamic', 'non_islamic', 'casual'; falls back to 'islamic' on unexpected LLM output
- `aclassify_non_islamic_query` and `classify_non_islamic_query` (bool-returning, used by `core/pipeline.py`) left completely untouched

**agents/prompts/agent_prompts.py:**
- Added `EARLY_EXIT_CASUAL` constant alongside `EARLY_EXIT_NON_ISLAMIC`
- Added "Voice & Personality" section to `AGENT_SYSTEM_PROMPT` (IMPORTANT_ADDITION from dispatch: covers non-streaming `/chat/agentic` path where `_generate_response_node` uses `make_cached_system_message(AGENT_SYSTEM_PROMPT)`)

### Task 2: Casual routing — state, tool, agent wiring (commit cb1bd52)

**agents/state/chat_state.py:**
- Added `is_casual: Optional[bool]` to `ChatState` with docstring
- `create_initial_state` initialises it to `None`

**agents/tools/classification_tools.py:**
- Replaced `check_if_non_islamic_tool` body: calls `classifier.aclassify_intent()` instead of `classifier.aclassify_non_islamic_query()`
- Now returns `is_non_islamic`, `is_casual`, and `explanation`; error fallback returns both as `False`

**agents/core/chat_agent.py:**
- `_tool_node`: extracts `is_casual` from `check_if_non_islamic_tool` result alongside `is_non_islamic`
- `_should_continue`: routing condition extended to `state.get("is_non_islamic") or state.get("is_fiqh") or state.get("is_casual")`
- `_check_early_exit_node`: replaced with 3-branch implementation (casual → non_islamic → UNETHICAL); each branch uses LLM-generated reply with hardcoded fallback; UNETHICAL branch unchanged

### Task 3: Tests (commit 449b71f)

`tests/test_dee12_personality.py` provides:
- `TestIntentClassifier`: 5 tests for `aclassify_intent` (casual/non_islamic/islamic/fallback/whitespace normalisation)
- `TestShouldContinueRouting`: 3 tests for `_should_continue` routing (casual/non_islamic/fiqh → exit)
- `TestCheckEarlyExitNode`: 5 tests for `_check_early_exit_node` (casual, casual-fallback, non-Islamic, non-Islamic-fallback, casual-precedes-non_islamic ordering)
- `TestInitialState`: 2 tests confirming `is_casual` in state with default `None`
- `TestPromptTemplates`: 6 static assertion tests (Voice section present, all intent labels, EARLY_EXIT_CASUAL importable, legacy bool classifiers intact)
- `@pytest.mark.real_llm` suite: 3 live end-to-end tests (non-Islamic declined, casual warm reply, Islamic question works)

## Deviations from Plan

### IMPORTANT_ADDITION — Voice & Personality in AGENT_SYSTEM_PROMPT

As directed in the dispatch `<IMPORTANT_ADDITION>` block, the "Voice & Personality" directive was also added to `AGENT_SYSTEM_PROMPT` in `agents/prompts/agent_prompts.py`. The plan targeted `generatorSystemTemplate` only (streaming path), but the non-streaming `/chat/agentic` path generates its answer in `_generate_response_node` using `make_cached_system_message(AGENT_SYSTEM_PROMPT)`. The addition is purely additive — all retrieval-planning instructions, Twelver Shia framing, early-exit rules, and no-fatwa constraints remain intact.

**Files modified:** `agents/prompts/agent_prompts.py`
**Rule:** No deviation rule needed — explicitly instructed by dispatch.

## Known Stubs

None. All paths are fully wired: `aclassify_intent` calls a real LLM, `_check_early_exit_node` generates real LLM replies with hardcoded fallbacks, and the state flows end-to-end.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced. The `intentClassifierSystemTemplate` prompt injection surface is mitigated by the single-token output constraint and the 'islamic' fallback for unexpected tokens (T-j8v-01). Dynamic refusal prompts embed `user_query` verbatim but only echo it back to the same user (T-j8v-02). No new packages installed (T-j8v-SC).

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | 6aa87c9 | feat(260701-j8v-01): intent classifier + warmer tone prompts |
| 2 | cb1bd52 | feat(260701-j8v-01): casual routing — state, tool, and agent wiring |
| 3 | 449b71f | test(260701-j8v-01): DEE-12 personality + intent routing test suite |

## Self-Check: PASSED

- [x] core/prompt_templates.py — modified, `python3 -m py_compile` OK
- [x] modules/classification/classifier.py — modified, `python3 -m py_compile` OK
- [x] agents/prompts/agent_prompts.py — modified, `python3 -m py_compile` OK
- [x] agents/state/chat_state.py — modified, `python3 -m py_compile` OK
- [x] agents/tools/classification_tools.py — modified, `python3 -m py_compile` OK
- [x] agents/core/chat_agent.py — modified, `python3 -m py_compile` OK
- [x] tests/test_dee12_personality.py — created, `python3 -m py_compile` OK
- [x] Commits 6aa87c9, cb1bd52, 449b71f exist in git log
- [x] Legacy bool classifiers (aclassify_non_islamic_query, classify_non_islamic_query) unchanged
- [x] 3-branch order in _check_early_exit_node: casual (line 321) → non_islamic (line 340) → UNETHICAL (line 361)
- [x] Voice & Personality in both generatorSystemTemplate and AGENT_SYSTEM_PROMPT
- [x] EARLY_EXIT_CASUAL and EARLY_EXIT_NON_ISLAMIC both defined in agents/prompts/agent_prompts.py
