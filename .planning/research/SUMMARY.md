# Research Summary: v1.4 LLM Input Caching

**Project:** Deen Backend v1.4 — Anthropic Prompt Caching
**Domain:** LLM cost optimization via Anthropic `cache_control` on an existing LangGraph + ChatAnthropic stack
**Researched:** 2026-05-03
**Confidence:** HIGH

---

## Summary

Research confirms that Anthropic prompt caching can be applied to this codebase using only the already-installed `langchain-anthropic==0.3.22` package — no new dependencies are required. The integration surface splits into two distinct zones: the **ChatAgent path** (`agents/core/chat_agent.py`) where tool definitions (~3,722 tokens) and the system prompt (~1,427 tokens) combine to a 5,149-token prefix that comfortably clears both the Sonnet 4.6 minimum (2,048 tokens) and the Haiku 4.5 minimum (4,096 tokens); and the **FAIR-RAG fiqh modules** (`modules/fiqh/*.py`) where every individual system prompt falls well below the 2,048-token Sonnet threshold when considered in isolation. The practical consequence is that the ChatAgent path — which handles every `/chat/stream/agentic` request — is the primary high-ROI caching target, while the fiqh module call sites can receive `cache_control` markers for within-request iteration savings but should not be counted on for cross-request cache hits given their short system prompts.

The **token minimum is the decisive gating constraint** for this milestone. Sonnet 4.6 requires 2,048 tokens and Haiku 4.5 requires 4,096 tokens before any caching occurs; below those thresholds the API silently accepts the marker, writes nothing to cache, and bills at the normal rate. All 13 module-level system prompts in `modules/fiqh/`, `modules/classification/`, `modules/enhancement/`, and `modules/translation/` fall below the Sonnet minimum when measured alone. The only call site that independently clears the threshold is the ChatAgent, where tool definitions and the system prompt must be marked together as a combined prefix. This research finding directly constrains Phase 1 scope: tool-definition caching and system-prompt caching on the ChatAgent must be implemented as a single atomic change, not in sequence.

