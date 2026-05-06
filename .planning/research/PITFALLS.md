# Pitfalls Research: v1.4 LLM Input Caching

**Project:** Deen Backend — v1.4 LLM Input Caching
**Researched:** 2026-05-03
**Scope:** Adding Anthropic prompt caching (`cache_control`) to an existing LangGraph + ChatAnthropic + SSE streaming system. Covers silent failures, dynamic-content invalidation, tool use, structured output, streaming, LangGraph-specific hazards, and metrics collection.
**Confidence:** HIGH (official Anthropic docs + LangChain GitHub issues + code inspection)

---

## Summary

Anthropic prompt caching works by exact byte-for-byte prefix matching against a per-workspace cache. The cache is a content-addressed prefix store: if a single byte of the cached region changes between calls, there is a complete miss and the full prefix is billed at the 1.25× write rate. Silent success (the API always returns 200) is the most dangerous failure mode — the only signal that caching is broken is inspecting `usage.cache_creation_input_tokens` and `usage.cache_read_input_tokens` in the response.

This codebase has five distinct LLM call sites (ChatAgent/bind_tools, decomposer, filter, SEA assessor, fiqh generator + streaming), each with different stability profiles and therefore different risk levels. The FAIR-RAG loop runs up to 3 iterations per fiqh query, which is the highest-value caching target. The main ChatAgent LLM is bound to 6 tools via `.bind_tools()`, and using the AnthropicPromptCachingMiddleware is **not compatible** with `bind_tools()` — they are mutually exclusive. That constraint shapes every decision in v1.4.

---

## Critical Pitfalls

Mistakes that silently produce zero cache hits or introduce billing errors / API errors.

---

### CRITICAL-1: Silent failure when cached content is below the minimum token threshold

**What goes wrong:**
Anthropic's API accepts `cache_control` markers on any content block regardless of length, but silently ignores them if the total cached prefix does not meet the model's minimum. No error is returned. Both `cache_creation_input_tokens` and `cache_read_input_tokens` will be 0 in the response, but the call succeeds and bills at the normal rate.

**Minimum token thresholds for this project's models (confirmed from official docs):**
- `claude-sonnet-4-6` (`LARGE_LLM`): **2048 tokens** minimum
- `claude-haiku-4-5-20251001` (`SMALL_LLM`): **4096 tokens** minimum

**Impact on this codebase:**
- `AGENT_SYSTEM_PROMPT` in `agents/prompts/agent_prompts.py` is ~700–800 words ≈ ~900–1100 tokens. Below the 2048-token threshold for Sonnet. System prompt alone cannot be cached without adding tool definitions to the prefix.
- Tool definitions for 6 tools bound to `ChatAgent` add approximately 800–1200 tokens. System + tools together: ~1700–2300 tokens. This is near the Sonnet threshold — must measure precisely before assuming cache eligibility.
- `SYSTEM_PROMPT` in `modules/fiqh/decomposer.py` is ~200 tokens. Far below 4096 for Haiku. Decomposer caching is **not viable** without a much longer system prompt.
- `SYSTEM_PROMPT` in `modules/fiqh/filter.py` is ~100 tokens. Not viable for caching.
- `SYSTEM_PROMPT` in `modules/fiqh/sea.py` is ~200 tokens. Not viable for caching on its own.
- `SYSTEM_PROMPT` in `modules/fiqh/generator.py` is ~150 tokens. Not viable for caching on its own.

**Prevention:**
- Before adding `cache_control` to any call site, estimate token count using `tiktoken` (or the Anthropic token counter). Only apply caching to call sites where static content meets the threshold.
- After applying `cache_control`, verify the first response has `cache_creation_input_tokens > 0` and the second identical call has `cache_read_input_tokens > 0`. If both are 0, the content is below threshold.
- The most reliable target is the `ChatAgent` system prompt + tool definitions together. Add tool definitions to the cached prefix and verify the combined count clears 2048 tokens for Sonnet.
- For Haiku call sites (decomposer, filter, SEA, refiner — all at `chat_models.get_classifier_model()`), caching the system prompt alone is almost certainly below 4096 tokens. These call sites likely cannot be cached unless retrieved evidence is also included in the cached prefix (which is usually dynamic — see CRITICAL-2).

**Confidence:** HIGH — confirmed from official Anthropic prompt caching documentation.

---

### CRITICAL-2: Caching dynamic content (retrieved evidence) causes 0% hit rate

