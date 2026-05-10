# Feature Landscape: Anthropic Prompt Caching (v1.4)

**Domain:** LLM cost optimization via Anthropic prompt caching
**Researched:** 2026-05-03
**Scope:** Which caching features apply to this codebase, which call sites benefit, what is essential vs optional

---

## Summary

Anthropic prompt caching lets API calls reuse a previously processed prompt prefix at 90% cost reduction (cache reads cost 0.1x base; cache writes cost 1.25x base for 5-minute TTL). The feature is applied by placing a `cache_control: {"type": "ephemeral"}` marker on content blocks. Everything **before and including** that marker is cached as a prefix — on a subsequent call with the same prefix, Anthropic charges for the cache read rather than re-processing the tokens.

The three categories of content worth caching, ordered by ROI for this codebase, are:

1. **Tool definitions on ChatAgent** — ~3,722 tokens across 6 tools, static across every request. Highest total cached token count.
2. **System prompt on ChatAgent** — ~1,427 tokens, static. When combined with tool definitions, the combined prefix (~5,149 tokens) comfortably clears the 2,048-token Sonnet 4.6 minimum and the 4,096-token Haiku 4.5 minimum.
3. **System prompts in module-level LLM calls** — the 7 module-level system prompts (fiqh classifier, generator, SEA, filter, decomposer, refiner, legacy classifier) range from 66 to 1,308 tokens. **None individually clears the 2,048-token Sonnet 4.6 minimum.** Caching them in isolation does nothing — the Anthropic API silently skips cache write and returns zeros in usage metadata.

Key constraint discovered during research: the `langchain_anthropic` package installed in this project (0.3.22) does **not** include the `middleware` subpackage (`AnthropicPromptCachingMiddleware`). That class exists in a separate, newer alpha branch of `langchain`. The direct `cache_control` dict approach on ChatAnthropic content blocks is the only available path with the current stack.

---

## How Prompt Caching Works

### Mechanism

When a request includes a `cache_control` marker on a content block, Anthropic:
1. Hashes the full prefix up to and including that block
2. Checks if a matching cache entry exists (within the 5-minute or 1-hour TTL window)
3. On a **cache hit**: charges `cache_read_input_tokens` at 0.1x base price; skips prefix processing
4. On a **cache miss**: charges `cache_creation_input_tokens` at 1.25x base price; writes the prefix to cache

The **20-block lookback** rule: Anthropic scans the last 20 content blocks looking for a previously cached prefix. Beyond 20 blocks, earlier cache entries become invisible.

Up to 4 independent `cache_control` breakpoints per request are supported. Content order matters: `tools` → `system` → `messages` (left to right is higher precedence in the hierarchy).

### Token Minimums (Per Model)

| Model | Minimum for cache eligibility |
|-------|-------------------------------|
| claude-sonnet-4-6 (LARGE_LLM) | 2,048 tokens |
| claude-haiku-4-5 (SMALL_LLM) | 4,096 tokens |

Prompts shorter than the minimum are processed normally; no error is raised, no cache entry is written. You must check `cache_creation_input_tokens` in the response usage to verify a cache write actually occurred.

### Pricing (Sonnet 4.6 / Haiku 4.5)

| Token type | Sonnet 4.6 | Haiku 4.5 |
|------------|-----------|----------|
| Base input | $3.00/M | $1.00/M |
| Cache write (5m) | $3.75/M | $1.25/M |
| Cache write (1h) | $6.00/M | $2.00/M |
| Cache read | $0.30/M | $0.10/M |
| Output | $15.00/M | $5.00/M |

Break-even on a 5m cache write: after **1.25 reads** of the same prefix within 5 minutes. At typical chat volume (multiple requests per session), break-even is easily reached on the ChatAgent's tool+system prefix.

### TTL Strategy

- **5-minute TTL (default)**: no extra setup cost, sufficient for interactive chat sessions where users send multiple messages in a sitting. Ideal for conversational workloads.
- **1-hour TTL**: 2x write cost vs base. Justified only for infrequent, scheduled batch calls or very long system prompts where re-cache overhead is significant. Not recommended for this real-time chat application.

### Cache Verification via Usage Metadata

Every `AIMessage` from `ChatAnthropic` exposes cache metrics in `response.usage_metadata`:

```python
usage = response.usage_metadata["input_token_details"]
cache_read = usage.get("cache_read", 0)        # tokens served from cache
cache_creation = usage.get("cache_creation", 0) # tokens written to cache
```

At the raw `anthropic` SDK level, the equivalent is `response.usage.cache_read_input_tokens` and `response.usage.cache_creation_input_tokens`.

---

## Call Site Audit: Token Counts and Eligibility

