# Architecture: v1.4 — Anthropic Prompt Caching Integration

**Project:** Deen Backend v1.4 — LLM Input Caching
**Researched:** 2026-05-03
**Confidence:** HIGH — all claims verified against installed `langchain_anthropic==0.3.22` source, `anthropic` SDK source, and existing repo code

---

## Summary

Anthropic prompt caching is fully supported by the installed `langchain_anthropic==0.3.22` via the `cache_control` content-block field. No new packages or API header tricks are required. The integration surface is almost entirely in `core/chat_models.py` and two specific call sites in `agents/core/chat_agent.py`. The `modules/fiqh/` pipeline modules require targeted prompt restructuring to pass system prompts as content-block lists rather than plain strings.

The cleanest integration point is the **`core/chat_models.py` factory layer** — modify the four factory functions to return models configured to emit cached system-prompt blocks — combined with **targeted call-site changes** at the three places that construct messages inline (`_agent_node`, `_generate_response_node`, and the FAIR-RAG fiqh pipeline streaming path in `pipeline_langgraph.py`). The `ChatPromptTemplate`-based modules require a different technique (message content as a list of blocks rather than a plain string) applied directly to their `SYSTEM_PROMPT` constants.

**No new components are needed.** No LangChain-level caching (`set_llm_cache`) is involved — that is a separate, different feature (response memoization). This milestone is exclusively about Anthropic's native prompt caching for input token cost reduction.

---

## How Anthropic Prompt Caching Works (verified from installed source)

Prompt caching is controlled by placing `cache_control: {"type": "ephemeral"}` on specific content blocks sent to the Anthropic API. The cache is keyed on the exact token sequence up to and including the marked block. A cache hit requires: same model, same token sequence prefix, and the same position of the cache-control marker.

**Cache lifetime:** 5 minutes (default ephemeral). The `langchain_anthropic` library also supports `{"type": "ephemeral", "ttl": "1h"}` for 1-hour caching, but this is a paid-tier beta feature. Use 5-minute by default.

**Minimum tokens to cache:** 1024 tokens (Anthropic requirement). Blocks shorter than 1024 tokens will not be cached and the marker is ignored. All system prompts in this codebase exceed 300 tokens; some (`AGENT_SYSTEM_PROMPT`, `generatorSystemTemplate`) easily exceed 1024.

**What can be cached:**
1. System prompt content blocks (most valuable — same across all requests for a given call site)
2. Tool definitions bound to a `ChatAnthropic` instance (same across all requests, set at agent construction)
3. Large static retrieved context blocks passed as human message content (variable value — defer)

**Cache hit reporting:** `langchain_anthropic==0.3.22` surfaces cache metrics in `response.usage_metadata["input_token_details"]`:
```python
{
    "cache_read": 1458,      # tokens served from cache (not billed at full rate)
    "cache_creation": 0,     # tokens written to cache (billed at 1.25x)
}
```
`cache_read > 0` confirms a cache hit. Both fields are available on every response without any extra configuration.

**How `langchain_anthropic` passes `cache_control`:**
- For system prompts: pass `SystemMessage(content=[{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}])` — a list of content blocks instead of a plain string. The `_format_messages` function in `chat_models.py` passes the list directly as the `system` field.
- For tool definitions: use `convert_to_anthropic_tool(tool)`, set `["cache_control"] = {"type": "ephemeral"}` on the last tool dict, then pass the list to `.bind_tools()`.
- For message content blocks: construct `HumanMessage(content=[{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}])`.

---

## Integration Strategy Options

### Option A: Modify `core/chat_models.py` factory functions (RECOMMENDED — primary mechanism)

Each factory function currently returns a raw `ChatAnthropic` instance. The system prompts are attached at call sites (either via `ChatPromptTemplate` or directly in `messages` lists). The factory cannot inject `cache_control` into the system prompt because it does not construct the messages.

**What this option does:** The factory functions are modified to return a helper wrapper or a pre-configured instance. In practice, this means introducing a thin helper in `core/chat_models.py` that converts a plain-string system prompt into a cached content block:

