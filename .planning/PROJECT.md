# Deen Backend — Fiqh Agentic RAG

## What This Is

An enhancement to the Deen Islamic education platform's chatbot agent that enables it to answer Twelver Shia fiqh questions grounded in Ayatollah Sistani's published rulings. The system implements a FAIR-RAG (Faithful Agentic Iterative Retrieval-Augmented Generation) pipeline that iteratively retrieves, verifies, and synthesizes evidence from Sistani's "Islamic Laws" (4th edition) before generating any answer — ensuring the chatbot never derives its own conclusions or issues fatwas.

The pipeline runs entirely on **Anthropic Claude** (claude-sonnet-4-6 / claude-haiku-4-5) for LLM calls and **HuggingFace `all-mpnet-base-v2`** (768-dim, no API key) for pgvector embeddings.

**Shipped:**
- v1.0 — 4 phases, 12 plans, 39 requirements (2026-03-25): FAIR-RAG pipeline built
- v1.1 — 3 phases, 6 plans (2026-04-07): AWS → Supabase migration
- v1.2 — 5 phases, 9 plans (2026-04-10): OpenAI → Claude + HuggingFace migration complete
- v1.3 — 4 phases, 9 plans (2026-04-28): Sentry Deep Integration complete
- v1.4 — 3 phases, 9 plans (2026-05-04): LLM Input Caching complete

## Core Value

Every fiqh answer must be strictly grounded in retrieved evidence from Ayatollah Sistani's published rulings — the system refuses to answer rather than hallucinate or speculate.

## Shipped Milestones

- **v1.0** (2026-03-25) — FAIR-RAG pipeline built; 4 phases, 12 plans, 39 requirements
- **v1.1** (2026-04-07) — AWS → Supabase migration; 3 phases, 6 plans
- **v1.2** (2026-04-10) — OpenAI → Claude + HuggingFace migration; 5 phases, 9 plans
- **v1.3** (2026-04-28) — Sentry Deep Integration; 4 phases, 8 plans, 22 requirements

## Requirements

### Active

(v1.5 requirements — defined when next milestone starts via /gsd-new-milestone)

### Validated

