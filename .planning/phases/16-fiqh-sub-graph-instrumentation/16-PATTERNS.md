# Phase 16: Fiqh Sub-graph Instrumentation - Pattern Map

**Mapped:** 2026-04-28
**Files analyzed:** 1 (one file modified: `agents/fiqh/fiqh_graph.py`)
**Analogs found:** 3 / 3

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `agents/fiqh/fiqh_graph.py` | LangGraph sub-graph node set + routing function | event-driven (iterative FAIR-RAG loop) | `agents/tools/retrieval_tools.py` (error path + `correlation_id_ctx` import) | exact — same structured logging pattern, same import alias, same exception shape |
| `agents/fiqh/fiqh_graph.py` | LangGraph sub-graph node set + routing function | event-driven (iterative FAIR-RAG loop) | `core/pipeline_langgraph.py` (multi-field INFO + WARNING + `correlation_id_ctx`) | exact — multi-field `extra={}`, WARNING with two fields, same import alias |
| `agents/fiqh/fiqh_graph.py` | LangGraph sub-graph node set + routing function | event-driven (iterative FAIR-RAG loop) | `api/chat.py` (Phase 14 multi-line `extra={}` style) | role-match — multi-line dict formatting, `logger.warning(...)` with named fields |

---

## Pattern Assignments

### `agents/fiqh/fiqh_graph.py` — all patterns

This file is the only modification target. Three distinct patterns apply across its 6 functions.

---

#### Pattern 1: Import block

**Analog:** `agents/tools/retrieval_tools.py` lines 9–12

```python
import logging
from core.context import correlation_id as correlation_id_ctx

logger = logging.getLogger(__name__)
```

**Apply to:** Add `from core.context import correlation_id as correlation_id_ctx` at line 13 or 14 of `fiqh_graph.py`, after `import logging` (line 12) and before `from typing import Literal` (line 13). The `logger = logging.getLogger(__name__)` at line 19 already exists — do not duplicate it.

**Exact insertion point in target file (current lines 11–19):**
```python
from __future__ import annotations
import logging
from core.context import correlation_id as correlation_id_ctx   # ADD THIS LINE
from typing import Literal

from langgraph.graph import END, StateGraph

from agents.state.fiqh_state import FiqhState

logger = logging.getLogger(__name__)
```

---

#### Pattern 2: `extra={}` structured logging — INFO path (multi-field, multi-line dict)

**Analog:** `core/pipeline_langgraph.py` lines 94–98

```python
logger.info("Pipeline started", extra={
    "correlation_id": correlation_id_ctx.get(),
    "session_id": session_id,
    "target_language": target_language,
})
```

**Analog:** `api/chat.py` lines 174–183

```python
logger.info(
    "Agentic stream request accepted",
    extra={
        "correlation_id": corr_id,
        "session_id": session_id,
        "endpoint": "/chat/stream/agentic",
        "user_id": user_id,
        "query_length": len(user_query),
    },
)
```

**Rules extracted from these analogs:**
- Message is a static string — no `%s`, no f-strings, no `[PREFIX]` tags in the message.
- All dynamic values go into `extra={}` as named keys.
- `correlation_id_ctx.get()` is always the first key.
- Multi-line dict style when there are 3+ keys (readability convention from api/chat.py).
- Single-line dict style acceptable for 1–2 keys (see `logger.debug` at pipeline_langgraph.py line 130).

**Apply to:** Every converted INFO/DEBUG call across all 5 node functions and `_route_after_assess`. Exact field sets per node are locked in CONTEXT.md D-03.

**Concrete per-node conversions (drop `[FIQH_GRAPH]` prefix from message strings — Phase 15 pattern):**

`_decompose_node` line 35 (INFO):
```python
logger.info("Fiqh query decomposed", extra={
    "correlation_id": correlation_id_ctx.get(),
})
```

`_retrieve_node` line 67 (INFO) — drop `current_query[:60]` per D-06:
```python
logger.info("Fiqh documents retrieved", extra={
    "correlation_id": correlation_id_ctx.get(),
    "iteration": iteration,
    "doc_count": len(new_docs),
})
```

