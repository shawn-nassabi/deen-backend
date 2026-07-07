---
phase: 260707-hyu-dee-68-multilingual-chatbot-response-qua
verified: 2026-07-07T00:00:00Z
status: human_needed
score: 3/3 must-haves verified (code inspection); test execution not run in this environment
has_blocking_gaps: false
human_verification:
  - test: "Run `source venv/bin/activate && pip install -r requirements.txt && pytest tests/test_dee68_multilingual_generation.py -q` (create/populate venv first if missing pytest — see note below)"
    expected: "13 passed, matching SUMMARY.md's reported test evidence (6 languages x 2 test classes + 1 english control case)"
    why_human: "The main-tree venv at /Users/admin2/deen-backend/venv has no pytest installed (`ModuleNotFoundError: No module named 'pytest'`); the executor ran tests in a separate isolated worktree venv, not this one. Code inspection (syntax check, structural comparison to the established tests/test_dee12_personality.py pattern, and static verification of the target_language plumbing) strongly supports the SUMMARY's claims, but no test in this repo checkout was actually executed by the verifier."
  - test: "Run `pytest tests/test_dee68_multilingual_quality.py -q --collect-only -m real_llm` and separately `pytest tests/test_dee68_multilingual_quality.py -q` (default filter)"
    expected: "6 tests collected under `-m real_llm`; 6 deselected under the default `not real_llm` filter (pytest.ini addopts confirmed present) — the real_llm harness never runs in default CI"
    why_human: "Same missing-pytest environment constraint as above; pytest.ini's marker registration and addopts were confirmed by static inspection (`markers = real_llm: ...`, `addopts = -m \"not real_llm\"`) but the collection behavior itself was not executed."
  - test: "Optionally run `pytest -m real_llm tests/test_dee68_multilingual_quality.py -q` with ANTHROPIC_API_KEY set to confirm actual live multilingual output quality across the 6 languages"
    expected: "All 6 real_llm cases pass: substantive response, correct routing, no self-attributed fatwa language, and correct in-language output (Arabic-script ratio > 0.15 for arabic/farsi/urdu; LLM-judge 'yes' for german/french/bahasa melayu)"
    why_human: "Requires live Anthropic API credentials and network access, explicitly opt-in and out of scope for automated static verification."
---

# Quick Task: DEE-68 Multilingual Chatbot Response Quality Verification Report

**Task Goal:** (1) Fix non-streaming `_generate_response_node` in `agents/core/chat_agent.py` to pass `target_language` into generation like the streaming path; (2) deterministic (mocked) tests asserting both paths inject the language instruction; (3) opt-in `real_llm` eval harness across the 6 languages modeled on `tests/test_dee12_personality.py`.

**Verified:** 2026-07-07
**Status:** human_needed (all code-level must-haves verified by direct inspection; live test execution could not be run in this environment and is deferred to the developer)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `POST /chat/agentic` (non-streaming) generates its response in the user's `target_language`, matching the streaming path | VERIFIED | `agents/core/chat_agent.py:307-316` — `_generate_response_node` now calls `prompt_templates.generator_messages(query=state["user_query"], references=references, target_language=state["target_language"])`, replacing the old hardcoded `[make_cached_system_message(AGENT_SYSTEM_PROMPT), HumanMessage(...)]` list. This is the exact same function/mechanism the streaming path uses (`core/pipeline_langgraph.py:478-482`). |
| 2 | Deterministic mocked tests prove both the streaming template and the non-streaming node inject the target-language instruction, for all 6 languages | VERIFIED (by inspection; not executed) | `tests/test_dee68_multilingual_generation.py` — `TestNonStreamingLanguageInjection` (parametrized over `LANGUAGES = ["arabic","farsi","urdu","german","bahasa melayu","french"]`, patches `agents.core.chat_agent._retry_ainvoke`, asserts the captured system message contains the language token, plus 1 english control case) and `TestGeneratorMessagesTemplateInjectsLanguage` (parametrized pure test directly on `core.prompt_templates.generator_messages`). File compiles cleanly (`python3 -m py_compile` succeeded) and structurally mirrors the established `tests/test_dee12_personality.py` pattern (same `_make_agent`/`_make_state` helpers, same `@pytest.mark.asyncio` + `AsyncMock`/`patch` idiom). |
| 3 | An opt-in `real_llm` harness verifies actual in-language output quality across Arabic, Farsi, Urdu, German, Bahasa Melayu, and French, never running in default CI | VERIFIED (by inspection; not executed) | `tests/test_dee68_multilingual_quality.py` — `@pytest.mark.real_llm class TestMultilingualQuality`, `@pytest.mark.parametrize("lang", LANGUAGES)` covering all 6 languages, drives `agent.ainvoke(user_query=..., session_id=..., target_language=lang)`, asserts substantive response, correct routing, no self-attributed fatwa phrases, and language correctness (Arabic-script-ratio for arabic/farsi/urdu, LLM-judge for german/french/bahasa melayu). `pytest.ini` confirmed: `markers = real_llm: opt-in tests...` and `addopts = -m "not real_llm"` — the marker is registered and excluded by default. File compiles cleanly. |

