# Phase 15: Pipeline and Tools Instrumentation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-27
**Phase:** 15-pipeline-and-tools-instrumentation
**Areas discussed:** Log levels (chat_agent.py), Query snippet in pipeline logs, Tool result logging, SSE generator error handling

---

## Log Levels — chat_agent.py

### Node traversal level

| Option | Description | Selected |
|--------|-------------|----------|
| All traversal at DEBUG | Consistent with PIPE-01 intent — node iteration, routing steps, tool execution all DEBUG | ✓ |
| Routing decisions at INFO | Routing decisions (fiqh routing, non-Islamic early exit, max iterations) at INFO; pure iteration counters at DEBUG | |
| You decide | Claude picks appropriate levels per line | |

**User's choice:** All traversal at DEBUG
**Notes:** Keeps all node-traversal noise below Sentry Logs threshold (INFO). Consistent with PIPE-01 explicit policy.

### Exception paths level

| Option | Description | Selected |
|--------|-------------|----------|
| All exceptions at ERROR | Consistent with Phase 14 — any exception path uses logger.error(exc_info=True). Sentry captures automatically. | ✓ |
| Recoverable failures at WARNING | LLM rejection errors and early-exit fallbacks at WARNING; only propagated exceptions at ERROR | |
| You decide | Claude picks ERROR vs WARNING per exception path | |

**User's choice:** All exceptions at ERROR
**Notes:** Single consistent policy. Sentry event for every exception is acceptable.

### LLM response content snippet (~line 172)

| Option | Description | Selected |
|--------|-------------|----------|
| Drop it entirely | Content may include retrieved Islamic text; tool call names already logged | ✓ |
| Keep at DEBUG | Useful for debugging agent decision-making; content is truncated | |

**User's choice:** Drop entirely
**Notes:** No LLM output content in logs at any level.

---

## Query Snippet in Pipeline Logs

### Include or omit user_query

| Option | Description | Selected |
|--------|-------------|----------|
| Omit query from pipeline logs | Log session_id and correlation_id only — clean PII stance | ✓ |
| Include truncated query at DEBUG only | Keep query[:100] but only at DEBUG (never reaches Sentry Logs) | |
| Include with future hook note | Include now, flag before_send_log as future work | |

**User's choice:** Omit entirely
**Notes:** before_send strips query from Sentry error events but NOT from Sentry Logs stream. Consistent no-content-in-logs policy across all layers.

### Pipeline start/end log fields

| Option | Description | Selected |
|--------|-------------|----------|
| session_id + correlation_id only | Minimal traceable pair | |
| session_id + correlation_id + target_language | Adds target_language for translation debugging | ✓ |

**User's choice:** session_id + correlation_id + target_language
**Notes:** target_language is useful operational context (shows whether translation path was triggered) with no PII risk.

---

## Tool Result Logging in chat_agent.py

| Option | Description | Selected |
|--------|-------------|----------|
| Drop result payload, keep tool name at DEBUG | No raw result dict — tool name and doc_count only | ✓ |
| Keep truncated result at DEBUG | str(result_data)[:200] at DEBUG | |
| Log doc_count only | Extract and log doc_count as structured field | |

**User's choice:** Drop result payload, keep tool name at DEBUG
**Notes:** Consistent with dropping LLM content. Tool name from logger name already provides context.

### retrieval_tools.py error log query snippet

| Option | Description | Selected |
|--------|-------------|----------|
| Include truncated query in error logs only | extra={correlation_id, query: query[:80], error: str(e)} | |
| Omit query, log tool name + error only | extra={correlation_id, error: str(e)} | ✓ |
| Follow TOOL-01 literally | Include query snippet as specified in requirement | |

**User's choice:** Omit query — tool name + error only
**Notes:** Overrides TOOL-01 literal "query snippet" specification. Consistent no-query-in-logs stance applies even to error paths. Tool name comes from `logging.getLogger(__name__)`.

---

## SSE Generator Error Handling

### Main SSE exception handler

| Option | Description | Selected |
|--------|-------------|----------|
| logger.error(exc_info=True) only | Same pattern as Phase 14. No duplicate events. | ✓ |
| logger.error + capture_exception() | Belt-and-suspenders — creates duplicate Sentry events (anti-pattern) | |

**User's choice:** logger.error(exc_info=True) only
**Notes:** LoggingIntegration handles the Sentry capture. Existing SSE error event yield stays unchanged.

### Secondary Redis write failure handler (~line 389)

| Option | Description | Selected |
|--------|-------------|----------|
| logger.warning(exc_info=True) | Recoverable secondary failure — doesn't create Sentry event | ✓ |
| logger.error(exc_info=True) | Consistent level for all exceptions, but creates Sentry noise for secondary failures | |

**User's choice:** logger.warning(exc_info=True)
**Notes:** Secondary failure inside an already-logged error path. WARNING level doesn't trigger Sentry event creation (event_level=ERROR).

---

## Claude's Discretion

None — all areas had explicit user selections.

## Deferred Ideas

None — discussion stayed within phase scope.
