# Phase 18: Module Prompt Restructuring - Research

**Researched:** 2026-05-03
**Domain:** LangChain prompt construction, Anthropic cache_control, Python refactoring patterns
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Each fiqh module adds a private `_build_messages(...)` function replacing `_prompt`. Call sites change from `_prompt.format_messages(...)` to `_build_messages(...)`.
- **D-02:** `_build_messages` returns `[make_cached_system_message(SYSTEM_PROMPT), HumanMessage(content=...)]`. All 6 fiqh module system prompts are fully static.
- **D-03:** `core/prompt_templates.py` replaces each `ChatPromptTemplate` export with a builder function returning `list[BaseMessage]`. Naming: `{feature}_messages(...)`.
- **D-04:** Static system prompts use `make_cached_system_message(STATIC_SYSTEM_PROMPT)`. Applies to: fiqh classifier, non-Islamic classifier, translation, primer generation.
- **D-05:** Dynamic system prompts use plain `SystemMessage(content=formatted_text)`. Dynamic: `generator` (`{target_language}`, `{references}`), `hikmah_elaboration` (`{hikmah_tree_name}`, `{lesson_name}`, `{lesson_summary}`, `{context_text}`, `{references}`).
- **D-06:** `enhancer_prompt_template` and `elaboration_enhancer_prompt_template` are explicitly excluded. Code comment required explaining exclusion.
- **D-07:** `generator_prompt_template` is the only template using `MessagesPlaceholder("chat_history")`.
- **D-08:** Update `stream_generator.generate_response_stream()` to fetch history explicitly: `make_history(session_id).messages`. Remove `with_redis_history()` wrapper.
- **D-09:** `agents/prompts/memory_prompts.py` (3 calls) and `agents/core/universal_memory_agent.py` (1 call) are out of Phase 18 scope.

### Claude's Discretion

- Exact function signatures for builder functions in `core/prompt_templates.py` — parameter names should match the existing template variable names.
- Whether to keep old `ChatPromptTemplate` variable names as comments or delete them — clean deletion is preferred.

### Deferred Ideas (OUT OF SCOPE)

- Memory agent prompt sweep (`agents/prompts/`, `agents/core/universal_memory_agent.py`)
- Refactoring dynamic system prompts to separate static/dynamic parts

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STRUCT-02 | All `ChatPromptTemplate` system-message patterns in `modules/fiqh/` (6 files), `modules/classification/` (1 file), `modules/translation/` (1 file), and `core/prompt_templates.py` (4 templates) are refactored to `SystemMessage(content=[...])` content-block format with `cache_control` — zero behavioral change; `modules/enhancement/enhancer.py` is explicitly excluded | Research confirms 10 call sites across 9 files, exact before/after patterns documented for each |

</phase_requirements>

---

## Summary

