# Phase 19: Observability and Verification - Pattern Map

**Mapped:** 2026-05-03
**Files analyzed:** 5 (4 source, 1 test)
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `core/sentry.py` (modify — add helper) | utility (observability) | event-driven (Sentry SDK breadcrumb) | `core/sentry.py:bind_sentry_scope` (same file) | exact |
| `core/context.py` (modify — option a, D-07) | utility (per-request scope) | request-response (ContextVar lifecycle) | `core/context.py:correlation_id` (same file) | exact |
| `agents/state/chat_state.py` (modify — option b, D-07) | model (TypedDict state) | request-response (LangGraph state mutation) | `agents/state/chat_state.py:iterations` field | exact |
| `agents/core/chat_agent.py` (modify `_agent_node`, lines 184-199) | service (graph node) | request-response (LangGraph node mutation) | existing `_agent_node` self (lines 184-199 already extract metrics) | exact |
| `core/pipeline_langgraph.py` (modify — fire breadcrumb at all `done` sites) | service (SSE generator) | streaming (SSE event emission) | existing `done` emission sites in same file (lines 201, 219, 378, 400) | exact |
| `agent_tests/test_prompt_cache.py` extension OR new `tests/test_cache_metrics_breadcrumb.py` | test | request-response (assert helper math + Sentry mock) | `agent_tests/test_prompt_cache.py:_extract_cache_usage` (already aggregates across iterations) | exact |

---

## Pattern Assignments

### `core/sentry.py` — add `record_cache_metrics_breadcrumb(...)`

**Analog (same file):** `core/sentry.py:bind_sentry_scope` (lines 49-73)

**SENTRY_ENABLED guard pattern** (lines 11, 65-66) — D-09 requires no-op when disabled:

```python
SENTRY_ENABLED: bool = os.getenv("SENTRY_ENABLED", "").lower() == "true"

# inside helper, very first statement:
def bind_sentry_scope(
    cid: str,
    endpoint: str,
    session_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Set per-request Sentry tags on the current isolation scope.

    No-op when SENTRY_ENABLED is False. ...
    """
    if not SENTRY_ENABLED:
        return
    scope = sentry_sdk.get_isolation_scope()
    scope.set_tag("correlation_id", cid)
    ...
```

**Pattern to copy for new helper:**
- Module-level import of `sentry_sdk` already present (line 4).
- Function: typed signature, docstring referencing the relevant decision (D-08, D-09).
- First line: `if not SENTRY_ENABLED: return` — identical guard.
- Use `sentry_sdk.add_breadcrumb(category=..., level="info", message=..., data={...})`.
- Per D-08: `data` dict carries `cache_efficiency_ratio`, `cache_read_tokens`, `cache_creation_tokens`, `iterations`.
- Per D-06: caller passes pre-computed ratio; helper does NOT do the divide (keeps the ZeroDivisionError guard with the caller, where the sums live).

---

### `core/context.py` — add cache-tokens ContextVar (D-07 option a)

**Analog (same file):** `core/context.py:correlation_id` (lines 1-6)

**Full file as analog (6 lines):**

```python
from contextvars import ContextVar

# Per-request correlation ID. Set once in CorrelationIdMiddleware.dispatch();
# readable from any coroutine in the same async task chain without threading
# the request object through function signatures.
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
```

**Pattern to copy:**
- Module-level `ContextVar[T]` declaration with `name=` and `default=`.
- Default is the type's empty value (zero for int, empty string for str).
- Comment names the writer (middleware) and the readers.

**Important nuance for cache-tokens:** `correlation_id` is a single scalar. For Phase 19, we need TWO accumulators (`cache_creation_tokens_total`, `cache_read_tokens_total`) plus an iteration count. Two patterns possible:
1. Two separate `ContextVar[int]` with `default=0`, plus reset to 0 in middleware (mirrors `correlation_id` 1:1).
2. A single `ContextVar[dict]` carrying both — closer to D-08 payload shape but unidiomatic vs the existing single-scalar precedent.

**Reset point** — analog: `core/middleware.py:CorrelationIdMiddleware.__call__` (line 29) sets `correlation_id.set(cid)` per request. The new ContextVars need an analogous reset in the same middleware. Excerpt:

```python
# core/middleware.py:23-29
async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] not in ("http", "websocket"):
        await self.app(scope, receive, send)
        return

    cid = str(uuid.uuid4())
    correlation_id.set(cid)
    # NEW (Phase 19, option a): reset cache token accumulators per request
    # cache_creation_tokens_total.set(0)
    # cache_read_tokens_total.set(0)
    # agent_iteration_count.set(0)
```

---

### `agents/state/chat_state.py` — add accumulator fields (D-07 option b)

**Analog (same file):** `iterations: int` field (lines 119-121) and `errors: List[str]` field (lines 115-117) on the `ChatState` TypedDict.

**Pattern to copy** (lines 119-122):

```python
# Metadata
iterations: int
"""Number of agent iterations (for debugging and limits)"""
```

**Initial-state factory pattern** — analog: `create_initial_state(...)` lines 137-198, specifically the `iterations=0,` line (194):

```python
return ChatState(
    messages=initial_messages or [],
    user_query=user_query,
    ...
    errors=[],
    iterations=0,
    # NEW (Phase 19, option b):
    # cache_creation_tokens_total=0,
    # cache_read_tokens_total=0,
    ...
)
```

**Pattern to copy:**
- Add fields under the `# Metadata` section (or a new `# Cache metrics` section).
- Type as `int`; one-line docstring explaining what the field accumulates.
- Default to `0` in `create_initial_state()`.
- Mutation pattern matches `state["iterations"] += 1` already used in `_agent_node` (line 156).

---

### `agents/core/chat_agent.py:_agent_node` — accumulate cache tokens

**Analog (same node, same file):** lines 184-199 (already extract `_cache_creation` and `_cache_read`).

**Existing extract block to extend** (lines 183-199):

```python
try:
    response = self.llm.invoke(messages)
    # Cache metrics: use response_metadata["usage"] (raw Anthropic dict).
    # Do NOT use the LangChain usage wrapper — it double-counts cached tokens
    # in streaming paths (GitHub #32818).
    _usage = response.response_metadata.get("usage", {})
    _cache_creation = _usage.get("cache_creation_input_tokens", 0) or 0
    _cache_read = _usage.get("cache_read_input_tokens", 0) or 0
    logger.debug(
        "Agent LLM cache metrics",
        extra={
            "correlation_id": correlation_id_ctx.get(),
            "cache_hit": _cache_read > 0,
            "cache_creation_tokens": _cache_creation,
            "cache_read_tokens": _cache_read,
        },
    )
    state["messages"].append(response)
    # NEW (Phase 19): accumulate into either ContextVar (D-07 option a)
    # or ChatState fields (D-07 option b).
    # Option b example:
    # state["cache_creation_tokens_total"] += _cache_creation
    # state["cache_read_tokens_total"] += _cache_read
    if not getattr(response, "tool_calls", None) and self._has_any_documents(state):
        state["ready_to_answer"] = True
except Exception as exc:
    logger.error("Agent node error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
    state["errors"].append(f"Agent error: {str(exc)}")
    state["should_end"] = True

return state
```

**Pattern constraints (D-04, locked):**
- MUST NOT switch source from `response.response_metadata["usage"]` to `response.usage_metadata` (LangChain double-counts cached tokens — PITFALLS.md CRITICAL-5).
- MUST keep the `or 0` fallback (Anthropic returns missing keys when cache disabled).
- Accumulation goes after the `state["messages"].append(response)` line, before the `ready_to_answer` check, so partial accumulation is preserved if the `ready_to_answer` branch were ever to short-circuit.
- `_tool_node`, `_generate_response_node`, fiqh sub-graph nodes do NOT touch the accumulator (D-03). Only `_agent_node` writes.

---

### `core/pipeline_langgraph.py` — fire breadcrumb at terminal `done` sites

**Analogs:** four `sse_event("done", {})` emission sites in the same file:
- Line 201 — `if final_state is None:` error short-circuit
- Line 219 — early-exit (non-Islamic / fiqh-rejected)
- Line 378 — main success path (both fiqh FAIR-RAG and hadith/non-fiqh streaming converge here)
- Line 400 — outer `except Exception as e:` error path

