# Stack Research: v1.4 LLM Input Caching

**Project:** Deen Backend v1.4 — Anthropic Prompt Caching
**Researched:** 2026-05-03
**Scope:** What library additions or changes are needed to apply Anthropic `cache_control` to all eligible LLM call sites in the existing `langchain-anthropic` + `ChatAnthropic` stack.

---

## Summary

**No new packages are required.** The installed `langchain-anthropic==0.3.22` already supports `cache_control` natively on both system prompts and tool definitions. The raw `anthropic` SDK (also installed, `anthropic==0.92.0`) does not need to be used directly. Cache hit/miss metrics are available on every response via `usage_metadata["input_token_details"]` with no extra configuration.

The only action required is upgrading `langchain-anthropic` from `0.3.22` to `0.3.25` (current pinned compatible release within the 0.3 series) to pick up a bug fix that affected `cache_control` propagation on non-direct `ChatAnthropic` subclasses (langchain-anthropic==1.4.2 release note confirms `restore cache_control on non-direct subclasses`). **Verify whether 0.3.25 is the maximum compatible version before pinning** — the v0.3 line was succeeded by a 1.x series; the project's other langchain pins may constrain this.

---

## Current Stack

| Package | Installed Version | Role |
|---------|-------------------|------|
| `langchain-anthropic` | `0.3.22` | `ChatAnthropic` class, all LLM call sites |
| `anthropic` | `0.92.0` | Underlying HTTP client (used by langchain-anthropic internally) |
| `langchain-core` | `0.3.84` | `UsageMetadata`, `InputTokenDetails`, message primitives |
| `langchain` | `0.3.27` | `ChatPromptTemplate`, `convert_to_anthropic_tool` |
| `langgraph` | `0.2.64` | Graph orchestration wrapping `ChatAnthropic` |

**LLM call sites (all use `ChatAnthropic`):**

| File | Model | Purpose |
|------|-------|---------|
| `core/chat_models.py` — `get_generator_model()` | `LARGE_LLM` (claude-sonnet-4-6) | Fiqh answer generation, general responses |
| `core/chat_models.py` — `get_classifier_model()` | `LARGE_LLM` | Fiqh classification, SEA structured output |
| `core/chat_models.py` — `get_translator_model()` | `LARGE_LLM` | Deterministic translation (temperature=0) |
| `core/chat_models.py` — `get_enhancer_model()` | `SMALL_LLM` (claude-haiku-4-5) | Query enhancement (short rewrites) |
| `agents/core/chat_agent.py` — `_create_llm_with_tools()` | `LARGE_LLM` | Main agent with 6 tools bound via `.bind_tools()` |
| `modules/fiqh/classifier.py` | via `get_classifier_model()` | FAIR-RAG 6-category fiqh classifier |
| `modules/fiqh/decomposer.py` | via `get_classifier_model()` | Query decomposition |
| `modules/fiqh/filter.py` | via `get_classifier_model()` | Evidence filter |
| `modules/fiqh/sea.py` | via `get_classifier_model()` | Structured evidence assessment |
| `modules/fiqh/refiner.py` | via `get_generator_model()` | Query refinement |
| `modules/fiqh/generator.py` | via `get_generator_model()` | Fiqh answer generation |

---

## Required Additions

### Package Changes

**No new packages.** One version bump to consider:

| Package | Current | Recommended | Why |
|---------|---------|-------------|-----|
| `langchain-anthropic` | `0.3.22` | `0.3.25` | Bug fix: `cache_control` propagation on non-direct ChatAnthropic subclasses was broken in pre-1.4.2 releases. `0.3.25` is the latest 0.3 series release compatible with the existing langchain 0.3.x ecosystem pins. |

> **Note:** The 1.x series of `langchain-anthropic` (starting at `1.0.0`) introduced `AnthropicPromptCachingMiddleware` but requires `langchain>=1.0` and `langchain-core>=1.0`. The project currently pins `langchain==0.3.27` and `langchain-core==0.3.84`. Do NOT upgrade to `langchain-anthropic>=1.0` without a full langchain major version migration — that is out of scope for v1.4.