`_filter_node` lines 97–100 (INFO):
```python
logger.info("Fiqh evidence filtered", extra={
    "correlation_id": correlation_id_ctx.get(),
    "iteration": state["iteration"],
    "doc_count": len(filtered),
})
```

`_assess_node` line 123 (INFO):
```python
logger.info("Fiqh SEA assessment complete", extra={
    "correlation_id": correlation_id_ctx.get(),
    "iteration": state["iteration"],
    "verdict": verdict,
    "doc_count": len(state["accumulated_docs"]),
})
```

`_refine_node` line 155 (INFO):
```python
logger.info("Fiqh query refined", extra={
    "correlation_id": correlation_id_ctx.get(),
})
```

`_route_after_assess` lines 181–185 (INFO):
```python
logger.info("Fiqh FAIR-RAG exiting", extra={
    "correlation_id": correlation_id_ctx.get(),
    "iteration": state["iteration"],
    "verdict": state["verdict"],
    "doc_count": len(state["accumulated_docs"]),
})
```

---

#### Pattern 3: `extra={}` structured logging — ERROR path (exc_info=True)

**Analog:** `agents/tools/retrieval_tools.py` lines 58–62

```python
except Exception as e:
    logger.error("Retrieval error", exc_info=True, extra={
        "correlation_id": correlation_id_ctx.get(),
        "error": str(e),
    })
```

**Analog:** `core/pipeline_langgraph.py` lines 383–387

```python
except Exception as e:
    logger.error("Pipeline error", exc_info=True, extra={
        "correlation_id": correlation_id_ctx.get(),
        "session_id": session_id,
    })
```

**Rules extracted from these analogs:**
- `exc_info=True` is always present on error calls — it attaches the traceback to the log record.
- `"error": str(e)` captures the exception message as a searchable Sentry field.
- The variable name from the except clause may be `exc` or `e` — `fiqh_graph.py` uses `exc`, keep it.
- No `capture_exception()` anywhere — LoggingIntegration auto-captures ERROR-level records (D-10, D-11).

**Concrete per-node conversions:**

`_decompose_node` line 37 (ERROR):
```python
except Exception as exc:
    logger.error("Fiqh decompose_node error", exc_info=True, extra={
        "correlation_id": correlation_id_ctx.get(),
        "error": str(exc),
    })
```

`_retrieve_node` line 69 (ERROR):
```python
except Exception as exc:
    logger.error("Fiqh retrieve_node error", exc_info=True, extra={
        "correlation_id": correlation_id_ctx.get(),
        "iteration": iteration,
        "error": str(exc),
    })
```

`_filter_node` line 103 (ERROR):
```python
except Exception as exc:
    logger.error("Fiqh filter_node error", exc_info=True, extra={
        "correlation_id": correlation_id_ctx.get(),
        "iteration": state["iteration"],
        "error": str(exc),
    })
```

`_assess_node` line 125 (ERROR):
```python
except Exception as exc:
    logger.error("Fiqh assess_node error", exc_info=True, extra={
        "correlation_id": correlation_id_ctx.get(),
        "iteration": state["iteration"],
        "error": str(exc),
    })
```

`_refine_node` line 157 (ERROR):
```python
except Exception as exc:
    logger.error("Fiqh refine_node error", exc_info=True, extra={
        "correlation_id": correlation_id_ctx.get(),
        "error": str(exc),
    })
```

---

#### Pattern 4: WARNING conditional — `if len(...) == 0` guard

**Analog:** `core/pipeline_langgraph.py` lines 398–401 (WARNING with named fields)

```python
logger.warning("Failed to append runtime history after error", exc_info=True, extra={
    "correlation_id": correlation_id_ctx.get(),
    "session_id": session_id,
})
```

**Analog:** `api/chat.py` lines 204–211 (WARNING without exc_info — conditional path, not exception path)

```python
logger.warning(
    "Config parse error, using default config",
    extra={
        "correlation_id": corr_id,
        "session_id": session_id,
        "endpoint": "/chat/stream/agentic",
    },
)
```

**Rules extracted from these analogs:**
- WARNING on conditional paths (not exception paths) does NOT use `exc_info=True` — there is no active exception.
- WARNING uses the same `extra={}` dict style as INFO: static message string, named fields.
- WARNING fires as an additional call alongside the surrounding INFO — does not replace it.