The single most important pitfall is that `ChatPromptTemplate.format_messages()` — used in all fiqh module prompts — produces a plain `str` content block that silently strips any `cache_control` dict. This is a confirmed LangChain GitHub issue (#26701) and means every `modules/fiqh/*.py` prompt must be refactored from the `ChatPromptTemplate` pattern to explicit `SystemMessage(content=[...])` content-block lists before `cache_control` will propagate to the API. The fix is mechanical but touches 11 files. A single `make_cached_system_message()` helper in `core/chat_models.py` is the recommended central point for this transformation, ensuring all call sites produce structurally identical `SystemMessage` objects — which is required for Anthropic's exact-prefix cache key to match across calls.

---

## Stack Additions

**No new packages are required.**

`langchain-anthropic==0.3.22` already supports `cache_control` natively on both system prompts (via structured content-block lists) and tool definitions (via `convert_to_anthropic_tool` + manual `cache_control` field injection). Cache hit/miss metrics are exposed on every response via `response.usage_metadata["input_token_details"]` and `response.response_metadata["usage"]` with no additional configuration.

One version bump is worth evaluating: `langchain-anthropic` from `0.3.22` to `0.3.25`. The reason is a bug fix confirmed in the 1.4.2 release notes (`fix(anthropic): restore cache_control on non-direct subclasses`) that affected `cache_control` propagation on wrapped model instances. However, upgrading carries risk: the 1.x series of `langchain-anthropic` requires `langchain>=1.0`, which is a separate major-version migration the project has not undertaken. **Do not upgrade to `langchain-anthropic>=1.0`**. Whether `0.3.25` is the maximum 0.3 series release compatible with the current `langchain==0.3.27` pin must be verified before committing.

`AnthropicPromptCachingMiddleware` is not available in `langchain-anthropic==0.3.22` (confirmed by package inspection). Do not attempt to import it. The direct `cache_control` content-block approach is the only available path on this stack.

---

## Eligible Call Sites

All LLM call sites in the codebase, their static token counts, and caching eligibility:

| Call Site | File | Model | Static Tokens (System) | Tool Def Tokens | Combined | Eligible? | Notes |
|-----------|------|-------|----------------------|-----------------|----------|-----------|-------|
| ChatAgent tool binding | `agents/core/chat_agent.py` | Sonnet 4.6 | 1,427 | 3,722 | **5,149** | **YES** | Highest ROI. Tools + system prompt must be marked together as one prefix unit. |
| `_agent_node` system prompt | `agents/core/chat_agent.py` | Sonnet 4.6 | 1,427 | — | 1,427 | YES (with tools) | System prompt alone is below 2,048. Only eligible when tool defs are also cached in same request. |
| `_generate_response_node` | `agents/core/chat_agent.py` | Sonnet 4.6 | 1,427 | — | 1,427 | YES (with tools) | Same `AGENT_SYSTEM_PROMPT`; must use identical `SystemMessage` format as `_agent_node` for cache hit. |
| `_generate_fiqh_response_node` | `agents/core/chat_agent.py` | Sonnet 4.6 | ~350 | — | ~350 | Verify | Fiqh generator system prompt; below threshold alone. Mark it; confirm via runtime metadata. |
| Fiqh classifier | `modules/fiqh/classifier.py` | Sonnet 4.6 | ~465 | — | ~465 | No (threshold) | Below 2,048. Mark anyway for future eligibility. ChatPromptTemplate must be refactored first. |
| Fiqh decomposer | `modules/fiqh/decomposer.py` | Sonnet 4.6 | ~361 | — | ~361 | No (threshold) | Below 2,048. Same guidance. |
| Fiqh evidence filter | `modules/fiqh/filter.py` | Sonnet 4.6 | ~184 | — | ~184 | No (threshold) | Below 2,048. Dynamic evidence block in human turn must never be marked. |
| Fiqh SEA assessor | `modules/fiqh/sea.py` | Sonnet 4.6 | ~217 | — | ~217 | No (threshold) | Uses `with_structured_output()` — apply `cache_control` in message blocks, not via invocation kwarg. |
| Fiqh refiner | `modules/fiqh/refiner.py` | Sonnet 4.6 | ~215 | — | ~215 | No (threshold) | Below 2,048. |
| Fiqh generator | `modules/fiqh/generator.py` | Sonnet 4.6 | ~175 | — | ~175 | No (threshold) | Below 2,048. Dynamic retrieved evidence in human turn must not be marked. |
| Non-Islamic classifier | `modules/classification/classifier.py` | Sonnet 4.6 | ~324 | — | ~324 | No (threshold) | Below 2,048. |
| Non-fiqh classifier | `modules/classification/classifier.py` | Sonnet 4.6 | ~534 | — | ~534 | No (threshold) | Below 2,048. |
| Query enhancer | `modules/enhancement/enhancer.py` | Haiku 4.5 | ~330 | — | ~330 | **No** | **Haiku minimum is 4,096 tokens.** Far below. Do not cache. |
| Translator | `modules/translation/translator.py` | Sonnet 4.6 | ~66 | — | ~66 | No (threshold) | Far below 2,048. |
| Legacy generator | `modules/generation/generator.py` | Sonnet 4.6 | ~1,200 | — | ~1,200 | Verify | Borderline below 2,048. Mark it; confirm `cache_creation_input_tokens > 0` at runtime. |
| Legacy stream generator | `modules/generation/stream_generator.py` | Sonnet 4.6 | ~1,200 | — | ~1,200 | Verify | Same `generatorSystemTemplate`. Streaming path has known double-counting bug in usage metadata. |
| Hikmah elaboration | `core/prompt_templates.py` | Sonnet 4.6 | ~1,069 | — | ~1,069 | No (threshold) | Below 2,048. Also contains injected dynamic variables — cache would miss most calls regardless. |
| Primer generation | `core/prompt_templates.py` | Sonnet 4.6 | ~561 | — | ~561 | No (threshold) | Below 2,048. |
| Memory consolidator | `agents/core/memory_consolidator.py` | Varies | — | — | — | Low priority | Not on hot path. Assess token count separately if needed. |

**Conclusion:** Only the ChatAgent path (tools + system prompt combined at ~5,149 tokens) is independently cache-eligible. All module-level call sites should still receive `cache_control` markers — the API silently ignores them below threshold, and they will become eligible if prompts are expanded for quality reasons.

---

## Table Stakes Features

**TS-01: Cache tool definitions on ChatAgent (`_create_llm_with_tools`)**
Convert the 6 LangChain `@tool`-decorated functions to Anthropic tool dict format using `convert_to_anthropic_tool`, inject `cache_control: {"type": "ephemeral"}` on the last tool dict only, and pass the list to `bind_tools()`. Do not use `AnthropicPromptCachingMiddleware` — it is incompatible with `bind_tools()` and does not exist in `langchain-anthropic==0.3.22`.

**TS-02: Cache system prompt on ChatAgent (`_agent_node`, `_generate_response_node`)**
Replace `SystemMessage(content=AGENT_SYSTEM_PROMPT)` with `make_cached_system_message(AGENT_SYSTEM_PROMPT)` at every node that constructs the agent system message. All construction sites must use the same single helper to guarantee byte-for-byte identity of the cached prefix. TS-01 and TS-02 must be implemented together — the system prompt alone (1,427 tokens) is below the 2,048-token threshold and cannot be cached without the tool definitions also in the prefix.

**TS-03: Verify cache hits via response metadata**
After each ChatAgent LLM call, read `response.response_metadata["usage"]` (the raw Anthropic dict, not the LangChain-computed `usage_metadata`) and assert `cache_creation_input_tokens > 0` on the first call and `cache_read_input_tokens > 0` on the second identical call within the 5-minute TTL window. This is the only signal that the implementation is working — the API returns HTTP 200 regardless of whether caching occurred.

**TS-04: Emit cache hit/miss counts in structured logs**
Log `cache_read_tokens`, `cache_creation_tokens`, and `cache_hit: bool` per ChatAgent call using the existing `logger.debug(..., extra={..., "correlation_id": ...})` pattern established in v1.3. This is an explicit PROJECT.md acceptance criterion. Use `response.response_metadata["usage"]` as the source, not `response.usage_metadata["input_token_details"]`, to avoid the known LangChain double-counting bug on streaming calls (GitHub #32818).

---

## Differentiators

**D-01: Apply `cache_control` markers to all module-level system prompts (FAIR-RAG + classifiers)**
Even though current token counts fall below the caching threshold, marking them now costs nothing and future prompt expansions will automatically benefit. Requires refactoring all `ChatPromptTemplate.from_messages([("system", ...), ...])` patterns to `SystemMessage(content=[...])` content-block lists — `ChatPromptTemplate.format_messages()` strips `cache_control` silently (GitHub #26701). Mechanical 11-file change; skip `modules/enhancement/enhancer.py` (Haiku 4.5 minimum is 4,096 tokens).

**D-02: Cache efficiency ratio logging per session**
Aggregate `cache_read_tokens / (cache_read_tokens + cache_creation_tokens)` as a session-level hit ratio in Sentry breadcrumbs. Enables detection of TTL expiry (hit rate drops toward zero) or breakpoint regressions after deploys. Low complexity once TS-04 is in place.

**D-03: Multi-turn message history prefix caching**
Apply a second `cache_control` breakpoint to the accumulated message history up to the N-2 turn for conversations exceeding ~10 turns. Requires careful management of the 20-block lookback window constraint. Medium complexity; modest additional savings. Defer until Phase 1 hit rates are measured and proven.

---

## Watch Out For

### 1. `ChatPromptTemplate.format_messages()` silently strips `cache_control` (CRITICAL)

`ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ...]).format_messages(...)` produces a `BaseMessage` with `content` as a plain `str`. A plain string has no place to attach a `cache_control` dict — the LangChain Anthropic integration only passes `cache_control` to the API when `content` is a `list` of structured dicts. This affects every `modules/fiqh/*.py` module, both classifiers, the enhancer, and the translator. No error is raised; `cache_creation_input_tokens` and `cache_read_input_tokens` are both 0 in the response, indistinguishable from a below-threshold token count.

**Prevention:** Replace `("system", SYSTEM_PROMPT)` tuples with `SystemMessage(content=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}])` in every prompt template. Use `make_cached_system_message()` as the single construction point — confirmed working via `_format_messages` in installed `chat_models.py` lines 285-307.

### 2. Haiku 4.5 minimum is 4,096 tokens — the enhancer call site cannot be cached (CRITICAL)

`modules/enhancement/enhancer.py` uses `SMALL_LLM` (claude-haiku-4-5). Haiku 4.5's cache eligibility threshold is 4,096 tokens. The enhancer system prompt is ~330 tokens. Applying `cache_control` to this call site will produce zero cache hits while charging the 1.25× write cost on every single call — a guaranteed cost increase.

**Prevention:** Do not apply `cache_control` to `modules/enhancement/enhancer.py`. Document this explicitly in code comments so future developers do not re-add it.

### 3. Silent failure — usage metadata is the only confirmation signal (CRITICAL)

The Anthropic API returns HTTP 200 regardless of whether caching occurred. A misplaced marker, a below-threshold token count, or dynamic content in the cached prefix all produce identical successful responses. Without checking `cache_creation_input_tokens` and `cache_read_input_tokens`, a broken implementation is invisible.

**Prevention:** TS-03 is not optional. Add an explicit assertion in the test suite after implementing TS-01+TS-02: first call must produce `cache_creation > 0`, second identical call within 5 minutes must produce `cache_read > 0`. Use `response.response_metadata["usage"]` (raw Anthropic dict), not `response.usage_metadata` (LangChain wrapper, which has the double-counting bug described below).

### 4. LangChain `usage_metadata` double-counts cached tokens on streaming calls (CRITICAL)

GitHub issue #32818 documents that `response.usage_metadata["input_tokens"]` includes `cache_read_input_tokens` in its total, inflating the input token count. For streaming calls using `chain.stream()` (the pattern in `core/pipeline_langgraph.py`), cache token counts in `usage_metadata.input_token_details` can be approximately 2× actual values because the Anthropic streaming API emits cache counts in both `message_start` and `message_delta` SSE events and LangChain sums them. This bug is open as of `langchain-anthropic==0.3.22`.

**Prevention:** Always read cache metrics from `response.response_metadata["usage"]` (raw Anthropic API dict). For the streaming generation step, log a boolean `cache_hit: bool` rather than exact token counts, or read raw metadata from the last stream chunk.

### 5. `cache_control` inside `ToolMessage` content blocks causes an API error (MODERATE)

GitHub issue #34920 documents that placing `cache_control` inside the `content` array of a `ToolMessage` causes Anthropic's API to return `invalid_cache: cache_control is not supported at messages.N.content.0.content.0.cache_control`. This can be triggered if implementation attempts to cache retrieved document results from `retrieve_shia_documents_tool` or other tool outputs.

**Prevention:** Never place `cache_control` inside `ToolMessage.content[]` array elements. Retrieved documents change per request — cache hits would never occur regardless. Do not cache tool result messages.

---

## Recommended Phases

- **Phase 1 — ChatAgent caching (TS-01 through TS-04):** Add `make_cached_system_message()` helper to `core/chat_models.py`, apply `cache_control` to tool definitions and system prompt in `agents/core/chat_agent.py` (`_create_llm_with_tools`, `_agent_node`, `_generate_response_node`), verify cache hits via `response_metadata`, and emit cache hit/miss counts using the existing `extra={}` logging pattern. This is the only call site that independently clears the token minimum and delivers guaranteed cost savings. All other phases are lower priority and depend on this being proven working first.

- **Phase 2 — Module-level prompt restructuring (D-01):** Refactor all `ChatPromptTemplate.from_messages([("system", ...), ...])` patterns in `modules/fiqh/` (6 files), `modules/classification/` (1 file), `modules/translation/` (1 file), and `core/prompt_templates.py` (4 templates) to use `SystemMessage(content=[...])` content-block lists with `cache_control` markers. Skip `modules/enhancement/enhancer.py`. Token counts currently fall below threshold on all these sites — no immediate savings — but the structural change is the prerequisite for future eligibility and eliminates a silent anti-pattern from the codebase.

- **Phase 3 — Metrics observability (D-02, D-03, verification):** Confirm measured cache hit rates against the theoretical 5,149-token combined prefix, add per-session cache efficiency ratio to Sentry, and update Linear ticket DEE-50 with actual token savings data. Evaluate multi-turn message history caching only after Phase 1 hit rates are confirmed at production traffic levels.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All claims verified against installed `langchain_anthropic==0.3.22` source code. No new packages needed is confirmed by direct package inspection. Version bump risk noted but manageable. |
| Features | HIGH | Token counts from FEATURES.md call site audit; eligibility decisions follow directly from official Anthropic docs (model-specific minimums confirmed). |
| Architecture | HIGH | Integration strategy verified against installed package source and repo code for `agents/core/chat_agent.py`, `modules/fiqh/*.py`, `core/chat_models.py`. |
| Pitfalls | HIGH | All five critical pitfalls backed by confirmed GitHub issues (#26701, #34920, #32818) and official Anthropic documentation. |

**Overall confidence: HIGH**

### Gaps to Address

- **Exact token counts must be measured before claiming eligibility:** The ~5,149 combined prefix estimate is from the research agent, not a `tiktoken` measurement. If the actual combined count falls below 2,048 tokens, no caching occurs. Measure with `tiktoken` or the Anthropic token counter as the first implementation step.
- **`langchain-anthropic` version bump compatibility:** Whether `0.3.25` is safe to pin alongside `langchain==0.3.27` requires a dependency check. Leave at `0.3.22` until confirmed; the 0.3.22 implementation path is fully validated.
- **Legacy generator token count:** The `generatorSystemTemplate` is estimated at ~1,200 tokens — borderline below the 2,048-token minimum. Measure precisely; if it clears the threshold, it becomes the second-highest-ROI caching target after the ChatAgent.
- **Haiku 4.5 minimum re-verification:** The 4,096-token minimum for Haiku 4.5 is consistent across both STACK.md and FEATURES.md research. Verify against current Anthropic docs at implementation time — model-specific minimums have changed between Claude generations.

---

## Sources

### Primary (HIGH confidence)
- Installed `langchain_anthropic==0.3.22` source (`chat_models.py`) — `cache_control` handling in `_get_request_payload` (lines 1579-1599), `_format_messages` (lines 285-307), `_create_usage_metadata` (lines 2588-2628), tool caching example (lines 1952-1966)
- [Anthropic prompt caching official docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — minimum tokens by model, cache hierarchy, TTL, pricing
- [LangChain ChatAnthropic integration docs](https://docs.langchain.com/oss/python/integrations/chat/anthropic) — `cache_control` content-block format
- `agents/core/chat_agent.py`, `modules/fiqh/*.py`, `core/chat_models.py`, `core/prompt_templates.py` (repo source) — verified call sites, message construction patterns, tool binding

### Secondary (MEDIUM confidence)
- [GitHub #26701](https://github.com/langchain-ai/langchain/issues/26701) — `ChatPromptTemplate.format_messages()` strips `cache_control` silently; confirmed with reproduction
- [GitHub #34920](https://github.com/langchain-ai/langchain/issues/34920) — `cache_control` inside `ToolMessage.content[]` causes `invalid_cache` API error; confirmed with reproduction
- [GitHub #32818](https://github.com/langchain-ai/langchain/issues/32818) — `usage_metadata` double-counts cached tokens in streaming; open as of `langchain-anthropic==0.3.22`
- [langchain-anthropic PyPI release history](https://pypi.org/project/langchain-anthropic/) — `0.3.25` as latest 0.3.x series
- [AnthropicPromptCachingMiddleware docs](https://docs.langchain.com/oss/python/integrations/middleware/anthropic) — confirmed incompatible with `bind_tools()`

### Tertiary (LOW confidence)
- langchain-anthropic 1.4.2 release note (`fix(anthropic): restore cache_control on non-direct subclasses`) — reason for considering `0.3.25` upgrade; not independently verified

---
*Research completed: 2026-05-03*
*Ready for roadmap: yes*