- ✓ Anthropic prompt caching on ChatAgent — combined tools + system prompt prefix (~5,149 tokens) cached per request; confirmed WRITE and HIT via `agent_tests/test_prompt_cache.py` — v1.4
- ✓ `make_cached_system_message(text: str) -> SystemMessage` helper in `core/chat_models.py` — single construction point for cached system messages; content-block format preserves `cache_control` through LangChain integration — v1.4
- ✓ All `ChatPromptTemplate` system-message patterns eliminated — 6 `modules/fiqh/` files + `core/prompt_templates.py` refactored to builder functions with `make_cached_system_message()`; `modules/enhancement/enhancer.py` explicitly excluded (Haiku 4.5 below 4,096-token threshold) — v1.4
- ✓ Per-turn cache metrics logged at DEBUG level — `cache_hit`, `cache_creation_tokens`, `cache_read_tokens` in `_agent_node` with `correlation_id` — v1.4
- ✓ Per-session cache efficiency Sentry breadcrumb — `cache_efficiency_ratio = cache_read / (cache_read + cache_creation)` emitted at all 4 SSE done sites; cold-cache guard prevents ZeroDivisionError — v1.4
- ✓ FastAPI backend with SSE streaming chat endpoint (`/chat/stream/agentic`) — v1.0
- ✓ LangGraph-based agentic pipeline with tool selection — v1.0
- ✓ Pinecone-based dense + sparse retrieval for hadith/Quran content — v1.0
- ✓ Redis-backed conversation memory — v1.0
- ✓ Query classification and routing (non-Islamic, fiqh early exit) — v1.0
- ✓ Translation and query enhancement tools — v1.0
- ✓ PostgreSQL persistence with Alembic migrations — v1.0
- ✓ AWS Cognito JWT authentication — v1.0 (replaced by Supabase Auth in v1.1)
- ✓ Fiqh book data ingestion pipeline (PDF parsing, chunking, embedding, Pinecone upload) — v1.0
- ✓ Dedicated Pinecone indexes for fiqh content (deen-fiqh-dense + deen-fiqh-sparse) — v1.0
- ✓ 6-category fiqh classifier (VALID_OBVIOUS/SMALL/LARGE/REASONER/OUT_OF_SCOPE_FIQH/UNETHICAL) — v1.0
- ✓ Query decomposition into 1-4 keyword-rich sub-queries with safe fallback — v1.0
- ✓ Hybrid retrieval with RRF merging (dense + sparse, BM25 encoder, dedup, up to 20 docs) — v1.0
- ✓ ChatState extended with `fiqh_category` field (backwards-compatible) — v1.0
- ✓ LLM-based evidence filtering (inclusive) — v1.0
- ✓ Structured Evidence Assessment (SEA) — checklist gap analysis with sufficiency verdict — v1.0
- ✓ Iterative query refinement targeting identified gaps using confirmed facts — v1.0
- ✓ Faithful answer generation with strict evidence-only grounding, inline [n] citations, fatwa disclaimer — v1.0
- ✓ FAIR-RAG coordinator: max-3-iteration retrieve→filter→assess→refine loop with early exit — v1.0
- ✓ FAIR-RAG sub-graph wired as LangGraph sub-graph invoked by main ChatAgent — v1.0
- ✓ SSE streaming of intermediate fiqh pipeline status events — v1.0
- ✓ `fiqh_references` SSE event with book/chapter/section/ruling_number per source — v1.0
- ✓ LLM-generated rejection for OUT_OF_SCOPE_FIQH and UNETHICAL categories — v1.0
- ✓ Session isolation via `checkpointer=False` on fiqh sub-graph — v1.0
- ✓ Non-fiqh path preserved unchanged — v1.0
- ✓ Database connection switched from AWS RDS to Supabase Postgres — v1.1
- ✓ All 13 SQLAlchemy tables + alembic_version created via genesis migration + 7 original migrations — v1.1
- ✓ JWTBearer middleware verifies Supabase Auth JWTs (ES256, JWKS from `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`) — v1.1
- ✓ Cognito env vars removed; SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY added — v1.1
- ✓ Account deletion uses Supabase Admin API (httpx DELETE) instead of boto3 — v1.1
- ✓ boto3 removed from requirements.txt and api/account.py — v1.1
- ✓ .env.example created with all required env vars; README updated — v1.1
- ✓ `ANTHROPIC_API_KEY` replaces `OPENAI_API_KEY`; langchain-anthropic + anthropic added — v1.2
- ✓ `LARGE_LLM` default → `claude-sonnet-4-6`; `SMALL_LLM` → `claude-haiku-4-5-20251001` — v1.2
- ✓ ChatAnthropic replaces init_chat_model/OpenAI in all LLM call sites — v1.2
- ✓ Claude-specific fixes: preamble-safe fiqh classifier, AIMessage filter, temperature ≤1.0 — v1.2
- ✓ HuggingFace `all-mpnet-base-v2` (768-dim, free) replaces text-embedding-3-small (1536-dim) — v1.2
- ✓ pgvector columns resized 1536→768 via Alembic migration; backfill script created — v1.2
- ✓ All OpenAI imports, OPENAI_API_KEY shim, voyageai dependency removed — v1.2
- ✓ All docs, comments, docstrings updated to reflect Claude + HuggingFace stack — v1.2
- ✓ `SENTRY_ENABLED` + `SENTRY_DSN` dual-gate — zero Sentry events in local dev; production-only via opt-in env var — v1.3
- ✓ `CorrelationIdMiddleware` generates server-side UUID per request; all log events carry `correlation_id` — v1.3
- ✓ `bind_sentry_scope()` sets `session_id`, `user_id`, `endpoint` as searchable Sentry tags per request — v1.3
- ✓ `before_send` hook redacts `user_query` and request body from Sentry events (GDPR Article 9 compliance) — v1.3
- ✓ All 4 main API routes (`chat`, `reference`, `hikmah`, `primers`) emit structured `extra={}` logs with `correlation_id`; zero `print()` calls — v1.3
- ✓ REF-02 data-leak bug fixed — `/references` HTTP 500 no longer exposes raw exception string — v1.3
- ✓ `core/pipeline_langgraph.py` and `agents/tools/retrieval_tools.py` — zero `print()` calls; node traversal at DEBUG — v1.3
- ✓ `agents/core/chat_agent.py` — all ~20 `print()` sites replaced with `logger.debug()` / `logger.error(exc_info=True)` — v1.3
- ✓ `agents/fiqh/fiqh_graph.py` — 10 log calls converted to `extra={}` style; 3 WARNING boundaries at FAIR-RAG silent failure paths; 7 unit tests — v1.3

### Out of Scope

