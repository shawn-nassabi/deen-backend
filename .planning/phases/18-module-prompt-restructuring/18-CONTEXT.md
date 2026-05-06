# Phase 18: Module Prompt Restructuring - Context

**Gathered:** 2026-05-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Eliminate every `ChatPromptTemplate.from_messages` call from `modules/fiqh/` (6 files), `modules/classification/classifier.py`, `modules/translation/translator.py`, and `core/prompt_templates.py` — replacing system-message construction with `make_cached_system_message()` (for static system prompts) or plain `SystemMessage` (for dynamic system prompts with runtime variables embedded). Also update `modules/generation/stream_generator.py` to fetch chat history explicitly rather than relying on `with_redis_history()` and `MessagesPlaceholder`. Memory agent prompts (`agents/prompts/`) are out of scope for this phase.

</domain>

<decisions>
## Implementation Decisions

### Replacement Pattern — modules/fiqh/ (6 files)
- **D-01:** Each fiqh module adds a private `_build_messages(...)` function that replaces the module-level `_prompt = ChatPromptTemplate.from_messages([...])` object. Call sites change from `_prompt.format_messages(...)` to `_build_messages(...)`. Function is private (`_` prefixed) — it's an implementation detail, not part of the public interface.
- **D-02:** `_build_messages` returns `[make_cached_system_message(SYSTEM_PROMPT), HumanMessage(content=...)]`. All 6 fiqh module system prompts are fully static (no runtime variables in system body), so `make_cached_system_message` is correct here.

### Replacement Pattern — core/prompt_templates.py
- **D-03:** Replace each `ChatPromptTemplate` export with a builder function that returns a `list[BaseMessage]`. Naming convention: `{feature}_messages(...)` (e.g., `fiqh_classifier_messages(query, chatContext)`, `translation_messages(source_language, text)`). Call sites in `modules/classification/classifier.py` and `modules/translation/translator.py` change from `.invoke({}).to_messages()` to calling the builder function directly.
- **D-04:** Builder functions for **static system prompts** use `make_cached_system_message(STATIC_SYSTEM_PROMPT)`. Applies to: fiqh classifier, non-Islamic classifier, translation, primer generation (its system body has no runtime variables — only `{{}}` escaped braces for JSON format output).
- **D-05:** Builder functions for **dynamic system prompts** (runtime variables embedded in the system message body) use plain `SystemMessage(content=formatted_text)` — NOT `make_cached_system_message`. Dynamic prompts: `generator` (has `{target_language}` and `{references}` in system body), `hikmah_elaboration` (has `{hikmah_tree_name}`, `{lesson_name}`, `{lesson_summary}`, `{context_text}`, `{references}` in system body). Using `make_cached_system_message` on dynamic content writes a new cache entry every call (content changes per request, never hits). On Sonnet, cache writes cost 25% more than regular input tokens — guaranteed cost increase with zero benefit.
- **D-06:** `enhancer_prompt_template` and `elaboration_enhancer_prompt_template` are explicitly excluded. The enhancer uses `SMALL_LLM` (Haiku 4.5), which requires a 4096-token minimum for caching; the enhancer system prompt is ~330 tokens — caching would guarantee cost increase with zero hits (per Phase 17 constraint). A code comment in `core/prompt_templates.py` must explain this exclusion.

### MessagesPlaceholder — generator_prompt_template
- **D-07:** `generator_prompt_template` is the only template using `MessagesPlaceholder("chat_history")`. The active pipeline (`pipeline_langgraph.py`) already passes `chat_history` explicitly as a list. `stream_generator.generate_response_stream()` currently uses `with_redis_history(chain)` which requires `MessagesPlaceholder` to work.
- **D-08:** Update `stream_generator.generate_response_stream()` to fetch history explicitly: `make_history(session_id).messages` (same call `pipeline_langgraph.py` uses). Pass the list directly to the builder function. Remove the `with_redis_history()` wrapper from this function. No behavior change — same history, same prompt content.

### Memory Agent Prompts
- **D-09:** `agents/prompts/memory_prompts.py` (3 calls) and `agents/core/universal_memory_agent.py` (1 call) are out of Phase 18 scope. Leave as-is. Add a backlog item for a follow-up sweep.

### Claude's Discretion
- Exact function signatures for builder functions in `core/prompt_templates.py` — parameter names should match the existing template variable names (e.g., `query`, `chatContext`, `source_language`, `text`) for clarity.
- Whether to keep the old `ChatPromptTemplate` variable names as comments or delete them entirely — clean deletion is preferred.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements and Goals
- `.planning/ROADMAP.md` §Phase 18 — Goal, STRUCT-02 requirement, and all 4 success criteria (locked)
- `.planning/REQUIREMENTS.md` — v1.4 requirements table with STRUCT-02

