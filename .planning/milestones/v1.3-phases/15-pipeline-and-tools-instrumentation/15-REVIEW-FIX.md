---
phase: 15-pipeline-and-tools-instrumentation
fixed_at: 2026-04-27T00:00:00Z
review_path: .planning/phases/15-pipeline-and-tools-instrumentation/15-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 15: Code Review Fix Report

**Fixed at:** 2026-04-27
**Source review:** `.planning/phases/15-pipeline-and-tools-instrumentation/15-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (1 Critical, 3 Warning; Info skipped per fix_scope=critical_warning)
- Fixed: 4
- Skipped: 0

## Fixed Issues

### CR-01: `EARLY_EXIT_FIQH` imported but never used — dead import masks silent behavior change

**Files modified:** `agents/core/chat_agent.py`
**Commit:** `a30f8b5`
**Applied fix:** Removed the unused `EARLY_EXIT_FIQH` symbol from the `from agents.prompts.agent_prompts import (...)` block. The import now only brings in `AGENT_SYSTEM_PROMPT`, which is the only symbol actually referenced in the file. The fiqh early-exit path continues to use a dynamically generated LLM rejection message in `_check_early_exit_node`, unchanged.

### WR-01: `import logging` placed after local imports in all three files — violates project import-ordering convention

**Files modified:** `agents/core/chat_agent.py`, `core/pipeline_langgraph.py`, `agents/tools/retrieval_tools.py`
**Commit:** `5acdccb`
**Applied fix:** Reorganized imports in all three files to follow stdlib → third-party → local order per CLAUDE.md.
- `core/pipeline_langgraph.py`: moved `import logging` into the stdlib block next to `import json` and `from typing`; `from core.context import correlation_id ...` left in the local block.
- `agents/core/chat_agent.py`: moved `import logging` into the stdlib block; `from core.context` placed after `from core.config import ANTHROPIC_API_KEY` so all `core.*` locals stay grouped.
- `agents/tools/retrieval_tools.py`: rewrote the import block — `import logging` and `from typing import Dict, List` now lead the stdlib group, `from langchain_core.tools` is the sole third-party import, and `from core.context` plus `from modules.retrieval` form the local group.

### WR-02: `exception str(e)` in `extra={"error": str(e)}` may transiently carry query content — latent D-05 violation

**Files modified:** `agents/tools/retrieval_tools.py`, `agents/core/chat_agent.py`
**Commit:** `66c02f3`
**Applied fix:** At the six log sites cited in the review (4 in `retrieval_tools.py`, 2 in `chat_agent.py`), replaced `"error": str(e)` (or `"error": str(exc)`) inside the `extra={...}` dict with `"error": f"{type(e).__name__}: {str(e)[:120]}"`. The 120-character cap prevents Pinecone/OpenAI exception messages from echoing user query content into structured log fields, while the prefixed type name preserves enough diagnostic value for triage. Full traceback detail remains available via `exc_info=True`. Other `str(exc)` usages in the same files (e.g. inside `state["errors"]` lists or returned tool dicts) were intentionally left unchanged — they were not flagged in the review and are not log fields.

### WR-03: `chat_pipeline_agentic` (non-streaming) has no exception handling — unhandled exceptions propagate to caller without logging

**Files modified:** `core/pipeline_langgraph.py`
**Commit:** `089caeb`
**Applied fix:** Wrapped the `agent.invoke(...)` call at the previously cited line ~435 with `try`/`except Exception` that calls `logger.error("Pipeline error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "session_id": session_id})` before re-raising. Mirrors the pattern used in the streaming variant `chat_pipeline_streaming_agentic` so that errors carry the same correlation_id/session_id context to logs before propagating to the global FastAPI middleware.

---

_Fixed: 2026-04-27_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
