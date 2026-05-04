# Roadmap: Deen Backend — Fiqh Agentic RAG

## Milestones

- ✅ **v1.0 Fiqh Agentic RAG MVP** — Phases 1-4 (shipped 2026-03-25)
- ✅ **v1.1 Supabase Migration** — Phases 5-7 (shipped 2026-04-07)
- ✅ **v1.2 Claude Migration** — Phases 8-12 (shipped 2026-04-10)
- ✅ **v1.3 Sentry Deep Integration** — Phases 13-16 (shipped 2026-04-28)
- 🔄 **v1.4 LLM Input Caching** — Phases 17-19 (in progress)

## Phases

<details>
<summary>✅ v1.0 Fiqh Agentic RAG MVP (Phases 1-4) — SHIPPED 2026-03-25</summary>

- [x] Phase 1: Data Foundation (3/3 plans) — completed 2026-03-24
- [x] Phase 2: Routing and Retrieval (3/3 plans) — completed 2026-03-25
- [x] Phase 3: FAIR-RAG Core Modules (3/3 plans) — completed 2026-03-25
- [x] Phase 4: Assembly and Integration (3/3 plans) — completed 2026-03-25

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

<details>
<summary>✅ v1.1 Supabase Migration (Phases 5-7) — SHIPPED 2026-04-07</summary>

- [x] Phase 5: Database Migration (2/2 plans) — completed 2026-04-06
- [x] Phase 6: Auth Migration (3/3 plans) — completed 2026-04-07
- [x] Phase 7: Cleanup (1/1 plan) — completed 2026-04-07

Full details: `.planning/milestones/v1.1-ROADMAP.md`

</details>

<details>
<summary>✅ v1.2 Claude Migration (Phases 8-12) — SHIPPED 2026-04-10</summary>

- [x] Phase 8: Config + Dependencies (2/2 plans) — completed 2026-04-09
- [x] Phase 9: LLM Swap (2/2 plans) — completed 2026-04-10
- [x] Phase 10: Embedding Migration (2/2 plans) — completed 2026-04-10
- [x] Phase 11: Dead Code Cleanup (2/2 plans) — completed 2026-04-10
- [x] Phase 12: Docs & Reference Cleanup (1/1 plan) — completed 2026-04-10

Full details: `.planning/milestones/v1.2-ROADMAP.md`

</details>

<details>
<summary>✅ v1.3 Sentry Deep Integration (Phases 13-16) — SHIPPED 2026-04-28</summary>

- [x] **Phase 13: Sentry Infrastructure** - correlation_id middleware, SENTRY_ENABLED gate, PII scrubber, LoggingIntegration (2/2 plans) — completed 2026-04-26
- [x] **Phase 14: Route Layer Instrumentation** - structured logging for chat, reference, hikmah, and primers APIs (3/3 plans) — completed 2026-04-26
- [x] **Phase 15: Pipeline and Tools Instrumentation** - structured logging for core pipeline and agent tools (2/2 plans) — completed 2026-04-28
- [x] **Phase 16: Fiqh Sub-graph Instrumentation** - structured warnings and searchable fields in fiqh FAIR-RAG loop (1/1 plans) — completed 2026-04-28

Full details: `.planning/milestones/v1.3-ROADMAP.md`

</details>

### v1.4 LLM Input Caching (Phases 17-19)

- [x] **Phase 17: ChatAgent Caching Foundation** - cache_control on tool definitions and system prompt; helper function; verification; per-call metrics logging (completed 2026-05-03)
- [x] **Phase 18: Module Prompt Restructuring** - refactor all ChatPromptTemplate system-message patterns to content-block format with cache_control markers (completed 2026-05-03)
- [ ] **Phase 19: Observability and Verification** - per-session cache efficiency ratio in Sentry; Linear ticket DEE-50 updated with measured results

## Phase Details

