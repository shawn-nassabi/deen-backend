---
phase: 260707-hyu
plan: 01
subsystem: agents/core (ChatAgent non-streaming generation)
tags: [multilingual, chatbot, generation, dee-68]
requires: []
provides:
  - "_generate_response_node target_language support"
  - "tests/test_dee68_multilingual_generation.py"
  - "tests/test_dee68_multilingual_quality.py"
affects:
  - "POST /chat/agentic (non-streaming agentic chat endpoint)"
tech-stack:
  added: []
  patterns:
    - "Shared core/prompt_templates.py::generator_messages() as the single source of the target-language directive for both streaming and non-streaming generation paths"
key-files:
  created:
    - tests/test_dee68_multilingual_generation.py
    - tests/test_dee68_multilingual_quality.py
    - .planning/quick/260707-hyu-dee-68-multilingual-chatbot-response-qua/deferred-items.md
  modified:
    - agents/core/chat_agent.py
decisions:
  - "Non-streaming _generate_response_node now calls prompt_templates.generator_messages(...) instead of building its own hardcoded [SystemMessage, HumanMessage] list, making it byte-for-byte consistent with the streaming path's language-injection mechanism"
  - "chat_history intentionally left at its default (empty) for the non-streaming node — scope is limited to language parity, not adding conversation history to a path that never had it"
metrics:
  duration: "~35 min (majority: cold venv creation + dependency install in isolated worktree)"
  completed: 2026-07-07
---

# Phase 260707-hyu Plan 01: Multilingual Chatbot Response Quality (DEE-68) Summary

Threaded `target_language` into the non-streaming `_generate_response_node` via the shared `generator_messages` template, so `POST /chat/agentic` now generates in the user's requested language exactly like `POST /chat/stream/agentic` already did.

## What Was Built

**Task 1 — Fix the bug (`agents/core/chat_agent.py`):**
`_generate_response_node` previously built its generation messages from a hardcoded `[make_cached_system_message(AGENT_SYSTEM_PROMPT), HumanMessage(...)]` list that never referenced `state["target_language"]` — every non-streaming response was generated in English regardless of the caller's preference. Replaced this with a direct call to `core/prompt_templates.py::generator_messages(query=state["user_query"], references=references, target_language=state["target_language"])` — the exact function the streaming path (`core/pipeline_langgraph.py`) already used. Both paths now share one code path for language injection, eliminating the possibility of the two endpoints drifting apart again. `chat_history` is left at its default (empty) since the non-streaming node never read conversation history before this fix and scope was limited to language parity.

**Task 2 — Deterministic regression tests (`tests/test_dee68_multilingual_generation.py`):**
13 tests, zero network calls:
- `TestNonStreamingLanguageInjection`: parametrized across arabic, farsi, urdu, german, "bahasa melayu", french — mocks `agents.core.chat_agent._retry_ainvoke`, asserts the captured system message contains the language token, plus one english control case proving the default path still completes and sets `final_response`.
- `TestGeneratorMessagesTemplateInjectsLanguage`: pure (no-mock) parametrized guard directly on `prompt_templates.generator_messages`, protecting the shared template mechanism against regression independent of which caller (streaming or non-streaming) uses it.

**Task 3 — Opt-in real_llm quality harness (`tests/test_dee68_multilingual_quality.py`):**
`@pytest.mark.real_llm` class driving `agent.ainvoke()` across all 6 languages with a fixed general-Islamic (non-fiqh) question ("What is the concept of Imamate in Twelver Shia Islam?"). Per-case assertions:
- Substantive response (`len(final_response) > 50`)
- Correct routing (`is_non_islamic is not True`, `is_casual is not True`)
- Religious-sensitivity guard: no self-attributed fatwa phrases ("i hereby issue a fatwa", "this is my fatwa")
- Language correctness: Unicode-block arithmetic (`_arabic_script_ratio`, threshold `> 0.15`) for arabic/farsi/urdu; LLM-judge via `core.chat_models.get_classifier_model()` for german/french/bahasa melayu

No new third-party dependencies — uses only Unicode codepoint arithmetic and the project's existing Anthropic client.

## Deviations from Plan

None — plan executed exactly as written for all three tasks.

## Environment Setup (not a plan deviation, documented for traceability)

This worktree had no pre-existing Python virtualenv with project dependencies installed. `requirements.txt` pins `torch==2.6.0`, which publishes no macOS x86_64 wheel on PyPI (only versions through `2.2.2` do, on this Intel Mac / Python 3.11 host). To get a working test environment, `venv/` was created fresh in the worktree and all packages were installed at their exact `requirements.txt`-pinned versions except `torch`, which was installed at `2.2.2` (the newest version with an available wheel for this platform). This is a pre-existing platform-compatibility gap unrelated to DEE-68 and out of scope to fix here; logged in `deferred-items.md` for visibility. It did not affect correctness of the DEE-68 deterministic tests (LangChain/LangGraph/Anthropic client behavior is unaffected by the torch minor-version difference — torch is only pulled in transitively via `langchain-huggingface`'s embedding dependency, not used directly in the code paths touched by this task).

## Deferred Items (out of scope, logged not fixed)

While running the full regression suite (`pytest tests -q --ignore=tests/db`) for verification, 17 pre-existing failures were observed in files **not** touched by this task (`test_agentic_streaming_pipeline.py`, `test_agentic_streaming_sse.py`, `test_async_concurrency_full.py`, `test_chat_agent_async.py`, `test_concurrency_baseline.py`, `test_fiqh_integration.py`, `test_primer_service.py`). Root causes: no local Redis reachable in this worktree, host-specific concurrency/timing thresholds, and a `langchain-core` sync-invocation behavior difference plus embedding-similarity numeric drift possibly related to the `torch` version noted above. Full detail in `.planning/quick/260707-hyu-dee-68-multilingual-chatbot-response-qua/deferred-items.md`. None of these touch `agents/core/chat_agent.py`, `core/prompt_templates.py`, or the new DEE-68 test files, and 284 tests passed alongside them — confirming no regression was introduced by this task's changes.

## Test Evidence

```
pytest tests/test_dee68_multilingual_generation.py -q
  13 passed, 4 warnings

pytest tests/test_dee68_multilingual_quality.py -q --collect-only -m real_llm
  6 tests collected

pytest tests/test_dee68_multilingual_quality.py -q   (default marker filter)
  6 deselected  (confirms real_llm harness is skipped by default per pytest.ini)

pytest tests/test_dee68_multilingual_generation.py tests/test_dee12_personality.py -q -x
  42 passed, 3 deselected

pytest tests -q --ignore=tests/db
  17 failed (pre-existing, unrelated — see deferred-items.md), 284 passed, 13 deselected
```

## Self-Check: PASSED

All created/modified files verified present on disk; all three task commit hashes (`fba9ea1`, `0d2555b`, `8efa49c`) verified present in git log.