### Critical Context from Phase 17
- `.planning/phases/17-chatagent-caching-foundation/17-CONTEXT.md` — Established decisions: `make_cached_system_message` helper location, never-cache enhancer constraint, token threshold minimums (Sonnet ≥ 2048, Haiku ≥ 4096), dynamic system prompt anti-pattern
- `.planning/research/PITFALLS.md` — Implementation pitfalls. Key ones for Phase 18: CRITICAL-1 (token thresholds), INTEGRATION-1 (ChatPromptTemplate strips cache_control — the very bug we're fixing)

### Primary Change Files
- `core/prompt_templates.py` — 9 `ChatPromptTemplate.from_messages` calls to replace (excludes enhancer)
- `modules/fiqh/classifier.py` — replace `_prompt` + `format_messages` call
- `modules/fiqh/refiner.py` — replace `_prompt` + `format_messages` call
- `modules/fiqh/sea.py` — replace `_prompt` + `format_messages` call
- `modules/fiqh/generator.py` — replace `_prompt` + `format_messages` call
- `modules/fiqh/decomposer.py` — replace `_prompt` + `format_messages` call
- `modules/fiqh/filter.py` — replace `_prompt` + `format_messages` call
- `modules/generation/stream_generator.py` — remove `with_redis_history()` dependency from `generate_response_stream()`
- `modules/classification/classifier.py` — update call sites from `.invoke().to_messages()` to builder function
- `modules/translation/translator.py` — update call site from `.invoke().to_messages()` to builder function

### Helper (Already Exists — Phase 17)
- `core/chat_models.py` — `make_cached_system_message(text: str) -> SystemMessage` (do not modify)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/chat_models.py:make_cached_system_message` — already exists from Phase 17; import and use at all static system prompt sites
- `core/chat_models.py:get_generator_model`, `get_classifier_model`, `get_translator_model` — model factory pattern to follow for any new helpers
- `core/memory.py:make_history(session_id)` — already used in `pipeline_langgraph.py` to fetch explicit history list; use in `stream_generator.py` to replace `with_redis_history`

### Established Patterns
- All 6 fiqh modules follow the same structure: module-level `SYSTEM_PROMPT` constant + `_prompt = ChatPromptTemplate.from_messages([...])` + a single public function that calls `model.invoke(_prompt.format_messages(...))`. The refactor is mechanical: rename `_prompt` removal, add `_build_messages(...)`, update the invoke call.
- `modules/fiqh/classifier.py` uses `structured_model = model.with_structured_output(FiqhCategory)` then `structured_model.invoke(_prompt.format_messages(...))`. After refactor: `structured_model.invoke(_build_messages(query))`. This pattern works identically — `with_structured_output` accepts a message list.
- `pipeline_langgraph.py:334` already shows the explicit history fetch + builder pattern to replicate in `stream_generator.py`

### Integration Points
- `modules/classification/classifier.py` imports `prompt_templates.fiqh_classifier_system_prompt` and `prompt_templates.nonislamic_classifer_prompt_template` — both change to builder function calls
- `modules/translation/translator.py` imports `prompt_templates.translation_prompt_template` — changes to a builder function call
- `modules/generation/generator.py` imports `prompt_templates.generator_prompt_template` and calls `.invoke({"query":query,"references":references})` — note: this call does NOT pass `chat_history` or `target_language`. After refactor the builder function must handle missing/optional args gracefully.
- `modules/generation/stream_generator.py` uses both `generator_prompt_template` (with `with_redis_history`) and `hikmah_elaboration_prompt_template` (direct chain.stream) — both need updating
- `tests/test_agentic_streaming_pipeline.py:185` monkeypatches `core.prompt_templates.generator_prompt_template` — this test must be updated to patch the new builder function

</code_context>

<specifics>
## Specific Ideas

- The comment explaining enhancer exclusion should be placed directly above `enhancer_prompt_template` and `elaboration_enhancer_prompt_template` in `core/prompt_templates.py`: something like `# NOT refactored to make_cached_system_message — SMALL_LLM (Haiku 4.5) requires 4096-token minimum; enhancer prompt is ~330 tokens (guaranteed cost increase, zero hits)`.
- Smoke test for Phase 18 success criterion: a single `pytest -q` run after all changes, verifying `/chat/stream/agentic` still returns a valid response.

</specifics>

<deferred>
## Deferred Ideas

- **Memory agent prompt sweep**: `agents/prompts/memory_prompts.py` (3 calls) and `agents/core/universal_memory_agent.py` (1 call) use `ChatPromptTemplate.from_messages`. Out of Phase 18 scope — add to Phase 999 backlog.
- **Refactor dynamic system prompts to separate static/dynamic parts**: Moving `{references}` and `{target_language}` out of the system message body and into the human message would make those system prompts static and cacheable. Larger behavioral change — out of Phase 18 scope, potential future optimization.

</deferred>

---

*Phase: 18-Module Prompt Restructuring*
*Context gathered: 2026-05-03*
