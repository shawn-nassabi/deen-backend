# Feature Landscape: Structured Sentry Logging (v1.3)

**Domain:** Observability instrumentation for a FastAPI + LangGraph + Pinecone backend
**Researched:** 2026-04-26
**Scope:** INFO/WARNING/ERROR log event catalogue across all main API surfaces, with structured field recommendations for Sentry filtering

---

## Current Logging State (Baseline Audit)

| File | Current State | Gap |
|------|--------------|-----|
| `api/chat.py` | `print()` only — no `logger` import, no structured fields | Full coverage needed |
| `core/pipeline_langgraph.py` | `print()` only throughout | Full coverage needed |
| `agents/core/chat_agent.py` | `print()` only throughout | Full coverage needed |
| `agents/tools/retrieval_tools.py` | `print()` only throughout | Full coverage needed |
| `api/reference.py` | `print()` only — also leaks internal error string into HTTP 500 response body | Full coverage needed + fix error leak |
| `api/hikmah.py` | `logger` imported, partial structured `extra={}` — INFO on elaboration request, ERROR on quiz CRUD ops | Standardize fields, add request-end INFO, add WARNING for not-found paths, add `correlation_id` |
| `api/primers.py` | `logger` imported, f-string log messages (not structured `extra={}`) | Convert to structured `extra={}` dict pattern, add `correlation_id`, add `duration_ms` |
| `agents/fiqh/fiqh_graph.py` | `logger` imported with good node-level INFO/ERROR — best-instrumented file | Add structured `extra={}` fields; current logs embed context in `%s` format strings which Sentry cannot filter on |
| `main.py` | `sentry_sdk.capture_exception(e)` in `catch_exceptions_mw` — working | Add `correlation_id` binding to Sentry scope |
| `core/logging_config.py` | `ExtraFormatter` supports `extra={}` dict pattern — infrastructure ready | No gaps; ensure `correlation_id` is not in the reserved-key exclusion set |

---

## Table Stakes: Required Log Events

These events MUST be present for Sentry to be actionable in production. Missing any of them makes incident triage materially harder.

### (a) Streaming Agentic Chat — `POST /chat/stream/agentic`

**Files:** `api/chat.py`, `core/pipeline_langgraph.py`, `agents/core/chat_agent.py`

#### INFO events

| Event | Where | Fields |
|-------|-------|--------|
| Request received | `api/chat.py` handler entry | `correlation_id`, `session_id`, `user_id`, `endpoint`, `query_snippet` (first 120 chars), `has_custom_config` |
| Fiqh classification result | `agents/core/chat_agent.py` `_fiqh_classification_node` | `correlation_id`, `session_id`, `fiqh_category`, `is_fiqh`, `duration_ms` |
| Agent iteration started | `agents/core/chat_agent.py` `_agent_node` | `correlation_id`, `session_id`, `iteration` |
| Tool called | `agents/core/chat_agent.py` `_tool_node` per tool dispatch | `correlation_id`, `session_id`, `tool_name`, `query_used` |
| Retrieval completed | `agents/core/chat_agent.py` `_record_retrieval_result` | `correlation_id`, `session_id`, `source`, `doc_count`, `query_used`, `duration_ms` |
| Fiqh sub-graph invoked | `agents/core/chat_agent.py` `_call_fiqh_subgraph_node` | `correlation_id`, `session_id`, `fiqh_category` |
| Fiqh sub-graph complete | `agents/core/chat_agent.py` `_call_fiqh_subgraph_node` after invoke | `correlation_id`, `session_id`, `doc_count`, `sea_verdict`, `iteration_count`, `duration_ms` |
| Response stream started | `core/pipeline_langgraph.py` before first `response_chunk` yield | `correlation_id`, `session_id`, `path` (`fiqh`/`hadith`/`early_exit`), `doc_count` |
| Request complete | `core/pipeline_langgraph.py` before `done` SSE event | `correlation_id`, `session_id`, `total_duration_ms`, `path`, `doc_count`, `history_written` |

#### WARNING events

