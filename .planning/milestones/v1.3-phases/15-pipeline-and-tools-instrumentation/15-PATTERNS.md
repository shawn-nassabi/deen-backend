# Phase 15: Pipeline and Tools Instrumentation - Pattern Map

**Mapped:** 2026-04-27
**Files analyzed:** 3
**Analogs found:** 3 / 3

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `core/pipeline_langgraph.py` | service | streaming / request-response | `api/chat.py` | role-match |
| `agents/tools/retrieval_tools.py` | utility | request-response | `api/chat.py` | role-match |
| `agents/core/chat_agent.py` | service | event-driven (LangGraph nodes) | `api/chat.py` | role-match |

---

## Pattern Assignments

### `core/pipeline_langgraph.py` (service, streaming)

**Analog:** `api/chat.py`

**Current state:** No `logging` import, no `logger` declaration. Has 5 `print()` calls that must be replaced.

**Imports pattern** — copy from `api/chat.py` lines 16-20, adapted for this module:
```python
import logging
from core.context import correlation_id as correlation_id_ctx

logger = logging.getLogger(__name__)
```
Place after the existing `from core import utils` import (current line 16). `__name__` resolves to `core.pipeline_langgraph`.

**Print-to-logger mapping:**

| Location | Current print() | Decision | Replacement |
|---|---|---|---|
| Line 90 | `print(f"[AGENTIC PIPELINE] Starting for query: {user_query[:100]}")` | D-01 / D-06 | `logger.info("Pipeline started", extra={"correlation_id": correlation_id_ctx.get(), "session_id": session_id, "target_language": target_language})` |
| Line 122 | `print(f"[AGENTIC PIPELINE] Node: {node_name}")` | D-01 | `logger.debug("Node traversal", extra={"correlation_id": correlation_id_ctx.get(), "node": node_name})` |
| Line 376 | `print(f"[AGENTIC PIPELINE] Error: {e}")` + `traceback.print_exc()` | D-02 / D-09 | `logger.error("Pipeline error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "session_id": session_id})` — remove the `import traceback; traceback.print_exc()` lines entirely |
| Line 389 | `print(f"[AGENTIC PIPELINE] Failed to append runtime history after error: {memory_exc}")` | D-03 | `logger.warning("Failed to append runtime history after error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "session_id": session_id})` |
| Line 414 | `print(f"[AGENTIC PIPELINE NON-STREAM] Starting for query: {user_query[:100]}")` | D-01 / D-06 | `logger.info("Pipeline started", extra={"correlation_id": correlation_id_ctx.get(), "session_id": session_id, "target_language": target_language})` |

Note: `session_id` is available as a parameter in both `chat_pipeline_streaming_agentic` (line 74) and `chat_pipeline_agentic` (line 397). Inside `response_generator()` (the nested async generator), `session_id` is closed over from the outer function — it is accessible without passing it explicitly.

**Error handling pattern** — copy from `api/chat.py` lines 241-251:
```python
logger.error(
    "Pipeline error",
    exc_info=True,
    extra={
        "correlation_id": correlation_id_ctx.get(),
        "session_id": session_id,
    },
)
```

**Warning pattern** — copy from `api/chat.py` lines 204-211 (warning without Sentry capture):
```python
logger.warning(
    "Failed to append runtime history after error",
    exc_info=True,
    extra={
        "correlation_id": correlation_id_ctx.get(),
        "session_id": session_id,
    },
)
```

**Pipeline start INFO pattern** — copy from `api/chat.py` lines 174-183, stripped to the three required fields (D-06):
```python
logger.info(
    "Pipeline started",
    extra={
        "correlation_id": correlation_id_ctx.get(),
        "session_id": session_id,
        "target_language": target_language,
    },
)
```

---

### `agents/tools/retrieval_tools.py` (utility, request-response)

**Analog:** `api/chat.py`

**Current state:** No `logging` import, no `logger` declaration. Has 4 identical `print(f"[<tool_name>] Error: {e}")` calls in exception handlers across 4 `@tool` functions.

