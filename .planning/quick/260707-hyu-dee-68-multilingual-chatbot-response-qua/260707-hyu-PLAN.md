---
phase: 260707-hyu
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - agents/core/chat_agent.py
  - tests/test_dee68_multilingual_generation.py
  - tests/test_dee68_multilingual_quality.py
autonomous: true
requirements:
  - DEE-68
must_haves:
  truths:
    - "POST /chat/agentic (non-streaming) generates its response in the user's target_language, matching the behavior already present on POST /chat/stream/agentic"
    - "Deterministic mocked tests prove both the streaming path's template and the non-streaming node inject the target-language instruction, for all 6 supported languages"
    - "An opt-in real_llm harness verifies actual in-language output quality across Arabic, Farsi, Urdu, German, Bahasa Melayu, and French without ever running in default CI"
  artifacts:
    - path: "agents/core/chat_agent.py"
      provides: "_generate_response_node building generation messages via prompt_templates.generator_messages(..., target_language=state['target_language']) instead of a hardcoded AGENT_SYSTEM_PROMPT + HumanMessage list"
    - path: "tests/test_dee68_multilingual_generation.py"
      provides: "Deterministic (mocked, no network) tests asserting both generation paths inject the target-language directive"
    - path: "tests/test_dee68_multilingual_quality.py"
      provides: "Opt-in @pytest.mark.real_llm eval harness driving agent.ainvoke() across 6 languages with script-detection + LLM-judge assertions"
  key_links:
    - from: "agents/core/chat_agent.py::_generate_response_node"
      to: "core/prompt_templates.py::generator_messages"
      via: "direct function call passing target_language=state['target_language']"
      pattern: "generator_messages\\(.*target_language"
    - from: "tests/test_dee68_multilingual_generation.py"
      to: "agents/core/chat_agent.py::_generate_response_node"
      via: "patched agents.core.chat_agent._retry_ainvoke, asserting captured message content"
      pattern: "_retry_ainvoke"
    - from: "tests/test_dee68_multilingual_quality.py"
      to: "agents/core/chat_agent.py::ChatAgent.ainvoke"
      via: "await agent.ainvoke(user_query=..., session_id=..., target_language=lang)"
      pattern: "agent\\.ainvoke\\("
---

<objective>
Fix DEE-68: the non-streaming `_generate_response_node` in `agents/core/chat_agent.py` currently ignores `state["target_language"]` and always generates in English, while the streaming path (`core/pipeline_langgraph.py`) already honors it correctly via `prompt_templates.generator_messages(..., target_language=target_language)`. Thread `target_language` into the non-streaming node so `POST /chat/agentic` matches `POST /chat/stream/agentic` behavior, then lock the fix in with deterministic tests and add an opt-in real-LLM multilingual quality harness.

Purpose: Users who set a non-English `target_language` on the non-streaming endpoint currently get an English answer regardless of their preference — a silent correctness bug with no test coverage today.

Output:
- `_generate_response_node` generates in the user's target language via the shared `generator_messages` template (same mechanism as streaming)
- `tests/test_dee68_multilingual_generation.py` — deterministic mocked tests proving both paths inject the language directive
- `tests/test_dee68_multilingual_quality.py` — opt-in `@pytest.mark.real_llm` harness verifying real in-language output across 6 languages, modeled on `tests/test_dee12_personality.py`
</objective>

<execution_context>
@/Users/admin2/.claude/plugins/cache/gsd-plugin/gsd/4.0.2/workflows/execute-plan.md
@/Users/admin2/.claude/plugins/cache/gsd-plugin/gsd/4.0.2/templates/summary.md
</execution_context>

<context>
@/Users/admin2/deen-backend/.planning/STATE.md
@/Users/admin2/deen-backend/CLAUDE.md