**Score:** 3/3 truths verified by code inspection. Live pytest execution not performed in this environment (see Human Verification below).

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `agents/core/chat_agent.py` | `_generate_response_node` building generation messages via `prompt_templates.generator_messages(..., target_language=state['target_language'])` instead of the old hardcoded list | VERIFIED | Confirmed at lines 307-316. `from core import prompt_templates` import present at line 34. `AGENT_SYSTEM_PROMPT` import (line 21) retained and still used elsewhere (`_agent_node`, line 212) — untouched per plan. |
| `tests/test_dee68_multilingual_generation.py` | Deterministic (mocked, no network) tests asserting both generation paths inject the target-language directive | VERIFIED | Exists, syntactically valid, 13 total test cases (2 parametrized classes x 6 languages = 12, + 1 english control case = 13), zero network dependencies (all mocked via `unittest.mock`). |
| `tests/test_dee68_multilingual_quality.py` | Opt-in `@pytest.mark.real_llm` eval harness driving `agent.ainvoke()` across 6 languages with script-detection + LLM-judge assertions | VERIFIED | Exists, syntactically valid, `@pytest.mark.real_llm` at class level, 6 parametrized cases (one per language), `_arabic_script_ratio` helper for arabic/farsi/urdu, LLM-judge via `core.chat_models.get_classifier_model()` for german/french/bahasa melayu, religious-sensitivity fatwa-language guard, unique `session_id` per case via `uuid.uuid4().hex`. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `agents/core/chat_agent.py::_generate_response_node` | `core/prompt_templates.py::generator_messages` | Direct function call passing `target_language=state['target_language']` | WIRED | Verified by direct code read (lines 312-316): call site exactly matches the plan's specified signature. `generator_messages` (`core/prompt_templates.py:70-85`) formats `generatorSystemTemplate` with `target_language`, which contains the literal directive `"IMPORTANT: You must generate your response in this target language: {target_language}."` (line 27). |
| `tests/test_dee68_multilingual_generation.py` | `agents/core/chat_agent.py::_generate_response_node` | Patched `agents.core.chat_agent._retry_ainvoke`, asserting captured message content | WIRED | Verified by code read: `patch("agents.core.chat_agent._retry_ainvoke", new=AsyncMock(...))`, then `mocked_retry_ainvoke.call_args[0][1]` inspected for the language token. |
| `tests/test_dee68_multilingual_quality.py` | `agents/core/chat_agent.py::ChatAgent.ainvoke` | `await agent.ainvoke(user_query=..., session_id=..., target_language=lang)` | WIRED | Verified by code read at line 69-73. |

### Data-Flow Trace (Level 4)