Phase 18 is a mechanical refactor across 9 source files (6 fiqh modules, 2 classification/translation modules, and `core/prompt_templates.py`) plus 3 consumer files that break when their imported symbols change. The goal is to eliminate `ChatPromptTemplate.from_messages()` as the system-message construction method because it silently strips `cache_control` from content blocks (GitHub #26701 — confirmed in Phase 17 PITFALLS.md).

The work divides into two patterns: (a) fiqh modules own their prompts internally — replace `_prompt = ChatPromptTemplate.from_messages([...])` with `_build_messages(...)` private function; (b) `core/prompt_templates.py` exports templates to other modules — replace each `ChatPromptTemplate` object export with a builder function that returns a `list[BaseMessage]`.

Three undocumented call sites discovered during research require Phase 18 changes that CONTEXT.md does not explicitly call out: `core/pipeline_langgraph.py` (which imports `_prompt` directly from `modules/fiqh/generator.py` and uses it in a `chain = prompt | model` pattern), `modules/generation/generator.py` (which calls `generator_prompt_template.invoke({...})` without `chat_history` or `target_language`), and `services/primer_service.py` (which calls `primer_generation_prompt_template.invoke(prompt_inputs)` then `model.ainvoke(formatted_prompt)`). All three must be updated.

**Primary recommendation:** Refactor files in dependency order: (1) update `core/prompt_templates.py` first to define all builder functions; (2) update the 6 fiqh modules; (3) update the 3 consumer files (`modules/classification/classifier.py`, `modules/translation/translator.py`, `modules/generation/stream_generator.py`); (4) update discovered call sites (`core/pipeline_langgraph.py`, `modules/generation/generator.py`, `services/primer_service.py`); (5) update the test monkeypatch.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| System message construction (cached) | Utility helper (`core/chat_models.py`) | — | Single source of truth for cache_control format |
| Fiqh module message building | Module-local (`modules/fiqh/*.py`) | — | Modules own their prompts; `_build_messages` is private |
| Cross-module prompt templates | Shared library (`core/prompt_templates.py`) | — | Consumed by classification, translation, generation, primer |
| History fetch for generation | Memory layer (`core/memory.py`) | — | `make_history(session_id).messages` already used in pipeline_langgraph.py |

---

## Call Site Inventory (Complete)

This is the authoritative list of every location that must change in Phase 18.

### Files with ChatPromptTemplate to remove (primary targets)

| File | Symbol removed | Pattern | Builder name |
|------|---------------|---------|-------------|
| `core/prompt_templates.py` | `generator_prompt_template` | dynamic system | `generator_messages(query, references, target_language, chat_history)` |
| `core/prompt_templates.py` | `fiqh_classifier_system_prompt` | static system | `fiqh_classifier_messages(query, chatContext)` |
| `core/prompt_templates.py` | `nonislamic_classifer_prompt_template` | static system | `nonislamic_classifier_messages(query, chatContext)` |
| `core/prompt_templates.py` | `translation_prompt_template` | static system | `translation_messages(source_language, text)` |
| `core/prompt_templates.py` | `hikmah_elaboration_prompt_template` | dynamic system | `hikmah_elaboration_messages(selected_text, context_text, hikmah_tree_name, lesson_name, lesson_summary, references)` |
| `core/prompt_templates.py` | `primer_generation_prompt_template` | static system | `primer_generation_messages(lesson_title, lesson_content, baseline_bullets, user_learning_notes, user_interest_notes, user_knowledge_notes, user_preference_notes)` |
| `modules/fiqh/classifier.py` | `_prompt` | static system | `_build_messages(query)` |
| `modules/fiqh/refiner.py` | `_prompt` | static system | `_build_messages(original_query, confirmed_facts, gaps, prior_queries)` |
| `modules/fiqh/sea.py` | `_prompt` | static system | `_build_messages(query, evidence)` |
| `modules/fiqh/generator.py` | `_prompt` | static system | `_build_messages(query, evidence)` |
| `modules/fiqh/decomposer.py` | `_prompt` | static system | `_build_messages(query)` |
| `modules/fiqh/filter.py` | `_prompt` | static system | `_build_messages(query, evidence)` |
| `core/prompt_templates.py` | `enhancer_prompt_template` | EXCLUDED | leave as-is, add comment |
| `core/prompt_templates.py` | `elaboration_enhancer_prompt_template` | EXCLUDED | leave as-is, add comment |

### Consumer files that must be updated when symbols change

| File | Line | Current usage | Required change |
|------|------|---------------|-----------------|
| `modules/classification/classifier.py` | 17 | `.invoke({...}).to_messages()` | call `fiqh_classifier_messages(query, chatContext)` |
| `modules/classification/classifier.py` | 34 | `.invoke({...}).to_messages()` | call `nonislamic_classifier_messages(query, chatContext)` |
| `modules/translation/translator.py` | 17 | `.invoke({...}).to_messages()` | call `translation_messages(source_language, text)` |
| `modules/generation/stream_generator.py` | 27 | `prompt = ...template` + `with_redis_history(chain)` | explicit history fetch + direct `model.stream(messages)` |
| `modules/generation/stream_generator.py` | 68 | `prompt = hikmah_elaboration_prompt_template` + `chain.stream({...})` | direct `model.stream(hikmah_elaboration_messages(...))` |
| `modules/generation/generator.py` | 17 | `generator_prompt_template.invoke({"query":q,"references":r})` | call `generator_messages(query, references)` with empty defaults |
| `core/pipeline_langgraph.py` | 224-225 | `from modules.fiqh.generator import (_prompt as fiqh_prompt, ...)` | import `_build_messages` instead, call `model.stream(_build_messages(...))` |
| `core/pipeline_langgraph.py` | 332-344 | `prompt = generator_prompt_template` + `chain = prompt \| chat_model` + `chain.stream({...})` | call `generator_messages(...)` + `chat_model.stream(messages)` |
| `services/primer_service.py` | 792, 859 | `primer_generation_prompt_template.invoke(prompt_inputs)` then `model.ainvoke(formatted_prompt)` | call `primer_generation_messages(**prompt_inputs)` then `model.ainvoke(messages)` |
| `tests/test_agentic_streaming_pipeline.py` | 185 | `monkeypatch.setattr("core.prompt_templates.generator_prompt_template", RunnableLambda(...))` | patch `core.prompt_templates.generator_messages` |

---

## Architecture Patterns

### Pattern 1: Fiqh module `_build_messages` (6 files, static system prompt)

**What:** Replace module-level `_prompt = ChatPromptTemplate.from_messages([...])` with a private function.
**When to use:** All 6 `modules/fiqh/` files.

Before:
```python
from langchain.prompts import ChatPromptTemplate  # REMOVE

_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{query}"),
])

def some_function(query: str):
    model = chat_models.get_xxx_model()
    result = model.invoke(_prompt.format_messages(query=query))
```

After:
```python
from langchain_core.messages import HumanMessage  # ADD
from core.chat_models import make_cached_system_message  # ADD

def _build_messages(query: str) -> list:
    return [
        make_cached_system_message(SYSTEM_PROMPT),
        HumanMessage(content=query),
    ]

def some_function(query: str):
    model = chat_models.get_xxx_model()
    result = model.invoke(_build_messages(query))
```

**Structured output variant** (`modules/fiqh/classifier.py`, `modules/fiqh/sea.py`):
```python
# Before:
structured_model = model.with_structured_output(FiqhCategory)
result = structured_model.invoke(_prompt.format_messages(query=query))

# After:
structured_model = model.with_structured_output(FiqhCategory)
result = structured_model.invoke(_build_messages(query))
```
`with_structured_output()` chains accept a message list — no change needed to the structured output call itself.

### Pattern 2: Multi-parameter `_build_messages` (refiner, sea, generator, filter)

Fiqh modules whose human message contains multiple variables:

```python
# modules/fiqh/refiner.py _build_messages
def _build_messages(
    original_query: str,
    confirmed_facts: str,
    gaps: str,
    prior_queries: str,
) -> list:
    return [
        make_cached_system_message(SYSTEM_PROMPT),
        HumanMessage(content=f"""Original query: {original_query}

Confirmed facts so far:
{confirmed_facts}

Information gaps to fill:
{gaps}

Previously tried queries (DO NOT REPEAT OR REPHRASE THESE):
{prior_queries}

Generate 1-4 new retrieval sub-queries targeting the gaps above."""),
    ]
```

Note: `refiner.py` currently formats strings before calling `_prompt.format_messages(...)`. The pre-formatting logic (`confirmed_facts_text`, `gaps_text`, `prior_queries_text`) stays in the public function; `_build_messages` receives already-formatted strings.

### Pattern 3: Static system prompt builder in `core/prompt_templates.py`

**What:** Replace `ChatPromptTemplate` module-level object with a function returning `list[BaseMessage]`.

```python
# Before:
fiqh_classifier_system_prompt = ChatPromptTemplate.from_messages([
    ("system", fiqhClassifierSystemTemplate),
    ("user", fiqhClassifierUserTemplate),
])

# After:
def fiqh_classifier_messages(query: str, chatContext: str) -> list:
    return [
        make_cached_system_message(fiqhClassifierSystemTemplate),
        HumanMessage(content=fiqhClassifierUserTemplate.format(
            chatContext=chatContext,
            query=query,
        )),
    ]
```

### Pattern 4: Dynamic system prompt builder in `core/prompt_templates.py`

Dynamic prompts use plain `SystemMessage` (not `make_cached_system_message`) because the system body contains request-specific variables.

```python
# generator_messages — system body contains {target_language} and {references}
from langchain_core.messages import SystemMessage, HumanMessage

def generator_messages(
    query: str,
    references: str,
    target_language: str = "english",
    chat_history: list | None = None,
) -> list:
    if chat_history is None:
        chat_history = []
    system_content = generatorSystemTemplate.format(
        target_language=target_language,
        references=references,
    )
    return [
        SystemMessage(content=system_content),
        *chat_history,
        HumanMessage(content=generatorUserTemplate.format(query=query)),
    ]
```

Key: `chat_history` default is `[]` (not `None`) in the returned list — use `if chat_history is None: chat_history = []` pattern to avoid mutable default argument bug.

### Pattern 5: Consumer call site update

```python
# modules/classification/classifier.py — before:
prompt = prompt_templates.fiqh_classifier_system_prompt.invoke({"query": query, "chatContext": chatContext})
response = chat_model.invoke(prompt.to_messages())

# After:
messages = prompt_templates.fiqh_classifier_messages(query=query, chatContext=chatContext)
response = chat_model.invoke(messages)
```

```python
# modules/translation/translator.py — before:
prompt = prompt_templates.translation_prompt_template.invoke({"source_language": ..., "text": text})
response = chat_model.invoke(prompt.to_messages())

# After:
messages = prompt_templates.translation_messages(source_language=source_language or "unknown", text=text)
response = chat_model.invoke(messages)
```

### Pattern 6: `generate_response_stream` explicit history fetch

```python
# modules/generation/stream_generator.py generate_response_stream — before:
prompt = prompt_templates.generator_prompt_template
chain = prompt | chat_model
chain_with_history = with_redis_history(chain)
for chunk in chain_with_history.stream(
    {"target_language": target_language, "query": query, "references": references},
    config={"configurable": {"session_id": session_id}},
):
    yield getattr(chunk, "content", str(chunk) if chunk is not None else "")

# After:
history_messages = make_history(session_id).messages
messages = prompt_templates.generator_messages(
    query=query,
    references=references,
    target_language=target_language,
    chat_history=history_messages,
)
for chunk in chat_model.stream(messages):
    yield getattr(chunk, "content", str(chunk) if chunk is not None else "")
```

Import `make_history` (already imported), remove `with_redis_history` from imports if no longer used in this file.

### Pattern 7: `generate_elaboration_response_stream` update

```python
# modules/generation/stream_generator.py — before:
prompt = prompt_templates.hikmah_elaboration_prompt_template
chain = prompt | chat_model
for chunk in chain.stream({
    "selected_text": selected_text, "context_text": context_text,
    "hikmah_tree_name": hikmah_tree_name, "lesson_name": lesson_name,
    "lesson_summary": lesson_summary, "references": references
}):
    content = getattr(chunk, "content", ...)

# After:
messages = prompt_templates.hikmah_elaboration_messages(
    selected_text=selected_text,
    context_text=context_text,
    hikmah_tree_name=hikmah_tree_name,
    lesson_name=lesson_name,
    lesson_summary=lesson_summary,
    references=references,
)
for chunk in chat_model.stream(messages):
    content = getattr(chunk, "content", ...)
```

### Pattern 8: `core/pipeline_langgraph.py` fiqh streaming path

```python
# core/pipeline_langgraph.py line 224-225 — before:
from modules.fiqh.generator import (
    _prompt as fiqh_prompt,
    _format_evidence,
    _build_references_section,
    INSUFFICIENT_WARNING,
    FATWA_DISCLAIMER,
)
...
model = chat_models.get_generator_model()
chain = fiqh_prompt | model
for chunk in chain.stream({"query": user_query, "evidence": _format_evidence(fiqh_docs)}):

# After:
from modules.fiqh.generator import (
    _build_messages as fiqh_build_messages,
    _format_evidence,
    _build_references_section,
    INSUFFICIENT_WARNING,
    FATWA_DISCLAIMER,
)
...
model = chat_models.get_generator_model()
fiqh_messages = fiqh_build_messages(query=user_query, evidence=_format_evidence(fiqh_docs))
for chunk in model.stream(fiqh_messages):
```

### Pattern 9: `core/pipeline_langgraph.py` non-fiqh generation path

```python
# core/pipeline_langgraph.py line 332-344 — before:
prompt = prompt_templates.generator_prompt_template
chain = prompt | chat_model
history_messages = make_history(runtime_session_id).messages
for chunk in chain.stream({
    "target_language": target_language,
    "query": user_query,
    "references": references,
    "chat_history": history_messages,
}):

# After:
history_messages = make_history(runtime_session_id).messages
messages = prompt_templates.generator_messages(
    query=user_query,
    references=references,
    target_language=target_language,
    chat_history=history_messages,
)
for chunk in chat_model.stream(messages):
```

### Pattern 10: `services/primer_service.py` update

```python
# services/primer_service.py lines 792 and 859 — before:
formatted_prompt = primer_generation_prompt_template.invoke(prompt_inputs)
response = await primers_model.ainvoke(formatted_prompt)  # or astream

# After:
messages = primer_generation_messages(**prompt_inputs)
response = await primers_model.ainvoke(messages)  # or astream
```

Note: `primers_model.ainvoke(messages_list)` accepts `list[BaseMessage]` — no adapter needed.

### Pattern 11: Test monkeypatch update

```python
# tests/test_agentic_streaming_pipeline.py line 185 — before:
monkeypatch.setattr("core.prompt_templates.generator_prompt_template", RunnableLambda(lambda x: x))

# After:
monkeypatch.setattr("core.prompt_templates.generator_messages", lambda **kwargs: kwargs)
```

The test currently verifies `payload["chat_history"]` (line 177). After refactor, `generator_messages` is called with keyword arguments and returns a messages list; the test's `fake_model_fn` receives the messages list, not a dict. The test assertion must change accordingly:

```python
# Before:
def fake_model_fn(payload):
    captured["history"] = payload["chat_history"]
    return "Generated answer"

# After: the model receives a list[BaseMessage], not a dict
# The pipeline_langgraph.py calls chat_model.stream(messages) directly
# So fake_model_fn receives the messages list
def fake_model_fn(messages):
    history_msgs = [m for m in messages if not hasattr(m, 'tool_calls')]
    captured["history"] = [m for m in messages if m.__class__.__name__ == 'HumanMessage']
    return "Generated answer"
```

Actually the test's assertion is `captured["history"][0].content == "Earlier context"` — the earlier context comes from `FakeHistory.messages` which is injected as `chat_history`. After refactor, `generator_messages(...)` embeds the history inside the messages list. The test must be updated to verify the messages list contains the earlier context message, not that a dict key `chat_history` holds it. See "Gotchas" section for exact fix.

### Pattern 12: Enhancer exclusion comment

```python
# core/prompt_templates.py — above enhancer_prompt_template:
# NOT refactored to make_cached_system_message — SMALL_LLM (Haiku 4.5) requires
# 4096-token minimum; enhancer system prompt is ~330 tokens (guaranteed cost
# increase with zero cache hits if cache_control were applied).
enhancer_prompt_template = ChatPromptTemplate.from_messages([...])

# NOT refactored — same reason as enhancer_prompt_template above.
elaboration_enhancer_prompt_template = ChatPromptTemplate.from_messages([...])
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Structured content blocks | Inline dict literals at every call site | `make_cached_system_message(text)` from `core/chat_models.py` | Already exists from Phase 17; ensures structural identity across all code paths |
| History injection | Re-implement `RunnableWithMessageHistory` | `make_history(session_id).messages` | Already used in `pipeline_langgraph.py`; identical pattern |
| Chain wrapping | `prompt \| model` with ChatPromptTemplate | `model.stream(messages)` / `model.invoke(messages)` | After refactor, builder returns plain list — no Runnable chain needed |

---

## Undocumented Call Sites (CRITICAL — NOT in CONTEXT.md)

These three call sites were discovered during research. If any is missed, the phase will produce import errors or broken behavior.

### Undocumented #1: `core/pipeline_langgraph.py` fiqh path

**Location:** Lines 224-225, 268-273
**Current code:**
```python
from modules.fiqh.generator import (
    _prompt as fiqh_prompt,   # <-- imports the module-level _prompt object
    ...
)
model = chat_models.get_generator_model()
chain = fiqh_prompt | model
for chunk in chain.stream({"query": user_query, "evidence": _format_evidence(fiqh_docs)}):
```
**Required change:** Import `_build_messages as fiqh_build_messages` instead. Remove `chain = fiqh_prompt | model`. Call `model.stream(fiqh_build_messages(query=..., evidence=...))`.

**Risk if missed:** `ImportError: cannot import name '_prompt' from 'modules.fiqh.generator'` at runtime when any fiqh query is processed. Silent failure — the fiqh path would crash on the first real fiqh query.

### Undocumented #2: `modules/generation/generator.py` (legacy path)

**Location:** Line 17
**Current code:**
```python
prompt = prompt_templates.generator_prompt_template.invoke({"query":query,"references":references})
response = chat_model.invoke(prompt.to_messages())
```
**Note:** This is ALREADY broken today — calling `.invoke()` without `chat_history` or `target_language` raises a `KeyError`. The legacy `generate_response()` function is only called by `POST /chat/` and `POST /chat/stream` (the legacy non-agentic endpoints).

**Required change:**
```python
messages = prompt_templates.generator_messages(query=query, references=references)
response = chat_model.invoke(messages)
```
The builder function must provide defaults for `target_language` (default: `"english"`) and `chat_history` (default: `[]`).

**Risk if missed:** `AttributeError: 'function' object has no attribute 'invoke'` after Phase 18 refactor replaces the template with a function.

### Undocumented #3: `services/primer_service.py`

**Location:** Lines 792 and 859
**Current code:**
```python
from core.prompt_templates import primer_generation_prompt_template
...
formatted_prompt = primer_generation_prompt_template.invoke(prompt_inputs)
response = await primers_model.ainvoke(formatted_prompt)  # or astream
```
**Required change:**
```python
from core.prompt_templates import primer_generation_messages
...
messages = primer_generation_messages(**prompt_inputs)
response = await primers_model.ainvoke(messages)  # or astream
```
`prompt_inputs` is a dict with keys matching the builder function's parameter names exactly.

**Risk if missed:** `AttributeError: 'function' object has no attribute 'invoke'` when any primer is generated.

---

## Common Pitfalls

### Pitfall 1: `f-string` vs `.format()` for human message templates

**What goes wrong:** The existing `fiqhClassifierUserTemplate`, `nonIslamicClassiferUserTemplate`, `translationUserTemplate` etc. are multi-line strings with `{variable}` placeholders. Using an f-string directly would require Python variables in scope. Using `.format()` is the correct approach — it matches how `ChatPromptTemplate` resolved them.

**How to avoid:** In builder functions, use `fiqhClassifierUserTemplate.format(chatContext=chatContext, query=query)` not an f-string. For templates with only one or two variables, both work — but `.format()` is safer for templates with many variables.

**Edge case:** `primerGenerationSystemTemplate` contains `{{` and `}}` (double-braces — escaped) for the JSON format example. `.format()` will correctly convert `{{` → `{` and `}}` → `}`. An f-string would also work. Either is fine.

### Pitfall 2: Mutable default argument in `generator_messages`

**What goes wrong:** Python reuses mutable default arguments across calls.

```python
# WRONG — mutable default:
def generator_messages(query, references, target_language="english", chat_history=[]):
    return [SystemMessage(...), *chat_history, HumanMessage(...)]

# RIGHT:
def generator_messages(query, references, target_language="english", chat_history=None):
    if chat_history is None:
        chat_history = []
    return [SystemMessage(...), *chat_history, HumanMessage(...)]
```

**Why it happens:** Classic Python gotcha. The empty list `[]` is shared across all calls with no `chat_history` argument.

### Pitfall 3: `pipeline_langgraph.py` imports `_prompt` by name

**What goes wrong:** `from modules.fiqh.generator import (_prompt as fiqh_prompt, ...)` — if `_prompt` is deleted from `generator.py` without updating this import, the first fiqh query will fail with `ImportError`.

**How to avoid:** CONTEXT.md does not mention this call site. It must be discovered from the codebase (confirmed in this research at line 225). Change import to `_build_messages as fiqh_build_messages`.

### Pitfall 4: `stream_generator.py` chain pattern vs direct stream

**What goes wrong:** `generate_elaboration_response_stream` uses `chain = prompt | chat_model` and `chain.stream({...dict...})`. After `hikmah_elaboration_prompt_template` becomes a function, `prompt | chat_model` raises `TypeError: unsupported operand type(s) for |: 'function' and 'ChatAnthropic'`.

**How to avoid:** Replace with `chat_model.stream(hikmah_elaboration_messages(...))`. The `|` operator only works with `Runnable` objects, not plain Python functions.

### Pitfall 5: `with_redis_history` import in `stream_generator.py`

**What goes wrong:** After removing `with_redis_history(chain)` from `generate_response_stream`, if `with_redis_history` is still imported at the top of the file but unused, `pytest-socket` or linting may warn. More importantly, `with_redis_history` is not used anywhere else in `stream_generator.py`.

**How to avoid:** Remove `with_redis_history` from the import line on line 5. Keep `make_history` and `trim_history` — these are still used.

Current import: `from core.memory import with_redis_history, trim_history, make_history`
After: `from core.memory import trim_history, make_history`

### Pitfall 6: Test `fake_model_fn` assertion logic change

**What goes wrong:** The test at line 176-178 expects `payload["chat_history"]` to exist because the current chain uses dict-based invocation. After refactor, `pipeline_langgraph.py` calls `chat_model.stream(messages)` where `messages` is a list of `BaseMessage` objects. The `fake_model_fn` will receive a list, not a dict.

**Current test:**
```python
def fake_model_fn(payload):
    captured["history"] = payload["chat_history"]
    return "Generated answer"
```

**After refactor, pipeline_langgraph.py calls `chat_model.stream(messages_list)`. The monkeypatched model receives the list directly.**

**Fix:** The test patches `core.prompt_templates.generator_messages` (not `generator_prompt_template`). Since `pipeline_langgraph.py` calls `prompt_templates.generator_messages(...)` to build the list and then `chat_model.stream(list)`, the test can either:

Option A — patch `generator_messages` to return a known value and check that `chat_model.stream` receives it:
```python
monkeypatch.setattr("core.prompt_templates.generator_messages", 
    lambda query, references, target_language, chat_history: chat_history)
# Then fake_model_fn(payload) where payload is the list of history messages
def fake_model_fn(payload):
    captured["history"] = payload  # payload is now the messages list returned by lambda
    return "Generated answer"
```

Option B — patch `generator_messages` to return a dict-like proxy and verify `"Earlier context"` appears in the messages. The simplest approach is Option A: make the lambda return `chat_history` directly so `fake_model_fn` receives it as `payload`.

**The assertion `captured["history"][0].content == "Earlier context"` still works with Option A** because `chat_history` is `[HumanMessage(content="Earlier context")]` from `FakeHistory`.

### Pitfall 7: `primer_service.py` `ainvoke` vs `astream` both need updating

**What goes wrong:** Only one of the two `primer_generation_prompt_template.invoke(prompt_inputs)` calls is updated. Both line 792 AND line 859 call it independently — they are in separate methods (`_generate_bullets_with_llm` and `_stream_bullets_with_llm`).

**How to avoid:** Both lines must change. The import at line 17 (`from core.prompt_templates import primer_generation_prompt_template`) must change to import `primer_generation_messages` instead.

---

## Code Examples

### Fiqh module — complete before/after (modules/fiqh/decomposer.py)

Before (lines 11, 41-44, 57-58):
```python
from langchain.prompts import ChatPromptTemplate  # REMOVE

_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "Query: {query}")
])