### What NOT to Add

| Package | Why to Exclude |
|---------|---------------|
| `anthropic` (raw client, direct usage) | `langchain-anthropic==0.3.22` already wraps it; direct usage bypasses LangChain's message abstraction and would require rewriting all call sites |
| `langchain-anthropic>=1.0` + `AnthropicPromptCachingMiddleware` | Requires `langchain>=1.0` which is a separate major-version migration; `AnthropicPromptCachingMiddleware` is NOT available in 0.3.x |
| Any new middleware package | Not needed; `cache_control` is applied at the message/tool construction level |

---

## Integration Points

### 1. System Prompt Caching — Message Content Block Format

`langchain-anthropic==0.3.22` supports `cache_control` directly in message content blocks. Pass a list of content dicts instead of a plain string for the system message:

```python
messages = [
    {
        "role": "system",
        "content": [
            {
                "type": "text",
                "text": AGENT_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
    },
    # ... human/assistant messages
]
response = llm.invoke(messages)
```

This is the correct form for all `SYSTEM_PROMPT` strings in `modules/fiqh/*.py` and `AGENT_SYSTEM_PROMPT` in `agents/core/chat_agent.py`.

**Alternatively**, pass `cache_control` as an invocation kwarg to cache the last message block automatically (useful for dynamic content):

```python
response = llm.invoke(messages, cache_control={"type": "ephemeral"})
```

This is handled in `_get_request_payload` at lines 1579–1599 of the installed `chat_models.py` — verified in source.

### 2. Tool Definition Caching — `convert_to_anthropic_tool` + `cache_control` field

To cache tool definitions (schema + docstrings), convert the last tool in the list to Anthropic's dict format and attach `cache_control` before calling `.bind_tools()`:

```python
from langchain_anthropic import convert_to_anthropic_tool

# In ChatAgent._create_llm_with_tools():
tools_list = list(self.tools)  # existing 6 tools
last_tool_dict = convert_to_anthropic_tool(tools_list[-1])
last_tool_dict["cache_control"] = {"type": "ephemeral"}
cacheable_tools = tools_list[:-1] + [last_tool_dict]

llm = ChatAnthropic(...)
return llm.bind_tools(cacheable_tools)
```

Anthropic caches everything in the `tools` array up to and including the block marked with `cache_control`. Marking only the last tool caches all tool definitions in one cache write. This is documented and verified in `chat_models.py` docstring at line 1953.

`convert_to_anthropic_tool` is importable from `langchain_anthropic` — confirmed in installed `__init__.py`.

### 3. Reading Cache Hit/Miss Metrics

Every `ChatAnthropic` response (streaming and non-streaming) includes cache metrics via `usage_metadata` — no extra configuration needed:

```python
response = llm.invoke(messages)
details = response.usage_metadata.get("input_token_details", {})
cache_read = details.get("cache_read", 0) or 0       # tokens served from cache
cache_creation = details.get("cache_creation", 0) or 0  # tokens written to cache
```

Internally, `_create_usage_metadata()` (line 2588 of installed `chat_models.py`) reads `cache_read_input_tokens` and `cache_creation_input_tokens` from the Anthropic API response and normalizes them to `cache_read` and `cache_creation` keys under `input_token_details`.