| Event | Where | Trigger |
|-------|-------|---------|
| Non-Islamic early exit | `core/pipeline_langgraph.py` `early_exit_message` branch | `correlation_id`, `session_id`, `reason` (`non_islamic`), `query_snippet` |
| UNETHICAL query routed to exit | `agents/core/chat_agent.py` `_route_after_fiqh_check` | `correlation_id`, `session_id`, `fiqh_category` |
| Retrieval returned zero docs | `agents/core/chat_agent.py` `_record_retrieval_result` when `count == 0` | `correlation_id`, `session_id`, `source`, `query_used` |
| Agent hit max iterations | `agents/core/chat_agent.py` `_agent_node` max-iterations branch | `correlation_id`, `session_id`, `iteration`, `max_iterations` |
| Config parse failure (fallback to default) | `api/chat.py` `AgentConfig.from_dict` except branch | `correlation_id`, `session_id`, `error` |
| Fiqh answer emitted with no docs (fallback message used) | `core/pipeline_langgraph.py` `not fiqh_docs` branch | `correlation_id`, `session_id`, `sea_verdict` |
| INSUFFICIENT evidence warning appended to answer | `core/pipeline_langgraph.py` `not is_sufficient` branch | `correlation_id`, `session_id`, `iteration_count` |
| Fiqh SSE trail was empty (pre-canned stages used as fallback) | `core/pipeline_langgraph.py` `not fiqh_trail_emitted` branch | `correlation_id`, `session_id` |
| Redis history write failed after error recovery | `core/pipeline_langgraph.py` history exception handler | `correlation_id`, `session_id`, `error` |

#### ERROR events

| Event | Where | Trigger |
|-------|-------|---------|
| Pipeline unhandled exception | `core/pipeline_langgraph.py` outer except block | `correlation_id`, `session_id`, `error`, `partial_text_length` — also call `sentry_sdk.capture_exception` |
| Agent node LLM call failed | `agents/core/chat_agent.py` `_agent_node` except block | `correlation_id`, `session_id`, `iteration`, `error` |
| Fiqh sub-graph invocation failed | `agents/core/chat_agent.py` `_call_fiqh_subgraph_node` except block | `correlation_id`, `session_id`, `fiqh_category`, `error` |
| Response generation LLM failed | `agents/core/chat_agent.py` `_generate_response_node` except block | `correlation_id`, `session_id`, `doc_count`, `error` |
| Fiqh response generation LLM failed | `agents/core/chat_agent.py` `_generate_fiqh_response_node` except block | `correlation_id`, `session_id`, `doc_count`, `error` |
| Route handler unhandled exception | `api/chat.py` outer except blocks | `correlation_id`, `session_id`, `endpoint`, `error` |

---

### (b) Reference Lookup — `POST /references`

**File:** `api/reference.py`

**Current state:** Single `print(str(e))` only. Additionally, the exception string is placed in the HTTP 500 response body via `detail=f"Internal Server Error: {str(e)}"` — this is a data-leak bug that must be fixed as part of this work.

#### INFO events

| Event | Where | Fields |
|-------|-------|--------|
| Request received | Handler entry | `correlation_id`, `endpoint`, `sect`, `limit`, `query_snippet` |
| References retrieved | After `pipeline.references_pipeline` returns | `correlation_id`, `endpoint`, `sect`, `doc_count`, `duration_ms` |

#### WARNING events

| Event | Where | Trigger |
|-------|-------|---------|
| Zero references returned | After call returns empty list | `correlation_id`, `endpoint`, `sect`, `query_snippet` |

#### ERROR events

| Event | Where | Trigger |
|-------|-------|---------|
| Pipeline exception | Except block | `correlation_id`, `endpoint`, `sect`, `error` — replace `print(str(e))`, fix `detail` to use generic message not `str(e)` |

---

### (c) Hikmah Elaboration — `POST /hikmah/elaborate/stream`

**File:** `api/hikmah.py`

**Current state:** INFO on request entry is present but uses ad-hoc field names. ERROR on CRUD ops is present. Gaps: no request-end INFO, no `duration_ms`, no `correlation_id` on any record, CRUD errors do not carry `correlation_id`.

#### INFO events

| Event | Where | Fields |
|-------|-------|--------|
| Elaboration request received | Handler entry (already exists) | Add `correlation_id`, `endpoint` to existing `extra={}` block; existing fields (`user_id`, `selected_text_len`, `lesson_name`, etc.) are correct |
| Elaboration stream returned | After pipeline call returns (currently missing) | `correlation_id`, `user_id`, `lesson_name`, `duration_ms` |