- Other maraji (scholars) beyond Sistani — single-scholar focus; cross-marja conflation risk
- Sistani.org Q&A data scraping — book corpus is bounded and sufficient; deferred to v2
- Model fine-tuning or training — agentic pipeline architecture only
- Frontend changes — backend API only; frontend consumes existing SSE protocol
- Arabic/Persian language support for the fiqh pipeline — English-first; translation tool handles queries
- Reasoner model routing (e.g., extended thinking for complex inheritance) — defer to future iteration
- Replacing Pinecone retrieval embeddings (all-mpnet-base-v2 already in use, no change needed)
- Adding Anthropic model providers via Bedrock or Vertex — direct API only for now
- Voyage AI `voyage-code-3` — dropped in favour of HuggingFace free embeddings; revisit only if retrieval quality degrades

## Current State

**v1.4 archived (2026-05-04)** — 19 phases, 47 plans across 5 milestones.

- Stack: FastAPI + LangGraph + Pinecone + Redis + Supabase + Anthropic Claude + HuggingFace + Sentry
- ~24,055 Python LOC
- Anthropic prompt caching active on ChatAgent; all module system prompts in content-block format
- Per-session cache efficiency ratio in Sentry breadcrumbs; per-call cache metrics in DEBUG logs

**Known tech debt (non-blocking):**
- OBS-02: measured cache hit rate requires post-deploy observation — procedure in `DEE-50-POST-DEPLOY-CHECKLIST.md`
- Non-streaming `chat_pipeline_agentic` has no cache breadcrumb — streaming path is production path; deferred
- `agent_tests/test_prompt_cache.py` requires live Anthropic API key — not in CI; manual run only
- HIST-01: message history caching (second breakpoint for sessions > 10 turns) — deferred to v1.5 after hit rates confirmed
- `ExtraFormatter` ANSI colorization not disabled for non-development environments — potential level-field corruption in Sentry if escape codes are transmitted
- Phase 8/10 SUMMARY.md files missing `requirements-completed` frontmatter field (documentation only)

## Context

**Shipped v1.2 (2026-04-10):**
- 5 phases, 9 plans, 75 files changed (+11,831 / -1,179 lines)
- Full OpenAI → Anthropic Claude + HuggingFace migration
- Claude-specific fixes discovered during migration: preamble parsing for fiqh classifier, AIMessage filtering for tool-call sequences, temperature constraint (≤1.0 vs ≤2.0 for OpenAI)
- Voyage AI dropped in favour of HuggingFace all-mpnet-base-v2 (already installed, free, no API key)

**Shipped v1.1 (2026-04-07):**
- 3 phases, 6 plans — AWS fully removed, Supabase Postgres + Auth in place
- Key fix: genesis Alembic migration created to support fresh-DB provisioning
- Operator onboarding: .env.example (28 vars) + README env section