def decompose_query(query: str) -> list[str]:
    model = chat_models.get_classifier_model()
    response = model.invoke(_prompt.format_messages(query=query))
```

After:
```python
# langchain.prompts import removed
from langchain_core.messages import HumanMessage
from core.chat_models import make_cached_system_message

def _build_messages(query: str) -> list:
    return [
        make_cached_system_message(SYSTEM_PROMPT),
        HumanMessage(content=f"Query: {query}"),
    ]

def decompose_query(query: str) -> list[str]:
    model = chat_models.get_classifier_model()
    response = model.invoke(_build_messages(query))
```

### `core/prompt_templates.py` — static system builder

Before:
```python
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
...
fiqh_classifier_system_prompt = ChatPromptTemplate.from_messages([
    ("system", fiqhClassifierSystemTemplate),
    ("user", fiqhClassifierUserTemplate),
])
```

After:
```python
from langchain_core.messages import SystemMessage, HumanMessage
from core.chat_models import make_cached_system_message
...
def fiqh_classifier_messages(query: str, chatContext: str) -> list:
    return [
        make_cached_system_message(fiqhClassifierSystemTemplate),
        HumanMessage(content=fiqhClassifierUserTemplate.format(
            chatContext=chatContext,
            query=query,
        )),
    ]
```

Note: `fiqhClassifierUserTemplate` uses `{chatContext}` and `{query}` — Python `.format()` substitutes them correctly.

### `core/prompt_templates.py` — dynamic system builder (generator)

```python
def generator_messages(
    query: str,
    references: str,
    target_language: str = "english",
    chat_history: list | None = None,
) -> list:
    if chat_history is None:
        chat_history = []
    return [
        SystemMessage(content=generatorSystemTemplate.format(
            target_language=target_language,
            references=references,
        )),
        *chat_history,
        HumanMessage(content=generatorUserTemplate.format(query=query)),
    ]
