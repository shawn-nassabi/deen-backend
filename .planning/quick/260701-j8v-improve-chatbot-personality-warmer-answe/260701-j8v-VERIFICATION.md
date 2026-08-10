---
phase: 260701-j8v
verified: 2026-07-01T00:00:00Z
status: gaps_found
score: 6/7 must-haves verified
has_blocking_gaps: false
gaps:
  - truth: "LLM failure on dynamic refusals falls back to a hardcoded constant (no user-facing error)"
    status: partial
    severity: minor
    reason: >
      The fallback constants (EARLY_EXIT_CASUAL, EARLY_EXIT_NON_ISLAMIC) are correctly in place
      in _check_early_exit_node. However, the 5 deterministic unit tests in TestCheckEarlyExitNode
      that verify LLM-call behaviour and fallback paths use the wrong mock patch target:
      patch("agents.core.chat_agent.get_classifier_model"). Because get_classifier_model is
      imported via local 'from core.chat_models import get_classifier_model' inside each if-branch
      at call time, the module-level patch has no effect. Python's 'from X import Y' inside a
      function body re-binds from X at runtime, bypassing any name injected at
      agents.core.chat_agent scope. The tests that assert fallback behaviour and branch ordering
      will not isolate the LLM — they will call the real get_classifier_model and fail without
      a live API key.  The correct patch target is core.chat_models.get_classifier_model.
    artifacts:
      - path: "tests/test_dee12_personality.py"
        issue: >
          Lines 157, 171, 181, 195, 206: patch("agents.core.chat_agent.get_classifier_model")
          does not intercept the local imports inside _check_early_exit_node. Affected tests:
          test_check_early_exit_casual, test_check_early_exit_casual_fallback,
          test_check_early_exit_non_islamic, test_check_early_exit_non_islamic_fallback,
          test_casual_branch_precedes_non_islamic.
    missing:
      - >
        Change all five patch() targets in TestCheckEarlyExitNode from
        'agents.core.chat_agent.get_classifier_model' to 'core.chat_models.get_classifier_model'.
        That is the module from which the function is imported inside the function bodies at
        runtime, so it is the correct intercept point.
---

# Phase 260701-j8v: Improve Chatbot Personality (DEE-12) Verification Report

**Phase Goal:** Improve chatbot personality — (1) warmer answer voice, (2) dynamic LLM-generated
non-Islamic refusal replacing the fixed string, (3) casual-message handling via a new 3-way intent
classifier + routing + warm reply.

**Verified:** 2026-07-01
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Answers from the main chat path feel warmer without losing scholarly authority | VERIFIED | `generatorSystemTemplate` has a "Voice & Personality" section (lines 13-18) inserted after the opening paragraph. All 8 objectives, all format rules, Twelver-Shia framing, citation rules, and no-fabrication constraints are intact below it. `AGENT_SYSTEM_PROMPT` has a "## Voice & Personality" section (lines 9-16). |
| 2 | Non-Islamic query receives a personalised LLM-generated decline that varies per query | VERIFIED | `_check_early_exit_node` non-Islamic branch (lines 340-357) calls `get_classifier_model()` + `_retry_ainvoke` with a per-query prompt; falls back to `EARLY_EXIT_NON_ISLAMIC` on exception. Pattern matches the UNETHICAL branch exactly. |
| 3 | Casual message receives a brief warm welcome reply instead of a retrieval-failure error | VERIFIED | `_check_early_exit_node` casual branch (lines 321-337) handles `is_casual=True` with an LLM-generated warm reply and `EARLY_EXIT_CASUAL` fallback. Branch is first in order (before non-Islamic). |
| 4 | Casual messages do not trigger document retrieval — they short-circuit to early exit | VERIFIED | `_should_continue` (line 491): `if state.get("is_non_islamic") or state.get("is_fiqh") or state.get("is_casual"):` routes directly to "exit". `_tool_node` (lines 249-253) sets `state["is_casual"]` from the tool result before another agent iteration can trigger retrieval. |
| 5 | Islamic questions still work normally | VERIFIED | `aclassify_intent` returns "islamic" for unknown output (fallback) and for valid Islamic queries. `_should_continue` only short-circuits on `is_casual` or `is_non_islamic`, so Islamic queries follow the normal retrieval → generate path. `aclassify_non_islamic_query` and `classify_non_islamic_query` are untouched (lines 48-81 of classifier.py). |
| 6 | LLM failure on dynamic refusals falls back to a hardcoded constant | PARTIAL | The fallback constants and try/except blocks exist in the source code and are correct. However, the 5 unit tests that verify these fallback paths use an incorrect mock patch target — they do not actually isolate the LLM in the test run. See Gaps. |
| 7 | `aclassify_non_islamic_query` and `classify_non_islamic_query` remain bool-returning and untouched | VERIFIED | Both functions are unchanged in `modules/classification/classifier.py` (lines 48-81). Their signatures, internal logic, and `@anthropic_retry` decorators are identical to pre-DEE-12 code. |