`state["target_language"]` originates from `create_initial_state(user_query, session_id, target_language="english", ...)` in `agents/state/chat_state.py` (confirmed `target_language: str` field, default `"english"`, threaded through to the returned state dict at line 175). This state field flows unmodified into `_generate_response_node`, which reads it directly (`state["target_language"]`) and passes it to `generator_messages`. No hardcoded override or stub value found between state creation and the generation call — data flows end-to-end from caller input to the LLM system prompt.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Modified/new files are syntactically valid Python | `python3 -m py_compile agents/core/chat_agent.py tests/test_dee68_multilingual_generation.py tests/test_dee68_multilingual_quality.py` | `SYNTAX OK` (no output = success) | PASS |
| `pytest.ini` registers and excludes `real_llm` by default | `grep -n "real_llm\|addopts\|markers" pytest.ini` | `markers = real_llm: opt-in tests...` / `addopts = -m "not real_llm"` | PASS |
| Task commit hashes exist in git history | `git log --oneline -- agents/core/chat_agent.py tests/test_dee68_multilingual_generation.py tests/test_dee68_multilingual_quality.py` | `8efa49c`, `0d2555b`, `fba9ea1` all present, matching SUMMARY.md's claimed hashes | PASS |
| Full test-suite execution (13 deterministic + 6 real_llm-collect) | `pytest tests/test_dee68_multilingual_generation.py -q` | `ModuleNotFoundError: No module named 'pytest'` in main-tree venv (`/Users/admin2/deen-backend/venv`) | SKIP — routed to Human Verification |

### Anti-Patterns Found

None. `grep -n -E "TODO|FIXME|XXX|TBD|HACK|PLACEHOLDER|not yet implemented|not available|coming soon" -i` against all three modified/created files returned zero matches.

### Requirements Coverage

No `.planning/REQUIREMENTS.md` exists in this repository (quick-task workflow, not a full phase) — requirements coverage cross-reference is not applicable. The PLAN.md frontmatter declares `requirements: [DEE-68]`, and the Linear ticket's stated scope (non-streaming multilingual generation parity + deterministic tests + opt-in real_llm harness) is fully covered by the three tasks verified above.

### Human Verification Required

### 1. Run the deterministic test suite

**Test:** `source venv/bin/activate && pip install -r requirements.txt && pytest tests/test_dee68_multilingual_generation.py -q` (the main-tree venv currently has no packages installed at all — not even pytest — so a full `pip install -r requirements.txt` is needed first; note the executor's SUMMARY documents a `torch==2.6.0`→`2.2.2` substitution was required on this Intel Mac/Python 3.11 host due to missing PyPI wheels, which is unrelated to DEE-68).
**Expected:** `13 passed`, matching the executor's reported test evidence.
**Why human:** The verifier's environment (`/Users/admin2/deen-backend/venv`) has no pytest installed, so the deterministic suite could not be executed here. Code inspection strongly supports correctness (syntax valid, exact structural match to the established `tests/test_dee12_personality.py` pattern, correct mock target `agents.core.chat_agent._retry_ainvoke`), but this is not equivalent to an actual green test run.

### 2. Confirm real_llm harness collection and default-skip behavior

**Test:** `pytest tests/test_dee68_multilingual_quality.py -q --collect-only -m real_llm` then `pytest tests/test_dee68_multilingual_quality.py -q` (default marker filter).
**Expected:** 6 tests collected under `-m real_llm`; 6 deselected under the default filter.
**Why human:** Same missing-pytest constraint. `pytest.ini`'s marker registration and `addopts = -m "not real_llm"` were statically confirmed, but the actual collection/deselection behavior was not executed.

### 3. (Optional) Confirm live multilingual output quality

**Test:** `pytest -m real_llm tests/test_dee68_multilingual_quality.py -q` with `ANTHROPIC_API_KEY` and other required env vars set.
**Expected:** All 6 language cases pass — substantive response, correct routing, no fatwa self-attribution, correct in-language output.
**Why human:** Requires live LLM API access; explicitly opt-in and outside the scope of automated static verification.

### Gaps Summary

No code-level gaps found. All three must-have truths, all three required artifacts, and all three key links are verified present and correctly wired by direct code inspection — the fix in `agents/core/chat_agent.py` exactly mirrors the streaming path's `generator_messages(...target_language=...)` call, and both new test files structurally and semantically match their plan specifications with zero anti-patterns. The sole open item is that this verifier's environment lacks a populated Python venv (no pytest installed), so the actual `pytest` runs could not be independently executed — this is routed to Human Verification rather than treated as a failure, per the explicit task instructions. The SUMMARY.md's test evidence (13 passed / 6 collected / 6 deselected / 284 passed with 17 pre-existing unrelated failures) is plausible and consistent with the code as read, but remains an executor claim pending independent confirmation.

---

_Verified: 2026-07-07_
_Verifier: Claude (gsd-verifier)_