**What goes wrong:**
Anthropic's cache is a prefix store: the exact bytes of the cached content must be identical across calls. Retrieved fiqh documents change every request (different queries return different chunks from Pinecone). If `cache_control` is applied to a content block that contains any retrieved documents, the hash never matches across calls.

**At-risk patterns in this codebase:**
- `modules/fiqh/filter.py`: `_prompt.format_messages(query=query, evidence=_format_evidence_with_ids(docs))` — both `query` and `evidence` are dynamic. No static prefix long enough to cache.
- `modules/fiqh/sea.py`: `_prompt.format_messages(query=query, evidence=_format_evidence(docs))` — same issue.
- `modules/fiqh/generator.py`: `_prompt.format_messages(query=query, evidence=_format_evidence(docs))` — same issue.
- `_generate_response_node` in `chat_agent.py`: The `HumanMessage` content includes `state['user_query']` and the `references` string (retrieved docs). This is entirely dynamic.

**The write-overhead trap:**
Applying `cache_control` to a block that changes every request causes a new cache **write** every call (billed at 1.25× the normal rate) with zero reads. This is strictly more expensive than not caching at all: every call pays the write surcharge with no offset from hits.

**Prevention:**
- Only apply `cache_control` to content blocks that are identical across the requests that should share the same cache entry.
- The evidence/retrieved context blocks in fiqh pipeline calls must NOT be marked with `cache_control`.
- The system prompts for decomposer, filter, SEA, generator are static text and can be tagged — but they must meet the minimum token threshold (see CRITICAL-1). Since these short prompts do not reach 4096 tokens alone, and adding dynamic evidence would break the cache, these Haiku call sites have limited caching opportunity unless prompt length is substantially increased.
- The `AGENT_SYSTEM_PROMPT` with tool definitions is the primary viable target because it is static across all non-fiqh requests.

**Confidence:** HIGH — cache invalidation on any prefix change is a documented fundamental of Anthropic's caching design.

---

### CRITICAL-3: `AnthropicPromptCachingMiddleware` is incompatible with `bind_tools()`

**What goes wrong:**
`langchain_anthropic.middleware.AnthropicPromptCachingMiddleware` is documented to work exclusively with LangChain's `create_agent()` pattern. It is explicitly **incompatible with `bind_tools()`**.

`ChatAgent._create_llm_with_tools()` in `agents/core/chat_agent.py` calls `llm.bind_tools(self.tools)`. Attempting to layer `AnthropicPromptCachingMiddleware` on top of this will either fail silently or conflict with the bound tool definitions.

**Consequence:**
Using the middleware with `bind_tools()` is not supported. The correct approach for the `ChatAgent` is to apply `cache_control` explicitly in the message construction rather than via middleware.

**Specific implementation required for ChatAgent:**
1. The tool definitions are cached by adding `cache_control={"type": "ephemeral"}` to the last tool in the tools list when constructing the `bind_tools()` call (this requires passing tools as dicts with `cache_control` fields, or using the `@tool(extras={"cache_control": ...})` decorator pattern).
2. Alternatively, apply `cache_control` on the `SystemMessage` content block in `_agent_node` when constructing the messages list: `SystemMessage(content=[{"type": "text", "text": AGENT_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}])`.

**Confidence:** HIGH — confirmed from LangChain official middleware documentation, explicit incompatibility note.

---

### CRITICAL-4: `cache_control` inside `ToolMessage` content blocks causes `invalid_cache` API error

**What goes wrong:**
GitHub issue #34920 in `langchain-ai/langchain` documents that placing `cache_control` inside the content blocks of a `ToolMessage` (e.g., `ToolMessage(content=[{"type": "text", "text": "...", "cache_control": {...}}])`) causes Anthropic's API to return:

```
invalid_cache: cache_control is not supported at messages.N.content.0.content.0.cache_control
```

The error occurs because LangChain passes the `cache_control` from the nested content block verbatim, but Anthropic's API requires it at the top-level `tool_result` object, not inside the nested content array.

**At-risk pattern:**
If any implementation attempt tries to cache retrieved documents by adding `cache_control` to tool result content blocks (e.g., to cache tool results from `retrieve_shia_documents_tool`), the API call will fail with a hard error.

**Prevention:**
- Never place `cache_control` inside the content array of `ToolMessage` objects.
- If caching tool results is needed (generally not recommended — tool results are dynamic), use `ToolMessage(content=[...], cache_control={"type": "ephemeral"})` at the message level, not inside content blocks.
- In practice: do not attempt to cache tool result messages at all. The retrieved document content changes per request, so tool result caching provides no value and risks `invalid_cache` errors.

