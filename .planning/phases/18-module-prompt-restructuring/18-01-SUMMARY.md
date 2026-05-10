---
plan: 18-01
phase: 18-module-prompt-restructuring
status: complete
commit: 6e77450
---

# Plan 18-01 Summary: Replace ChatPromptTemplate with Builder Functions

## What Was Built

Eliminated `ChatPromptTemplate.from_messages()` pattern from `core/prompt_templates.py` and all 6 `modules/fiqh/` files. This pattern silently strips `cache_control` from content blocks during `format_messages()` (GitHub #26701), breaking prompt caching.

**core/prompt_templates.py:**
- Changed imports: removed `MessagesPlaceholder`, added `SystemMessage`, `HumanMessage`, `make_cached_system_message`
- Replaced 6 `ChatPromptTemplate` objects with builder functions:
  - `generator_messages()` — uses plain `SystemMessage` (dynamic: has `{target_language}`, `{references}` in body)
  - `fiqh_classifier_messages()` — uses `make_cached_system_message` (static)
  - `nonislamic_classifier_messages()` — uses `make_cached_system_message` (static)
  - `translation_messages()` — uses `make_cached_system_message` (static)
  - `hikmah_elaboration_messages()` — uses plain `SystemMessage` (dynamic: has runtime vars in body)
  - `primer_generation_messages()` — uses `make_cached_system_message` (static)
- Added exclusion comments to 2 enhancer `ChatPromptTemplate` objects (Haiku 4.5 below 4096-token minimum)

**modules/fiqh/ (all 6 files):**
- Removed `from langchain.prompts import ChatPromptTemplate`
- Added `from langchain_core.messages import HumanMessage` and `from core.chat_models import make_cached_system_message`
- Replaced `_prompt = ChatPromptTemplate.from_messages([...])` module-level variable with `_build_messages(...)` private function in each file
- Updated all `model.invoke(_prompt.format_messages(...))` call sites to `model.invoke(_build_messages(...))`

## Key Files

- `core/prompt_templates.py` — 6 builder functions exported (2 enhancer ChatPromptTemplates remain)
- `modules/fiqh/decomposer.py` — `_build_messages(query: str)`
- `modules/fiqh/classifier.py` — `_build_messages(query: str)` with structured output
- `modules/fiqh/filter.py` — `_build_messages(query: str, evidence: str)`
- `modules/fiqh/sea.py` — `_build_messages(query: str, evidence: str)` with structured output
- `modules/fiqh/generator.py` — `_build_messages(query: str, evidence: str)` (CRITICAL: also imported by pipeline_langgraph.py)
- `modules/fiqh/refiner.py` — `_build_messages(original_query, confirmed_facts, gaps, prior_queries)`

## Verification

- `grep -c 'ChatPromptTemplate.from_messages' core/prompt_templates.py` → 2 (enhancers only)
- `grep -rn 'ChatPromptTemplate' modules/fiqh/` → 0 results
- `grep -rn 'format_messages' modules/fiqh/` → 0 results
- `grep -c 'make_cached_system_message' core/prompt_templates.py` → 6
- All 6 fiqh module imports confirmed OK

## Self-Check: PASSED
