# Requirements: v1.3 Sentry Deep Integration

**Milestone goal:** Instrument all main API endpoints with structured info/warning/error logging that flows to Sentry with correlation_id per request — production-only, opt-in via env var.

**Scope:** Pure observability pass — no API surface changes, no LangGraph topology changes, no new database tables.

---

## Active Requirements

### INFRA — Sentry Configuration & Infrastructure

- [x] **INFRA-01**: System sends zero data to Sentry when `SENTRY_ENABLED` is `false` or unset — local dev never triggers Sentry events
- [x] **INFRA-02**: `main.py` initializes Sentry only when both `SENTRY_ENABLED=true` AND `SENTRY_DSN` are set; `LoggingIntegration(level=INFO, event_level=ERROR, sentry_logs_level=INFO)` is explicitly configured in `sentry_sdk.init()`
- [x] **INFRA-03**: Every HTTP request carries a unique `correlation_id` UUID; all log events from that request include it — enabling full request-chain filtering in Sentry
- [x] **INFRA-04**: Sentry events for a request include `session_id`, `user_id` (when authenticated), and `endpoint` as searchable tags on the per-request isolation scope
- [x] **INFRA-05**: `send_default_pii=True` removed; a `before_send` hook redacts `user_query` and request body content from Sentry events (GDPR Article 9 compliance — Islamic religious content is special-category data)

### CHAT — Agentic Chat API (`api/chat.py`)

- [ ] **CHAT-01**: `/chat/stream/agentic` and `/chat/agentic` log request start and completion at INFO with `correlation_id`, `session_id`, and `endpoint` in structured `extra={}`
- [ ] **CHAT-02**: Config parse errors logged at WARNING; unhandled exceptions logged at ERROR and captured in Sentry — no duplicate events (pick `logger.error(exc_info=True)` OR `capture_exception()`, not both)
- [ ] **CHAT-03**: All `print()` calls in `api/chat.py` replaced with `logger.*`

### REF — References API (`api/reference.py`)

- [ ] **REF-01**: `/references` logs request start and completion at INFO; exceptions logged at ERROR with `correlation_id` context
- [ ] **REF-02**: HTTP 500 response body no longer exposes raw exception string (data-leak bug fixed — exception string was previously returned as `detail`)
- [ ] **REF-03**: All `print()` calls in `api/reference.py` replaced with `logger.*`

### HIK — Hikmah API (`api/hikmah.py`)

- [ ] **HIK-01**: All existing `logger.*` calls in `api/hikmah.py` include `correlation_id` in `extra={}`
- [ ] **HIK-02**: Remaining `print()` call (in `/hikmah/elaborate/stream` error path) replaced with `logger.*`

### PRIM — Primers API (`api/primers.py`)

- [ ] **PRIM-01**: All `logger.*` calls in `api/primers.py` converted from f-string interpolation to structured `extra={}` so fields like `lesson_id` and `user_id` are searchable in Sentry Logs

### PIPE — Core Pipeline (`core/pipeline_langgraph.py`)

- [ ] **PIPE-01**: All `print()` calls replaced with `logger.*`; LangGraph per-node traversal events logged at DEBUG (not INFO — avoids Sentry log quota overrun at scale)
- [ ] **PIPE-02**: Pipeline start/end and SSE generator exceptions captured correctly with no duplicate Sentry events; `correlation_id` included in all pipeline log calls

### TOOL — Agent Tools (`agents/tools/retrieval_tools.py`, `agents/core/chat_agent.py`)

- [ ] **TOOL-01**: All `print()` calls in `agents/tools/retrieval_tools.py` replaced with `logger.error()` including query snippet and exception context in `extra={}`
- [ ] **TOOL-02**: Any `print()` calls in `agents/core/chat_agent.py` replaced with `logger.*`

### FIQH — Fiqh Sub-graph (`agents/fiqh/fiqh_graph.py`)

- [ ] **FIQH-01**: All existing log calls converted from `%s` format strings to `extra={}` with `iteration`, `verdict`, and `doc_count` as top-level searchable fields in Sentry Logs
- [ ] **FIQH-02**: WARNING logged when zero documents are retrieved on any FAIR-RAG iteration
- [ ] **FIQH-03**: WARNING logged when the evidence filter removes all accumulated documents (fail-open path triggered)
- [ ] **FIQH-04**: WARNING logged when max iterations are reached with an INSUFFICIENT evidence verdict

---

## Future Requirements

*(Deferred to a later milestone)*

- Sentry Performance tracing — custom spans for retrieval, LLM generation, fiqh iterations
- `before_send_log` hook for fine-grained Sentry log quota throttling (stable at sentry-sdk >= 2.35.0; current pin is 2.27.0)
- LLM token counts in log context (input/output tokens per Claude call)
- `ExtraFormatter` ANSI colorization disabled for non-development environments to prevent potential level-field corruption in Sentry

---

## Out of Scope

- Frontend changes — backend observability only
- New API endpoints or LangGraph topology changes
- Sentry alerting rules / notification configuration (Sentry dashboard work, not code)
- Upgrading `sentry-sdk` beyond 2.27.0 — pin stays; `_experiments.enable_logs` remains in `_experiments` (top-level only valid at >= 2.35.0)
- Memory admin, account, or onboarding API instrumentation — low traffic, defer

---

## Traceability

| REQ-ID | Phase |
|--------|-------|
| INFRA-01 | Phase 13 |
| INFRA-02 | Phase 13 |
| INFRA-03 | Phase 13 |
| INFRA-04 | Phase 13 |
| INFRA-05 | Phase 13 |
| CHAT-01 | Phase 14 |
| CHAT-02 | Phase 14 |
| CHAT-03 | Phase 14 |
| REF-01 | Phase 14 |
| REF-02 | Phase 14 |
| REF-03 | Phase 14 |
| HIK-01 | Phase 14 |
| HIK-02 | Phase 14 |
| PRIM-01 | Phase 14 |
| PIPE-01 | Phase 15 |
| PIPE-02 | Phase 15 |
| TOOL-01 | Phase 15 |
| TOOL-02 | Phase 15 |
| FIQH-01 | Phase 16 |
| FIQH-02 | Phase 16 |
| FIQH-03 | Phase 16 |
| FIQH-04 | Phase 16 |