**Confidence:** HIGH — confirmed from GitHub issue #34920 with reproduction and confirmed API error message.

---

### CRITICAL-5: `input_tokens` in LangChain usage metadata double-counts cached tokens (known bug)

**What goes wrong:**
GitHub issue #32818 in `langchain-ai/langchain` documents that with `langchain-anthropic` (including 0.3.x), the `usage_metadata["input_tokens"]` field includes `cache_read_input_tokens` in its count, making it appear much larger than the actual freshly-processed input. The Anthropic API correctly reports them separately (e.g., `input_tokens: 3`, `cache_read_input_tokens: 151995`), but LangChain combines them: reported `input_tokens: 151998`.

Additionally, when using `chain.stream()` or `model.stream()`, cache token counts in `usage_metadata.input_token_details` can be double the actual values because the Anthropic streaming API emits cache token counts in both `message_start` and `message_delta` SSE events as cumulative values, and LangChain sums them.

**Consequence for cache metrics logging:**
The Sentry/structured logging instrumentation in v1.3 uses `extra={}` style logging. If cache metrics are extracted from `response.usage_metadata` in streaming calls, the values will be inaccurate. Logging `cache_read_input_tokens` as a cost metric from streaming responses will report inflated numbers.

**Prevention:**
- For non-streaming calls, read cache metrics directly from `response.response_metadata["usage"]` (the raw Anthropic API response dict), which has the correct values: `cache_creation_input_tokens` and `cache_read_input_tokens` as separate fields.
- For streaming calls using `chain.stream()` (the pattern used in `core/pipeline_langgraph.py` for the generation step), do not use the accumulated chunk's usage metadata for cache hit/miss metrics. Instead, use `model.invoke()` for the specific call sites where you need accurate cache metrics, or explicitly subtract the known double-counted fields.
- Log a boolean `cache_hit: true/false` (based on `cache_read > 0`) and the raw `cache_read_input_tokens` value from the non-streaming path. For the streaming path, acknowledge that the reported numbers may be ~2× actual.
- Issue status: still open as of langchain-anthropic 0.3.22 (installed version). No fix shipped yet.

**Confidence:** HIGH — confirmed from GitHub issue #32818 and the langchain-anthropic 0.3.19 bug report with reproduction steps.

---

## Integration Pitfalls

Mistakes at the intersection of Anthropic caching APIs and this codebase's patterns.

---

### INTEGRATION-1: ChatAnthropic instances created per-call in `core/chat_models.py` lose cache write investment

**What goes wrong:**
Every function in `core/chat_models.py` (`get_generator_model()`, `get_classifier_model()`, etc.) constructs a **new** `ChatAnthropic` instance on every call:

```python
def get_generator_model():
    return ChatAnthropic(model=LARGE_LLM, api_key=ANTHROPIC_API_KEY, max_tokens=4096)
```

The `ChatAnthropic` instance itself does not own the cache — the cache lives on Anthropic's servers and is keyed by the exact content prefix. However, creating a new instance per call means any per-instance configuration (such as `model_kwargs` or invocation-level settings) is re-applied each call. More importantly, the FAIR-RAG loop creates a generator model, a classifier model, and a filter model on each of its up to 3 iterations. The LLM client instance object is discarded after each call. This is fine for caching correctness (cache lives server-side), but it means per-request startup overhead is repeated unnecessarily, and it makes applying `cache_control` at the instance level (e.g., as a default invocation parameter) require modifying all call sites simultaneously.

**Prevention:**
- Move `ChatAnthropic` instantiation from inside per-call functions to module-level singletons. This is cheap — `ChatAnthropic` is a configuration object, not a connection. Module-level singletons make it easy to add `cache_control` defaults at the instance level rather than at every `invoke()` call site.
- For FAIR-RAG call sites specifically, the 3-iteration loop calls `get_generator_model()` in `filter.py`, `sea.py`, and `generator.py` on each iteration. Singleton instances avoid 3 redundant object constructions per fiqh request.

**Confidence:** HIGH — code inspection of `core/chat_models.py`.

---

### INTEGRATION-2: `ChatPromptTemplate.format_messages()` produces plain `str` content blocks, stripping `cache_control`

**What goes wrong:**
`ChatPromptTemplate.format_messages()` returns `BaseMessage` objects with `content` as a plain `str`. When `content` is a `str`, there is no place to attach a `cache_control` dict — it is not a content block list. The LangChain Anthropic integration only passes `cache_control` to the API when `content` is a list of dicts (the structured content blocks format).