### Phase 13: Sentry Infrastructure
**Goal**: Sentry is initialized safely — active only in production when explicitly enabled, with PII scrubbed and every request carrying a traceable correlation_id
**Depends on**: Nothing (infrastructure foundation — all other v1.3 phases depend on this)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05
**Success Criteria** (what must be TRUE):
  1. Running the server locally with `SENTRY_ENABLED` unset (or `false`) produces zero outbound connections to Sentry and zero Sentry events in any Sentry project
  2. Setting `SENTRY_ENABLED=true` AND a valid `SENTRY_DSN` causes `sentry_sdk.init()` to execute exactly once at startup with `LoggingIntegration(level=INFO, event_level=ERROR)` configured
  3. Every HTTP response carries an `X-Correlation-ID` header; querying Sentry Logs for that UUID shows all log events from that single request
  4. A Sentry event captured during a request includes `session_id`, `user_id` (if authenticated), `endpoint`, and `correlation_id` as tags visible in the Sentry issue detail view
  5. A test request containing `user_query` in the body does not expose that text in any Sentry event payload (`before_send` hook strips it)
**Plans**: 2 plans

Plans:
- [x] 13-01-PLAN.md — Create core/context.py, core/middleware.py, core/sentry.py (new infrastructure modules)
- [x] 13-02-PLAN.md — Wire new modules into main.py (replace sentry init, register middleware, refactor catch_exceptions_mw)

### Phase 14: Route Layer Instrumentation
**Goal**: All four main API handlers emit structured INFO/WARNING/ERROR logs with correlation_id in every log call, and the 500-leaking data bug in `/references` is fixed
**Depends on**: Phase 13
**Requirements**: CHAT-01, CHAT-02, CHAT-03, REF-01, REF-02, REF-03, HIK-01, HIK-02, PRIM-01
**Success Criteria** (what must be TRUE):
  1. A request to `/chat/stream/agentic` produces at least two INFO log lines — one at request start and one at completion — each containing `correlation_id`, `session_id`, and `endpoint` as structured fields (not interpolated strings)
  2. A deliberately malformed config in the request body triggers a WARNING log (not ERROR) and no unhandled exception reaches the 500 middleware
  3. No `print()` call exists in `api/chat.py`, `api/reference.py`, or `api/hikmah.py` — grep returns zero results
  4. A request to `/references` that triggers an internal exception returns an HTTP 500 with `{"detail": "internal_error"}` — the raw exception message is not present in the response body
  5. Log events from `api/hikmah.py` and `api/primers.py` include `correlation_id` and domain fields (`lesson_id`, `user_id` etc.) as top-level `extra={}` keys, not embedded in f-string message text
**Plans**: 3 plans

Plans:
**Wave 1**
- [x] 14-01-PLAN.md — Instrument api/reference.py (add logger, fix REF-02 data-leak, remove print()) and api/hikmah.py (inject correlation_id into all extra={} calls, remove print()+traceback)
- [x] 14-02-PLAN.md — Instrument api/primers.py (convert all f-string logs to extra={}, inject correlation_id, remove traceback.print_exc())

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 14-03-PLAN.md — Instrument api/chat.py (add logger, wire bind_sentry_scope, add start/completion INFO logs for both agentic endpoints, config parse at WARNING, remove all print()+traceback)

### Phase 15: Pipeline and Tools Instrumentation
**Goal**: The core LangGraph pipeline and all agent tools emit structured logs via `logger.*` — no remaining `print()` calls, and pipeline exceptions are captured in Sentry without duplication
**Depends on**: Phase 13
**Requirements**: PIPE-01, PIPE-02, TOOL-01, TOOL-02
**Success Criteria** (what must be TRUE):
  1. Grepping `core/pipeline_langgraph.py`, `agents/tools/retrieval_tools.py`, and `agents/core/chat_agent.py` for `print(` returns zero results
  2. LangGraph per-node traversal events appear at DEBUG level in local logs — they do not appear in Sentry Logs (which only receives INFO and above)
  3. An exception thrown inside the SSE generator is captured exactly once in Sentry — no duplicate events from both `logger.error(exc_info=True)` and a separate `capture_exception()` call
  4. A retrieval tool failure log includes `correlation_id`, a query snippet, and the exception message as separate searchable fields in Sentry Logs
**Plans**: 2 plans

Plans:
- [x] 15-01-PLAN.md — Instrument core/pipeline_langgraph.py (5 print() → logger.*) and agents/tools/retrieval_tools.py (4 print() → logger.error)
- [x] 15-02-PLAN.md — Instrument agents/core/chat_agent.py (~20 print() → logger.debug/error across 9 methods)