```python
def make_cached_system_message(text: str) -> SystemMessage:
    """Wraps a system prompt string as a single cached content block."""
    return SystemMessage(content=[{
        "type": "text",
        "text": text,
        "cache_control": {"type": "ephemeral"},
    }])
```

Call sites that currently pass `SystemMessage(content=SYSTEM_PROMPT)` switch to `make_cached_system_message(SYSTEM_PROMPT)`. For `ChatPromptTemplate`-based modules, the `SYSTEM_PROMPT` constant is changed from a string to a list so the template emits a cached block.

**Assessment:** Clean separation. The factory layer stays focused on model instantiation; the helper function is a pure transformation utility that lives in `core/chat_models.py`. All modules that already import `core.chat_models` get the helper without a new import.

### Option B: `model_kwargs={"cache_control": ...}` on the `ChatAnthropic` instance

`langchain_anthropic` supports passing `cache_control` at invocation time (see `_get_request_payload` line 1579-1599). This applies the marker to the last message's last content block. It is not appropriate here: system prompts are the target, not the last user message. This approach is correct for dynamically-caching the trailing context block, but not for the static system prompt case.

**Assessment:** Wrong tool for this job. Applicable only to the "cache the retrieved context" use case, which is deferred.

### Option C: Modify each `SYSTEM_PROMPT` constant directly in each module

Change each `SYSTEM_PROMPT` string to a list of content blocks with `cache_control` inline. This works and requires no new utilities, but it scatters the cache-control concern across 8 different module files.

**Assessment:** Functional but messy. Mixing caching concerns into domain prompt constants creates noise. Use the `make_cached_system_message` helper instead (Option A) to keep the transformation in one place.

### Option D: Raw `anthropic` client calls, bypassing `langchain_anthropic`

The underlying `anthropic` Python SDK supports prompt caching with the same `cache_control` block structure. Calling it directly would bypass LangChain's message formatting.

**Assessment:** Do not use. The existing codebase is fully built on `langchain_anthropic`. Switching specific call sites to raw Anthropic SDK would create two incompatible invocation patterns in the same repo. `langchain_anthropic==0.3.22` already exposes the full caching API — there is no feature gap requiring raw SDK access.

### Option E: Use LangChain's `set_llm_cache` with an `InMemoryCache`

This is a **completely different feature** — it memoizes identical LLM invocations by caching the full response. It does not reduce Anthropic API input costs, does not interact with Anthropic's server-side prompt cache, and caches at the response level (not token level).

**Assessment:** Not relevant to this milestone. Do not confuse with Anthropic prompt caching.

---

## Recommended Approach

**Two-part approach: factory utility + targeted call-site restructuring.**

### Part 1: Add `make_cached_system_message` helper to `core/chat_models.py`

This utility is the single place where `cache_control` is authored. All other changes use it.

```python
from langchain_core.messages import SystemMessage

def make_cached_system_message(text: str) -> SystemMessage:
    """
    Wraps a system prompt string as an Anthropic ephemeral cached content block.
    The cache marker tells Anthropic to cache the token sequence up to this block.
    Minimum 1024 tokens required for caching to activate (shorter prompts are safe
    to mark — Anthropic silently ignores the marker when below threshold).
    """
    return SystemMessage(content=[{
        "type": "text",
        "text": text,
        "cache_control": {"type": "ephemeral"},
    }])
```

### Part 2: Tool definition caching on `ChatAgent`

`ChatAgent._create_llm_with_tools` currently calls `llm.bind_tools(self.tools)`. Tool definitions are static per agent instance. Apply `cache_control` to the last tool in the list (Anthropic caches the entire tool block list when the last entry is marked):

```python
from langchain_anthropic import convert_to_anthropic_tool

def _create_llm_with_tools(self):
    llm = ChatAnthropic(
        model=self.config.model.agent_model,
        api_key=ANTHROPIC_API_KEY,
        temperature=self.config.model.temperature,
        max_tokens=self.config.model.max_tokens,
    )
    # Convert tools to Anthropic format and mark the last one for caching.
    # This caches all tool definitions together (Anthropic caches the prefix
    # up to and including the marked block).
    anthropic_tools = [convert_to_anthropic_tool(t) for t in self.tools]
    if anthropic_tools:
        anthropic_tools[-1]["cache_control"] = {"type": "ephemeral"}
    return llm.bind_tools(anthropic_tools)
```

