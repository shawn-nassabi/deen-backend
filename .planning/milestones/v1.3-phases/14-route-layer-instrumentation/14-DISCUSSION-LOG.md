# Phase 14: Route Layer Instrumentation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-26
**Phase:** 14-route-layer-instrumentation
**Areas discussed:** Streaming completion log, Sentry scope binding timing, Extra log fields

---

## Streaming Completion Log

| Option | Description | Selected |
|--------|-------------|----------|
| Outer handler (Recommended) | Log 'request accepted, returning stream' when the StreamingResponse is assembled. Simpler, keeps correlation_id in scope, signals handler setup completed successfully. | ✓ |
| Inside SSE generator | Log 'stream finished' at end of async generator. Captures actual end-of-stream; ContextVar still set (same async task). | |
| Both | Two logs: one in outer handler at setup, one inside generator at close. Most complete, slight duplication. | |

**User's choice:** Outer handler
**Notes:** Completion log is when the handler finishes setting up the stream, not when streaming ends.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Same fields for both (Recommended) | Both /chat/stream/agentic and /chat/agentic log the same fields at start and completion. | ✓ |
| Non-streaming logs response length | Non-streaming endpoint also logs response_length at completion. | |

**User's choice:** Same fields for both
**Notes:** Consistent pattern across streaming and non-streaming endpoints.

---

## Sentry Scope Binding Timing

| Option | Description | Selected |
|--------|-------------|----------|
| After JWT extraction (Recommended) | Call once with all available fields (correlation_id, endpoint, session_id, user_id). Aligns with Phase 13 D-07 intent. | ✓ |
| Early with corr_id only, then update | Call immediately with correlation_id + endpoint, then call again after user_id is available. | |
| You decide | Leave to planner/executor based on code structure. | |

**User's choice:** After JWT extraction
**Notes:** Accepted tradeoff — errors before JWT extraction won't have full Sentry scope.

---

| Option | Description | Selected |
|--------|-------------|----------|
| All four route files (Recommended) | bind_sentry_scope() in chat.py, reference.py, hikmah.py, primers.py. Every endpoint gets scope set. | ✓ |
| Chat only | Only chat.py gets scope binding. Simpler for low-traffic routes. | |

**User's choice:** All four route files
**Notes:** Consistent observability across all endpoints.

---

## Extra Log Fields

| Option | Description | Selected |
|--------|-------------|----------|
| Add user_id + query_length (Recommended) | user_id identifies requester (null for unauthenticated); query_length gives size context without leaking query text. | ✓ |
| Minimum only | Just correlation_id, session_id, endpoint — matches acceptance criteria exactly. | |
| user_id only | Add user_id; skip query_length. | |

**User's choice:** Add user_id + query_length
**Notes:** Both fields are safe for Sentry Logs — no PII.

---

| Option | Description | Selected |
|--------|-------------|----------|
| No extra fields at completion (Recommended) | Completion log mirrors start log fields. No latency_ms — timing derivable from Sentry/middleware. | ✓ |
| Add target_language | Log the language param at start for translation debugging. | |
| Add latency_ms | Compute and log elapsed time at completion. | |

**User's choice:** No extra fields at completion
**Notes:** Keeps completion log field set consistent with start log.

---

| Option | Description | Selected |
|--------|-------------|----------|
| correlation_id + existing domain fields (Recommended) | Add correlation_id to every extra={} in hikmah.py and primers.py. Keep existing domain fields (lesson_id, user_id) — don't restructure. | ✓ |
| Only correlation_id | Just inject correlation_id; don't touch domain field layout. | |

**User's choice:** correlation_id + existing domain fields
**Notes:** Preserve existing domain field structure; only inject correlation_id.

---

## Claude's Discretion

None — all areas were resolved with explicit user choices.

## Deferred Ideas

None — discussion stayed within phase scope.