### Phase 16: Fiqh Sub-graph Instrumentation
**Goal**: The FAIR-RAG loop emits structured, searchable warnings at every meaningful failure boundary — zero-doc retrievals, total evidence loss, and iteration exhaustion are all visible in Sentry
**Depends on**: Phase 13
**Requirements**: FIQH-01, FIQH-02, FIQH-03, FIQH-04
**Success Criteria** (what must be TRUE):
  1. All existing log calls in `agents/fiqh/fiqh_graph.py` use `extra={}` with `iteration`, `verdict`, and `doc_count` as top-level keys — Sentry Logs search for `iteration:2` returns matching events
  2. Running a fiqh query that results in zero retrieved documents on any iteration produces a WARNING log — visible in Sentry Logs with the iteration number
  3. A scenario where the evidence filter removes all accumulated documents produces a WARNING log with `doc_count=0` before the fail-open path executes
  4. Exhausting all 3 FAIR-RAG iterations with an INSUFFICIENT verdict produces a WARNING log containing `verdict:INSUFFICIENT` and `iteration:3` as structured fields
**Plans**: 1 plan

Plans:
- [x] 16-01-PLAN.md — Instrument agents/fiqh/fiqh_graph.py (convert 10 existing log calls to extra={} style, add 3 WARNING boundaries) and create tests/test_fiqh_graph_logging.py (7 unit tests for WARNING boundaries)

### Phase 17: ChatAgent Caching Foundation
**Goal**: The ChatAgent delivers confirmed Anthropic prompt cache hits on every `/chat/stream/agentic` request — tool definitions and system prompt are cached together as a single prefix, and cache metrics are observable in structured logs
**Depends on**: Nothing (self-contained change to agents/core/chat_agent.py and core/chat_models.py)
**Requirements**: CACHE-01, CACHE-02, CACHE-03, CACHE-04, STRUCT-01
**Success Criteria** (what must be TRUE):
  1. After the first `/chat/stream/agentic` request, a DEBUG log line appears containing `cache_creation_input_tokens > 0` and `cache_hit: false` — confirming the cache was written
  2. After a second identical request within 5 minutes, a DEBUG log line appears containing `cache_read_input_tokens > 0` and `cache_hit: true` — confirming the cache was read
  3. `response.response_metadata["usage"]` (raw Anthropic dict, not LangChain wrapper) is the source for all cache metrics — `usage_metadata` is not used for cache counts
  4. `core/chat_models.py` contains a `make_cached_system_message(text: str) -> SystemMessage` function; every construction of the ChatAgent system prompt calls this helper — no inline `SystemMessage(content=AGENT_SYSTEM_PROMPT)` string patterns remain in `agents/core/chat_agent.py`
  5. The 6 ChatAgent tool definitions are passed to `bind_tools()` with `cache_control: {"type": "ephemeral"}` on the last tool dict only — confirmed by inspecting the outbound Anthropic API payload
**Plans**: 3 plans

Plans:
- [x] 17-01-PLAN.md — Add make_cached_system_message helper to core/chat_models.py + cache_control on last retrieval tool
- [x] 17-02-PLAN.md — Wire helper into agents/core/chat_agent.py (both SystemMessage sites) + cache metrics logging
- [x] 17-03-PLAN.md — Create agent_tests/test_prompt_cache.py (two-call cache write/hit verification)

### Phase 18: Module Prompt Restructuring
**Goal**: All module-level system prompts across FAIR-RAG and classifier/translation modules are in content-block format with cache_control markers, eliminating the silent ChatPromptTemplate stripping anti-pattern from the codebase
**Depends on**: Phase 17 (make_cached_system_message helper must exist before call sites use it)
**Requirements**: STRUCT-02
**Success Criteria** (what must be TRUE):
  1. Grepping `modules/fiqh/`, `modules/classification/`, `modules/translation/`, and `core/prompt_templates.py` for `ChatPromptTemplate.from_messages` returns zero results — all system-message patterns have been replaced
  2. Every refactored system message constructs via `make_cached_system_message()` from `core/chat_models.py` — no inline `[{"type": "text", "text": ..., "cache_control": ...}]` dict literals appear at call sites
  3. `modules/enhancement/enhancer.py` is untouched — a code comment explains why caching is explicitly excluded (Haiku 4.5 requires 4,096-token minimum; enhancer prompt is ~330 tokens)
  4. A smoke test of the `/chat/stream/agentic` endpoint after the refactor returns a valid response — zero behavioral regression