**Concrete new WARNING insertions (FIQH-02, FIQH-03, FIQH-04):**

FIQH-02 — in `_retrieve_node`, inside `try` block, immediately after `new_docs = retrieve_fiqh_documents(current_query)` (after current line 66), before the dedup loop:
```python
new_docs = retrieve_fiqh_documents(current_query)
if len(new_docs) == 0:
    logger.warning("Fiqh retrieval returned zero documents", extra={
        "correlation_id": correlation_id_ctx.get(),
        "iteration": iteration,
        "doc_count": 0,
    })
logger.info("Fiqh documents retrieved", extra={
    "correlation_id": correlation_id_ctx.get(),
    "iteration": iteration,
    "doc_count": len(new_docs),
})
```

FIQH-03 — in `_filter_node`, inside `try` block, immediately after `filtered = filter_evidence(...)` (after current line 96):
```python
filtered = filter_evidence(state["query"], state["accumulated_docs"])
if len(filtered) == 0:
    logger.warning("Fiqh evidence filter removed all documents", extra={
        "correlation_id": correlation_id_ctx.get(),
        "iteration": state["iteration"],
        "doc_count": 0,
    })
logger.info("Fiqh evidence filtered", extra={
    "correlation_id": correlation_id_ctx.get(),
    "iteration": state["iteration"],
    "doc_count": len(filtered),
})
```

FIQH-04 — in `_route_after_assess`, inside the `if state["verdict"] == "SUFFICIENT" or state["iteration"] >= 3:` block, after the INFO log, guarded by `state["verdict"] != "SUFFICIENT"`, before `return "exit"`:
```python
if state["verdict"] == "SUFFICIENT" or state["iteration"] >= 3:
    logger.info("Fiqh FAIR-RAG exiting", extra={
        "correlation_id": correlation_id_ctx.get(),
        "iteration": state["iteration"],
        "verdict": state["verdict"],
        "doc_count": len(state["accumulated_docs"]),
    })
    if state["iteration"] >= 3 and state["verdict"] != "SUFFICIENT":
        logger.warning(
            "Fiqh FAIR-RAG exhausted max iterations with insufficient evidence",
            extra={
                "correlation_id": correlation_id_ctx.get(),
                "iteration": state["iteration"],
                "verdict": state["verdict"],
                "doc_count": len(state["accumulated_docs"]),
            },
        )
    return "exit"
```

---

## Shared Patterns

### `correlation_id_ctx.get()` access

**Source:** `agents/tools/retrieval_tools.py` line 10, `core/pipeline_langgraph.py` line 17, `agents/core/chat_agent.py` line 34

```python
from core.context import correlation_id as correlation_id_ctx
```

Call site:
```python
"correlation_id": correlation_id_ctx.get(),
```

**Apply to:** Every log call in `fiqh_graph.py` — INFO, WARNING, and ERROR paths alike (D-02).

**ContextVar propagation:** `fiqh_subgraph.invoke()` is called synchronously from `chat_agent.py` line 312. The ContextVar value set by `CorrelationIdMiddleware` propagates through the synchronous call stack without any additional wiring. `.get()` returns `""` in unit tests without the middleware — this is safe (empty string in Sentry is searchable and not harmful).

---

### Error handling structure

**Source:** `agents/tools/retrieval_tools.py` lines 58–69

```python
except Exception as e:
    logger.error("Retrieval error", exc_info=True, extra={
        "correlation_id": correlation_id_ctx.get(),
        "error": str(e),
    })
    # fallback return value follows — no re-raise
```

**Apply to:** All five `except` blocks in `fiqh_graph.py`. Each node already has a fallback value assignment after the error log — that behavior is unchanged. Never call `capture_exception()` (D-11).

---

## No Analog Found

None. All three patterns required for Phase 16 have direct analogs in the instrumented Phase 14–15 files.

---

## Metadata

**Analog search scope:** `agents/tools/`, `core/`, `api/`
**Files scanned:** 3 analog files (`agents/tools/retrieval_tools.py`, `core/pipeline_langgraph.py`, `api/chat.py`) + target file (`agents/fiqh/fiqh_graph.py`)
**Pattern extraction date:** 2026-04-28
