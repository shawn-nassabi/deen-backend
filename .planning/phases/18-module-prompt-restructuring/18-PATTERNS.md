# Phase 18: Module Prompt Restructuring - Pattern Map

**Mapped:** 2026-05-03
**Files analyzed:** 14 (new/modified)
**Analogs found:** 14 / 14

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `core/prompt_templates.py` | utility (prompt builder) | transform | itself (before/after) | self |
| `modules/fiqh/decomposer.py` | utility (LLM call) | request-response | `modules/fiqh/filter.py` | exact |
| `modules/fiqh/classifier.py` | utility (LLM call, structured output) | request-response | `modules/fiqh/sea.py` | exact |
| `modules/fiqh/refiner.py` | utility (LLM call, multi-param) | request-response | `modules/fiqh/filter.py` | exact |
| `modules/fiqh/sea.py` | utility (LLM call, structured output) | request-response | `modules/fiqh/classifier.py` | exact |
| `modules/fiqh/generator.py` | utility (LLM call) | request-response | `modules/fiqh/decomposer.py` | exact |
| `modules/fiqh/filter.py` | utility (LLM call) | request-response | `modules/fiqh/decomposer.py` | exact |
| `modules/classification/classifier.py` | utility (LLM call, consumer) | request-response | `modules/translation/translator.py` | exact |
| `modules/translation/translator.py` | utility (LLM call, consumer) | request-response | `modules/classification/classifier.py` | exact |
| `modules/generation/stream_generator.py` | service (streaming) | streaming | `core/pipeline_langgraph.py` lines 325-351 | role-match |
| `modules/generation/generator.py` | utility (LLM call, legacy) | request-response | `modules/fiqh/generator.py` | role-match |
| `core/pipeline_langgraph.py` | pipeline (streaming) | streaming | itself (before/after) | self |
| `services/primer_service.py` | service (async LLM) | request-response | itself (before/after) | self |
| `tests/test_agentic_streaming_pipeline.py` | test | request-response | itself (before/after) | self |

---

## Pattern Assignments

### `core/prompt_templates.py` (utility, transform)

**Analog:** Phase 17 established helper in `core/chat_models.py`

**Current imports** (lines 1):
```python
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
```

**Required imports after refactor:**
```python
from langchain.prompts import ChatPromptTemplate  # Only for excluded enhancer templates
from langchain_core.messages import SystemMessage, HumanMessage
from core.chat_models import make_cached_system_message
```
Note: `MessagesPlaceholder` is removed entirely — no longer needed after `generator_prompt_template` is replaced.

**Pattern A — Static system prompt builder** (apply to: `fiqh_classifier_messages`, `nonislamic_classifier_messages`, `translation_messages`, `primer_generation_messages`):

Current form at lines 186-187:
```python
fiqh_classifier_system_prompt = ChatPromptTemplate.from_messages(
    [("system", fiqhClassifierSystemTemplate), ("user", fiqhClassifierUserTemplate)])
```

After-refactor form:
```python
def fiqh_classifier_messages(query: str, chatContext: str) -> list:
    return [
        make_cached_system_message(fiqhClassifierSystemTemplate),
        HumanMessage(content=fiqhClassifierUserTemplate.format(
            chatContext=chatContext,
            query=query,
        )),
    ]
```

**Pattern B — Dynamic system prompt builder** (apply to: `generator_messages`, `hikmah_elaboration_messages`):

Dynamic prompts have runtime variables embedded in the system body — use plain `SystemMessage`, NOT `make_cached_system_message`.

Current form at lines 60-64:
```python
generator_prompt_template = ChatPromptTemplate.from_messages([
  ("system", generatorSystemTemplate),
  MessagesPlaceholder("chat_history"),
  ("human", generatorUserTemplate)
])
```

After-refactor form:
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

**Enhancer exclusion comment** (lines 104 and 135, leave `ChatPromptTemplate` as-is):
```python
# NOT refactored to make_cached_system_message — SMALL_LLM (Haiku 4.5) requires
# 4096-token minimum; enhancer system prompt is ~330 tokens (guaranteed cost
# increase with zero cache hits if cache_control were applied).
enhancer_prompt_template = ChatPromptTemplate.from_messages([...])

# NOT refactored — same reason as enhancer_prompt_template above.
elaboration_enhancer_prompt_template = ChatPromptTemplate.from_messages([...])
```

**`primer_generation_messages` note:** `primerGenerationSystemTemplate` uses `{{` and `}}` (escaped braces for JSON format example). Python `.format()` correctly converts `{{` → `{` and `}}` → `}`. The system prompt is ~900 tokens — below Haiku's 4096-token minimum — so `make_cached_system_message` is applied per D-04 for structural consistency; cache hits are not guaranteed.

