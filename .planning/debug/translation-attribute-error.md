---
slug: translation-attribute-error
status: resolved
trigger: |
  Sentry alert: AttributeError: module 'core.prompt_templates' has no attribute 'translation_prompt_template'
  Origin: modules/translation/translator.py line 38 in _atranslate_to_english_call
  Message context: "atranslate_to_english failed after retries"
  Wrapped by core.resilience.anthropic_retry — tenacity retries all exhaust, then raises.
  First observed event: 2026-05-19 11:42:24 UTC during /chat/stream/agentic for session 31f3fce3-5470-4055-94c6-8b1f789e5667
created: 2026-05-19
updated: 2026-05-19
---

# translation-attribute-error

## Symptoms

- **Expected behavior:** When the agentic pipeline receives a non-English query, `atranslate_to_english` should translate it to English via the LLM and return the translated string. On any unhandled failure it should log + return the original text (the function has a broad `try/except Exception`).
- **Actual behavior:** Every call into `_atranslate_to_english_call` immediately raises `AttributeError: module 'core.prompt_templates' has no attribute 'translation_prompt_template'`. The tenacity retry wrapper retries this deterministic error to exhaustion, then `atranslate_to_english` catches and logs `"atranslate_to_english failed after retries"`. The function still returns the original text (so the user-visible chat does not crash), but Sentry captures the exhausted exception on every multilingual request and translation never actually happens.
- **Error message:**
  ```
  AttributeError: module 'core.prompt_templates' has no attribute 'translation_prompt_template'
    File "/app/modules/translation/translator.py", line 38, in _atranslate_to_english_call
        prompt = prompt_templates.translation_prompt_template.invoke(...)
  ```
- **Timeline:** Started after DEE-42 (native-async LLM modules). The sync `translate_to_english` path was migrated correctly to `prompt_templates.translation_messages(...)`. The new async path `_atranslate_to_english_call` was written referencing `translation_prompt_template`, which never existed in `core/prompt_templates.py`.
- **Reproduction:** Any `/chat/stream/agentic` request whose detected `source_language` is non-English triggers `atranslate_to_english` → `_atranslate_to_english_call` → AttributeError. Sentry session shows correlation_id `dfe62a7b-4866-42d4-aabd-2777c5cbe22e`.

## Current Focus

- hypothesis: |
    `modules/translation/translator.py:38` calls `prompt_templates.translation_prompt_template.invoke(...)`, but `core/prompt_templates.py` only exports the helper function `translation_messages(source_language, text) -> list[...]` (line 262) — there is no `translation_prompt_template` ChatPromptTemplate object. The async migration (DEE-42) copy-pasted the call-shape from `enhancer_prompt_template` (which IS a ChatPromptTemplate) without realising the translation prompt had been refactored to a function. The sync sibling `translate_to_english` already uses `translation_messages(...)` correctly, so the fix is to mirror the sync path inside the async call: build messages via `translation_messages(...)`, then `await chat_model.ainvoke(messages)`.
- test: |
    Static repro: `python -c "from core import prompt_templates; print(hasattr(prompt_templates, 'translation_prompt_template'))"` returns `False`. After fix, an async test that calls `atranslate_to_english("Bonjour", "french")` should not raise AttributeError and should return an English string (or the original text under network failure, not under retry-exhausted-AttributeError).
- expecting: |
    `_atranslate_to_english_call` invokes the same `prompt_templates.translation_messages(...)` helper as the sync path, then awaits `chat_model.ainvoke(messages)`. No Sentry exception. Multilingual queries get translated.
- next_action: |
    (resolved) Fix applied + regression test added.

## Evidence

- timestamp: 2026-05-19 — `grep "translation_prompt_template" core/prompt_templates.py` returns no matches — confirms attribute is undefined.
- timestamp: 2026-05-19 — `grep "translation_messages\|translation_prompt_template" --include="*.py"` shows: `prompt_templates.py:262 def translation_messages(...)`, `translator.py:26 prompt_templates.translation_messages(...)` (sync, OK), `translator.py:38 prompt_templates.translation_prompt_template.invoke(...)` (async, BROKEN). Single-site bug.
- timestamp: 2026-05-19 — Sentry stack trace shows the AttributeError is raised inside the `@anthropic_retry` wrapper from `core/resilience.py:104-106`, after `tenacity` exhausts retries on the deterministic exception. User-visible behaviour is graceful (function returns original text), but translation is silently disabled for non-English queries.
- timestamp: 2026-05-19 — Verified post-fix: `python -c "from core import prompt_templates; print(hasattr(prompt_templates, 'translation_prompt_template'))"` still returns `False`, but the broken reference at `modules/translation/translator.py:38` is gone (now uses `translation_messages`). New test file `tests/test_translator_async.py` (5 tests) passes.

## Eliminated

(none — single-site bug, hypothesis verified)

## Resolution

- **Root cause:** The async helper `_atranslate_to_english_call` in `modules/translation/translator.py` referenced `prompt_templates.translation_prompt_template`, an attribute that never existed on `core/prompt_templates.py` — the translation prompt is exported as the helper function `translation_messages(source_language, text)`. The DEE-42 async migration copy-pasted the ChatPromptTemplate `.invoke(...).to_messages()` call-shape from `enhancer_prompt_template` (which IS a ChatPromptTemplate) instead of mirroring the sync `translate_to_english` path, which already used `translation_messages` correctly.
- **Fix:** Replaced lines 37-41 of `modules/translation/translator.py` with `messages = prompt_templates.translation_messages(source_language=..., text=...)` followed by `await chat_model.ainvoke(messages)` — identical to the sync `translate_to_english` body but on the async client.
- **Test:** Added `tests/test_translator_async.py` (5 tests, all passing):
  1. `test_atranslate_to_english_returns_translated_content` — happy path returns the mocked LLM content.
  2. `test_atranslate_to_english_does_not_raise_attribute_error` — regression assertion; before the fix this returned the original text (`"Salam"`), now returns `"Peace"`.
  3. `test_atranslate_to_english_english_short_circuits` — `source_language='english'` skips the LLM.
  4. `test_atranslate_to_english_empty_string_short_circuits` — empty input returns `""` without invoking the model.
  5. `test_prompt_templates_has_translation_messages_helper` — pins the public surface so the broken attribute name cannot quietly reappear.
- **Files changed:** `modules/translation/translator.py`, `tests/test_translator_async.py` (new).
- **Out of scope (noted, not done):** Tightening `core/resilience.anthropic_retry` so deterministic non-transient exceptions like `AttributeError` are not retried at all. The current `_is_anthropic_transient` predicate is what gates retries — AttributeError likely already short-circuits — but this was not investigated further as the user-facing symptom is fixed.