**Plans**: 3 plans

Plans:

**Wave 1** *(parallel — no dependencies between plans)*
- [x] 18-01-PLAN.md — Refactor core/prompt_templates.py (replace 6 ChatPromptTemplate objects with builder functions, add exclusion comments on 2 enhancer templates) + refactor all 6 modules/fiqh/ files (replace _prompt with _build_messages)

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 18-02-PLAN.md — Update 6 consumer files: modules/classification/classifier.py, modules/translation/translator.py, modules/generation/generator.py (legacy), modules/generation/stream_generator.py (remove with_redis_history), core/pipeline_langgraph.py (fiqh import + non-fiqh generation path), services/primer_service.py (both call sites)

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 18-03-PLAN.md — Update test monkeypatch in tests/test_agentic_streaming_pipeline.py + smoke test checkpoint

### Phase 19: Observability and Verification
**Goal**: Cache efficiency is visible in Sentry per session, and the Linear ticket DEE-50 documents confirmed hit rates and implementation details after live deployment
**Depends on**: Phase 17 (cache metrics must be flowing before ratios can be computed), Phase 18 (all call sites restructured)
**Requirements**: OBS-01, OBS-02
**Success Criteria** (what must be TRUE):
  1. A completed chat session produces a Sentry breadcrumb containing `cache_efficiency_ratio` (float 0.0–1.0) computed as `cache_read_tokens / (cache_read_tokens + cache_creation_tokens)` — visible in the Sentry issue detail breadcrumb trail
  2. A session with a cold cache (first-ever request or after TTL expiry) produces `cache_efficiency_ratio: 0.0`; a warm-cache session produces a ratio > 0.0
  3. Linear ticket DEE-50 contains: list of eligible call sites, the approach taken (content-block format + bind_tools injection), and measured cache hit rates from at least one production deployment
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Data Foundation | v1.0 | 3/3 | Complete | 2026-03-24 |
| 2. Routing and Retrieval | v1.0 | 3/3 | Complete | 2026-03-25 |
| 3. FAIR-RAG Core Modules | v1.0 | 3/3 | Complete | 2026-03-25 |
| 4. Assembly and Integration | v1.0 | 3/3 | Complete | 2026-03-25 |
| 5. Database Migration | v1.1 | 2/2 | Complete | 2026-04-06 |
| 6. Auth Migration | v1.1 | 3/3 | Complete | 2026-04-07 |
| 7. Cleanup | v1.1 | 1/1 | Complete | 2026-04-07 |
| 8. Config + Dependencies | v1.2 | 2/2 | Complete | 2026-04-09 |
| 9. LLM Swap | v1.2 | 2/2 | Complete | 2026-04-10 |
| 10. Embedding Migration | v1.2 | 2/2 | Complete | 2026-04-10 |
| 11. Dead Code Cleanup | v1.2 | 2/2 | Complete | 2026-04-10 |
| 12. Docs & Reference Cleanup | v1.2 | 1/1 | Complete | 2026-04-10 |
| 13. Sentry Infrastructure | v1.3 | 2/2 | Complete | 2026-04-26 |
| 14. Route Layer Instrumentation | v1.3 | 3/3 | Complete | 2026-04-26 |
| 15. Pipeline and Tools Instrumentation | v1.3 | 2/2 | Complete | 2026-04-28 |
| 16. Fiqh Sub-graph Instrumentation | v1.3 | 1/1 | Complete | 2026-04-28 |
| 17. ChatAgent Caching Foundation | v1.4 | 3/3 | Complete | 2026-05-03 |
| 18. Module Prompt Restructuring | v1.4 | 0/3 | Not started | - |
| 19. Observability and Verification | v1.4 | 0/? | Not started | - |