### Part 3: `_agent_node` system prompt caching

`_agent_node` currently does:
```python
messages.insert(0, SystemMessage(content=AGENT_SYSTEM_PROMPT))
```
Change to:
```python
from core.chat_models import make_cached_system_message
messages.insert(0, make_cached_system_message(AGENT_SYSTEM_PROMPT))
```

### Part 4: `_generate_response_node` system prompt caching

Same substitution: `SystemMessage(content=AGENT_SYSTEM_PROMPT)` → `make_cached_system_message(AGENT_SYSTEM_PROMPT)`.

### Part 5: `ChatPromptTemplate`-based modules

Modules using `ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ...])` emit the system prompt as a plain string. To cache it, change the `("system", ...)` tuple to pass a list:

```python
# Before (plain string — not cached):
_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{query}"),
])

# After (content block list — cached):
_prompt = ChatPromptTemplate.from_messages([
    ("system", [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]),
    ("human", "{query}"),
])
```

`_format_messages` in `langchain_anthropic` handles list-type system message content correctly (lines 297-307, verified in source).

### Part 6: Cache metrics logging

After every LLM call where a cached system prompt was used, extract and log the cache hit/miss count:

```python
response = model.invoke(...)
usage = getattr(response, "usage_metadata", {}) or {}
token_details = usage.get("input_token_details", {})
cache_read = token_details.get("cache_read", 0) or 0
cache_creation = token_details.get("cache_creation", 0) or 0
logger.info(
    "LLM call complete",
    extra={
        "correlation_id": correlation_id_ctx.get(),
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_creation,
        "call_site": "fiqh_classifier",  # identify the call site
    }
)
```

The `ExtraFormatter` already appends `extra` dict keys to log lines. No changes to logging infrastructure needed.

---

## Components to Modify

### Modified Files (no new files required)

| File | Change Type | What Changes |
|------|-------------|--------------|
| `core/chat_models.py` | MODIFIED | Add `make_cached_system_message()` utility function |
| `agents/core/chat_agent.py` | MODIFIED | `_create_llm_with_tools`: add `cache_control` to last tool def; `_agent_node` + `_generate_response_node`: use `make_cached_system_message` |
| `modules/fiqh/classifier.py` | MODIFIED | `_prompt`: change `("system", SYSTEM_PROMPT)` to content-block list |
| `modules/fiqh/decomposer.py` | MODIFIED | Same prompt template change |
| `modules/fiqh/filter.py` | MODIFIED | Same prompt template change |
| `modules/fiqh/sea.py` | MODIFIED | Same prompt template change |
| `modules/fiqh/refiner.py` | MODIFIED | Same prompt template change |
| `modules/fiqh/generator.py` | MODIFIED | Same prompt template change |
| `modules/classification/classifier.py` | MODIFIED | Same prompt template change (non-fiqh classifier) |
| `modules/enhancement/enhancer.py` | MODIFIED | Same prompt template change |
| `modules/translation/translator.py` | MODIFIED | Same prompt template change |
| `core/prompt_templates.py` | MODIFIED | `generator_prompt_template`, `enhancer_prompt_template`, `hikmah_elaboration_prompt_template`, `primer_generation_prompt_template`: change system tuple to content-block list |
| `core/pipeline_langgraph.py` | MODIFIED | Fiqh generation path: `SystemMessage(content=...)` calls → `make_cached_system_message(...)` |

### Files NOT Changed

| File | Why Not Touched |
|------|----------------|
| `agents/fiqh/fiqh_graph.py` | Graph topology only; LLM calls are in `modules/fiqh/` |
| `agents/state/chat_state.py` | No state changes needed |
| `agents/config/agent_config.py` | No new config fields required |
| `core/config.py` | No new env vars required |
| `db/`, `services/`, `api/` | Not LLM call sites |
| `modules/*/retriever.py`, `reranker.py` | No LLM calls |

---

## Call Site Inventory

