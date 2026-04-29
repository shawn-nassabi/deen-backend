---
phase: 15-pipeline-and-tools-instrumentation
reviewed: 2026-04-27T00:00:00Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - core/pipeline_langgraph.py
  - agents/tools/retrieval_tools.py
  - agents/core/chat_agent.py
findings:
  critical: 1
  warning: 3
  info: 1
  total: 5
status: issues_found
---

# Phase 15: Code Review Report

**Reviewed:** 2026-04-27
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

Phase 15 replaced all `print()` calls with structured `logger.*` calls across three files. The instrumentation is largely correct — no `capture_exception()` calls, no `user_query`/`working_query` in `extra={}` dicts, no LLM response content in logs, no query parameter in retrieval error logs, and `exc_info=True` is consistently used on error-level calls. However, one dead import left over in `chat_agent.py` is masking a pre-existing unused symbol, there are three import-ordering violations introduced by this phase, and a latent PII risk path exists where exception strings can transiently carry query content into structured log fields.

---

## Critical Issues

### CR-01: `EARLY_EXIT_FIQH` imported but never used — dead import masks silent behavior change

**File:** `agents/core/chat_agent.py:20`
**Issue:** `EARLY_EXIT_FIQH` is imported from `agents.prompts.agent_prompts` but is never referenced anywhere in the file body. The symbol appears exactly once — the import line itself. This is a dead import introduced alongside the logging changes. The fiqh early-exit path (`_route_after_fiqh_check` returning `"exit"`) routes to `_check_early_exit_node`, which uses a *dynamically generated LLM rejection message* for `UNETHICAL` queries — not `EARLY_EXIT_FIQH`. The import implies `EARLY_EXIT_FIQH` was intended to be used (e.g., as the `early_exit_message` for the fiqh path), but it silently is not. If this constant was meant to guard the fiqh early-exit message, its absence is a behavioral gap; if it was deliberately removed, the import should be deleted.

**Fix:** Either delete the unused import:
```python
# Remove line 20:
    EARLY_EXIT_FIQH,
```
Or, if `EARLY_EXIT_FIQH` was meant to be the `early_exit_message` emitted when routing `"exit"` for an `UNETHICAL` fiqh query, wire it in `_check_early_exit_node` and confirm the intent with the original spec. The unused import as-is creates a silent discrepancy between the declared intent and the running behavior.

---

## Warnings

### WR-01: `import logging` placed after local imports in all three files — violates project import-ordering convention

**File:** `core/pipeline_langgraph.py:16`, `agents/core/chat_agent.py:33`, `agents/tools/retrieval_tools.py:9`
**Issue:** In all three files, the new `import logging` (stdlib) was appended after third-party and/or local imports rather than being inserted into the stdlib block at the top. Per CLAUDE.md: "Standard library imports first, then third-party, then local — this order is followed in well-maintained files."

- `core/pipeline_langgraph.py`: `import logging` at line 16, after local imports at lines 13–15.
- `agents/core/chat_agent.py`: `import logging` at line 33, after all third-party (lines 11–15) and local (lines 17–32) imports.
- `agents/tools/retrieval_tools.py`: `import logging` at line 9, after third-party `langchain_core` at line 6 and local `modules.retrieval` at line 7; `from typing import Dict, List` (also stdlib) is similarly misplaced at line 8.

**Fix:** Move `import logging` and `from core.context import correlation_id as correlation_id_ctx` to immediately after the other stdlib imports (`import json`, `from typing import ...`) in each file:

```python
# Correct order (example for pipeline_langgraph.py):
import json
import logging
from typing import AsyncGenerator, Optional

from fastapi.responses import StreamingResponse

from agents.config.agent_config import AgentConfig, DEFAULT_AGENT_CONFIG
from agents.core.chat_agent import ChatAgent
from core import utils
from core.context import correlation_id as correlation_id_ctx
```

---

### WR-02: `exception str(e)` in `extra={"error": str(e)}` may transiently carry query content — latent D-05 violation

**File:** `agents/tools/retrieval_tools.py:61,123,184,247` and `agents/core/chat_agent.py:120,177`
**Issue:** Several `logger.error(...)` calls place `str(e)` in `extra={"error": str(e)}`. This is correct per the phase spec. However, certain upstream exception messages can embed the offending input. For example:

- Pinecone SDK errors on malformed namespace or vector dimensions sometimes include the query vector or raw text in their message.
- OpenAI errors (`openai.BadRequestError`) routinely include the rejected content in the error body (e.g., `"This model's maximum context length is N tokens... your messages resulted in M tokens: <content snippet>..."`).
- `classify_fiqh_query()` and `enhance_query_tool` both call the LLM with the user query — if they raise, `str(exc)` may contain a snippet of the prompt.

When this happens, D-05 ("no user query content in log fields") is violated at runtime even though the code does not put `user_query` directly into `extra={}`. The risk is real on the LLM and vector-search code paths.

**Fix:** Sanitize the error string before logging, or limit it to the exception type and a fixed-length prefix:

```python
# In each except block, instead of:
"error": str(e),

# Use:
"error": f"{type(e).__name__}: {str(e)[:120]}",
```

A 120-character cap prevents large payload echoes while still identifying the error class. Alternatively, log only `type(e).__name__` and rely on `exc_info=True` (which writes the full traceback to the log file rather than the structured field) for full detail.

---

### WR-03: `chat_pipeline_agentic` (non-streaming) has no exception handling — unhandled exceptions propagate to caller without logging

**File:** `core/pipeline_langgraph.py:435`
**Issue:** The streaming variant `chat_pipeline_streaming_agentic` has a comprehensive `try/except` block (lines 107–403) with `logger.error("Pipeline error", exc_info=True, ...)`. The non-streaming variant `chat_pipeline_agentic` (line 408) calls `agent.invoke(...)` at line 435 with no surrounding `try/except`. Any exception from the agent — `ChatAnthropic` auth failure, Pinecone timeout, LangGraph state error — propagates unlogged directly to the API route handler. The global middleware at `main.py:95` will catch it there, but without the `correlation_id` and `session_id` context that this function has access to, making the error harder to trace.

**Fix:** Wrap the `agent.invoke()` call with the same error pattern used in the streaming path:

```python
try:
    final_state = agent.invoke(
        user_query=user_query,
        session_id=session_id,
        target_language=target_language,
        config=agent_config.to_dict()
    )
except Exception as e:
    logger.error("Pipeline error", exc_info=True, extra={
        "correlation_id": correlation_id_ctx.get(),
        "session_id": session_id,
    })
    raise
```

---

## Info

### IN-01: `memory_exc` caught but referenced only via `exc_info=True` — variable is bound but unused

**File:** `core/pipeline_langgraph.py:397`
**Issue:** `except Exception as memory_exc:` binds the exception to `memory_exc`, but the variable is never referenced in the handler body. The `logger.warning(...)` call at line 398 uses `exc_info=True`, which correctly captures the current exception via Python's `sys.exc_info()` — so the log output is correct. However, the named variable `memory_exc` is dead weight and will trigger a linter warning (F841 in flake8/ruff).

**Fix:** Either rename to the conventional throwaway name or drop it:

```python
# Option A: use underscore convention
except Exception:
    logger.warning("Failed to append runtime history after error", exc_info=True, extra={
        "correlation_id": correlation_id_ctx.get(),
        "session_id": session_id,
    })
```

---

_Reviewed: 2026-04-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