**Score:** 6/7 truths verified (truth 6 is partial due to test wiring)

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `core/prompt_templates.py` | `intentClassifierSystemTemplate` + `intent_classifier_messages()` + warmed `generatorSystemTemplate` | VERIFIED | All three present. `intentClassifierSystemTemplate` (lines 260-305) has all 3 labels, 7 casual examples, 7 non_islamic examples, 7 islamic examples, and the single-token instruction. `intent_classifier_messages()` (lines 315-322) returns `[make_cached_system_message(...), HumanMessage(...)]`. Voice & Personality section in `generatorSystemTemplate` at lines 13-18. |
| `modules/classification/classifier.py` | `aclassify_intent()` returning `'islamic'|'non_islamic'|'casual'` | VERIFIED | `_aclassify_intent_call` (lines 84-87) with `@anthropic_retry`. `aclassify_intent` (lines 90-107): calls `intent_classifier_messages`, strips + lowercases response, returns one of the 3 valid labels, falls back to "islamic" on unexpected output. |
| `agents/tools/classification_tools.py` | `check_if_non_islamic_tool` returning `is_non_islamic` + `is_casual` | VERIFIED | Tool now calls `classifier.aclassify_intent(query, session_id)` (line 47). Returns `{is_non_islamic, is_casual, explanation}`. Except block returns `is_non_islamic=False, is_casual=False`. |
| `agents/state/chat_state.py` | `is_casual: Optional[bool]` field + default in `create_initial_state` | VERIFIED | `is_casual: Optional[bool]` declared in `ChatState` (lines 49-50) with docstring. `create_initial_state` sets `is_casual=None` (line 179). |
| `agents/core/chat_agent.py` | `_check_early_exit_node` with 3 branches; `_should_continue` routing `is_casual`; `_tool_node` setting `is_casual` | VERIFIED | All three wiring points confirmed. Branch order: casual (line 321) → non-Islamic (line 340) → UNETHICAL (line 361). `_should_continue` at line 491 includes `is_casual`. `_tool_node` sets `state["is_casual"]` at line 251. |
| `agents/prompts/agent_prompts.py` | `EARLY_EXIT_CASUAL` constant + `AGENT_SYSTEM_PROMPT` Voice directive | VERIFIED | `EARLY_EXIT_CASUAL` at line 147. `AGENT_SYSTEM_PROMPT` has "## Voice & Personality" section (lines 9-16). |
| `tests/test_dee12_personality.py` | Deterministic unit tests + opt-in `real_llm` tests | PARTIAL | File exists, is syntactically valid. `TestIntentClassifier`, `TestShouldContinueRouting`, `TestInitialState`, `TestPromptTemplates` use correct patch targets and will work. `TestCheckEarlyExitNode` (5 tests) patches `agents.core.chat_agent.get_classifier_model` which is not a module-level name in `chat_agent.py` — the patch does not intercept the local `from core.chat_models import get_classifier_model` inside the function bodies. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `classification_tools.py::check_if_non_islamic_tool` | `classifier.py::aclassify_intent` | direct call | VERIFIED | Line 47: `label = await classifier.aclassify_intent(query, session_id)` |
| `chat_agent.py::_tool_node` | `chat_state.py::is_casual` | `result_data.get('is_casual', False)` | VERIFIED | Line 251: `state["is_casual"] = result_data.get("is_casual", False)` |
| `chat_agent.py::_should_continue` | check_early_exit node | `or state.get('is_casual')` | VERIFIED | Line 491: condition includes `state.get("is_casual")` |
| `chat_agent.py::_check_early_exit_node` | `core.chat_models.get_classifier_model` + `_retry_ainvoke` | local import inside branches | VERIFIED (source) / PARTIAL (tests) | Source logic correct. Test patch targets wrong (see Gaps). |

---

### Behavioral Spot-Checks

Step 7b: SKIPPED — no runnable entry point without live deps (torch, langchain, Pinecone). All 7
changed files pass `python3 -m py_compile` cleanly.

### Probe Execution

No probes declared for this quick task. Step 7c: N/A.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `agents/core/chat_agent.py` | 322, 342, 362 | Repeated `from core.chat_models import get_classifier_model` inside three if-branches | Info | Minor duplication; functionally harmless; makes test mocking harder (see Gaps). |

No TBD/FIXME/XXX debt markers found in any modified file. No placeholder returns. No hardcoded
empty data structures in rendering paths.

---

### Human Verification Required

None needed for automated checks. All code-level verification is complete.

---

### Gaps Summary

**One minor gap (does not block goal achievement):**

The 5 tests in `TestCheckEarlyExitNode` use the wrong mock patch target. They patch
`agents.core.chat_agent.get_classifier_model`, but `get_classifier_model` is only ever imported
via `from core.chat_models import get_classifier_model` *inside* each branch of
`_check_early_exit_node` at call time. Python's `from X import Y` inside a function body
binds a fresh local name from module `X` — it does not read from the patching module's namespace.
The injected mock is therefore invisible to the function and the real `get_classifier_model` is
called instead.

**Fix:** Change all five `patch("agents.core.chat_agent.get_classifier_model", ...)` calls to
`patch("core.chat_models.get_classifier_model", ...)`. That intercepts the import at its source
module, which is what Python resolves at call time.

Affected tests (all in `TestCheckEarlyExitNode`):
- `test_check_early_exit_casual`
- `test_check_early_exit_casual_fallback`
- `test_check_early_exit_non_islamic`
- `test_check_early_exit_non_islamic_fallback`
- `test_casual_branch_precedes_non_islamic`

This gap is **minor** (severity: minor) because the production behaviour — the fallback logic and
branch ordering in `_check_early_exit_node` — is correctly implemented in source. The gap is
purely a test-isolation defect: the deterministic test suite cannot confirm fallback paths without
a live API key, which contradicts the plan's requirement for network-free unit tests.

---

_Verified: 2026-07-01_
_Verifier: Claude (gsd-verifier)_