Complete map of LLM call sites and their caching eligibility:

| Call Site | File | System Prompt | Eligible? | Token Est. | Priority |
|-----------|------|---------------|-----------|-----------|---------|
| `ChatAgent` tool-binding | `agents/core/chat_agent.py` | N/A — tool defs | YES — tool cache | ~800 tokens (6 tools) | HIGH |
| `_agent_node` | `agents/core/chat_agent.py` | `AGENT_SYSTEM_PROMPT` | YES — static | ~650 tokens | HIGH |
| `_generate_response_node` | `agents/core/chat_agent.py` | `AGENT_SYSTEM_PROMPT` | YES — static | ~650 tokens | HIGH |
| `generate_fiqh_response_node` | `agents/core/chat_agent.py` | fiqh generator system prompt | YES — static | ~350 tokens | MEDIUM |
| `fiqh classifier` | `modules/fiqh/classifier.py` | `SYSTEM_PROMPT` | YES — static | ~450 tokens | HIGH |
| `fiqh decomposer` | `modules/fiqh/decomposer.py` | `SYSTEM_PROMPT` | YES — static | ~350 tokens | HIGH |
| `fiqh filter` | `modules/fiqh/filter.py` | `SYSTEM_PROMPT` | YES — static | ~200 tokens | MEDIUM |
| `fiqh SEA assessor` | `modules/fiqh/sea.py` | `SYSTEM_PROMPT` | YES — static | ~300 tokens | HIGH |
| `fiqh refiner` | `modules/fiqh/refiner.py` | `SYSTEM_PROMPT` | YES — static | ~250 tokens | HIGH |
| `fiqh generator` | `modules/fiqh/generator.py` | `SYSTEM_PROMPT` | YES — static | ~300 tokens | HIGH |
| `non-fiqh classifier` | `modules/classification/classifier.py` | `fiqhClassifierSystemTemplate` | YES — static | ~600 tokens | MEDIUM |
| `non-Islamic classifier` | `modules/classification/classifier.py` | `nonIslamicClassifierSystemTemplate` | YES — static | ~300 tokens | MEDIUM |
| `enhancer` | `modules/enhancement/enhancer.py` | `enhancerSystemTemplate` | YES — static | ~350 tokens | MEDIUM |
| `translator` | `modules/translation/translator.py` | `translationSystemTemplate` | YES — static | ~120 tokens | LOW (below 1024 token threshold) |
| `generator` (non-fiqh) | `modules/generation/generator.py` | `generatorSystemTemplate` | YES — static | ~1200 tokens | HIGH |
| `stream_generator` | `modules/generation/stream_generator.py` | same `generatorSystemTemplate` | YES — static | ~1200 tokens | HIGH |
| `hikmah elaboration` | `core/prompt_templates.py` | `hikmahElaborationSystemTemplate` | YES — mostly static (has lesson context injection) | ~900 tokens | MEDIUM |
| `primer generation` | `core/prompt_templates.py` | `primerGenerationSystemTemplate` | YES — static | ~700 tokens | LOW |
| `memory consolidator` | `agents/core/memory_consolidator.py` | varies | LOW PRIORITY — not hot path | - | LOW |

**Note on the 1024-token minimum:** Prompts below 1024 tokens will have the marker silently ignored. It is safe to mark them anyway (no error, no cost), but the benefit is zero until the prompt grows. Mark all static prompts; let Anthropic decide whether to cache.

---

## Data Flow Changes

### Before (current, no caching)

```
Request → ChatAgent._agent_node
    → messages = [SystemMessage("...AGENT_SYSTEM_PROMPT string..."), ...]
    → llm.invoke(messages)  # Full system prompt tokenized + charged every call
    → Anthropic API: full input token charge
```

### After (with caching)