This affects every fiqh module prompt:
- `modules/fiqh/decomposer.py`, `filter.py`, `sea.py`, `generator.py` all use `ChatPromptTemplate.from_messages([...]).format_messages(...)`.

GitHub issue #26701 documents this incompatibility: Anthropic prompt caching does not work when the message content is a plain string generated by `format_messages()`.

**Consequence:**
Trying to add `cache_control` to the system prompt of any fiqh module using the existing `ChatPromptTemplate` pattern will silently fail — no error, no cache write, `cache_creation_input_tokens = 0`.

**Prevention:**
- For call sites where `cache_control` should be applied to the system message, do NOT use `ChatPromptTemplate.format_messages()` to construct the messages. Instead, construct the message list manually with structured content blocks:

```python
from langchain_core.messages import SystemMessage, HumanMessage

messages = [
    SystemMessage(content=[
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]),
    HumanMessage(content=f"Query: {query}\n\nEvidence:\n{evidence}"),
]
response = model.invoke(messages)
```

- This pattern requires refactoring the `_prompt = ChatPromptTemplate.from_messages([...])` in fiqh modules. The refactor is small but must be done for caching to function.
- The `AGENT_SYSTEM_PROMPT` in `chat_agent.py` is already constructed as a `SystemMessage(content=AGENT_SYSTEM_PROMPT)` — converting this to the structured content block format is straightforward.

**Confidence:** HIGH — GitHub issue #26701, confirmed behavior in langchain-anthropic.

---

### INTEGRATION-3: Tool definitions in `bind_tools()` are not automatically cached — explicit `cache_control` required per tool

**What goes wrong:**
Calling `llm.bind_tools(self.tools)` in `ChatAgent._create_llm_with_tools()` passes the tool schemas to the API but does NOT attach `cache_control` to any of them. Anthropic's API places tool definitions before the system message in the caching hierarchy (Tools → System → Messages). If tool definitions are not cached, every call reprocesses them, and any `cache_control` on the system message starts from the wrong position in the hierarchy.

For the ChatAgent's 6 tools, the tool definitions collectively represent a significant static payload. Not caching them wastes the largest static cacheable block in the agent path.

**Prevention:**
- Use LangChain's `@tool(extras={"cache_control": {"type": "ephemeral"}})` decorator on the last tool in the list, OR construct tool dicts manually with `cache_control` on the last tool entry.
- Per Anthropic's caching model, only the LAST tool definition needs `cache_control` — this marks the end of the tools prefix as the cache breakpoint, and all preceding tool definitions are included in the cached prefix automatically.
- After `bind_tools()`, verify with a test call that `cache_creation_input_tokens > 0` and that a second identical call produces `cache_read_input_tokens > 0`.

**Confidence:** HIGH — Anthropic prompt caching docs on tool definitions, LangChain tool extras documentation.

---

### INTEGRATION-4: 5-minute TTL makes FAIR-RAG loop iteration caching irrelevant for cross-request savings but critical within-request

**What goes wrong:**
The FAIR-RAG loop (`fiqh_graph.py`) runs up to 3 iterations within a single request: decompose → retrieve → filter → assess → [refine → retrieve → filter → assess] × 2. Each LLM call in the loop uses a fresh system prompt + evidence. The 5-minute TTL (default) means:

- **Within a single fiqh request**: The 3 iterations happen within seconds of each other. The system prompt is the same string in all 3 iterations. If the system prompt is cached on the first iteration, iterations 2 and 3 can read from cache. This **works** for within-request iteration savings.
- **Across user requests**: If two different users send fiqh queries more than 5 minutes apart, the system prompt cache has expired. The first user's request writes the cache; the second user (>5 min later) misses and writes again. For low-traffic periods, cache hit rate will be low.
- **The expensive Haiku problem**: `get_classifier_model()` (LARGE_LLM=Sonnet) is used for decomposer and SEA, and `get_generator_model()` (LARGE_LLM=Sonnet) for filter and generation. The SMALL_LLM (Haiku) is only used for query enhancement. The 4096-token minimum for Haiku means the short Haiku call sites (enhancer) cannot be cached without a substantially longer system prompt.