**Imports pattern** — add at top of file after existing imports (current lines 6-8):
```python
import logging
from core.context import correlation_id as correlation_id_ctx

logger = logging.getLogger(__name__)
```
`__name__` resolves to `agents.tools.retrieval_tools`. Per D-08, the module path serves as the tool identifier in log records — no explicit `tool_name` field needed.

**Print-to-logger mapping:**

| Location | Current print() | Tool function | Replacement |
|---|---|---|---|
| Line 55 | `print(f"[retrieve_shia_documents_tool] Error: {e}")` | `retrieve_shia_documents_tool` | `logger.error("Retrieval error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(e)})` |
| Line 114 | `print(f"[retrieve_sunni_documents_tool] Error: {e}")` | `retrieve_sunni_documents_tool` | `logger.error("Retrieval error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(e)})` |
| Line 172 | `print(f"[retrieve_combined_documents_tool] Error: {e}")` | `retrieve_combined_documents_tool` | `logger.error("Retrieval error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(e)})` |
| Line 232 | `print(f"[retrieve_quran_tafsir_tool] Error: {e}")` | `retrieve_quran_tafsir_tool` | `logger.error("Retrieval error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(e)})` |

**Error handling pattern** — copy from `api/chat.py` lines 241-251, simplified to D-08 fields (no query, no endpoint):
```python
except Exception as e:
    logger.error(
        "Retrieval error",
        exc_info=True,
        extra={
            "correlation_id": correlation_id_ctx.get(),
            "error": str(e),
        },
    )
    return {
        "documents": [],
        "count": 0,
        "source": "...",
        "query_used": query,
        "error": str(e),
    }
```

---

### `agents/core/chat_agent.py` (service, event-driven)

**Analog:** `api/chat.py`

**Current state:** No `logging` import, no `logger` declaration. Has approximately 20 `print()` calls across 9 methods. One print (line 173-175, agent response content snippet) is **dropped entirely** per D-04. One print (line 202, tool result payload) is replaced with DEBUG per D-07.

**Imports pattern** — add after existing imports (after `from core.config import ANTHROPIC_API_KEY` at line 33):
```python
import logging
from core.context import correlation_id as correlation_id_ctx

logger = logging.getLogger(__name__)
```
`__name__` resolves to `agents.core.chat_agent`.

**Print-to-logger mapping by method:**

`_fiqh_classification_node` (lines 101-122):
```python
# line 102: print("[FIQH CLASSIFICATION NODE] Classifying query...")
logger.debug("Fiqh classification started", extra={"correlation_id": correlation_id_ctx.get()})

# line 109: print(f"[FIQH CLASSIFICATION NODE] Category: {category}, is_fiqh: {is_fiqh}")
logger.debug("Fiqh classification complete", extra={"correlation_id": correlation_id_ctx.get(), "fiqh_category": category, "is_fiqh": is_fiqh})

# line 116: print(f"[FIQH CLASSIFICATION NODE] Error: {exc}")
logger.error("Fiqh classification error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
```

`_route_after_fiqh_check` (lines 124-135):
```python
# line 127: print(f"[ROUTING] Valid fiqh category ({category}) — routing to fiqh sub-graph")
logger.debug("Routing to fiqh sub-graph", extra={"correlation_id": correlation_id_ctx.get(), "fiqh_category": category})

# line 130: print(f"[ROUTING] Unethical query — routing to early exit")
logger.debug("Routing to early exit: unethical query", extra={"correlation_id": correlation_id_ctx.get()})

# line 134: print("[ROUTING] Not a fiqh query — routing to agent")
logger.debug("Routing to agent: not a fiqh query", extra={"correlation_id": correlation_id_ctx.get()})
```