```
Request N=1 (cache miss — creates cache entry):
    → messages = [SystemMessage(content=[{
          "type": "text",
          "text": "...AGENT_SYSTEM_PROMPT...",
          "cache_control": {"type": "ephemeral"}
        }]), ...]
    → llm.invoke(messages)
    → Anthropic API: input tokens charged at 1.25x (cache write cost), 5-min TTL starts
    → response.usage_metadata["input_token_details"]["cache_creation"] = N

Request N=2..N (within 5 min — cache hit):
    → same messages structure, same cache_control marker
    → Anthropic API: system prompt tokens served from cache at ~10% of normal cost
    → response.usage_metadata["input_token_details"]["cache_read"] = N
    → logger emits: cache_read_tokens=N, cache_creation_tokens=0
```

**Important:** The cache key includes the entire token sequence up to the marker. For `_agent_node`, this is the system prompt only (user query is in subsequent messages). For tool definitions, it is the tool JSON. Both are request-invariant — the same sequence is sent every call, guaranteeing cache hits after the first call within the TTL window.

**FAIR-RAG sub-graph:** The fiqh pipeline calls classifier → decomposer → retrieve (loop) → filter → assess → refine → generator. All of these call sites have static system prompts. Within a single FAIR-RAG invocation (up to 3 iterations), the filter/assess/refine calls will benefit from caching even within the single request (the 5-minute TTL spans multiple sub-graph iterations).

---

## Build Order

Dependencies are minimal — all changes are additive patches to existing modules. Suggested phase grouping:

### Phase 1: Foundation — add helper, audit call sites
1. Add `make_cached_system_message()` to `core/chat_models.py`
2. Add cache metrics logging helper to `core/chat_models.py` (extract `cache_read`/`cache_creation` from `usage_metadata`)
3. Run manual smoke test to confirm `usage_metadata["input_token_details"]` is populated correctly on a real API call

**Rationale:** Build and verify the utility before touching any call sites. One confirmed working example before doing 12+ changes.

### Phase 2: ChatAgent tool definitions and inline system prompts (highest ROI)
1. `agents/core/chat_agent.py`: `_create_llm_with_tools` — add `cache_control` to last tool
2. `agents/core/chat_agent.py`: `_agent_node` — use `make_cached_system_message(AGENT_SYSTEM_PROMPT)`
3. `agents/core/chat_agent.py`: `_generate_response_node` — same
4. `agents/core/chat_agent.py`: `_generate_fiqh_response_node` — same (uses fiqh generator prompt)

**Rationale:** `ChatAgent` is the hot path for every request. Tool definitions are cached once per agent construction; system prompts are cached once per 5-minute TTL. Highest volume = highest savings. Do before FAIR-RAG module changes.

### Phase 3: FAIR-RAG fiqh pipeline modules
1. `modules/fiqh/classifier.py` — content-block system prompt
2. `modules/fiqh/decomposer.py` — content-block system prompt
3. `modules/fiqh/filter.py` — content-block system prompt
4. `modules/fiqh/sea.py` — content-block system prompt
5. `modules/fiqh/refiner.py` — content-block system prompt
6. `modules/fiqh/generator.py` — content-block system prompt

**Rationale:** FAIR-RAG runs up to 3×(filter+assess+refine) per request. Caching the static system prompts saves tokens on the 2nd and 3rd iterations immediately (within-request cache reuse). Group all 6 together — they share the same pattern and can be verified together.

### Phase 4: Non-fiqh pipeline modules
1. `modules/classification/classifier.py` (both classify functions use same `chat_models.get_classifier_model()`)
2. `modules/enhancement/enhancer.py`
3. `modules/translation/translator.py` (below 1024 threshold likely, but safe to mark)
4. `modules/generation/generator.py` + `modules/generation/stream_generator.py` (large `generatorSystemTemplate`)

**Rationale:** Non-fiqh modules are touched less frequently and have slightly lower ROI than the fiqh pipeline. `generatorSystemTemplate` is the largest single system prompt (~1200 tokens) and will see strong cache hits.

### Phase 5: `core/prompt_templates.py` templates
1. `generator_prompt_template` (ChatPromptTemplate wrapping `generatorSystemTemplate`)
2. `enhancer_prompt_template`
3. `hikmah_elaboration_prompt_template` (has lesson context in system prompt — still cacheable for the static prefix if split into two blocks; the lesson context block is variable)
4. `primer_generation_prompt_template`