**Prevention:**
- Use `"ttl": "1h"` for system prompts at call sites where the same system prompt is re-invoked regularly but potentially more than 5 minutes apart. The `AGENT_SYSTEM_PROMPT` (used on every non-fiqh chat request) is the best candidate for 1-hour TTL.
- Use default 5-minute TTL for fiqh call sites where the same prompt appears in iterations 2 and 3 of the same FAIR-RAG loop — within-request savings are guaranteed regardless of TTL.
- Do not expect cross-request savings from fiqh call sites with short, low-token system prompts unless the prompt is extended to clear the minimum token threshold.

**Confidence:** HIGH — TTL behavior confirmed from official Anthropic docs. Within-request iteration savings confirmed as valid.

---

### INTEGRATION-5: `with_structured_output()` creates a new LLM chain that strips custom invocation parameters

**What goes wrong:**
`modules/fiqh/sea.py` calls `model.with_structured_output(SEAResult)`. This wraps the `ChatAnthropic` instance in a new chain (specifically, it calls `.bind()` internally and adds output parsing). When you subsequently call `structured_model.invoke(messages)`, any `cache_control` parameter passed at invocation time may not propagate through the chain wrapper correctly.

More critically, if `cache_control` is applied at the `ChatAnthropic` instance level (e.g., as a constructor parameter or via `model.bind(cache_control=...)`), calling `.with_structured_output()` on top creates a new binding chain that may override or lose the `cache_control` configuration.