---

### `modules/fiqh/decomposer.py` (utility, request-response) — reference example for all 6 fiqh modules

**Analog:** itself (simplest case), confirmed against all 6 fiqh files

**Current imports** (lines 8-12):
```python
from langchain.prompts import ChatPromptTemplate
from core import chat_models
```

**Required imports after refactor** (replace `ChatPromptTemplate` import):
```python
from langchain_core.messages import HumanMessage
from core.chat_models import make_cached_system_message
from core import chat_models
```

**Current `_prompt` declaration** (lines 41-44):
```python
_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "Query: {query}")
])
```

**After-refactor `_build_messages`** (delete `_prompt`, add function):
```python
def _build_messages(query: str) -> list:
    return [
        make_cached_system_message(SYSTEM_PROMPT),
        HumanMessage(content=f"Query: {query}"),
    ]
```

**Current call site** (line 57):
```python
response = model.invoke(_prompt.format_messages(query=query))
```

**After-refactor call site:**
```python
response = model.invoke(_build_messages(query))
```

---

### `modules/fiqh/classifier.py` (utility, request-response, structured output)

**Analog:** `modules/fiqh/sea.py` — both use `with_structured_output`

**Current `_prompt`** (lines 60-63):
```python
_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{query}"),
])
```

**After-refactor `_build_messages`:**
```python
def _build_messages(query: str) -> list:
    return [
        make_cached_system_message(SYSTEM_PROMPT),
        HumanMessage(content=query),
    ]
```

**Current call site** (lines 79-81) — structured output variant:
```python
structured_model = model.with_structured_output(FiqhCategory)
result = structured_model.invoke(_prompt.format_messages(query=query))
```

**After-refactor call site** (no change to `with_structured_output` call itself):
```python
structured_model = model.with_structured_output(FiqhCategory)
result = structured_model.invoke(_build_messages(query))
```

---

### `modules/fiqh/refiner.py` (utility, request-response, multi-param human message)

**Analog:** `modules/fiqh/filter.py` — also passes pre-formatted string variables into human message

**Current `_prompt`** (lines 36-50):
```python
_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", """Original query: {original_query}
...
Generate 1-4 new retrieval sub-queries targeting the gaps above."""),
])
```

**After-refactor `_build_messages`** — receives already-formatted strings (pre-formatting logic stays in `refine_query`):
```python
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

**Current call site** (lines 79-84):
```python
response = model.invoke(_prompt.format_messages(
    original_query=original_query,
    confirmed_facts=confirmed_facts_text,
    gaps=gaps_text,
    prior_queries=prior_queries_text,
))
```

**After-refactor call site:**
```python
response = model.invoke(_build_messages(
    original_query=original_query,
    confirmed_facts=confirmed_facts_text,
    gaps=gaps_text,
    prior_queries=prior_queries_text,
))
```

---

### `modules/fiqh/sea.py` (utility, request-response, structured output, 2-param)

**Analog:** `modules/fiqh/classifier.py` — both use `with_structured_output`

**Current `_prompt`** (lines 52-55):
```python
_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "Query: {query}\n\nRetrieved Evidence:\n{evidence}"),
])
```

**After-refactor `_build_messages`:**
```python
def _build_messages(query: str, evidence: str) -> list:
    return [
        make_cached_system_message(SYSTEM_PROMPT),
        HumanMessage(content=f"Query: {query}\n\nRetrieved Evidence:\n{evidence}"),
    ]
```

**Current call site** (lines 86-90):
```python
result = structured_model.invoke(
    _prompt.format_messages(
        query=query,
        evidence=_format_evidence(docs),
    )
)
```

**After-refactor call site:**
```python
result = structured_model.invoke(
    _build_messages(query=query, evidence=_format_evidence(docs))
)
```

---

### `modules/fiqh/generator.py` (utility, request-response, 2-param)

**Analog:** `modules/fiqh/filter.py` — same 2-param human message structure

**Current `_prompt`** (lines 45-53):
```python
_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", """Question: {query}

Evidence:
{evidence}

Generate a comprehensive answer with inline [n] citations referencing the evidence numbers above."""),
])
```

**After-refactor `_build_messages`:**
```python
def _build_messages(query: str, evidence: str) -> list:
    return [
        make_cached_system_message(SYSTEM_PROMPT),
        HumanMessage(content=f"""Question: {query}

Evidence:
{evidence}

