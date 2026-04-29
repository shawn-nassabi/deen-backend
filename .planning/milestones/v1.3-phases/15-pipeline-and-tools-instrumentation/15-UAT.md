---
status: complete
phase: 15-pipeline-and-tools-instrumentation
source: [15-01-SUMMARY.md, 15-02-SUMMARY.md]
started: 2026-04-27T00:00:00Z
updated: 2026-04-27T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Server boots after instrumentation changes
expected: Start the server (`uvicorn main:app --reload`). It comes up without import errors or startup exceptions, and log output uses the structured `[LEVEL] name - message key=value` format rather than old `[AGENTIC PIPELINE] ...` print-style prefixes.
result: pass

### 2. Pipeline INFO log on agentic chat request
expected: Send a request to `POST /chat/stream/agentic` (e.g., curl with a simple query). Server stdout shows `logger.info("Pipeline started")` with `correlation_id=...`, `session_id=...`, `target_language=...` in the extra fields. SSE response streams normally — no regression.
result: pass

### 3. Retrieval tool error logs structured payload
expected: Trigger a retrieval failure (e.g., temporarily set `PINECONE_API_KEY` to invalid, or use a session that hits a missing index). Server log shows `logger.error("Retrieval error", exc_info=True, ...)` with `correlation_id` and a sanitized `error` field. Pipeline still returns a response (tools fail soft) — no crash.
result: pass

### 4. Non-streaming /chat/agentic logs exceptions with context
expected: Hit `POST /chat/agentic` while in a state that forces an error in `agent.invoke()` (e.g., bad OPENAI_API_KEY in `.env`). Server log shows `logger.error("Pipeline error", exc_info=True, extra={"correlation_id": ..., "session_id": ...})` from the new try/except in `chat_pipeline_agentic`. Client receives HTTP 500 with `{"detail": "internal_error"}`.
result: pass
note: "Tested with invalid Anthropic key — exception was caught inside `_agent_node` and surfaced as `logger.error('Agent node error', exc_info=True, ...)` rather than escaping to the WR-03 `chat_pipeline_agentic` try/except. Both paths are structured-logged with correlation_id, so the observable behavior matches D-02. The WR-03 wrapper remains a safety net for exceptions that escape `agent.invoke()`."

### 5. No user query content in structured log fields
expected: Replay the chat request from test 2 with a memorable query phrase (e.g., "purple elephant in Mecca"). Grep server stdout (`grep -i "purple elephant"`) — the phrase does NOT appear in any structured `extra` field on any log line. Privacy guarantee D-05 holds.
result: pass

### 6. Sentry receives error event without duplicates
expected: With `SENTRY_ENABLED=true SENTRY_DSN=<valid>`, trigger an exception in the pipeline (e.g., the test 4 setup). Sentry dashboard shows exactly ONE issue/event for that exception — not two. Confirms LoggingIntegration is the sole capture path (D-02) and no `capture_exception()` is double-firing.
result: pass

## Summary

total: 6
passed: 6
issues: 0
pending: 0
skipped: 0

## Gaps

[none yet]