**Prevention:**
- Apply `cache_control` to the message content blocks directly (structured content block format), not via invocation-level parameters, when using `with_structured_output()`. The message-level `cache_control` is part of the message structure and is passed through all chain wrappers transparently.
- Test the SEA call site by checking `response.response_metadata` for cache tokens after adding `cache_control` to the SystemMessage content block. Verify `cache_creation_input_tokens > 0` on first call.
- Note: `with_structured_output()` uses tool use internally (Anthropic's structured output maps to a `tool_use` call). Tool use is compatible with prompt caching per official Anthropic docs — caching works correctly when tool_use is the response format.

**Confidence:** MEDIUM — LangChain's chain composition behavior with `cache_control` propagation is not fully documented. The message-level approach is the safe fallback.

---

## LangGraph-Specific Pitfalls

Mistakes caused by the interaction between LangGraph's graph execution model and Anthropic's caching semantics.

---

### LANGGRAPH-1: LangGraph `MemorySaver` message history grows the messages prefix on every turn, breaking static cache breakpoints

**What goes wrong:**
`ChatAgent` compiles the graph with `checkpointer=MemorySaver()` and passes `thread_id=session_id`. On each turn, LangGraph's `add_messages` reducer appends new `HumanMessage`, `AIMessage`, and `ToolMessage` objects to the messages list in `ChatState`. The `_agent_node` then constructs a fresh `messages` list including all prior messages.

If `cache_control` is placed on the `SystemMessage` (the first message in the list), the cache breakpoint position is always at block 0 (the system message). As the conversation grows, the total number of content blocks before the breakpoint stays at 0, but the blocks after it grow. This is fine — the system prompt cache entry is correctly reused.

However, if `cache_control` is also applied to the last `HumanMessage` (to cache the growing conversation history), the breakpoint moves each turn. The 20-block lookback window means that after ~20 messages, the previously cached block at the earlier position is no longer within lookup range, causing cold misses and repeated cache writes.

**At-risk pattern in this codebase:**
The `_build_initial_user_message` and `_build_iteration_summary` methods construct `HumanMessage` objects with per-request content (`user_query`, `working_query`, `runtime_session_id`). These are inherently dynamic and must never be the target of a `cache_control` breakpoint.

**Prevention:**
- Place `cache_control` ONLY on the `SystemMessage` (static system prompt). Do not place it on `HumanMessage` objects that contain user queries or session-specific content.
- For multi-turn conversation history caching (where you want to cache prior turns), use automatic caching (`cache_control={"type": "ephemeral"}` passed as an invocation parameter) rather than explicit block-level breakpoints. Automatic caching moves the breakpoint forward automatically as the conversation grows, which handles the lookback window correctly.
- The fiqh sub-graph (`fiqh_graph.py`) runs with `checkpointer=False` — no persistent message accumulation across calls. Cache breakpoints in fiqh modules are simpler: only the system prompt of each module is a candidate.

**Confidence:** HIGH — Anthropic docs on 20-block lookback window. LangGraph MemorySaver message accumulation behavior confirmed from code inspection.

---

### LANGGRAPH-2: `_agent_node` message list reconstruction on every iteration re-inserts `SystemMessage` — must ensure structural identity

**What goes wrong:**
In `_agent_node`, on `iteration == 1`, a new `SystemMessage(content=AGENT_SYSTEM_PROMPT)` is inserted at position 0 of the message list. On subsequent iterations (`iteration > 1`), the code appends a new `HumanMessage` with an iteration summary, but does NOT re-insert the SystemMessage — the existing one from the LangGraph state carries forward.

This means the exact byte sequence of the SystemMessage content must be structurally identical every time it appears in the messages list sent to the API. If the SystemMessage is constructed differently on different code paths (e.g., one path passes `content=str`, another passes `content=[{"type": "text", "text": str, "cache_control": {...}}]`), the API will see different byte sequences and cache will miss.

**Subtle identity risk:**
The `_generate_response_node` and `_generate_fiqh_response_node` methods ALSO construct a `SystemMessage(content=AGENT_SYSTEM_PROMPT)` independently. If the agent path uses a structured content block format with `cache_control` but `_generate_response_node` still uses the plain string format, those two paths have structurally different SystemMessages pointing to the same `AGENT_SYSTEM_PROMPT` string — the cache will create two separate cache entries and hit rate appears split.

**Prevention:**
- Define a single helper function (e.g., `make_cached_system_message() -> SystemMessage`) that returns the SystemMessage in the correct structured content block format with `cache_control`. All code paths that construct a SystemMessage with `AGENT_SYSTEM_PROMPT` must use this single helper.
- Never construct the SystemMessage inline with different formats in different node methods.

**Confidence:** HIGH — derived from code inspection of `_agent_node`, `_generate_response_node`, and `_check_early_exit_node`.

---

### LANGGRAPH-3: Fiqh sub-graph `checkpointer=False` means no cross-iteration state sharing at the graph level, but does not prevent within-request LLM cache hits

**What goes wrong (misconception):**
The comment in `fiqh_graph.py` says `checkpointer=False: stateless per-invocation; no cross-session leakage`. Some implementers may incorrectly believe that `checkpointer=False` also prevents prompt caching from working within the sub-graph's 3-iteration loop. This is a misconception.

Anthropic prompt caching is entirely server-side — it has nothing to do with LangGraph's checkpointer. The checkpointer controls whether LangGraph saves `FiqhState` between separate `invoke()` calls (it does not). Prompt caching is keyed by the exact byte prefix of the messages sent to the Anthropic API in a single `invoke()` call, and the 5-minute TTL means cache entries persist on Anthropic's servers.

**The actual issue:**
The fiqh sub-graph invokes `_decompose_node` (Sonnet/Haiku) once, then loops: retrieve → filter → assess → refine → retrieve... for up to 3 iterations. Each `filter`, `assess`, and `generate` call re-creates a `ChatAnthropic` instance (from `get_generator_model()` / `get_classifier_model()`) and sends the system prompt as a fresh string. If the system prompt is structurally identical across iterations within the loop, the cache hit on iteration 2 and 3 is served from Anthropic's server-side cache (written on iteration 1). The `checkpointer=False` setting is irrelevant.

**Prevention:**
- Apply `cache_control` to system prompt content blocks in fiqh modules where the system prompt meets the minimum token threshold. Iterations 2 and 3 will get cache hits from Anthropic's server-side cache regardless of LangGraph state.
- Do not be misled by `checkpointer=False` into thinking caching is impossible in the fiqh sub-graph.

**Confidence:** HIGH — Anthropic cache is server-side, independent of LangGraph state. Confirmed from architecture analysis.

---

### LANGGRAPH-4: Non-deterministic tool definition ordering in `bind_tools()` can silently change the cache key

**What goes wrong:**
`ChatAgent.__init__` constructs `self.tools = [check_if_non_islamic_tool, translate_to_english_tool, ...]` as a fixed list. This is safe. However, if any future change makes the tool list dynamic (e.g., loading tools from config, filtering enabled tools based on `AgentConfig.enable_classification`), the tool list order could change between requests, changing the byte sequence of the tools prefix and causing cache misses.

Similarly, the `AgentConfig` has `enable_classification`, `enable_translation`, `enable_enhancement` flags. If these flags are used to conditionally include/exclude tools in `self.tools`, a request with `enable_classification=False` would produce a different tool prefix than one with `enable_classification=True`, splitting the cache into two separate entries.

**Prevention:**
- Keep the tool list order in `ChatAgent.__init__` as a static, deterministic constant. Never sort or filter it dynamically.
- If `enable_*` flags are implemented by changing which tools are bound, accept that each unique combination of flags creates a separate cache entry. Document this explicitly.
- Apply `cache_control` to the last tool in the list. Any change to the list after the last tool (additions of new tools at the end) will invalidate this breakpoint. Changes before the last tool also invalidate it. Treat the tool list as append-only from a caching perspective.

**Confidence:** HIGH — derived from code inspection of `AgentConfig` and tool list construction.

---

## Streaming + Caching Pitfalls

---

### STREAMING-1: Cache metrics are not reliably available from `chain.stream()` in the SSE pipeline

**What goes wrong:**
`core/pipeline_langgraph.py` uses `chain.stream()` (synchronous LangChain stream, blocking the event loop inline) for the final generation step. In Anthropic's streaming API, cache metadata (`cache_creation_input_tokens`, `cache_read_input_tokens`) is emitted in the `message_start` SSE event, not in the per-chunk `content_block_delta` events. LangChain's streaming accumulation can lose or mis-report these values.

The known double-counting bug (GitHub issue #10249 in langchain-js, similar in Python) means that the accumulated `usage_metadata` from a streaming call may report cache token counts at 2× their actual values.

**Consequence:**
If cache hit/miss logging is implemented by reading cache tokens from the streaming response's final accumulated metadata, the logged values will be inaccurate. This makes the "Emit cache hit/miss counts in structured logs" requirement in v1.4 unreliable when measured through streaming paths.

**Prevention:**
- For the generation step in `core/pipeline_langgraph.py` (which uses `chain.stream()`): use `response.response_metadata.get("usage", {})` from the last stream chunk rather than `usage_metadata` from the accumulated LangChain message object, as the raw metadata is passed through more faithfully.
- Alternatively, instrument cache metrics at the `invoke()` call sites (decomposer, filter, SEA, fiqh generator non-streaming path) rather than the streaming path. These non-streaming calls return accurate usage metadata.
- Log a simple `cache_hit: bool` (any `cache_read_input_tokens > 0`) rather than exact token counts from streaming paths.

**Confidence:** HIGH — streaming cache metadata inaccuracy confirmed from GitHub issue #32818 and #10249.

---

### STREAMING-2: Caching does not change the SSE event protocol or latency profile for the first streaming token

**What goes wrong (misconception):**
A common assumption is that prompt caching will reduce time-to-first-token (TTFT) for the SSE streaming path at `/chat/stream/agentic`. This is true for subsequent calls after the cache is warm. However, the first call (cache write) is 1.25× more expensive in tokens billed AND has higher latency because the API must process and store the prefix.

Latency improvement from caching applies to TTFT (the time before the first streaming token arrives), not to streaming throughput (tokens per second after generation starts). The existing SSE frontend protocol and the `response_chunk` events are unaffected.

**Prevention:**
- Do not advertise caching as reducing TTFT for the first call on a cold cache. The first call per 5-minute window will have similar or slightly higher latency than without caching.
- Measure TTFT before and after adding `cache_control` with a warm cache (second+ call within TTL) to verify the actual latency improvement for this system prompt length.

**Confidence:** HIGH — caching mechanics well-documented in Anthropic docs.

---

## Prevention Checklist

Use this checklist before shipping each call site modification in v1.4.

**Before applying `cache_control` to a call site:**
- [ ] Estimated token count of static content meets model minimum: Sonnet ≥ 2048, Haiku ≥ 4096
- [ ] Content being marked with `cache_control` is 100% static across all requests that should share the cache
- [ ] Using structured content blocks (`content=[{"type": "text", "text": ..., "cache_control": {...}}]`), NOT `ChatPromptTemplate.format_messages()`
- [ ] `cache_control` is NOT placed inside `ToolMessage.content[]` array elements
- [ ] Tool definitions use `cache_control` on the LAST tool only (marks end of tools prefix)
- [ ] Single helper function creates the `SystemMessage` with `cache_control` — no inline duplication
- [ ] Tool list order is static and deterministic

**After applying `cache_control`:**
- [ ] First call: `response.response_metadata["usage"]["cache_creation_input_tokens"] > 0` (cache write occurred)
- [ ] Second identical call within TTL: `response.response_metadata["usage"]["cache_read_input_tokens"] > 0` (cache hit)
- [ ] Neither value is 0 on both calls (both 0 = below minimum token threshold or dynamic content in prefix)
- [ ] Structured log emits `cache_hit: bool` and `cache_creation_tokens: int` using `extra={}` style
- [ ] Cache metric logging uses `response.response_metadata["usage"]` (raw), not `usage_metadata` (LangChain computed, potentially double-counted in streaming)

**For the `ChatAgent` bind_tools path specifically:**
- [ ] NOT using `AnthropicPromptCachingMiddleware` (incompatible with `bind_tools`)
- [ ] Tool `cache_control` applied via `@tool(extras={...})` on the last tool or via manual tool dict construction
- [ ] System prompt structured content block format used consistently across `_agent_node`, `_generate_response_node`, `_check_early_exit_node`, and `_generate_fiqh_response_node`

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Audit call sites for caching eligibility | Missing token count verification → silent 0-hit caching | Count tokens explicitly for each call site; Sonnet≥2048, Haiku≥4096 |
| Applying `cache_control` to ChatAgent system prompt | `ChatPromptTemplate`-style string content blocks strip `cache_control` silently | Use structured content block list format: `content=[{..., "cache_control": {...}}]` |
| Caching tool definitions with `bind_tools` | `AnthropicPromptCachingMiddleware` incompatibility; `cache_control` on wrong tool | Apply to last tool only; use `@tool(extras={...})` or manual dict construction |
| Fiqh module system prompts (decomposer, filter, SEA, generator) | System prompts are ~100–200 tokens; below 4096-token Haiku minimum | Do not apply `cache_control` to these call sites unless system prompts are substantially extended |
| `with_structured_output(SEAResult)` in sea.py | Chain wrapper may strip invocation-level `cache_control` | Apply `cache_control` in message content blocks, not via invocation parameter |
| Streaming generation step in `pipeline_langgraph.py` | Double-counted cache token metrics in `usage_metadata` | Read raw cache metrics from `response_metadata["usage"]` not `usage_metadata` |
| Cache metric logging via Sentry `extra={}` | Inflated `input_tokens` includes cached tokens — misleading cost metrics | Log `cache_read_input_tokens` and `cache_creation_input_tokens` directly; compute `total_input_tokens = cache_read + cache_creation + input_tokens` |
| ToolMessage results from retrieval tools | `cache_control` in `ToolMessage.content[]` blocks triggers `invalid_cache` API error | Never cache tool result content blocks; retrieved docs are dynamic anyway |
| Multi-turn ChatAgent with MemorySaver | Cache breakpoint on dynamic HumanMessage invalidates every turn | Only cache SystemMessage; use automatic caching for conversation history growth |
| Cold cache on first request per TTL window | Write cost 1.25× normal; higher latency for TTFT | Expected behavior; measure and communicate latency profile clearly |

---

## Sources

- [Anthropic Prompt Caching — Official Docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — minimum tokens by model, cache invalidation hierarchy, TTL, tools/system/messages ordering, streaming behavior
- [LangChain ChatAnthropic Integration](https://docs.langchain.com/oss/python/integrations/chat/anthropic) — automatic caching, explicit cache breakpoints, usage metadata access pattern
- [AnthropicPromptCachingMiddleware](https://docs.langchain.com/oss/python/integrations/middleware/anthropic) — middleware incompatibility with `bind_tools()` confirmed
- [GitHub #26701 — Prompt caching does not work with ChatPromptTemplate](https://github.com/langchain-ai/langchain/issues/26701) — `format_messages()` produces string content, not structured blocks
- [GitHub #34920 — `cache_control` inside ToolMessage.content[] causes `invalid_cache` error](https://github.com/langchain-ai/langchain/issues/34920) — ToolMessage placement restriction
- [GitHub #32818 — Usage metadata inaccurate for prompt cache reads/writes](https://github.com/langchain-ai/langchain/issues/32818) — double-counting in langchain-anthropic 0.3.x streaming
- [GitHub #10249 (langchainjs) — cache tokens double-counted in streaming](https://github.com/langchain-ai/langchainjs/issues/10249) — cumulative SSE event double-counting mechanism
- [GitHub #33709 — AnthropicPromptCachingMiddleware breaks model fallback](https://github.com/langchain-ai/langchain/issues/33709) — middleware fragility
- [ProjectDiscovery Blog — How We Cut LLM Costs by 59% With Prompt Caching](https://projectdiscovery.io/blog/how-we-cut-llm-cost-with-prompt-caching) — dynamic content invalidation "7% → 74%" case study
- [DEV Community — Anthropic Silently Dropped Prompt Cache TTL from 1 Hour to 5 Minutes](https://dev.to/whoffagents/anthropic-silently-dropped-prompt-cache-ttl-from-1-hour-to-5-minutes-16ao) — TTL change impact