Generate a comprehensive answer with inline [n] citations referencing the evidence numbers above."""),
    ]
```

**Current call site** (lines 110-113):
```python
response = model.invoke(_prompt.format_messages(
    query=query,
    evidence=_format_evidence(docs),
))
```

**After-refactor call site:**
```python
response = model.invoke(_build_messages(
    query=query,
    evidence=_format_evidence(docs),
))
```

**CRITICAL — also exported to pipeline_langgraph.py:** The `_prompt` object is imported externally. When `_prompt` is deleted, the import in `core/pipeline_langgraph.py` line 225 must change in the same commit (see pipeline_langgraph.py section below).

---

### `modules/fiqh/filter.py` (utility, request-response, 2-param)

**Analog:** `modules/fiqh/generator.py` — identical structure

**Current `_prompt`** (lines 35-38):
```python
_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "Query: {query}\n\nEvidence passages:\n{evidence}"),
])
```

**After-refactor `_build_messages`:**
```python
def _build_messages(query: str, evidence: str) -> list:
    return [
        make_cached_system_message(SYSTEM_PROMPT),
        HumanMessage(content=f"Query: {query}\n\nEvidence passages:\n{evidence}"),
    ]
```

**Current call site** (lines 68-71):
```python
response = model.invoke(_prompt.format_messages(
    query=query,
    evidence=_format_evidence_with_ids(docs),
))
```

**After-refactor call site:**
```python
response = model.invoke(_build_messages(
    query=query,
    evidence=_format_evidence_with_ids(docs),
))
```

---

### `modules/classification/classifier.py` (utility, consumer)

**Analog:** `modules/translation/translator.py` — same consumer pattern

**Current imports** (lines 1-3):
```python
from modules.context import context
from core import chat_models
from core import prompt_templates
```
Imports are unchanged — `prompt_templates` is still imported; only the call form changes.

**Current call site 1** (lines 17-18):
```python
prompt = prompt_templates.fiqh_classifier_system_prompt.invoke({"query": query,"chatContext": chatContext})
response = chat_model.invoke(prompt.to_messages())
```

**After-refactor call site 1:**
```python
messages = prompt_templates.fiqh_classifier_messages(query=query, chatContext=chatContext)
response = chat_model.invoke(messages)
```

**Current call site 2** (lines 34-35):
```python
prompt = prompt_templates.nonislamic_classifer_prompt_template.invoke({"query": query,"chatContext": chatContext})
response = chat_model.invoke(prompt.to_messages())
```

**After-refactor call site 2:**
```python
messages = prompt_templates.nonislamic_classifier_messages(query=query, chatContext=chatContext)
response = chat_model.invoke(messages)
```

---

### `modules/translation/translator.py` (utility, consumer)

**Analog:** `modules/classification/classifier.py` — same consumer pattern

**Current call site** (lines 17-18):
```python
prompt = prompt_templates.translation_prompt_template.invoke({"source_language": source_language or "unknown", "text": text})
response = chat_model.invoke(prompt.to_messages())
```

**After-refactor call site:**
```python
messages = prompt_templates.translation_messages(source_language=source_language or "unknown", text=text)
response = chat_model.invoke(messages)
```

---

### `modules/generation/stream_generator.py` (service, streaming)

**Analog:** `core/pipeline_langgraph.py` lines 325-351 — already uses explicit history fetch + `chat_model.stream(messages)` pattern

**Current imports** (line 5):
```python
from core.memory import with_redis_history, trim_history, make_history
```

**After-refactor imports** (remove `with_redis_history` — unused after this change):
```python
from core.memory import trim_history, make_history
```

**`generate_response_stream` — current pattern** (lines 27-38):
```python
prompt = prompt_templates.generator_prompt_template
chain = prompt | chat_model

chain_with_history = with_redis_history(chain)

for chunk in chain_with_history.stream(
    {"target_language": target_language, "query": query, "references": references},
    config={"configurable": {"session_id": session_id}},
):
    yield getattr(chunk, "content", str(chunk) if chunk is not None else "")
```

**After-refactor pattern** — mirrors `pipeline_langgraph.py` lines 334-348 exactly:
```python
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

**`generate_elaboration_response_stream` — current pattern** (lines 68-76):
```python
prompt = prompt_templates.hikmah_elaboration_prompt_template
chain = prompt | chat_model

for chunk in chain.stream(
    {"selected_text": selected_text, "context_text": context_text,
     "hikmah_tree_name": hikmah_tree_name, "lesson_name": lesson_name,
     "lesson_summary": lesson_summary, "references": references}):
    content = getattr(chunk, "content", str(chunk) if chunk is not None else "")
```

**After-refactor pattern** (remove `prompt | chat_model` chain, call builder directly):
```python
messages = prompt_templates.hikmah_elaboration_messages(
    selected_text=selected_text,
    context_text=context_text,
    hikmah_tree_name=hikmah_tree_name,
    lesson_name=lesson_name,
    lesson_summary=lesson_summary,
    references=references,
)
for chunk in chat_model.stream(messages):
    content = getattr(chunk, "content", str(chunk) if chunk is not None else "")
```

---

### `modules/generation/generator.py` (utility, legacy call site)

**Analog:** `modules/fiqh/generator.py` — same invoke-model pattern

**Current call site** (lines 17-19):
```python
prompt = prompt_templates.generator_prompt_template.invoke({"query":query,"references":references})
response = chat_model.invoke(prompt.to_messages())
```

**After-refactor call site** (`target_language` and `chat_history` use defaults from builder):
```python
messages = prompt_templates.generator_messages(query=query, references=references)
response = chat_model.invoke(messages)
```

---

### `core/pipeline_langgraph.py` (pipeline, streaming) — two change sites

**Analog:** existing lines 334-348 (non-fiqh path) serve as the after pattern for both sites

**Change site 1: fiqh path import** (line 224-225):
```python
# BEFORE:
from modules.fiqh.generator import (
    _prompt as fiqh_prompt,
    _format_evidence,
    _build_references_section,
    INSUFFICIENT_WARNING,
    FATWA_DISCLAIMER,
)
```
```python
# AFTER:
from modules.fiqh.generator import (
    _build_messages as fiqh_build_messages,
    _format_evidence,
    _build_references_section,
    INSUFFICIENT_WARNING,
    FATWA_DISCLAIMER,
)
```

**Change site 1: fiqh streaming loop** (lines 267-273):
```python
# BEFORE:
model = chat_models.get_generator_model()
chain = fiqh_prompt | model
response_tokens = []
for chunk in chain.stream({
    "query": user_query,
    "evidence": _format_evidence(fiqh_docs),
}):
```
```python
# AFTER:
model = chat_models.get_generator_model()
fiqh_messages = fiqh_build_messages(
    query=user_query,
    evidence=_format_evidence(fiqh_docs),
)
response_tokens = []
for chunk in model.stream(fiqh_messages):
```

**Change site 2: non-fiqh generation path** (lines 332-344):
```python
# BEFORE:
prompt = prompt_templates.generator_prompt_template
chain = prompt | chat_model
history_messages = make_history(runtime_session_id).messages

response_tokens = []
for chunk in chain.stream(
    {
        "target_language": target_language,
        "query": user_query,
        "references": references,
        "chat_history": history_messages,
    },
):
```
```python
# AFTER:
history_messages = make_history(runtime_session_id).messages
messages = prompt_templates.generator_messages(
    query=user_query,
    references=references,
    target_language=target_language,
    chat_history=history_messages,
)
response_tokens = []
for chunk in chat_model.stream(messages):
```

---

### `services/primer_service.py` (service, async LLM) — two call sites

**Analog:** `modules/generation/generator.py` after-refactor pattern — same `model.invoke(messages)` approach

**Current import** (line 17):
```python
from core.prompt_templates import primer_generation_prompt_template
```

**After-refactor import:**
```python
from core.prompt_templates import primer_generation_messages
```

**Call site 1** (line 792, inside `_generate_bullets_with_llm`):
```python
# BEFORE:
formatted_prompt = primer_generation_prompt_template.invoke(prompt_inputs)
response = await primers_model.ainvoke(formatted_prompt)
```
```python
# AFTER:
messages = primer_generation_messages(**prompt_inputs)
response = await primers_model.ainvoke(messages)
```

**Call site 2** (lines 859, 868, inside `_stream_bullets_with_llm`):
```python
# BEFORE:
formatted_prompt = primer_generation_prompt_template.invoke(prompt_inputs)
...
async for chunk in primers_model.astream(formatted_prompt):
```
```python
# AFTER:
messages = primer_generation_messages(**prompt_inputs)
...
async for chunk in primers_model.astream(messages):
```

`prompt_inputs` keys (`lesson_title`, `lesson_content`, `baseline_bullets`, `user_learning_notes`, `user_interest_notes`, `user_knowledge_notes`, `user_preference_notes`) must match the parameter names of `primer_generation_messages(...)` exactly.

---

### `tests/test_agentic_streaming_pipeline.py` (test, monkeypatch update)

**Analog:** same file — test logic is self-contained

**Current monkeypatch** (line 185):
```python
monkeypatch.setattr("core.prompt_templates.generator_prompt_template", RunnableLambda(lambda x: x))
```

**After-refactor monkeypatch** (patch the function, not a template object):
```python
monkeypatch.setattr(
    "core.prompt_templates.generator_messages",
    lambda query, references, target_language, chat_history: chat_history,
)
```

**Current `fake_model_fn`** (lines 176-178):
```python
def fake_model_fn(payload):
    captured["history"] = payload["chat_history"]
    return "Generated answer"
```

**After-refactor `fake_model_fn`** — `pipeline_langgraph.py` now calls `chat_model.stream(messages)` where `messages` is the list returned by the lambda (which is `chat_history`):
```python
def fake_model_fn(payload):
    captured["history"] = payload  # payload is now the chat_history list directly
    return "Generated answer"
```

**Assertion at line 206 remains valid** because `chat_history` is `[HumanMessage(content="Earlier context")]` from `FakeHistory`, and the lambda returns it as-is, so `fake_model_fn` receives it as `payload`:
```python
assert captured["history"] and captured["history"][0].content == "Earlier context"
```

---

## Shared Patterns

### `make_cached_system_message` (static system prompts)
**Source:** `core/chat_models.py` lines 6-24
**Apply to:** All 6 fiqh `_build_messages` functions; `fiqh_classifier_messages`, `nonislamic_classifier_messages`, `translation_messages`, `primer_generation_messages` in `core/prompt_templates.py`
```python
def make_cached_system_message(text: str) -> SystemMessage:
    return SystemMessage(content=[
        {
            "type": "text",
            "text": text,
            "cache_control": {"type": "ephemeral"},
        }
    ])
```
Import: `from core.chat_models import make_cached_system_message`

### Plain `SystemMessage` (dynamic system prompts)
**Source:** `langchain_core.messages`
**Apply to:** `generator_messages`, `hikmah_elaboration_messages` in `core/prompt_templates.py`
Use `SystemMessage(content=template_string.format(**runtime_vars))` — NOT `make_cached_system_message` — because system body changes every request, making caching a guaranteed cost increase with zero hits.

### Explicit history fetch pattern
**Source:** `core/pipeline_langgraph.py` lines 326-334 (already in production)
**Apply to:** `modules/generation/stream_generator.py:generate_response_stream`
```python
from core.memory import make_history
history_messages = make_history(session_id).messages
```

### Direct model streaming (no chain wrapper)
**Source:** `core/pipeline_langgraph.py` line 270 (fiqh path), line 346 (non-fiqh path)
**Apply to:** Both streaming functions in `stream_generator.py`, both streaming paths in `pipeline_langgraph.py`
```python
for chunk in model.stream(messages):
    token = getattr(chunk, "content", str(chunk) if chunk is not None else "")
```
The `prompt | model` chain pattern is only valid when `prompt` is a LangChain `Runnable`. After refactor, builder functions return a plain `list[BaseMessage]` — the `|` operator would raise `TypeError`.

### Type annotation convention
**Source:** `core/chat_models.py` (all functions typed), `modules/fiqh/refiner.py` (typed return)
**Apply to:** All new builder functions
```python
def _build_messages(...) -> list:      # fiqh module functions (RESEARCH uses bare list)
def generator_messages(...) -> list:   # prompt_templates builder functions
```
Full annotation `list[BaseMessage]` is preferred per CLAUDE.md type hints convention; import `BaseMessage` from `langchain_core.messages` if using it.

### Mutable default argument guard
**Source:** RESEARCH.md Pitfall 2 (standard Python convention)
**Apply to:** `generator_messages` in `core/prompt_templates.py`
```python
def generator_messages(..., chat_history: list | None = None) -> list:
    if chat_history is None:
        chat_history = []
    return [SystemMessage(...), *chat_history, HumanMessage(...)]
```

---

## No Analog Found

All 14 files have existing code in the codebase that serves as a direct analog. No files require falling back to RESEARCH.md patterns for the primary implementation.

---

## Metadata

**Analog search scope:** `core/`, `modules/fiqh/`, `modules/classification/`, `modules/translation/`, `modules/generation/`, `services/`, `tests/`
**Files scanned:** 14 primary files read directly
**Pattern extraction date:** 2026-05-03

**Change order (from RESEARCH.md):**
1. `core/prompt_templates.py` — define all builder functions; keeps broken-import window minimal
2. 6 fiqh modules — any order; fully independent
3. `modules/classification/classifier.py`, `modules/translation/translator.py`
4. `modules/generation/stream_generator.py`
5. `modules/generation/generator.py`
6. `services/primer_service.py`
7. `core/pipeline_langgraph.py` — both fiqh and non-fiqh paths
8. `tests/test_agentic_streaming_pipeline.py`
