---
plan: 18-02
phase: 18-module-prompt-restructuring
status: complete
commit: 8754d9b
---

# Plan 18-02 Summary: Update Consumer Call Sites

## What Was Built

Updated all 6 consumer files that referenced the now-deleted ChatPromptTemplate objects or `_prompt` module variable from `modules/fiqh/generator`.

**modules/classification/classifier.py:**
- `check_if_fiqh()`: replaced `.invoke({}).to_messages()` chain with `fiqh_classifier_messages(query=query, chatContext=chatContext)`
- `check_if_non_islamic()`: replaced `.invoke({}).to_messages()` chain with `nonislamic_classifier_messages(query=query, chatContext=chatContext)`

**modules/translation/translator.py:**
- Replaced `.invoke({}).to_messages()` chain with `translation_messages(source_language=..., text=...)`

**modules/generation/generator.py:**
- Replaced `generator_prompt_template.invoke({}).to_messages()` with `generator_messages(query=query, references=references)`

**modules/generation/stream_generator.py:**
- Removed `with_redis_history` import (unused after refactor)
- `generate_response_stream()`: replaced `with_redis_history` chain pattern with explicit `make_history(session_id).messages` fetch + `generator_messages()` + `chat_model.stream(messages)`
- `generate_elaboration_response_stream()`: replaced `hikmah_elaboration_prompt_template | chat_model` chain with `hikmah_elaboration_messages()` + `chat_model.stream(messages)`

**core/pipeline_langgraph.py:**
- Fiqh path: import `_build_messages as fiqh_build_messages` (was `_prompt as fiqh_prompt`)
- Fiqh streaming loop: replaced `fiqh_prompt | model` chain with `fiqh_build_messages()` + `model.stream(fiqh_messages)`
- Non-fiqh path: replaced `generator_prompt_template | chat_model` chain with `generator_messages()` + `chat_model.stream(messages)`

**services/primer_service.py:**
- Import: `primer_generation_prompt_template` → `primer_generation_messages`
- `_generate_bullets_with_llm()`: `formatted_prompt = primer_generation_prompt_template.invoke(prompt_inputs)` → `messages = primer_generation_messages(**prompt_inputs)` + `primers_model.ainvoke(messages)`
- `_stream_bullets_with_llm()`: same pattern with `primers_model.astream(messages)`

## Verification

- No `to_messages()` calls remain in any of the 6 updated files
- No old template object names remain in any consumer
- `grep -c 'fiqh_build_messages' core/pipeline_langgraph.py` → 2 (import + call site)
- `grep -c 'primer_generation_messages' services/primer_service.py` → 2 (both call sites)
- Import smoke test passes for all updated modules

## Self-Check: PASSED