| Call site | File | Model | System prompt tokens | Tool def tokens | Combined | Sonnet eligible? | Haiku eligible? |
|-----------|------|-------|---------------------|-----------------|----------|-----------------|-----------------|
| **ChatAgent (bind_tools)** | `agents/core/chat_agent.py` | Sonnet 4.6 | 1,427 | 3,722 | **5,149** | YES | YES |
| Legacy generator system | `core/prompt_templates.py` | Sonnet 4.6 | 1,308 | — | 1,308 | NO (borderline) | NO |
| Hikmah elaboration system | `core/prompt_templates.py` | Sonnet 4.6 | 1,069 | — | 1,069 | NO | NO |
| Fiqh classifier (legacy) | `core/prompt_templates.py` | Sonnet 4.6 | 534 | — | 534 | NO | NO |
| Primer generation system | `core/prompt_templates.py` | Sonnet 4.6 | 561 | — | 561 | NO | NO |
| Fiqh classifier (FAIR-RAG) | `modules/fiqh/classifier.py` | Sonnet 4.6 | 465 | — | 465 | NO | NO |
| Fiqh query decomposer | `modules/fiqh/decomposer.py` | Sonnet 4.6 | 361 | — | 361 | NO | NO |
| Fiqh refiner | `modules/fiqh/refiner.py` | Sonnet 4.6 | 215 | — | 215 | NO | NO |
| Fiqh evidence filter | `modules/fiqh/filter.py` | Sonnet 4.6 | 184 | — | 184 | NO | NO |
| Fiqh SEA assessor | `modules/fiqh/sea.py` | Sonnet 4.6 | 217 | — | 217 | NO | NO |
| Fiqh generator | `modules/fiqh/generator.py` | Sonnet 4.6 | 175 | — | 175 | NO | NO |
| Enhancer | `modules/enhancement/enhancer.py` | Haiku 4.5 | 330 | — | 330 | NO | NO |
| Non-Islamic classifier | `modules/classification/classifier.py` | Sonnet 4.6 | 324 | — | 324 | NO | NO |
| Translation | `core/prompt_templates.py` | Sonnet 4.6 | 66 | — | 66 | NO | NO |

**Conclusion: Only the ChatAgent call site (tools + system prompt = ~5,149 tokens) is independently eligible for prompt caching. All module-level call sites fall below the minimum threshold on their system prompts alone.**

---

## Table Stakes Features

Features that must be implemented for v1.4 to achieve its stated goal of measurable cost reduction.

### TS-01: Cache Tool Definitions on ChatAgent

**What:** Mark the 6 tool definitions bound to `ChatAgent._create_llm_with_tools()` with `cache_control`. Tool definitions are static for the lifetime of the application — they never change between requests.

**Why table stakes:** Tool definitions account for ~3,722 of the 5,149 combined tokens in the ChatAgent prefix. Caching them captures the largest single block of reusable tokens. Every invocation of the ChatAgent (every `/chat/stream/agentic` request) benefits.

**How:** Pass tool definitions as structured dicts with `cache_control` instead of LangChain tool objects in `bind_tools()`. The `extras={"cache_control": {"type": "ephemeral"}}` argument on `@tool` decorators is an undocumented LangChain feature — use the raw Anthropic tool format (`{"name": ..., "description": ..., "input_schema": ..., "cache_control": {"type": "ephemeral"}}`) passed directly to the Anthropic API, or use LangChain's `convert_to_openai_tool`/Anthropic-specific tool format conversion followed by manual injection of `cache_control`.

**Complexity:** Medium. Requires manually converting the 6 LangChain `@tool`-decorated functions to the Anthropic tool dict format so `cache_control` can be injected into the last tool definition. `bind_tools()` does not natively propagate `cache_control` from LangChain tool objects in `langchain-anthropic==0.3.22`.

**Dependency:** TS-02 must be applied at the same time — tool definitions and system prompt form a single prefix; both must be marked to maximize the cached prefix length.

### TS-02: Cache System Prompt on ChatAgent

**What:** Mark `AGENT_SYSTEM_PROMPT` (~1,427 tokens) with `cache_control` in the `_agent_node` when building the message list.

**Why table stakes:** The system prompt appears on every iteration-1 ChatAgent call. Combined with tool definitions, the prefix reaches 5,149 tokens — well above both the Sonnet 4.6 (2,048) and Haiku 4.5 (4,096) minimums. Without caching the system prompt, the 5m cache window on tool definitions alone could expire before the system prompt cache is written.

**How:** In `_agent_node`, replace `SystemMessage(content=AGENT_SYSTEM_PROMPT)` with a structured content block dict: `{"role": "system", "content": [{"type": "text", "text": AGENT_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]}`. This requires the message list construction to use raw dict format rather than LangChain `SystemMessage` objects for the system turn, or using `SystemMessage(content=[...])` with a list of content blocks.

**Complexity:** Low. Single location in `_agent_node`. The content block format is supported by `ChatAnthropic`.