#### WARNING events

| Event | Where | Trigger |
|-------|-------|---------|
| Selected text too short / empty | Before pipeline call, if `len(selected_text or "") < 5` | `correlation_id`, `user_id`, `selected_text_len` |

#### ERROR events

| Event | Where | Trigger |
|-------|-------|---------|
| Elaboration pipeline exception | Except block — replace `print("UNHANDLED ERROR")` | `correlation_id`, `user_id`, `lesson_name`, `error` |
| Quiz CRUD errors | Already logged to `logger.error` (all 6 quiz routes) | Add `correlation_id` to all existing `extra={}` blocks |

---

### (d) Primers — `GET /primers/{lesson_id}/baseline`, `POST /primers/personalized`, `POST /primers/personalized/stream`

**File:** `api/primers.py`

**Current state:** `logger` imported and used, but messages use f-string interpolation (`f"Fetching baseline primer | lesson_id={lesson_id}"`). Sentry cannot filter or query on f-string-embedded values — they are opaque log message strings, not structured attributes. The pattern must be converted to `extra={}`.

#### INFO events

| Event | Where | Fields (convert from f-string to `extra={}`) |
|-------|-------|------|
| Baseline primer fetch started | Handler entry | `correlation_id`, `lesson_id` |
| Baseline primer returned successfully | After return (already present as INFO) | `correlation_id`, `lesson_id` |
| Personalized primer generation started | Handler entry (already present) | `correlation_id`, `user_id`, `lesson_id`, `force_refresh`, `filter_mode` |
| Personalized primer returned | After result (already present) | `correlation_id`, `user_id`, `lesson_id`, `from_cache`, `personalized_available`, `duration_ms` |
| Streaming primer started | `event_generator()` entry | `correlation_id`, `user_id`, `lesson_id` |
| Streaming primer completed | After generator loop | `correlation_id`, `user_id`, `lesson_id`, `duration_ms` |

#### WARNING events

| Event | Where | Trigger |
|-------|-------|---------|
| Lesson not found | Already logged as WARNING in baseline and personalized handlers | Add `correlation_id` to both; change from f-string to `extra={}` |
| Personalized primer unavailable (empty fallback returned as 200) | When `personalized_available=False` in returned result | `correlation_id`, `user_id`, `lesson_id` |
| Stream generator service emitted error event | When `event_type == "error"` in streaming loop | `correlation_id`, `user_id`, `lesson_id` |

#### ERROR events

| Event | Where | Trigger |
|-------|-------|---------|
| Baseline primer exception | Except block (already logged as ERROR) | Add `correlation_id`; convert from f-string to `extra={}` |
| Personalized primer exception | Except block (already logged as ERROR) | Add `correlation_id`; note this returns a fallback 200 not a 500 — Sentry still needs it captured via `sentry_sdk.capture_exception` or logger ERROR |
| Streaming primer exception | Inner and outer except blocks (already logged) | Add `correlation_id`; convert from f-string |

---

### (e) Fiqh Pipeline Stages (FAIR-RAG sub-graph)

**File:** `agents/fiqh/fiqh_graph.py`

**Current state:** Best-instrumented file in the codebase. Already uses `logger.info` and `logger.error` with correct severity levels. Gaps: all context is embedded in `%s` format-string arguments (`logger.info("[FIQH_GRAPH] Retrieved %d docs for query: %s", len(new_docs), current_query[:60])`). Sentry parses these as opaque message strings, not filterable attributes.

#### INFO events (already emitted — add structured `extra={}` fields)

