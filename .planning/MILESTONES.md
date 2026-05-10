# Milestones

## v1.4 LLM Input Caching (Shipped: 2026-05-04)

**Phases completed:** 3 phases, 9 plans

**Timeline:** 2026-05-03 → 2026-05-04 (2 days)
**Files changed:** 22 Python files (+909 / -128 lines)
**Python LOC:** ~24,055 total

**Key accomplishments:**

1. `make_cached_system_message()` helper in `core/chat_models.py` + `retrieve_quran_tafsir_tool_cached` dict — two caching primitives implementing Anthropic content-block format; `@tool(extras=...)` discovered as invalid API, worked around with `convert_to_anthropic_tool()` + dict mutation
2. Cached system prompt and cache metrics logging wired into `agents/core/chat_agent.py` — `_agent_node` and `_generate_response_node` both use content-block format; per-call `cache_hit`, `cache_creation_tokens`, `cache_read_tokens` emitted at DEBUG with `correlation_id`
3. `agent_tests/test_prompt_cache.py` standalone two-call verification — confirms `cache_creation_input_tokens > 0` (WRITE) on first call and `cache_read_input_tokens > 0` (HIT) on second identical call
4. All 10 `ChatPromptTemplate` objects in `core/prompt_templates.py` and 6 `modules/fiqh/` files replaced with builder functions using `make_cached_system_message()` — eliminating the silent `cache_control` stripping anti-pattern (GitHub #26701)
5. 6 consumer files updated (`classifier.py`, `translator.py`, `generator.py`, `stream_generator.py`, `pipeline_langgraph.py`, `primer_service.py`) — `with_redis_history` chain removed; fiqh import alias updated
6. `record_cache_metrics_breadcrumb` helper in `core/sentry.py` + `cache_creation_tokens_total`/`cache_read_tokens_total` accumulator fields on `ChatState`; `_emit_cache_metrics_breadcrumb` fires at all 4 SSE done sites; 9 hermetic tests pass (17/17 with pre-existing suite)

**Requirements:** 7/8 fully delivered (OBS-02 partial — implementation complete; measured hit rate pending post-deploy observation per DEE-50-POST-DEPLOY-CHECKLIST.md)

**Known deferred items at close:** 0

---

## v1.3 Sentry Deep Integration (Shipped: 2026-04-28)

**Phases completed:** 4 phases, 8 plans

**Timeline:** 2026-04-26 → 2026-04-28 (3 days)
**Files changed:** 64 files (+10,017 / -217 lines)
**Python LOC:** ~23,274 total

**Key accomplishments:**

1. `core/context.py`, `core/middleware.py`, `core/sentry.py` — correlation_id ContextVar, server-side UUID middleware, dual-gated Sentry SDK init with GDPR-compliant PII scrubbing and `before_send` hook
2. `main.py` wired with side-effect `import core.sentry`, CorrelationIdMiddleware registered, `catch_exceptions_mw` refactored to `logger.error(exc_info=True)` — zero `capture_exception()` calls
3. All 4 main API routes instrumented with `extra={}` structured logging, `bind_sentry_scope()`, and zero `print()` calls; REF-02 data-leak bug closed
4. `core/pipeline_langgraph.py` and `agents/tools/retrieval_tools.py` — 9 `print()` calls replaced with `logger.*`; node traversal at DEBUG to avoid Sentry log quota overrun
5. `agents/core/chat_agent.py` — all ~20 `print()` calls across 9 methods converted to `logger.debug()` / `logger.error(exc_info=True)` with `correlation_id` in every `extra={}`
6. `agents/fiqh/fiqh_graph.py` — 10 existing log calls converted to `extra={}` style; 3 new WARNING boundaries at FAIR-RAG silent failure paths; 7 unit tests in `tests/test_fiqh_graph_logging.py` proving all boundaries fire correctly

**Requirements:** 22/22 complete (INFRA-01..05, CHAT-01..03, REF-01..03, HIK-01..02, PRIM-01, PIPE-01..02, TOOL-01..02, FIQH-01..04)

---

## v1.2 Claude Migration (Shipped: 2026-04-10)

**Phases completed:** 5 phases, 9 plans, 20 tasks

**Key accomplishments:**

- One-liner:
- ChatAnthropic replaces init_chat_model/OpenAI in all four factory functions, OPENAI_API_KEY shim added for legacy import compat, ModelConfig updated with Claude API constraints (temperature<=1.0, max_tokens=4096)
- ChatAnthropic wired end-to-end in ChatAgent and hikmah script; fiqh classifier made preamble-safe via with_structured_output(FiqhCategory); D-08 AIMessage filter added to prevent Claude tool-call sequence crashes
- One-liner:
- One-liner:
- Dead `openai` imports, `OPENAI_API_KEY` references, and `voyageai` dependency fully excised from application code — zero OpenAI import sites remain
- One-liner:
- Removed all 10 stale OpenAI/GPT references from user-facing docs, in-code comments, docstrings, and planning artifacts — README, DEPLOYMENT, CHATBOT, pipeline.py, README_LANGGRAPH, decomposer.py, and 09-VERIFICATION.md now accurately reflect the Claude + HuggingFace stack

---

## v1.1 Supabase Migration (Shipped: 2026-04-07)

**Phases completed:** 3 phases, 6 plans, 6 tasks

**Key accomplishments:**

- Supabase env vars (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) replace Cognito constants in core/config.py with startup ValueError guard
- JWKS fetch URL in core/auth.py changed from AWS Cognito to Supabase Auth endpoint; Cognito references fully removed
- httpx DELETE to Supabase Admin API replaces boto3 AdminDeleteUser in account deletion; GET /account/me cleaned of Cognito username field
- boto3 removed from requirements.txt and api/account.py; .env.example and README.md Environment Variables section added for operator onboarding

---

## v1.0 Fiqh Agentic RAG MVP (Shipped: 2026-03-25)

**Phases completed:** 4 phases, 12 plans, 17 tasks

**Key accomplishments:**

- pymupdf and pinecone-text pinned in requirements.txt, fiqh Pinecone index env vars exported from core/config.py, and data/ directory scaffolded with BM25 encoder gitignored
- PyMuPDF-based PDF parsing with ruling-boundary chunking producing 3000 structured chunks from 2796 Sistani rulings, with chapter/section/topic metadata on every chunk
- Full Pinecone fiqh ingestion pipeline: BM25Encoder fitted on 3000 chunks + dense embedding via all-mpnet-base-v2 + dual upsert to deen-fiqh-dense and deen-fiqh-sparse indexes with idempotent index creation
- 6-category fiqh classifier (classify_fiqh_query, gpt-4o-mini) added to modules/fiqh/classifier.py; fiqh_category field added to ChatState for downstream routing
- Query decomposer (decompose_query) with JSON fence stripping and safe fallback to original query; unit tests for classifier and decomposer (mocked LLM)
- Hybrid fiqh retriever using BM25 sparse + dense Pinecone raw index queries merged with Reciprocal Rank Fusion (k=60), returning up to 20 deduplicated docs per query via decomposed sub-queries.
- LLM-based evidence filter (gpt-4.1) and Structured Evidence Assessment (gpt-4o-mini with Pydantic structured output) for the FAIR-RAG pipeline — 23 mock-based unit tests, all pass
- Query refiner (gpt-4.1) targeting SEA gaps + confirmed facts, and answer generator (gpt-4.1) with inline [n] citations, ## Sources section, mandatory fatwa disclaimer, and insufficient-evidence warning — 23 mock-based unit tests, all pass
- Pure Python FAIR-RAG coordinator wiring all Phase 3 modules (filter, SEA, refiner, generator) with Phase 2 retriever into a max-3-iteration retrieve-filter-assess-refine loop — 9 mock-based unit tests, all pass
- FiqhState TypedDict (7 fields), ChatState fiqh result fields, and format_fiqh_references_as_json() — state contracts enabling Plans 02 and 03 to import concrete types without circular uncertainty

---