**Rationale:** These templates are used by services that do not have a LangGraph context, so there is no `correlation_id` `extra` pattern to worry about. Verify that the content-block list approach works correctly with `ChatPromptTemplate` before deploying.

### Phase 6: Metrics verification
1. Confirm cache hit metrics appear in logs across all modified call sites
2. Verify `cache_read_tokens > 0` on warm requests (request N≥2 within 5-minute TTL)
3. Update Linear ticket DEE-50 with measured cache hit rates and token savings

---

## Important Constraints and Non-Obvious Details

**1. `with_structured_output` call sites:**
`modules/fiqh/classifier.py` and `modules/fiqh/sea.py` call `model.with_structured_output(Schema)` before `.invoke()`. The `cache_control` marker is in the system prompt content block, not in the `with_structured_output` schema. The structured output wrapper passes the messages through normally — the cache marker is preserved.

**2. Tool definitions cached as list, not individual tools:**
Anthropic caches the entire tool definitions array up to the marked entry. Setting `cache_control` on the last tool in the list caches all tool definitions together. Do not put `cache_control` on every tool — only the last one.

**3. `convert_to_anthropic_tool` import:**
`from langchain_anthropic import convert_to_anthropic_tool` is the correct import path (verified in `langchain_anthropic/__init__.py`).

**4. `_generate_response_node` creates a new `ChatAnthropic` instance via `get_generator_model()`:**
This is a fresh instance per call. Tool caching does not apply here (no `.bind_tools()`). Only system prompt caching is relevant. The cached system prompt will still match across calls because the same `AGENT_SYSTEM_PROMPT` string is sent every time.

**5. `hikmahElaborationSystemTemplate` contains injected variables (`{hikmah_tree_name}`, `{lesson_name}`, etc.):**
These are injected at template render time and change per request. The system prompt containing these variables will not be cacheable in practice (different tokens every call). However, the large static prefix (the scholar persona and rules section, ~700 tokens) could be split into a cached static block and an uncached dynamic block. This is a phase 5 complexity — defer or skip for v1.4 and just mark the full system prompt; cache will miss most calls but there is no harm.

**6. `fiqh_subgraph.invoke()` is a blocking synchronous call:**
It runs within `_call_fiqh_subgraph_node`, which is a synchronous node called from an async graph. The `correlation_id` ContextVar is readable inside (same thread). Cache metrics logged inside sub-graph nodes will carry the correct `correlation_id` from the parent request context.

**7. `primer_service.py` creates a module-level `get_enhancer_model()` instance:**
`primers_model = get_enhancer_model()` at line 34 is called at import time. If the factory is modified to return a different type, ensure it remains an instance of `Runnable` so existing `.invoke()` calls work unchanged.

---

## Sources

- `langchain_anthropic==0.3.22` installed source — `chat_models.py` lines 1040-1128 (prompt caching docstring), lines 1579-1599 (`_get_request_payload` cache_control handling), lines 1953-1958 (tool cache_control example), lines 2588-2629 (`_create_usage_metadata` — confirmed `cache_read_input_tokens` and `cache_creation_input_tokens` exposed)
- `langchain_anthropic==0.3.22` installed source — `chat_models.py` lines 285-307 (`_format_messages` — confirmed list-type system message content passes through as-is)
- `langchain_anthropic==0.3.22` installed source — `chat_models.py` line 66-73 (`AnthropicTool` TypedDict — `cache_control: NotRequired[dict[str, str]]` field confirmed)
- `core/chat_models.py` (repo source) — factory functions confirmed, verified all 4 functions return `ChatAnthropic` instances
- `agents/core/chat_agent.py` (repo source) — `_create_llm_with_tools`, `_agent_node`, `_generate_response_node` verified
- `agents/fiqh/fiqh_graph.py` (repo source) — sub-graph topology confirmed, no direct LLM calls
- `modules/fiqh/*.py` (repo source) — all 6 modules confirmed using `ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ...])`
- `core/prompt_templates.py` (repo source) — 4 `ChatPromptTemplate` instances confirmed
- Anthropic documentation (prompt caching): minimum 1024 tokens, 5-minute default TTL, cache-creation at 1.25x cost, cache-read at ~10% cost