```

### `core/prompt_templates.py` — file header change

Before line 1:
```python
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
```

After (for templates that remain as ChatPromptTemplate — the two excluded enhancers):
```python
from langchain.prompts import ChatPromptTemplate  # Only for excluded enhancer templates
from langchain_core.messages import SystemMessage, HumanMessage
from core.chat_models import make_cached_system_message
```

`MessagesPlaceholder` import is no longer needed once `generator_prompt_template` is replaced.

---

## Recommended Change Order

Apply in this sequence to minimize time with broken intermediate state:

1. **`core/prompt_templates.py`** — Define all builder functions, keep enhancers as-is with comments. Remove `MessagesPlaceholder` from import. This file has no runtime callers that will break before step 2-7 are done (Python's module-level execution only runs definitions).

2. **6 fiqh modules** in any order: `classifier.py`, `refiner.py`, `sea.py`, `generator.py`, `decomposer.py`, `filter.py`. Each is self-contained. These are independent — no ordering constraint between them.

3. **`modules/classification/classifier.py`** and **`modules/translation/translator.py`** — Update call sites to use new builder functions from step 1.

4. **`modules/generation/stream_generator.py`** — Update both `generate_response_stream` and `generate_elaboration_response_stream`. Remove `with_redis_history` import.

5. **`modules/generation/generator.py`** — Update legacy call site.

6. **`services/primer_service.py`** — Update both `.invoke()` call sites and the import.

7. **`core/pipeline_langgraph.py`** — Update both: fiqh path (import `_build_messages`, remove chain pattern) and non-fiqh generation path (use `generator_messages`, call `chat_model.stream(messages)`).

8. **`tests/test_agentic_streaming_pipeline.py`** — Update monkeypatch and `fake_model_fn` assertion.

**Rationale for this order:** `core/prompt_templates.py` is the most-imported file; updating it first means all other files can import the new names immediately. Fiqh modules are fully independent. Consumer files (classification, translation, stream_generator, generator, primer_service, pipeline_langgraph) are updated after their dependencies are ready. Test is last since it tests the full path.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `ChatPromptTemplate.from_messages` for system prompts | `SystemMessage(content=[{type,text,cache_control}])` | Phase 17 established the helper | Enables Anthropic prompt caching; ChatPromptTemplate silently strips cache_control |
| `with_redis_history(chain)` for history injection | Explicit `make_history(session_id).messages` fetch | Phase 17 already used explicit fetch in pipeline_langgraph.py | Removes indirect chain wrapper; identical behavior |

**Deprecated patterns being removed:**
- `ChatPromptTemplate.from_messages(...)` at all system-prompt call sites (except excluded enhancers)
- `prompt.invoke({...}).to_messages()` consumer pattern
- `with_redis_history(chain)` in `stream_generator.generate_response_stream`
- `chain = template | model` pattern where `template` is a `ChatPromptTemplate`

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `generate_response()` in `modules/generation/generator.py` is the legacy path called only by `POST /chat/` and `POST /chat/stream` (not agentic path) | Undocumented Call Sites | If called by active agentic path, behavioral difference in `target_language` default would affect production responses |
| A2 | All 6 fiqh module `SYSTEM_PROMPT` constants have no runtime variables embedded (they are 100% static) | Standard Stack | If any contain `{variable}` formatting, `make_cached_system_message` would produce incorrect prompts on calls with missing variables |
| A3 | `primer_generation_prompt_template.invoke(prompt_inputs)` currently works (prompt_inputs dict has all required keys) | Undocumented Call Sites | If keys mismatch, the existing code may already be broken; Phase 18 change would propagate same-named keys to builder function |

**A2 verification:** Confirmed by reading all 6 fiqh SYSTEM_PROMPT constants — none contain `{}` single-brace Python format strings. [VERIFIED: code inspection]

**A1 verification:** `pipeline_langgraph.py` uses `prompt_templates.generator_messages` (the active agentic path) — confirmed it doesn't call `modules/generation/generator.py:generate_response()`. The legacy `generator.py` is imported in `modules/generation/stream_generator.py` (no), actually `generator.py` stands alone. [VERIFIED: code inspection, `generator.py` is only imported in `api/chat.py` for the legacy endpoint]

---

## Open Questions (RESOLVED)

1. **`primer_generation_prompt_template` — which model does `primers_model` use?**
   - What we know: `primers_model = get_enhancer_model()` (line 34 of `primer_service.py`) which returns `ChatAnthropic(model=SMALL_LLM)` — Haiku 4.5.
   - What's unclear: `primerGenerationSystemTemplate` is ~700 words ≈ ~900 tokens — below Haiku's 4096-token minimum. Should `make_cached_system_message` even be applied to this template?
   - CONTEXT.md D-04 says "primer generation (its system body has no runtime variables)" → use `make_cached_system_message`. But PITFALLS CRITICAL-1 says Haiku requires 4096 tokens.
   - **Finding:** `primerGenerationSystemTemplate` uses Haiku 4.5 (`SMALL_LLM`). At ~900 tokens, applying `make_cached_system_message` will produce zero cache hits (silent, not an error). The `cache_control` marker is harmlessly ignored below threshold.
   - **Recommendation:** Still apply `make_cached_system_message` per D-04 (structural consistency; the marker is harmless when below threshold). Add an inline comment noting the token count may be below Haiku's 4096-token minimum and cache hits are not guaranteed. The planner should confirm with the user if they want the comment or to skip `make_cached_system_message` for this one template.

2. **`hikmah_elaboration_prompt_template` — the current `stream_generator.py` uses it as `prompt | chat_model` (a LangChain Runnable chain), which enables streaming via `chain.stream({dict})`.**
   - After refactor, `hikmah_elaboration_messages(...)` returns a list and `chat_model.stream(messages)` is called.
   - What's unclear: Does the LangChain `ChatAnthropic.stream(messages_list)` return the same `AIMessageChunk` objects as `chain.stream({dict})`?
   - **Finding:** `ChatAnthropic.stream(messages)` accepts `list[BaseMessage]` and returns `AIMessageChunk` iterator — identical to chain streaming. The `getattr(chunk, "content", ...)` pattern in `stream_generator.py` works unchanged. [ASSUMED — based on LangChain API contract; verified by pattern in `pipeline_langgraph.py` which already uses `model.stream(messages)` at line 270]

---

## Environment Availability

Step 2.6: SKIPPED (no external dependencies — pure code refactoring, no new tools, services, or runtimes required)

---

## Sources

### Primary (HIGH confidence)
- `core/prompt_templates.py` — direct code inspection; all 9 ChatPromptTemplate call sites enumerated [VERIFIED: code inspection]
- `modules/fiqh/{classifier,refiner,sea,generator,decomposer,filter}.py` — direct code inspection; all 6 `_prompt` patterns confirmed [VERIFIED: code inspection]
- `modules/classification/classifier.py`, `modules/translation/translator.py` — consumer call site patterns confirmed [VERIFIED: code inspection]
- `modules/generation/stream_generator.py`, `modules/generation/generator.py` — current patterns and required changes confirmed [VERIFIED: code inspection]
- `core/pipeline_langgraph.py` lines 224-225, 332-344 — two undocumented call sites confirmed [VERIFIED: code inspection]
- `services/primer_service.py` lines 17, 792, 859 — undocumented call site confirmed [VERIFIED: code inspection]
- `tests/test_agentic_streaming_pipeline.py` line 185 — monkeypatch confirmed [VERIFIED: code inspection]
- `core/chat_models.py` — `make_cached_system_message` helper confirmed present [VERIFIED: code inspection]
- `core/memory.py` — `make_history(session_id)` signature confirmed [VERIFIED: code inspection]
- `.planning/research/PITFALLS.md` — INTEGRATION-2 (ChatPromptTemplate strips cache_control), CRITICAL-1 (token thresholds) [CITED: project research]
- `.planning/phases/18-module-prompt-restructuring/18-CONTEXT.md` — all locked decisions [CITED: context]

### Secondary (MEDIUM confidence)
- Python `.format()` behavior on `{{` / `}}` double-braces in `primerGenerationSystemTemplate` — confirmed via Python 3.11 runtime test [VERIFIED: runtime]
- `ChatPromptTemplate.invoke()` without `chat_history`/`target_language` raises `KeyError` — confirmed via runtime test [VERIFIED: runtime]

---

## Metadata

**Confidence breakdown:**
- Call site inventory: HIGH — all files read directly, no grep misses
- Before/after patterns: HIGH — derived from actual code, not assumptions
- Undocumented call sites: HIGH — confirmed via grep and direct file reads
- Test update strategy: MEDIUM — the exact assertion logic in the test monkeypatch requires planner to verify against test behavior

**Research date:** 2026-05-03
**Valid until:** Until any of the 9 primary files are modified (stable refactor scope)

## Project Constraints (from CLAUDE.md)

Directives that the planner must verify compliance with:

| Directive | Implication for Phase 18 |
|-----------|--------------------------|
| `snake_case` for modules/functions; `PascalCase` for classes | Builder function names must be `snake_case`: `generator_messages`, `fiqh_classifier_messages`, `_build_messages` |
| Add type hints to new/changed functions | All builder functions need `-> list[BaseMessage]` return type annotations |
| Prefer `logger.*` over `print()` in new code | No new `print()` statements in builder functions |
| Commit style: short imperative subjects | Plan must specify commit message format per file group |
| GSD workflow enforcement: use `/gsd:execute-phase` for planned phase work | Covered by this planning workflow |
| Route handlers: no business logic | Not applicable — changes are in modules/core layer |
| Error handling: tools return error dicts, don't raise | Not applicable — these are prompt builders, not tools |