**Important:** `input_tokens` in `usage_metadata` is the LangChain-normalized total (base + cache_read + cache_creation). To get only the un-cached new tokens: `input_tokens - cache_read - cache_creation`. This is a known quirk of the LangChain wrapper (issue #32818, closed).

For structured log emission (Sentry-compatible with existing `extra={}` pattern):

```python
logger.info(
    "LLM call completed",
    extra={
        "correlation_id": correlation_id_ctx.get(),
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_creation,
        "cache_hit": cache_read > 0,
    }
)
```

### 4. ChatPromptTemplate Call Sites in `modules/fiqh/`

The fiqh modules use `ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ...])` which passes the system prompt as a plain string. To cache these, the string form must be converted to a content-block list. There are two options:

**Option A — Wrap at invocation via `cache_control` kwarg (lowest friction):**
```python
chain = _prompt | llm
response = chain.invoke({"query": query}, config={"cache_control": {"type": "ephemeral"}})
```

This works when `_get_request_payload` receives `cache_control` in kwargs — the installed source handles it.

**Option B — Switch to explicit content block in the prompt template:**
```python
from langchain_core.messages import SystemMessage

_prompt = ChatPromptTemplate.from_messages([
    SystemMessage(content=[
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]),
    ("human", "{query}"),
])
```

Option B is more explicit and guarantees the cache breakpoint is on the system block, not the last human message. Preferred for static system prompts that never change between calls.

---

## Version Notes

### Token Minimums for Caching

Both models in use meet the minimum requirements:

| Model | Minimum cached tokens | Notes |
|-------|----------------------|-------|
| `claude-sonnet-4-6` | 1,024 tokens | Most system prompts in the codebase exceed this |
| `claude-haiku-4-5-20251001` | 2,048 tokens | Haiku 4.5 has a higher minimum; the enhancer model prompt may be too short |

If a prompt is below the minimum, the API does not error — `cache_creation_input_tokens` and `cache_read_input_tokens` will both be 0 in the response. Check `cache_creation == 0 AND cache_read == 0` to detect this.

### Cache TTL

Default TTL is 5 minutes. Cache is refreshed (at no additional cost) every time the cached prefix is accessed within the TTL window. For tool definitions and static system prompts (which are identical on every request), the 5-minute default is sufficient and avoids the 2x write cost of the 1-hour TTL.

### Cache Hierarchy

Anthropic applies `cache_control` in this order: `tools` → `system` → `messages`. A change to any level invalidates that level and all downstream levels. Implication: tool definitions should be marked as one cache unit (mark only the last tool); system prompt as a second cache unit; dynamic retrieved context as a third (if applicable). Maximum 4 breakpoints per request.

### Pricing Impact

| Operation | Cost multiplier |
|-----------|----------------|
| Cache write | 1.25x base input token price |
| Cache read | 0.10x base input token price |

For any call where the cached prefix is read more than once within the TTL, net cost is lower than uncached. System prompts and tool schemas are identical on every request — cache hits begin from the second request within each 5-minute window.

---

## Sources

- [LangChain ChatAnthropic docs — prompt caching section](https://docs.langchain.com/oss/python/integrations/chat/anthropic) — `cache_control` invocation kwarg and content-block format (HIGH confidence — official LangChain docs, verified against installed source `chat_models.py`)
- [Anthropic prompt caching docs](https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching) — token minimums per model, cache TTL, usage fields, pricing, 4-breakpoint maximum (HIGH confidence — official Anthropic docs)
- Installed `langchain_anthropic/chat_models.py` lines 1579–1599 — `_get_request_payload` cache_control kwarg handling (HIGH confidence — verified in installed source)
- Installed `langchain_anthropic/chat_models.py` lines 1952–1966 — `bind_tools` + `convert_to_anthropic_tool` + `cache_control` pattern (HIGH confidence — verified in installed source docstring)
- Installed `langchain_anthropic/chat_models.py` lines 2588–2628 — `_create_usage_metadata` confirming `cache_read_input_tokens` → `cache_read` and `cache_creation_input_tokens` → `cache_creation` normalization (HIGH confidence — verified in installed source)
- [langchain-anthropic PyPI release history](https://pypi.org/project/langchain-anthropic/) — latest 0.3.x is `0.3.25`; 1.x series requires langchain>=1.0 (HIGH confidence — PyPI page)
- [langchain-anthropic==1.4.2 release note](https://github.com/langchain-ai/langchain/releases) — `fix(anthropic): restore cache_control on non-direct subclasses` (MEDIUM confidence — release note, reason for recommending 0.3.25 over 0.3.22)
- [LangChain issue #32818](https://github.com/langchain-ai/langchain/issues/32818) — `input_tokens` inflation quirk when prompt caching active (MEDIUM confidence — GitHub issue, closed)