<!-- Key interfaces the executor needs — extracted from codebase. Use directly, no exploration. -->
<interfaces>
From `agents/core/chat_agent.py` (current `_generate_response_node`, ~lines 306-336):
- Builds `all_docs = state["retrieved_docs"] + state.get("quran_docs", [])` then `references = utils.compact_format_references(all_docs)` — KEEP UNCHANGED.
- Currently builds `generation_messages = [make_cached_system_message(AGENT_SYSTEM_PROMPT), HumanMessage(content=f"User query: {state['user_query']}\n\nRetrieved references:\n{references}\n\n...")]` — THIS is what must change.
- Calls `llm = get_generator_model()` then `response = await _retry_ainvoke(llm, generation_messages)`, then `state["final_response"] = response.content` — KEEP UNCHANGED.
- Module-level imports already present: `from agents.prompts.agent_prompts import AGENT_SYSTEM_PROMPT, EARLY_EXIT_FIQH` (AGENT_SYSTEM_PROMPT still needed elsewhere — do not remove), `from core import utils`, `from core.chat_models import make_cached_system_message`.
- `_retry_ainvoke(llm, messages)` is a module-level `@anthropic_retry`-decorated async helper (top of file) — the exact call site to patch in tests: `agents.core.chat_agent._retry_ainvoke`.

From `core/pipeline_langgraph.py` (streaming path, ~lines 470-483) — the pattern to mirror:
- `references = utils.compact_format_references(all_docs)`
- `messages = prompt_templates.generator_messages(query=user_query, references=references, target_language=target_language, chat_history=history_messages)`
- Non-streaming does NOT need `chat_history` — `_generate_response_node` never read conversation history before this fix; stay scoped to language parity only, call without `chat_history` (it defaults to `None` → `[]`).

From `core/prompt_templates.py`:
- `generator_messages(query: str, references: str, target_language: str = "english", chat_history: list | None = None) -> list` returns `[SystemMessage(content=generatorSystemTemplate.format(target_language=target_language, references=references)), *chat_history, HumanMessage(content=generatorUserTemplate.format(query=query))]`.
- `generatorSystemTemplate` contains the literal directive: `"IMPORTANT: You must generate your response in this target language: {target_language}."` — this is the string tests assert on (formatted, so the language token itself appears, not the literal `{target_language}`).
- `SystemMessage.content` here is a plain string (NOT a content-block list — `generator_messages` is intentionally NOT cached, per STATE.md Phase 18 decision D-05, since the system body contains runtime variables).

From `agents/state/chat_state.py`:
- `ChatState["target_language"]: str` — default `"english"` set in `create_initial_state(user_query, session_id, target_language="english", ...)`.

From `tests/test_dee12_personality.py` — the established two-layer test pattern to model both new test files on:
- Deterministic tests: `patch("agents.core.chat_agent._retry_ainvoke" or "modules.classification.classifier._aclassify_intent_call" or "core.chat_models.get_classifier_model", new_callable=AsyncMock, return_value=MagicMock(content=...))`, run via `@pytest.mark.asyncio`.
- `_make_agent()` helper: `ChatAgent(DEFAULT_AGENT_CONFIG)` from `agents.config.agent_config`.
- `_make_state()` helper: `create_initial_state(user_query, session_id)` then `state.update(overrides)`.
- Opt-in real_llm class decorated `@pytest.mark.real_llm` at class level, driving `await agent.ainvoke(user_query=..., session_id=f"<prefix>-{uuid.uuid4().hex}")`, asserting on `result.get("final_response")` / `result.get("early_exit_message")`.
- `pytest.ini` has `addopts = -m "not real_llm"` and a registered `real_llm` marker — opt-in tests never run in default CI; only via `pytest -m real_llm`.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Thread target_language into non-streaming generation</name>
  <files>agents/core/chat_agent.py</files>
  <behavior>
    - `_generate_response_node` with `state["target_language"] == "urdu"` produces a generation system message whose content contains "urdu" (case-insensitive)
    - `_generate_response_node` with `state["target_language"] == "english"` (default) still succeeds and sets `state["final_response"]` from the mocked LLM response, with no exception raised
    - `_generate_response_node` still uses `references = utils.compact_format_references(all_docs)` built from `retrieved_docs` + `quran_docs`
  </behavior>
  <action>
In `agents/core/chat_agent.py`, add a top-level import `from core import prompt_templates` next to the existing `from core import utils` import.