| Event | Current log | Add to `extra={}` |
|-------|------------|-------------------|
| Decompose complete | `"Decomposed into %d sub-queries"` | `correlation_id`, `session_id`, `sub_query_count`, `iteration` |
| Retrieve complete | `"Retrieved %d docs for query: %s"` | `correlation_id`, `session_id`, `doc_count`, `query_snippet`, `iteration`, `duration_ms` |
| Filter complete | `"Filtered: %d -> %d docs"` | `correlation_id`, `session_id`, `pre_filter_count`, `post_filter_count`, `iteration` |
| SEA assessment complete | `"SEA verdict: %s (iteration %d)"` | `correlation_id`, `session_id`, `sea_verdict`, `iteration`, `confirmed_fact_count`, `gap_count` |
| Refine complete | `"Refined into %d queries"` | `correlation_id`, `session_id`, `refinement_count`, `iteration` |
| Exit routing decision | `"Exiting after iteration %d (verdict=%s)"` | `correlation_id`, `session_id`, `iteration`, `sea_verdict`, `exit_reason` (`sufficient` or `max_iterations`) |

#### WARNING events (new — not currently emitted)

| Event | Trigger | Fields |
|-------|---------|--------|
| Retrieved zero docs on iteration N | `len(new_docs) == 0` in `_retrieve_node` | `correlation_id`, `session_id`, `iteration`, `query_snippet` |
| Filter removed all docs (fail-open triggered) | `len(filtered) == 0` in `_filter_node` except path | `correlation_id`, `session_id`, `iteration`, `pre_filter_count` |
| Max iterations reached with INSUFFICIENT verdict | `_route_after_assess` exits because `iteration >= 3` and `verdict != "SUFFICIENT"` | `correlation_id`, `session_id`, `final_verdict`, `total_doc_count` |

#### ERROR events (already emitted — add structured `extra={}` fields)

| Event | Current log | Add to `extra={}` |
|-------|------------|-------------------|
| Decompose error | `"decompose_node error: %s"` | `correlation_id`, `session_id`, `error`, `iteration` |
| Retrieve error | `"retrieve_node error: %s"` | `correlation_id`, `session_id`, `error`, `iteration`, `query_snippet` |
| Filter error | `"filter_node error: %s"` | `correlation_id`, `session_id`, `error`, `iteration` |
| Assess error | `"assess_node error: %s"` | `correlation_id`, `session_id`, `error`, `iteration` |
| Refine error | `"refine_node error: %s"` | `correlation_id`, `session_id`, `error`, `iteration` |

---

## Recommended Structured Fields (Universal Set)

Every log record should carry these fields in the `extra={}` dict. The correlation_id middleware generates a UUID once per request and stores it on a Python `ContextVar`; all downstream callees read from the context var.

### Mandatory on every record

| Field | Type | Source |
|-------|------|--------|
| `correlation_id` | `str` (UUID4) | Middleware ContextVar — generated once per request |
| `endpoint` | `str` | Middleware or route handler (e.g. `/chat/stream/agentic`) |

### Per-context (add when in scope)

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| `session_id` | `str` | Request body | Carry from route handler into pipeline |
| `user_id` | `str` or `None` | JWT `sub` claim | `None` for unauthenticated; never log full JWT |
| `query_snippet` | `str` | `user_query[:120]` | Truncate at 120 chars — sufficient for triage |
| `duration_ms` | `int` | `time.monotonic()` delta | Measure at each stage boundary |
| `doc_count` | `int` | Retrieval result length | At the point of the log call |
| `iteration` | `int` | LangGraph state field | Fiqh sub-graph iteration number |
| `fiqh_category` | `str` | Classifier result | One of `VALID_OBVIOUS`/`VALID_SMALL`/`VALID_LARGE`/`VALID_REASONER`/`OUT_OF_SCOPE_FIQH`/`UNETHICAL`/`""` |
| `sea_verdict` | `str` | SEA result | `SUFFICIENT` or `INSUFFICIENT` |
| `source` | `str` | Tool result | `shia`, `sunni`, `quran_tafsir`, `fiqh` |
| `path` | `str` | Pipeline branch taken | `fiqh`, `hadith`, `early_exit` |
| `error` | `str` | `str(e)` | WARNING/ERROR records only |

### Sentry Scope Bindings (set in correlation middleware)

Set these via `sentry_sdk.configure_scope` or `sentry_sdk.set_tag` so that every Sentry event — including automatically captured exceptions from `catch_exceptions_mw` — carries them:

| Sentry field | Value |
|-------------|-------|
| `sentry_sdk.set_user({"id": user_id})` | Authenticated user ID, or omit if unauthenticated |
| `sentry_sdk.set_tag("correlation_id", ...)` | UUID per request |
| `sentry_sdk.set_tag("endpoint", ...)` | Request path |
| `sentry_sdk.set_tag("env", ...)` | `os.getenv("ENV")` |