**Shipped v1.0 (2026-03-25):**
- 4 phases, 12 plans, 39 requirements satisfied
- 3000 chunks from Sistani's "Islamic Laws" 4th ed. in Pinecone (ns1)
- 6 tech debt items accumulated (all low severity, no blockers)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Separate Pinecone index for fiqh | Keep fiqh corpus isolated from hadith/Quran for precision | ✓ deen-fiqh-dense + deen-fiqh-sparse, 3000 chunks in ns1 |
| FAIR-RAG as LangGraph sub-graph | Integrates cleanly with existing agent; main agent routes to sub-graph | ✓ `agents/fiqh/fiqh_graph.py` compiled with `checkpointer=False` |
| Dynamic LLM allocation | 13% cheaper, 97% vs 94% negative rejection per FARSIQA | ✓ claude-haiku-4-5 for SEA/decompose/filter, claude-sonnet-4-6 for generation/refinement |
| Max 3 iterations | Both FAIR-RAG and FARSIQA show iteration 4 gives negligible/negative improvement | ✓ FiqhState iteration counter, `_route_after_assess` exits at iteration >= 3 |
| Single book corpus only | Bounded corpus makes data quality controllable; expand later | ✓ Sistani "Islamic Laws" 4th ed., 3000 chunks |
| 6-category classifier over binary | Current binary classifier did not route fiqh queries accurately | ✓ VALID_OBVIOUS/SMALL/LARGE/REASONER/OUT_OF_SCOPE_FIQH/UNETHICAL |
| Pre-canned SSE stage events | Fiqh sub-graph runs as black box; FiqhState.status_events not propagated back | ⚠ UX inaccuracy: `fiqh_refine` always emits regardless of actual iterations |
| No module-level fiqh env var guard | Guard in ingestion script only — avoids breaking server startup for devs without fiqh indexes | ✓ Works correctly in all environments |
| Genesis Alembic migration (0000_initial_schema.py) | Pre-alembic RDS tables had no migration; fresh DB would fail at step 2 of chain | ✓ All 8 migrations run cleanly on fresh Supabase DB |
| Direct connection port 5432 (not pooler 6543) | asyncpg incompatible with transaction pooler | ✓ Both DATABASE_URL and ASYNC_DATABASE_URL use port 5432 |
| supabase-py SDK not added | App uses SQLAlchemy directly; SDK wraps PostgREST/storage/realtime which are unused | ✓ Zero new dependencies for DB layer |
| boto3 retained through Phase 6 (removed in Phase 7) | Explicit phase boundary kept scope clean — auth and cleanup are separate concerns | ✓ Clean separation |
| HuggingFace over Voyage AI for embeddings | all-mpnet-base-v2 already installed, free, no API key needed; Voyage AI costs money and adds dependency | ✓ 768-dim vectors, zero additional cost or API key requirement |
| with_structured_output for fiqh classifier | Claude returns preamble text before JSON; structured output bypasses parsing fragility | ✓ Preamble-safe classification in Phase 9 |
| AIMessage filter before LLM history | Claude errors on consecutive tool-call messages without intermediate assistant turn | ✓ D-08 filter in `_agent_node` prevents tool-call sequence crashes |
| Side-effect import for Sentry init (`import core.sentry`) | Keeps main.py clean; module-level init fires once at import time via Python's sys.modules caching | ✓ No `sentry_sdk.init()` in main.py; init guaranteed single-fire by import machinery |
| logger.error(exc_info=True) over capture_exception() | LoggingIntegration auto-captures ERROR log events — calling both creates duplicate Sentry events | ✓ `capture_exception()` removed from catch_exceptions_mw; zero duplicate events |
| Never read incoming X-Correlation-ID header | D-03 threat: clients could inject forged IDs to manipulate Sentry trace correlation | ✓ CorrelationIdMiddleware generates server-side UUID only; client header ignored |
| FastApiIntegration excluded from integrations list | sentry-sdk[fastapi] auto-enables FastApiIntegration; explicit inclusion causes duplicate setup | ✓ No FastApiIntegration in integrations=[...] list |
| Combined tools+system prefix as single cache breakpoint | System prompt alone (1,427 tokens) is below 2,048-token Sonnet minimum; only clears threshold when combined with tool definitions (~5,149 tokens total) | ✓ Single `bind_tools()` + `make_cached_system_message()` prefix |
| `convert_to_anthropic_tool()` + dict mutation for tool cache_control | `@tool(extras=...)` is not a valid API in langchain-core==0.3.84 — TypeError at import time | ✓ `retrieve_quran_tafsir_tool_cached` dict exported from retrieval_tools.py |
| `response.response_metadata["usage"]` for cache metrics (not `usage_metadata`) | LangChain wrapper double-counts cached tokens in streaming paths (GitHub #32818) | ✓ Raw Anthropic dict used consistently; `usage_metadata` banned by grep test |
| `SystemMessage(content=[...])` content-block format for all system prompts | `ChatPromptTemplate.format_messages()` silently strips `cache_control` (GitHub #26701) | ✓ All 10 `ChatPromptTemplate` objects replaced; zero stripping risk |
| `modules/enhancement/enhancer.py` excluded from caching | Haiku 4.5 requires 4,096-token minimum; enhancer prompt is ~330 tokens — caching would charge 1.25× write cost with zero hits | ✓ Comment in enhancer.py explaining exclusion |
| Never put `cache_control` inside `ToolMessage.content[]` | Confirmed API error: `invalid_cache` at `messages.N.content.0.content.0.cache_control` (GitHub #34920) | ✓ Only tool definitions and system prompt carry cache_control |
| ChatState int fields over ContextVar for cache accumulation | Matches existing `final_state.get(...)` pattern; less invasive than module-level globals | ✓ `cache_creation_tokens_total`, `cache_read_tokens_total` on ChatState |

## Constraints

- **Tech Stack**: Must integrate with existing FastAPI + LangGraph + Pinecone + Redis stack
- **LLM Provider**: Anthropic Claude — claude-sonnet-4-6 (large) and claude-haiku-4-5 (small) for dynamic allocation
- **Retrieval**: Pinecone for both dense and sparse indices (separate from existing hadith/Quran indices)
- **Iterations**: Max 3 retrieval iterations per query (research shows diminishing returns beyond 3)
- **Religious Sensitivity**: Never issue fatwas, always include disclaimers, refuse rather than speculate
- **Streaming**: Must emit SSE events compatible with existing frontend protocol

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition:** update Validated, Active, Out of Scope, and Key Decisions.

**After each milestone** (via `/gsd:complete-milestone`): full review of all sections.

---
*Last updated: 2026-05-04 after v1.4 milestone*