In `_generate_response_node`, replace the hardcoded `generation_messages` list (currently `[make_cached_system_message(AGENT_SYSTEM_PROMPT), HumanMessage(content=f"User query: {state['user_query']}\n\nRetrieved references:\n{references}\n\n...")]`) with a call to `prompt_templates.generator_messages(query=state["user_query"], references=references, target_language=state["target_language"])`. This is the exact function the streaming path in `core/pipeline_langgraph.py` already calls with `target_language=target_language` — both paths now share the identical language-injection mechanism (the `generatorSystemTemplate`'s `{target_language}` directive).

Do not thread `chat_history` through — leave it at its default (empty). Keep everything else in the method unchanged: the `all_docs`/`references` computation, the `get_generator_model()` + `_retry_ainvoke` call, `state["final_response"] = response.content`, `state["response_generated"] = True`, the debug log, and the existing `try`/`except` error handling with its fallback message.

Leave the `AGENT_SYSTEM_PROMPT` import in place — `_agent_node` still uses it via `make_cached_system_message(AGENT_SYSTEM_PROMPT)`.
  </action>
  <verify>
    <automated>cd /Users/admin2/deen-backend && python -c "
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from agents.core.chat_agent import ChatAgent
from agents.config.agent_config import DEFAULT_AGENT_CONFIG
from agents.state.chat_state import create_initial_state

async def main():
    agent = ChatAgent(DEFAULT_AGENT_CONFIG)
    state = create_initial_state('What is Imamate?', 'verify-session', target_language='urdu')
    state['retrieved_docs'] = []
    state['quran_docs'] = []
    mock_response = MagicMock(content='stub answer', response_metadata={})
    with patch('agents.core.chat_agent._retry_ainvoke', new=AsyncMock(return_value=mock_response)) as m:
        result = await agent._generate_response_node(state)
    assert result['final_response'] == 'stub answer'
    call_messages = m.call_args[0][1]
    system_content = call_messages[0].content
    system_text = system_content if isinstance(system_content, str) else str(system_content)
    assert 'urdu' in system_text.lower(), f'target_language not injected: {system_text[:200]}'
    print('Task 1 verify passed')

asyncio.run(main())
"
</automated>
  </verify>
  <done>
    - `_generate_response_node` calls `prompt_templates.generator_messages(query=state['user_query'], references=references, target_language=state['target_language'])`
    - Generation system message content contains the literal target-language token when `target_language != "english"`
    - `target_language="english"` (default) path still completes without error and sets `final_response`
    - `_agent_node`'s use of `AGENT_SYSTEM_PROMPT` is untouched
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Deterministic language-injection tests for both paths</name>
  <files>tests/test_dee68_multilingual_generation.py</files>
  <behavior>
    - For each of arabic, farsi, urdu, german, "bahasa melayu", french: `_generate_response_node` (mocked LLM) produces a system message containing the language token
    - For `target_language="english"` (control case): `_generate_response_node` still completes and sets `final_response`, with no assertion requiring the literal word "english" to appear verbatim beyond the template's own formatting
    - For each of the 6 languages: `prompt_templates.generator_messages(query=..., references=..., target_language=lang)` returns a system message containing the language token — guards the shared template against regression
  </behavior>
  <action>
Create `tests/test_dee68_multilingual_generation.py`, modeled on the deterministic-test half of `tests/test_dee12_personality.py` (module docstring noting these are mocked/no-network, `from __future__ import annotations`, `pytest`, `unittest.mock.AsyncMock/MagicMock/patch`).

Define `LANGUAGES = ["arabic", "farsi", "urdu", "german", "bahasa melayu", "french"]` at module level.

Class `TestNonStreamingLanguageInjection`: reuse the `_make_agent()` / `_make_state()` helper pattern from `test_dee12_personality.py` (`ChatAgent(DEFAULT_AGENT_CONFIG)`; `create_initial_state(user_query, session_id, target_language=lang)` then set `retrieved_docs=[]` and `quran_docs=[]` on the returned state dict). Use `@pytest.mark.parametrize("lang", LANGUAGES)` on an `@pytest.mark.asyncio` test method that: patches `agents.core.chat_agent._retry_ainvoke` with `AsyncMock(return_value=MagicMock(content="stub answer", response_metadata={}))`; calls `await agent._generate_response_node(state)`; asserts the patched mock's captured `messages` argument (second positional arg) has a system message (first element) whose `.content` (as string) contains `lang.lower()`; asserts `result["final_response"] == "stub answer"`. Add one more non-parametrized test with `target_language="english"` (the default) asserting the node still completes and sets `final_response` without raising.

Class `TestGeneratorMessagesTemplateInjectsLanguage`: `@pytest.mark.parametrize("lang", LANGUAGES)` on a plain (non-async) test calling `prompt_templates.generator_messages(query="test query", references="", target_language=lang)` directly and asserting the returned list's first element (`SystemMessage`) has `.content` containing `lang.lower()`. This is a pure/no-mock regression guard on the shared template mechanism used by both the streaming and (post-fix) non-streaming paths.
  </action>
  <verify>
    <automated>cd /Users/admin2/deen-backend && python -m pytest tests/test_dee68_multilingual_generation.py -q -x 2>&1 | tail -25</automated>
  </verify>
  <done>
    - `tests/test_dee68_multilingual_generation.py` exists and is syntactically valid
    - All parametrized tests pass for all 6 languages plus the english control case, with zero network calls
    - `pytest tests/test_dee68_multilingual_generation.py -q` exits 0
  </done>
</task>

<task type="auto">
  <name>Task 3: Opt-in real_llm multilingual quality harness</name>
  <files>tests/test_dee68_multilingual_quality.py</files>
  <action>
Create `tests/test_dee68_multilingual_quality.py`, header docstring modeled on `tests/test_dee12_personality.py`'s real_llm section ("Requires ANTHROPIC_API_KEY and other env vars to be set. Run with: pytest -m real_llm tests/test_dee68_multilingual_quality.py").

Define a module-level helper `_arabic_script_ratio(text: str) -> float` with a type hint: iterate `text`, count characters where `c.isalpha()` and the Unicode codepoint falls in U+0600–U+06FF (`0x0600 <= ord(c) <= 0x06FF`), divide by the total count of alphabetic characters in `text`; return `0.0` if there are no alphabetic characters (avoid division by zero).

Define `LANGUAGES = ["arabic", "farsi", "urdu", "german", "bahasa melayu", "french"]` and a small fixed list of 2 representative general-Islamic questions that are NOT fiqh rulings (e.g. "What is the concept of Imamate in Twelver Shia Islam?" and "What is the significance of Ashura?") — general theology/history questions route through the normal hadith/Quran agent path, not the fiqh sub-graph, keeping the harness focused on generation-language correctness rather than fiqh routing.

`@pytest.mark.real_llm` class `TestMultilingualQuality`. Use `@pytest.mark.parametrize("lang", LANGUAGES)` on an `@pytest.mark.asyncio` test method (one question fixed per parametrized case, e.g. the Imamate question, to bound total live-LLM calls to 6) that: builds `agent = ChatAgent(DEFAULT_AGENT_CONFIG)`; calls `result = await agent.ainvoke(user_query=question, session_id=f"dee68-{lang.replace(' ', '')}-{uuid.uuid4().hex}", target_language=lang)`; extracts `final_response = result.get("final_response") or ""`; asserts `len(final_response) > 50` (substantive answer, mirrors the threshold in `test_dee12_personality.py`'s `test_real_islamic_question_works`); asserts `result.get("is_non_islamic") is not True` and `result.get("is_casual") is not True` (routed correctly, not misclassified).

For language-correctness, branch on script: if `lang in {"arabic", "farsi", "urdu"}`, assert `_arabic_script_ratio(final_response) > 0.15`. Otherwise (`german`, `french`, `bahasa melayu`), use an LLM-judge: call `core.chat_models.get_classifier_model()`, build a `HumanMessage` asking it to respond with only "yes" or "no" to whether the given text is written in `{lang}`, `await model.ainvoke([...])`, assert the stripped lowercased response starts with "yes".

Add a lightweight religious-sensitivity guard shared across all cases: assert the response does not contain a self-attributed fatwa claim — a case-insensitive substring check that `"i hereby issue a fatwa"` and `"this is my fatwa"` are absent (these are general theology questions, not fiqh rulings, so no formal fatwa language is expected in a correct response).

Use unique `session_id` values (`uuid.uuid4().hex`) per case to avoid Redis cross-test contamination, matching the existing real_llm pattern. Do not add new third-party dependencies (no `langdetect`) — the harness relies only on Unicode-block arithmetic and the project's existing `core.chat_models.get_classifier_model()`.
  </action>
  <verify>
    <automated>cd /Users/admin2/deen-backend && python -m pytest tests/test_dee68_multilingual_quality.py -q --collect-only -m real_llm 2>&1 | tail -15</automated>
  </verify>
  <done>
    - `tests/test_dee68_multilingual_quality.py` exists, is syntactically valid, and collects 6 parametrized test cases under `-m real_llm`
    - All tests are decorated `@pytest.mark.real_llm` so they are skipped by default per `pytest.ini`'s `addopts = -m "not real_llm"`
    - Harness covers all 6 target languages: Arabic-script detection for arabic/farsi/urdu, LLM-judge for german/french/bahasa melayu
    - No new third-party dependencies added
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client `target_language` field → LLM system prompt | User-supplied string is interpolated into `generatorSystemTemplate` via `.format(target_language=...)` on both the streaming and (post-fix) non-streaming paths |
| LLM response → HTTP response body | Model output returned to the client without additional server-side validation |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-hyu-01 | Tampering | `target_language` interpolated into `generatorSystemTemplate` via `str.format` | accept | Pre-existing exposure already shipped on the streaming path (`core/pipeline_langgraph.py`) in production; this change only makes the non-streaming path consistent with an already-accepted risk, not a new surface. `str.format` with a single named placeholder has no template-injection risk beyond arbitrary text substitution (no `eval`/code execution) |
| T-hyu-02 | Information Disclosure | none — no new data exposed; `target_language` is client-supplied and only affects the client's own response language | accept | No cross-user or privileged data involved |
| T-hyu-03 | Denial of Service | `_generate_response_node` unchanged call pattern (still one `_retry_ainvoke` call with existing 5-retry/60s-timeout Anthropic client config) | accept | No new LLM call added — this is a substitution of message-construction logic, not an additional round trip |
| T-hyu-SC | Tampering | npm/pip/cargo installs | accept | No new packages installed; Task 3 explicitly avoids adding `langdetect` or any other dependency — uses only Unicode-block arithmetic and the existing Anthropic client |
</threat_model>

<verification>
Run the new deterministic suite plus the full non-real_llm test suite to confirm no regressions:

```bash
cd /Users/admin2/deen-backend && python -m pytest tests/test_dee68_multilingual_generation.py tests/test_dee12_personality.py -q -x 2>&1 | tail -30
cd /Users/admin2/deen-backend && python -m pytest tests -q --ignore=tests/db 2>&1 | tail -30
```

Confirm the real_llm harness collects but does not run by default:

```bash
cd /Users/admin2/deen-backend && python -m pytest tests/test_dee68_multilingual_quality.py -q 2>&1 | tail -10
```
</verification>

<success_criteria>
- `POST /chat/agentic` with a non-English `target_language` generates its answer in that language, matching `POST /chat/stream/agentic` behavior
- `_generate_response_node` and the streaming path both construct generation messages via `core/prompt_templates.py::generator_messages`
- `tests/test_dee68_multilingual_generation.py` passes fully with zero network calls, covering all 6 languages
- `tests/test_dee68_multilingual_quality.py` exists, is `real_llm`-gated, and is skipped by default per `pytest.ini`
- No regressions in `pytest tests -q --ignore=tests/db` (default marker filter excludes `real_llm`)
- No new third-party dependencies added
</success_criteria>

<output>
Create `.planning/quick/260707-hyu-dee-68-multilingual-chatbot-response-qua/260707-hyu-SUMMARY.md` when done.
</output>