`_agent_node` (lines 137-181):
```python
# line 138: print(f"[AGENT NODE] Iteration {state['iterations']}")
logger.debug("Agent node iteration", extra={"correlation_id": correlation_id_ctx.get(), "iteration": state["iterations"]})

# line 142: print(f"[AGENT NODE] Max iterations reached ({self.config.max_iterations})")
logger.debug("Max iterations reached", extra={"correlation_id": correlation_id_ctx.get(), "max_iterations": self.config.max_iterations})

# lines 173-175: print("[AGENT NODE] Agent response:", response.content ...) — D-04: DROP ENTIRELY. No replacement.

# line 177: print(f"[AGENT NODE] Error: {exc}")
logger.error("Agent node error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
```

`_tool_node` (lines 183-236):
```python
# line 184: print("[TOOL NODE] Executing tools")
logger.debug("Tool node executing", extra={"correlation_id": correlation_id_ctx.get()})

# line 188: print("[TOOL NODE] No tool calls found")
logger.debug("Tool node: no tool calls found", extra={"correlation_id": correlation_id_ctx.get()})

# line 202: print(f"[TOOL NODE] Tool {tool_name} result: {str(result_data)[:200]}") — D-07: tool_name only, no payload
logger.debug("Tool executed", extra={"correlation_id": correlation_id_ctx.get(), "tool_name": tool_name})
```

`_generate_response_node` (lines 238-268):
```python
# line 239: print("[GENERATE RESPONSE NODE] Generating final response")
logger.debug("Generating final response", extra={"correlation_id": correlation_id_ctx.get()})

# line 262: print(f"[GENERATE RESPONSE NODE] Response generated: {len(response.content)} chars")
logger.debug("Response generated", extra={"correlation_id": correlation_id_ctx.get(), "response_chars": len(response.content)})

# line 264: print(f"[GENERATE RESPONSE NODE] Error: {exc}")
logger.error("Response generation error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
```

`_check_early_exit_node` (lines 270-303):
```python
# line 271: print("[CHECK EARLY EXIT NODE]")
logger.debug("Check early exit node", extra={"correlation_id": correlation_id_ctx.get()})

# line 297: print(f"[CHECK EARLY EXIT NODE] LLM rejection error: {exc}")
logger.error("LLM rejection error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
```

`_call_fiqh_subgraph_node` (lines 305-348):
```python
# line 311: print(f"[FIQH SUBGRAPH NODE] Invoking FAIR-RAG sub-graph for: {state['user_query'][:80]}") — D-05: drop query snippet
logger.debug("Invoking FAIR-RAG sub-graph", extra={"correlation_id": correlation_id_ctx.get()})

# lines 328-332: print(f"[FIQH SUBGRAPH NODE] Sub-graph complete: ...")
logger.debug("Fiqh sub-graph complete", extra={"correlation_id": correlation_id_ctx.get(), "doc_count": len(fiqh_filtered_docs), "status_event_count": len(status_events)})

# line 342: print(f"[FIQH SUBGRAPH NODE] Error: {exc}")
logger.error("Fiqh sub-graph error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
```

`_generate_fiqh_response_node` (lines 350-397):
```python
# line 357: print("[GENERATE FIQH RESPONSE NODE] Generating fiqh answer (non-streaming path)")
logger.debug("Generating fiqh answer (non-streaming)", extra={"correlation_id": correlation_id_ctx.get()})

# line 392: print(f"[GENERATE FIQH RESPONSE NODE] Error: {exc}")
logger.error("Fiqh response generation error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
```