**Dependency:** Must be applied together with TS-01.

### TS-03: Verify Cache Hits via Usage Metadata

**What:** After each ChatAgent LLM call, read `response.usage_metadata["input_token_details"]` and extract `cache_read` and `cache_creation` counts.

**Why table stakes:** Cache breakpoints placed incorrectly produce zero cache hits silently. The only way to confirm the implementation is working is to assert `cache_creation_input_tokens > 0` on the first call and `cache_read_input_tokens > 0` on subsequent calls. Without this check, a misplaced breakpoint or below-minimum token count would silently degrade to full-price calls with no error.

**How:** In `_agent_node`, inspect `response.usage_metadata` after `self.llm.invoke(messages)`. Log `cache_creation` and `cache_read` values.

**Complexity:** Low. Read-only inspection of existing response object.

### TS-04: Emit Cache Hit/Miss Counts in Structured Logs

**What:** Log `cache_read_tokens` and `cache_creation_tokens` per ChatAgent call using the existing `logger.debug()` + `extra={}` pattern established in v1.3.

**Why table stakes:** PROJECT.md explicitly requires "Emit cache hit/miss counts in structured logs (correlation_id + extra={} style)". This is a stated acceptance criterion for the milestone.

**How:** Add `cache_read_tokens` and `cache_creation_tokens` to the existing `logger.debug("Agent node iteration", extra={...})` call in `_agent_node`. The Sentry/structured logging infrastructure from v1.3 already supports arbitrary `extra={}` fields.

**Complexity:** Trivial once TS-03 is in place.

---

## Differentiators

Nice-to-have features that improve coverage or provide additional insight, but do not block the primary cost-reduction goal.

### D-01: Cache Message History Prefix in Multi-Turn Conversations

**What:** For long conversations (10+ turns), apply a second `cache_control` breakpoint to the message history up to the N-2 turn. This freezes the conversation prefix in cache while the last 1-2 turns remain uncached.

**When valuable:** Conversations where a user sends many messages in a 5-minute window. The message history grows with each turn, but earlier turns are identical across all subsequent requests in the same session.

**Complexity:** Medium. The 20-block lookback window imposes a hard constraint: once a conversation exceeds ~20 message blocks, older cache entries fall out of the lookback window. Requires careful turn-counting logic to place the breakpoint within the lookback window.

**Risk:** Overcomplicates `_agent_node` message construction. Diminishing returns beyond early turns because the conversation prefix changes every turn anyway.

### D-02: Cache Retrieved Document Context in FAIR-RAG Generator

**What:** In `modules/fiqh/generator.py`, apply `cache_control` to the system prompt + retrieved evidence block when the evidence set is reused across FAIR-RAG iterations.

**When valuable:** If the same evidence set is passed to the generator multiple times (e.g., for refinement iterations where evidence does not change). In practice, the FAIR-RAG pipeline calls the generator only once per query after evidence is finalized — no reuse occurs.

**Complexity:** Low in principle, but the evidence block changes every call (different retrieved docs), so the cache would never hit. This differentiator is low-priority and likely provides zero savings.

**Verdict:** Skip unless profiling shows repeated calls with identical evidence.

### D-03: Log Cache Efficiency Ratio Per Session

**What:** Aggregate `cache_read_tokens` / (`cache_read_tokens` + `cache_creation_tokens`) as a per-session hit ratio in Sentry.

**When valuable:** Ongoing cost monitoring dashboard. Lets the team detect TTL expiry (hit rate drops toward zero) or breakpoint regressions.

**Complexity:** Low. Requires a rolling accumulator on `ChatState` or session-level aggregation in `pipeline_langgraph.py`.

### D-04: Upgrade Module-Level System Prompts to Clear Minimum Threshold

**What:** Expand the fiqh classifier, decomposer, SEA, filter, refiner, and generator system prompts by appending detailed context or more comprehensive instructions until they each exceed 2,048 tokens.

**When valuable:** Only if a business reason to expand those prompts exists. **Padding system prompts solely to enable caching is an anti-feature** — it increases uncached call costs and output complexity with no quality benefit.

**Verdict:** Do not pursue unless prompt quality improvements naturally bring token counts above threshold.

---

## Anti-Features

### AF-01: Pad System Prompts to Hit Token Threshold

**What goes wrong:** Adding filler content to `modules/fiqh/classifier.py`, `sea.py`, etc. to force their system prompts above 2,048 tokens so they qualify for caching.

**Why avoid:** Padding increases the uncached token cost (first call per 5-minute window is charged at 1.25x cache write). It does not improve model quality. Any write with fewer than 1 subsequent read in the same 5-minute window loses money versus no caching. Module-level calls are called once per fiqh query iteration — cache hits within the 5-minute window are unlikely for most users.

### AF-02: Apply cache_control to Dynamic Content Blocks

