# Deen Backend — Fiqh Agentic RAG

## What This Is

An enhancement to the Deen Islamic education platform's chatbot agent that enables it to answer Twelver Shia fiqh questions grounded in Ayatollah Sistani's published rulings. The system implements a FAIR-RAG (Faithful Agentic Iterative Retrieval-Augmented Generation) pipeline that iteratively retrieves, verifies, and synthesizes evidence from Sistani's "Islamic Laws" (4th edition) before generating any answer — ensuring the chatbot never derives its own conclusions or issues fatwas.

The pipeline runs entirely on **Anthropic Claude** (claude-sonnet-4-6 / claude-haiku-4-5) for LLM calls and **HuggingFace `all-mpnet-base-v2`** (768-dim, no API key) for pgvector embeddings.

**Shipped:**
- v1.0 — 4 phases, 12 plans, 39 requirements (2026-03-25): FAIR-RAG pipeline built
- v1.1 — 3 phases, 6 plans (2026-04-07): AWS → Supabase migration
- v1.2 — 5 phases, 9 plans (2026-04-10): OpenAI → Claude + HuggingFace migration complete

## Core Value

Every fiqh answer must be strictly grounded in retrieved evidence from Ayatollah Sistani's published rulings — the system refuses to answer rather than hallucinate or speculate.

## Current Milestone: v1.3 Sentry Deep Integration

**Goal:** Instrument all main API endpoints with structured info/warning/error logging that flows to Sentry with correlation_id per request — production-only, opt-in via env var.

**Target features:**
- `SENTRY_ENABLED` env var gates all Sentry initialization (defaults false — local dev never sends events)
- Request-scoped correlation_id middleware — UUID generated per request, propagated through all downstream log calls
- Sentry scope binding — session_id, user_id, endpoint, and correlation_id attached as context on every Sentry event
- Replace all `print()` with `logger.*` in `api/chat.py`, `core/pipeline_langgraph.py`, `agents/tools/retrieval_tools.py`, `api/reference.py`
- Consistent info/warning/error coverage across all main APIs (agentic chat, references, hikmah, primers)
- Standardize hikmah and primers (already partially logged) to use the same context field pattern

## Requirements

### Validated

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

### Active

*(v1.3 requirements — defined below in REQUIREMENTS.md)*

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

**v1.3 in progress (Phase 14 complete 2026-04-26)** — Route layer instrumentation shipped.

- 14 phases, 29 plans across 4 milestones
- Stack: FastAPI + LangGraph + Pinecone + Redis + Supabase + Anthropic Claude + HuggingFace + Sentry
- Phase 13 complete: `core/sentry.py` (SDK init gate), `core/context.py` (correlation_id ContextVar), `core/middleware.py` (CorrelationIdMiddleware), wired into `main.py`
- Phase 14 complete: `api/reference.py`, `api/hikmah.py`, `api/primers.py`, `api/chat.py` — all instrumented with structured `extra={}` logging, correlation_id in every log call, `bind_sentry_scope()` wired after JWT extraction, all `print()` removed, REF-02 data-leak fixed (`detail="internal_error"`)
- Next: Phase 15 — pipeline and tools instrumentation (core/pipeline_langgraph.py, agents/tools/)

**Known tech debt (non-blocking):**
- Live Claude API smoke test (POST /chat/stream/agentic with real ANTHROPIC_API_KEY) not yet run in CI — runtime environment confirmation only
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
*Last updated: 2026-04-26 — Phase 14 complete (Route Layer Instrumentation shipped)*