`_should_continue` (lines 399-432):
```python
# line 401: print("[ROUTING] Early exit: non-Islamic or fiqh query")
logger.debug("Routing: early exit", extra={"correlation_id": correlation_id_ctx.get()})

# line 404: print("[ROUTING] Should end flag set")
logger.debug("Routing: should_end flag set", extra={"correlation_id": correlation_id_ctx.get()})

# line 410: print("[ROUTING] No messages, ending")
logger.debug("Routing: no messages, ending", extra={"correlation_id": correlation_id_ctx.get()})

# line 413: print(f"[ROUTING] Continue to tools: {len(last_message.tool_calls)} tool calls")
logger.debug("Routing: continue to tools", extra={"correlation_id": correlation_id_ctx.get(), "tool_call_count": len(last_message.tool_calls)})

# line 419: print("[ROUTING] Agent marked evidence sufficient - ending for streaming")
logger.debug("Routing: evidence sufficient, ending for streaming", extra={"correlation_id": correlation_id_ctx.get()})

# line 421: print("[ROUTING] Agent marked evidence sufficient - generating response")
logger.debug("Routing: evidence sufficient, generating response", extra={"correlation_id": correlation_id_ctx.get()})

# line 425: print("[ROUTING] Agent stopped after retrieval - ending for streaming")
logger.debug("Routing: stopped after retrieval, ending for streaming", extra={"correlation_id": correlation_id_ctx.get()})

# line 427: print("[ROUTING] Agent stopped after retrieval - generating response")
logger.debug("Routing: stopped after retrieval, generating response", extra={"correlation_id": correlation_id_ctx.get()})

# line 431: print("[ROUTING] No evidence available - ending")
logger.debug("Routing: no evidence, ending", extra={"correlation_id": correlation_id_ctx.get()})
```

`_load_runtime_messages` (lines 601-610):
```python
# line 609: print(f"[CHAT AGENT] Failed to load history for session {session_id}: {exc}")
logger.error("Failed to load runtime history", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
```

---

## Shared Patterns

### Logger Declaration
**Source:** `api/chat.py` lines 16-20
**Apply to:** All three target files
```python
import logging
from core.context import correlation_id as correlation_id_ctx

logger = logging.getLogger(__name__)
```

### ERROR-level structured logging (triggers Sentry via LoggingIntegration)
**Source:** `api/chat.py` lines 241-251
**Apply to:** All exception `except` blocks in all three files
**Rule (D-02):** Never add `capture_exception()` alongside — LoggingIntegration fires automatically on ERROR.
```python
logger.error(
    "<short description>",
    exc_info=True,
    extra={
        "correlation_id": correlation_id_ctx.get(),
        "error": str(exc),
    },
)
```

### WARNING-level structured logging (recoverable, no Sentry event)
**Source:** `api/chat.py` lines 204-211
**Apply to:** Secondary failure in SSE generator history write (`pipeline_langgraph.py` line 389 area, D-03)
```python
logger.warning(
    "<short description>",
    exc_info=True,
    extra={
        "correlation_id": correlation_id_ctx.get(),
        "session_id": session_id,
    },
)
```

### DEBUG-level structured logging (node traversal, routing, tool execution)
**Rule (D-01):** All node traversal, routing decisions, and iteration counters use DEBUG. DEBUG does not appear in Sentry Logs (INFO+ only).
```python
logger.debug(
    "<short description>",
    extra={
        "correlation_id": correlation_id_ctx.get(),
        # ...domain-specific fields
    },
)
```

### Do NOT call `bind_sentry_scope()`
**Source:** `api/chat.py` line 173 — `bind_sentry_scope()` is called once at the route handler boundary.
**Rule:** Pipeline and tool files must NOT call `bind_sentry_scope()` — the scope is already bound by the time these are invoked. Calling it again would rebind and lose the original scope data.

### No user query content in log fields
**Rule (D-05):** `user_query`, `working_query`, and all LLM-generated content are excluded from all `extra={}` dicts across all three files. The `session_id` and `correlation_id` are sufficient for request tracing.

---

## No Analog Found

None. All three files have a direct analog in `api/chat.py` (Phase 14 instrumented).

---

## Metadata

**Analog search scope:** `api/`, `core/`, `agents/`
**Files scanned:** 6 (CONTEXT.md, api/chat.py, core/context.py, core/logging_config.py, core/pipeline_langgraph.py, agents/tools/retrieval_tools.py, agents/core/chat_agent.py)
**Pattern extraction date:** 2026-04-27