**What goes wrong:** Placing `cache_control` on the human turn message that contains the user query, retrieved docs, or session-specific context.

**Why avoid:** These blocks change every request. The cache hash never matches, causing a cache write on every call (charged at 1.25x) with zero reads. Net effect: 25% cost increase on those tokens.

### AF-03: Using AnthropicPromptCachingMiddleware from LangChain (Not Available in Current Stack)

**What goes wrong:** Attempting to import `langchain_anthropic.middleware.AnthropicPromptCachingMiddleware` — this module does not exist in `langchain-anthropic==0.3.22` (confirmed by inspection of the installed package).

**Why avoid:** The middleware is part of LangChain's v1-alpha "agents" framework, which requires a different version of `langchain`. Upgrading to enable it carries unknown breaking changes to the existing LangGraph-based pipeline.

**Instead:** Use the direct `cache_control` dict injection approach on `ChatAnthropic` content blocks and tool definitions.

### AF-04: Using 1-Hour TTL for Interactive Chat

**What goes wrong:** Setting `"ttl": "1h"` on the ChatAgent system/tools cache.

**Why avoid:** 1-hour cache writes cost 2x base input price. A 5,149-token prefix at 1-hour TTL costs ~$0.031 per write (Sonnet 4.6). This is only cost-effective if the same prefix is read more than 2 times in an hour before it expires. For interactive chat, the 5-minute TTL is re-warmed on nearly every message (multiple messages per session within 5 minutes), so 1-hour TTL provides no additional benefit while doubling write costs.

---

## Cost Model

### Baseline (No Caching)

Each ChatAgent call processes the full tool definitions + system prompt each time:
- 5,149 tokens × $3.00/M (Sonnet 4.6) = **$0.0155 per call** for the prefix alone

At 100 ChatAgent calls per day:
- Prefix cost: $0.0155 × 100 = **$1.55/day** just for the static prefix

### With Caching (5-Minute TTL)

Assume a typical session: 1 cache write per 5-minute window, then 3 cache reads (user sends 4 messages per session in quick succession).

- Write cost: 5,149 tokens × $3.75/M = $0.0193 (one time per 5m window)
- Read cost: 5,149 tokens × $0.30/M × 3 reads = $0.0046

Session total for prefix: $0.0193 + $0.0046 = **$0.0239** vs $0.0620 without caching (4 calls × $0.0155) = **61.4% reduction on prefix tokens per session**

At 100 sessions per day (4 messages each), **~$3.81 saved per day** on prefix tokens for Sonnet 4.6 calls.

### Breakeven Analysis

A cache write is cost-neutral after 1.25 reads of the same prefix within the TTL window. For a 5-minute window: if a user sends 2 or more messages within 5 minutes, caching is profitable on those calls. At typical chat interaction patterns (multiple rapid-fire questions), breakeven is routinely exceeded.

### Monitoring Approach

Use `cache_creation_input_tokens` and `cache_read_input_tokens` from the Anthropic API response. A healthy implementation shows:
- First message in a session: `cache_creation_input_tokens` ≈ 5,149, `cache_read_input_tokens` = 0
- Subsequent messages in session (within 5 min): `cache_creation_input_tokens` = 0, `cache_read_input_tokens` ≈ 5,149
- Sessions with only 1 message: no net savings (write charged at 1.25x, no reads)

---

## Feature Dependencies

```
TS-01 (cache tool definitions) ─┐
                                 ├─> both required together to form >2048-token prefix
TS-02 (cache system prompt)   ──┘

TS-02 (cache system prompt)
    -> TS-03 (verify via usage metadata) — needed to confirm TS-01/TS-02 actually work
        -> TS-04 (emit in structured logs) — trivial once TS-03 is in place
```

D-01 (message history caching) depends on TS-01 + TS-02 being stable first.
D-03 (hit ratio logging) depends on TS-04.

---

## MVP Recommendation

Implement in this order:

1. **TS-01 + TS-02 together** — Apply `cache_control` to the ChatAgent tool definitions and system prompt as a single unit. These form the combined prefix; they must be activated together.
2. **TS-03** — Immediately verify cache hits in response metadata after any real API call. Required to confirm the implementation is correct before claiming milestone success.
3. **TS-04** — Log cache hit/miss counts using `extra={}` + `correlation_id` pattern from v1.3. This is an explicit PROJECT.md acceptance criterion.

Defer:
- D-01 (message history caching) — adds complexity, requires careful 20-block window management; modest additional savings.
- D-02 (FAIR-RAG evidence caching) — generator is called once per query; no repeated calls = no cache hits.
- D-03 (hit ratio aggregation) — useful monitoring but not a cost-reduction feature itself.
- D-04 (expand module-level prompts) — do not pad prompts; wait for organic growth or explicit quality improvements.