**Note:** CONTEXT.md mentions "five `done` emission sites" but only four exist in the current file. Planner should treat all four as in-scope; D-02 requires breadcrumb to fire on every successful path (lines 219 and 378 both qualify; lines 201 and 400 are error paths where firing is allowed but optional per D-02 wording — planner's call).

**Surrounding pattern (line 378 — main success path)**:

```python
                if hadith_docs:
                    hadith_json = utils.format_references_as_json(hadith_docs)
                    yield sse_event("hadith_references", {"references": hadith_json})

                if quran_docs:
                    quran_json = utils.format_quran_references_as_json(quran_docs)
                    yield sse_event("quran_references", {"references": quran_json})

            yield sse_event("done", {})
            # NEW (Phase 19): fire breadcrumb here, BEFORE returning control
            # to FastAPI. correlation_id_ctx still in scope; final_state still
            # readable; SENTRY_ENABLED guard inside helper.
```

**Pattern to copy (read site for accumulator):**
- D-07 option (a) — ContextVar: `from core.context import cache_creation_tokens_total, cache_read_tokens_total`, then read with `.get()`. Already-imported sibling: line 17 `from core.context import correlation_id as correlation_id_ctx`.
- D-07 option (b) — ChatState: read from `final_state.get("cache_creation_tokens_total", 0)` etc. Existing precedent (lines 207, 251, 315): `final_state.get("early_exit_message")`, `final_state.get("fiqh_filtered_docs", [])`, `final_state.get("retrieved_docs", [])`.

**Ratio computation pattern (D-05, D-06)** — must guard ZeroDivisionError:

```python
sum_creation = ...   # from accumulator
sum_read = ...       # from accumulator
total = sum_creation + sum_read
ratio = (sum_read / total) if total > 0 else 0.0  # D-06: cold-cache → 0.0
```

**Helper invocation:**

```python
from core.sentry import record_cache_metrics_breadcrumb  # add to imports near top of file

record_cache_metrics_breadcrumb(
    cache_efficiency_ratio=ratio,
    cache_read_tokens=sum_read,
    cache_creation_tokens=sum_creation,
    iterations=n_agent_calls,
)
```

**Logging-extra parallelism (Established Pattern in CONTEXT.md):** Existing logging convention puts `correlation_id` in `extra={}` on every log call. The breadcrumb call is parallel — Sentry breadcrumbs are auto-tagged with the request's isolation scope tags (already including `correlation_id` via `bind_sentry_scope` at the route handler — see `api/chat.py:173, 278`), so the helper does NOT need to re-emit `correlation_id` in `data`.

---

### Test file — extend `agent_tests/test_prompt_cache.py` OR new unit test

**Analog:** `agent_tests/test_prompt_cache.py:_extract_cache_usage` (lines 38-60).

**Aggregation pattern already proven in this file** (matches D-05 sum-then-divide):

```python
def _extract_cache_usage(final_state: dict) -> dict:
    """Aggregate cache_creation_input_tokens and cache_read_input_tokens across
    all AIMessages in final_state['messages'].

    Sums across all agent iterations: iteration 1 writes the cache
    (cache_creation > 0) and subsequent iterations read it (cache_read > 0).
    Checking only the last AIMessage misses the write on multi-iteration calls.
    """
    messages = final_state.get("messages", [])
    total_creation = 0
    total_read = 0
    total_input = 0
    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, "response_metadata"):
            usage = msg.response_metadata.get("usage", {})
            total_creation += usage.get("cache_creation_input_tokens", 0) or 0
            total_read += usage.get("cache_read_input_tokens", 0) or 0
            total_input += usage.get("input_tokens", 0) or 0
    return {
        "cache_creation_input_tokens": total_creation,
        "cache_read_input_tokens": total_read,
        "input_tokens": total_input,
    }
```

**Pattern to copy:**
- Use this aggregator unchanged in any new test that wants to compute the expected ratio independently of the production helper.
- Two-call shape (lines 63-127): call 1 (cache write), call 2 (cache hit) — already proven; Phase 19 reuses to assert the breadcrumb data on call 2 has `cache_efficiency_ratio > 0`.

**Streaming-pipeline test analog** for breadcrumb-emission tests (`tests/test_agentic_streaming_pipeline.py`):

```python
# tests/test_agentic_streaming_pipeline.py:142-216 pattern:
def test_streaming_pipeline_uses_runtime_history_and_appends_once(monkeypatch):
    captured = {"history": None, "append_calls": []}

    class FakeAgent:
        def __init__(self, config): self.config = config
        async def astream(self, **kwargs):
            yield {"agent": {...}}

    monkeypatch.setattr(pipeline_langgraph, "ChatAgent", FakeAgent)
    monkeypatch.setattr("core.memory.make_history", fake_make_history)
    ...

    async def _run():
        response = await pipeline_langgraph.chat_pipeline_streaming_agentic(...)
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    output = asyncio.run(_run())
    assert ...
```

**Pattern to copy for breadcrumb test:**
- `monkeypatch.setattr` `pipeline_langgraph.ChatAgent` with a `FakeAgent` whose `astream` yields a final state carrying the desired token counts (option b) or whose `_agent_node` mutates the new ContextVars (option a).
- `monkeypatch.setattr("core.sentry.record_cache_metrics_breadcrumb", capturing_fn)` — capture call args; assert ratio matches expected `sum_read / (sum_read + sum_creation)`.
- Also assert cold-cache case (call with both sums = 0) → `cache_efficiency_ratio == 0.0` with no ZeroDivisionError raised — covers ROADMAP success criterion 2.

**Discretion (per CONTEXT.md):** the planner can choose between (i) extending `agent_tests/test_prompt_cache.py` with a new function that asserts breadcrumb math via real Anthropic call (slower, requires API key), or (ii) a new `tests/test_cache_metrics_breadcrumb.py` with `monkeypatch` + a fake Sentry SDK to seam the helper math (faster, hermetic). The fast unit-seam is recommended for CI; the integration extension is recommended for post-deploy verification.

---

## Shared Patterns

### Sentry SENTRY_ENABLED guard

**Source:** `core/sentry.py:11, 65-66` (`SENTRY_ENABLED` constant + `if not SENTRY_ENABLED: return` early-exit)
**Apply to:** any new function in `core/sentry.py` that touches the Sentry SDK.

```python
SENTRY_ENABLED: bool = os.getenv("SENTRY_ENABLED", "").lower() == "true"

def some_helper(...) -> None:
    if not SENTRY_ENABLED:
        return
    # ... sentry_sdk calls ...
```

### Per-request ContextVar lifecycle

**Source:** `core/context.py:correlation_id` (declaration) + `core/middleware.py:CorrelationIdMiddleware.__call__` line 29 (per-request reset)
**Apply to:** any new accumulator that must be per-request scoped.

```python
# core/context.py
my_var: ContextVar[T] = ContextVar("my_var", default=<zero>)

# core/middleware.py — inside CorrelationIdMiddleware.__call__
my_var.set(<zero>)  # reset per request
```

**Important note on streaming**: the SSE generator (`core/pipeline_langgraph.py:response_generator`) runs as an async generator within the same FastAPI task as the request handler. ContextVar reads inside that generator see the value set by `CorrelationIdMiddleware` for this request. The middleware reset at request entry is sufficient; no additional reset needed at SSE generator yields.

### LangGraph node mutation

**Source:** `agents/core/chat_agent.py:_agent_node` line 156 (`state["iterations"] += 1`)
**Apply to:** any new field added to ChatState that needs in-place mutation (option b).

```python
def _agent_node(self, state: ChatState) -> ChatState:
    state["iterations"] += 1  # in-place mutation
    # ... node logic ...
    return state
```

### Structured logging convention (parallel to breadcrumb data)

**Source:** `agents/core/chat_agent.py:191-199`
**Apply to:** the new breadcrumb call as a *parallel* pattern (NOT a copy — breadcrumbs use `data=`, logs use `extra=`).

The DEBUG log already emits per-iteration metrics:

```python
logger.debug(
    "Agent LLM cache metrics",
    extra={
        "correlation_id": correlation_id_ctx.get(),
        "cache_hit": _cache_read > 0,
        "cache_creation_tokens": _cache_creation,
        "cache_read_tokens": _cache_read,
    },
)
```

The Phase 19 breadcrumb is the per-turn aggregate complement at INFO level via Sentry breadcrumb. The DEBUG log stays — Phase 19 does not remove or alter it.

---

## No Analog Found

No files in scope lack an analog. Every Phase 19 file modification has a precedent in the same file or a sibling file in the same module.

---

## Metadata

**Analog search scope:** `core/`, `agents/`, `tests/`, `agent_tests/`
**Files scanned:** 11 (sentry.py, context.py, middleware.py, chat_agent.py, chat_state.py, pipeline_langgraph.py, test_prompt_cache.py, test_agentic_streaming_pipeline.py, fiqh_graph.py, retrieval_tools.py, main.py)
**Pattern extraction date:** 2026-05-03