Session_id cannot be set in the middleware because it lives in the request body, not the URL. Set it in the route handler after body parsing via `sentry_sdk.set_tag("session_id", session_id)`.

---

## Differentiators (Nice-to-Have, Not Blocking)

| Feature | Value | Complexity |
|---------|-------|------------|
| `sub_query_count` on decompose log | Reveals whether decomposer generates 1 vs 4 sub-queries — useful for prompt regression detection | Low — already computed |
| `confirmed_fact_count` and `gap_count` on SEA log | Tracks quality of evidence assessment; detects model regressions | Low — values on `SEAResult` |
| `history_written` flag on pipeline-complete INFO | Confirms Redis persistence succeeded per turn | Low |
| `is_fiqh_path` boolean on pipeline-start INFO | Enables Sentry dashboard split by query type | Low |
| `pre_filter_count` vs `post_filter_count` on filter log | Tracks evidence reduction ratio | Low |
| `total_duration_ms` on route-handler completion | End-to-end latency in Sentry Performance | Medium — timing wrapper |
| LLM token counts on generation logs | Cost attribution and prompt size drift detection | Medium — requires `response.usage` access |

---

## Anti-Features: What NOT to Log

| Anti-Feature | Why Avoid |
|-------------|-----------|
| Full `user_query` text in log records | PII risk — use `query_snippet` (first 120 chars) only |
| Full retrieved document text | Payload too large for Sentry; use `doc_count` and metadata only |
| Full `assistant_text` in logs | Response content is verbose, adds no triage value |
| JWT token strings | Security breach — never log tokens or credential values |
| Error string in HTTP 500 response body | Already present in `api/reference.py` — must be removed; leaks internals to clients |
| `logger.debug()` in production hot paths | Retrieval and generation are called per request — debug-level there creates log volume without actionable signal |
| One log call per SSE `response_chunk` token | `response_chunk` events fire 50-200 times per response — log only at start and end of generation, never per token |

---

## Feature Dependencies

```
correlation_id middleware (must exist first)
    -> All structured log records carry correlation_id via ContextVar
    -> Sentry scope binding (set_tag in middleware)
        -> Sentry event filtering by correlation_id in Issues and Logs views

replace print() with logger.* (prerequisite for Sentry log capture)
    -> api/chat.py                          (no logger today)
    -> core/pipeline_langgraph.py           (no logger today)
    -> agents/core/chat_agent.py            (no logger today)
    -> agents/tools/retrieval_tools.py      (no logger today)
    -> api/reference.py                     (no logger today)

convert extra={} structured fields (prerequisite for Sentry attribute filtering)
    -> api/primers.py           (convert f-strings to extra={})
    -> agents/fiqh/fiqh_graph.py  (add extra={} to existing logger.* calls)
    -> api/hikmah.py            (add correlation_id to existing extra={} blocks)
```

---

## MVP Recommendation

Prioritize in this order:

1. **Correlation ID middleware** — without it, no log records can be traced across a single request in Sentry. All other work depends on this.
2. **Replace all `print()` in `api/chat.py`, `core/pipeline_langgraph.py`, `agents/core/chat_agent.py`, `agents/tools/retrieval_tools.py`, `api/reference.py`** — these files produce zero Sentry log events today; highest single-step observability impact.
3. **Table-stakes INFO/WARNING/ERROR on `POST /chat/stream/agentic`** — primary production endpoint; cover fully before other APIs.
4. **Fix `api/reference.py` error-string leak** — `detail=f"Internal Server Error: {str(e)}"` exposes internal error details to API consumers; replace with generic message.
5. **Convert `api/primers.py` f-strings to `extra={}`** — quick refactor; enables Sentry filtering on primer logs.
6. **Add structured `extra={}` fields to `agents/fiqh/fiqh_graph.py`** — logger calls are already correct level; this is a field-addition pass only.
7. **Standardize `api/hikmah.py`** — already partially done; add `correlation_id` and `duration_ms` to existing records.

Defer until after MVP: LLM token count logging, sub-query count, full end-to-end latency middleware, Sentry Performance integration.
