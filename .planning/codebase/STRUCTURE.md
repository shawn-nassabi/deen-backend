# Codebase Structure

**Analysis Date:** 2026-05-09

## Directory Layout

```
deen-backend/
├── main.py                     # ASGI app entry point: routers, middleware, lifespan
├── CLAUDE.md                   # Project instructions for Claude Code
├── requirements.txt            # Pinned dependencies (committed)
├── Dockerfile                  # python:3.11-slim, non-root appuser, encoder regen
├── docker-compose.yml          # api service + caddy reverse proxy
├── alembic.ini                 # Alembic config
├── pytest.ini                  # Test runner config (asyncio_mode, markers)
│
├── api/                        # HTTP route handlers — thin, no business logic
│   ├── chat.py                 # /chat/* (primary agentic + legacy endpoints)
│   ├── reference.py            # /references (semantic reference lookup)
│   ├── hikmah.py               # /hikmah/* (elaboration, quiz)
│   ├── primers.py              # /primers (personalized primers)
│   ├── onboarding.py           # /onboarding
│   ├── account.py              # /account
│   ├── feedback.py             # /feedback
│   └── memory_admin.py         # /admin/memory
│
├── core/                       # Shared utilities and pipeline orchestration
│   ├── pipeline_langgraph.py   # Active agentic pipeline (SSE streaming, token loop)
│   ├── pipeline.py             # Legacy sync pipeline (/chat/, /references, /hikmah)
│   ├── chat_models.py          # LLM factory functions by role (generator/classifier/etc.)
│   ├── memory.py               # Async Redis history + sync shim
│   ├── vectorstore.py          # Pinecone client wrappers (dense + sparse)
│   ├── auth.py                 # Supabase JWKS fetch + auth dependency instances
│   ├── config.py               # Env var loading (dotenv), startup guards
│   ├── middleware.py           # CorrelationIdMiddleware (pure ASGI)
│   ├── context.py              # ContextVar for correlation_id
│   ├── sentry.py               # Sentry SDK init + bind_sentry_scope()
│   ├── logging_config.py       # setup_logging(), ExtraFormatter, get_memory_logger()
│   ├── prompt_templates.py     # Shared LangChain prompt templates
│   └── utils.py                # format_references_as_json, compact_format_references, etc.
│
├── agents/                     # LangGraph agent layer
│   ├── core/
│   │   └── chat_agent.py       # ChatAgent class: StateGraph, nodes, routing, compile
│   ├── state/
│   │   ├── chat_state.py       # ChatState TypedDict + create_initial_state()
│   │   └── fiqh_state.py       # FiqhState TypedDict for fiqh sub-graph
│   ├── tools/
│   │   ├── __init__.py         # Re-exports all tool functions
│   │   ├── classification_tools.py   # check_if_non_islamic_tool, check_if_fiqh_tool
│   │   ├── enhancement_tools.py      # enhance_query_tool
│   │   ├── translation_tools.py      # translate_to_english_tool, translate_response_tool
│   │   └── retrieval_tools.py        # retrieve_shia/sunni/combined/quran_tafsir tools
│   ├── fiqh/
│   │   └── fiqh_graph.py       # Compiled fiqh sub-graph (stateless, module-level singleton)
│   ├── config/
│   │   └── agent_config.py     # AgentConfig, RetrievalConfig, ModelConfig Pydantic models
│   ├── prompts/
│   │   └── agent_prompts.py    # AGENT_SYSTEM_PROMPT, EARLY_EXIT_* constants
│   ├── models/                 # (currently empty / placeholder)
│   ├── utils/                  # (currently empty / placeholder)
│   └── workflows/              # (currently empty / placeholder)
│
├── modules/                    # Discrete AI pipeline stages
│   ├── classification/
│   │   └── classifier.py       # aclassify_non_islamic_query(), aclassify_fiqh_query()
│   ├── embedding/
│   │   └── embedder.py         # getDenseEmbedder(), generate_sparse_embedding()
│   ├── retrieval/
│   │   └── retriever.py        # aretrieve_shia/sunni/quran_documents() + sync versions
│   ├── reranking/
│   │   └── reranker.py         # rerank_documents() — sync, called via asyncio.to_thread
│   ├── enhancement/
│   │   └── enhancer.py         # aenhance_query()
│   ├── translation/
│   │   └── translator.py       # atranslate_to_english(), atranslate_response()
│   ├── generation/
│   │   ├── generator.py        # generate_response() — sync, used by legacy pipeline
│   │   └── stream_generator.py # generate_streaming_response() — sync, legacy pipeline
│   ├── context/                # Context assembly utilities for legacy pipeline
│   └── fiqh/                   # FAIR-RAG fiqh pipeline stages
│       ├── classifier.py       # aclassify_fiqh_query() — 6-category LLM classifier
│       ├── decomposer.py       # adecompose_query() — multi-part query splitting
│       ├── retriever.py        # aretrieve_fiqh_documents() — BM25 + dense fiqh search
│       ├── filter.py           # afilter_evidence() — relevance filtering
│       ├── sea.py              # aassess_evidence(), SEAResult — sufficiency assessment
│       ├── refiner.py          # arefine_query() — targeted gap-filling queries
│       ├── generator.py        # Final answer synthesis; FATWA_DISCLAIMER, INSUFFICIENT_WARNING
│       └── fair_rag.py         # run_fair_rag() — sync entry point (used outside LangGraph)
│
├── services/                   # Business services consumed by routes and pipeline
│   ├── chat_persistence_service.py   # ChatSession/ChatMessage CRUD, Redis hydration
│   ├── memory_service.py             # UserMemoryProfile + MemoryEvent persistence
│   ├── consolidation_service.py      # Periodic memory consolidation logic
│   ├── embedding_service.py          # User memory note embeddings
│   ├── primer_service.py             # Baseline + personalized primer generation + cache
│   ├── hikmah_quiz_service.py        # Hikmah elaboration, quiz logic
│   └── account_service.py            # Account management
│
├── db/                         # Database layer
│   ├── session.py              # Sync engine (psycopg2), SessionLocal, get_db()
│   ├── async_session.py        # Async engine (asyncpg), AsyncSessionLocal, get_db_async()
│   ├── config.py               # pydantic-settings Settings class, DATABASE_URL property
│   ├── models/                 # SQLAlchemy ORM models (13 tables)
│   │   ├── chat_sessions.py    # ChatSession (id, user_id, title, timestamps)
│   │   ├── chat_messages.py    # ChatMessage (session_id FK, role, content)
│   │   ├── users.py            # User model
│   │   ├── lessons.py          # Lesson, with baseline_primer field
│   │   ├── lesson_content.py   # LessonContent
│   │   ├── lesson_page_quiz_questions.py  # Quiz question model
│   │   ├── lesson_page_quiz_choices.py    # Quiz choice model
│   │   ├── lesson_page_quiz_attempts.py   # Quiz attempt model
│   │   ├── user_progress.py    # UserProgress
│   │   ├── hikmah_trees.py     # HikmahTree
│   │   ├── personalized_primers.py  # PersonalizedPrimer cache
│   │   ├── embeddings.py       # User note embeddings (768-dim pgvector)
│   │   └── user_onboarding_profiles.py  # UserOnboardingProfile
│   ├── schemas/                # Pydantic schemas for API request/response
│   │   ├── users.py
│   │   ├── lessons.py
│   │   ├── user_progress.py
│   │   ├── personalized_primers.py
│   │   └── chat_history.py     # SavedChatListResponse, SavedChatDetailResponse
│   ├── repositories/           # Repository pattern for complex queries
│   │   ├── memory_profile_repository.py
│   │   ├── memory_event_repository.py
│   │   └── memory_consolidation_repository.py
│   ├── routers/                # CRUD FastAPI routers (sync sessions)
│   │   ├── users.py
│   │   ├── lessons.py
│   │   ├── lesson_content.py
│   │   ├── user_progress.py
│   │   └── hikmah_trees.py
│   ├── crud/                   # Thin CRUD helpers
│   │   └── base.py             # Generic CRUDBase[ModelType, CreateSchema, UpdateSchema]
│   └── utils/                  # DB utility helpers
│
├── models/                     # Root-level Pydantic schemas and auth models
│   ├── schemas.py              # ChatRequest, ElaborationRequest, ReferenceRequest, etc.
│   └── JWTBearer.py            # JWTBearer, DevBypassBearer, JWKS, JWTAuthorizationCredentials
│
├── alembic/                    # DB migrations
│   ├── env.py
│   └── versions/               # 11 migration files
│       ├── 0000_initial_schema.py
│       ├── 20260305_create_chat_history_tables.py
│       ├── 20260407_create_memory_agent_tables.py
│       └── ...
│
├── tests/                      # Primary test suite (pytest)
│   ├── conftest.py             # Fixtures, stubs, mock factories
│   ├── conftest_async_stubs.py # Async stub implementations
│   ├── __snapshots__/          # syrupy SSE snapshot files
│   ├── test_agentic_streaming_sse.py
│   ├── test_async_concurrency_full.py   # DEE-46: concurrency gate (>=3x p95 baseline)
│   ├── test_sse_event_order_snapshot.py # DEE-46: SSE event order snapshots
│   ├── test_sentry_async_propagation.py # DEE-46: per-coroutine Sentry scope isolation
│   ├── test_real_llm_perf.py           # DEE-46: real LLM perf (marker: real_llm)
│   ├── test_fiqh_*.py                   # Fiqh subsystem tests (unit + integration)
│   ├── test_chat_persistence_service.py
│   ├── test_chat_agent_async.py
│   └── db/                              # DB compatibility tests (requires Postgres)
│
├── agent_tests/                # Integration tests run as scripts
│   └── test_memory_agent.py
│
├── scripts/                    # One-off and ingestion scripts
│   ├── ingest_fiqh.py          # Parse PDF + embed + upsert to Pinecone fiqh indexes
│   └── loadtest_agentic.py     # In-process concurrency load test (N=10)
│
├── data/                       # Runtime data (gitignored artifacts)
│   └── fiqh_bm25_encoder.json  # GITIGNORED — regenerated by Dockerfile or --encoder-only
│
├── documentation/              # Internal design docs
│   ├── async_baseline.md       # DEE-36 concurrency snapshots (phase-0 → phase-7)
│   └── fiqh_related_docs/
│
├── caddy/
│   └── Caddyfile               # Reverse proxy config (deen-fastapi.duckdns.org)
│
├── .github/
│   └── workflows/
│       └── deploy-dev.yml      # DEE-47: CI/CD main → dev Hetzner deploy pipeline
│
└── .planning/                  # GSD planning artifacts (not deployed)
    ├── codebase/               # This document and sibling analysis docs
    └── milestones/             # Phase plans
```

## Directory Purposes

**`api/`:**
- Purpose: One file per feature domain; thin route handlers only — parse, validate, call pipeline or service, return
- Contains: `async def` route handlers, `Depends(auth)`, `Depends(get_db_async)` or `Depends(get_db)`, `HTTPException` raises
- Key files: `api/chat.py` (primary endpoint), `api/reference.py`, `api/hikmah.py`
- Rule: No business logic here; maximum 30-40 lines per handler body

**`core/`:**
- Purpose: Shared infrastructure and pipeline orchestration
- Contains: Active pipeline (`pipeline_langgraph.py`), legacy pipeline (`pipeline.py`), all cross-cutting utilities
- Key files: `core/pipeline_langgraph.py`, `core/memory.py`, `core/vectorstore.py`, `core/config.py`
- Note: `core/pipeline.py` is legacy — new endpoint work goes to `core/pipeline_langgraph.py`

**`agents/`:**
- Purpose: LangGraph agent orchestration, state schemas, tool definitions, fiqh sub-graph, config
- Contains: `core/chat_agent.py` (ChatAgent), `state/`, `tools/`, `fiqh/`, `config/`, `prompts/`
- Key files: `agents/core/chat_agent.py`, `agents/fiqh/fiqh_graph.py`, `agents/state/chat_state.py`

**`modules/`:**
- Purpose: Discrete AI processing stages; each module is independently testable
- Contains: `classification/`, `embedding/`, `retrieval/`, `reranking/`, `enhancement/`, `translation/`, `generation/`, `fiqh/`
- Pattern: Each module exposes an `async def a<function_name>()` and a sync `def <function_name>()` fallback
- Key files: `modules/retrieval/retriever.py`, `modules/fiqh/sea.py`, `modules/fiqh/generator.py`

**`services/`:**
- Purpose: Business services — DB persistence, memory operations, primer generation
- Contains: One service class or module per domain concern
- Key files: `services/chat_persistence_service.py` (most critical — hydrates Redis, wraps streaming)

**`db/`:**
- Purpose: All database concerns — ORM models, schemas, sessions, CRUD, migrations
- Critical split: `db/session.py` (sync psycopg2) vs `db/async_session.py` (async asyncpg)
- Key files: `db/models/chat_sessions.py`, `db/models/chat_messages.py`, `db/async_session.py`

**`models/`:**
- Purpose: Root-level Pydantic schemas for API request/response and auth bearer
- Contains: `models/schemas.py` (all request/response models), `models/JWTBearer.py`
- Note: Separate from `db/schemas/` which are DB-specific Pydantic schemas

**`alembic/versions/`:**
- Purpose: Sequential DB migration scripts (11 files); always run `alembic upgrade head` after pulling
- Generated: No; committed manually
- Committed: Yes

**`data/`:**
- Purpose: Runtime binary/JSON artifacts; all gitignored
- Key file: `data/fiqh_bm25_encoder.json` — BM25 sparse encoder for fiqh retrieval; regenerated by `python scripts/ingest_fiqh.py --encoder-only`

**`tests/`:**
- Purpose: Primary pytest suite — unit tests and stub-driven integration tests
- Key files: `tests/conftest.py`, `tests/test_async_concurrency_full.py`, `tests/test_fiqh_integration.py`
- Special: `tests/db/` requires a reachable Postgres instance; excluded from default `pytest tests -q`

## Key File Locations

**Entry Points:**
- `main.py`: ASGI app definition, all router registration, middleware stack, lifespan hook
- `main.py:lifespan()`: Supabase config validation + fiqh BM25 encoder startup warning

**Primary Chat Path:**
- `api/chat.py:chat_pipeline_agentic_ep()`: `/chat/stream/agentic` handler
- `core/pipeline_langgraph.py:chat_pipeline_streaming_agentic()`: SSE generator
- `agents/core/chat_agent.py:ChatAgent`: LangGraph graph definition and execution
- `agents/state/chat_state.py:create_initial_state()`: State factory — always use this

**Fiqh Sub-graph:**
- `agents/fiqh/fiqh_graph.py:fiqh_subgraph`: Module-level compiled graph singleton
- `agents/state/fiqh_state.py:FiqhState`: Sub-graph state schema
- `modules/fiqh/sea.py`: SEAResult, `aassess_evidence()` — determines loop exit
- `modules/fiqh/generator.py`: FATWA_DISCLAIMER, INSUFFICIENT_WARNING, final synthesis

**Database Sessions:**
- `db/async_session.py:get_db_async()`: Async session — use for chat endpoints
- `db/session.py:get_db()`: Sync session — use for all other endpoints (for now)
- `db/config.py:Settings`: Pydantic settings for DB credentials

**Configuration:**
- `core/config.py`: All env vars loaded via dotenv; startup guards for required keys
- `agents/config/agent_config.py:DEFAULT_AGENT_CONFIG`: Default agent config instance
- `agents/config/agent_config.py:AgentConfig.from_dict()`: Parse per-request config overrides

**Memory:**
- `core/memory.py:amake_history()`: Async entry point — use this in new code
- `core/memory.py:make_history()`: Sync shim — legacy use only
- `services/chat_persistence_service.py:build_runtime_session_id()`: `{user_id}:{session_id}` key builder

**Authentication:**
- `core/auth.py:auth`: Single dependency instance — import `auth` not `JWTBearer` directly
- `models/JWTBearer.py:DevBypassBearer`: Dev-mode passthrough; auto-selected by `core/auth.py`

**Testing:**
- `tests/conftest.py`: Mock factories for LLM, Pinecone, Redis
- `tests/conftest_async_stubs.py`: Async stub implementations
- `tests/__snapshots__/`: syrupy snapshot files for SSE event order tests

## Naming Conventions

**Files:**
- All lowercase with underscores: `chat_persistence_service.py`, `pipeline_langgraph.py`
- Exception: `models/JWTBearer.py` (PascalCase, matches class name)
- Module directories are short lowercase: `api/`, `agents/`, `core/`, `modules/`

**Functions:**
- `snake_case`: `generate_response`, `retrieve_shia_documents`, `build_runtime_session_id`
- Async variants prefixed with `a`: `aclassify_fiqh_query`, `amake_history`, `aretrieve_shia_documents`
- Private helpers prefixed with `_`: `_extract_user_id`, `_fiqh_classification_node`, `_build_graph`
- LangGraph tools use descriptive verb phrases: `enhance_query_tool`, `retrieve_shia_documents_tool`

**Classes:** `PascalCase`: `ChatAgent`, `ChatState`, `FiqhState`, `AgentConfig`, `AsyncRedisChatMessageHistory`

**Constants:** `UPPER_SNAKE_CASE`: `FATWA_DISCLAIMER`, `REFERENCES_MARKER`, `DEFAULT_AGENT_CONFIG`, `VALID_FIQH_CATEGORIES`

**DB models:** `PascalCase` class names, `snake_case` for `__tablename__` and column names

## Where to Add New Code

**New agentic tool:**
- Implementation: `agents/tools/<domain>_tools.py` — `@tool async def <name>_tool()`
- Module logic: `modules/<domain>/<name>.py` — `async def a<name>()` + sync fallback
- Register: Add to `self.tools` list in `agents/core/chat_agent.py:ChatAgent.__init__()`
- Tests: `tests/test_<domain>_tool.py` with mocked module calls

**New LangGraph graph node:**
- Add `async def _<name>_node(self, state: ChatState) -> dict:` in `agents/core/chat_agent.py`
- Register: `workflow.add_node("<name>", self._<name>_node)` in `_build_graph()`
- Add edges to `_build_graph()` and routing logic to `_should_continue()` or a new routing function
- Add SSE status message to `NODE_STATUS_MESSAGES` in `core/pipeline_langgraph.py`

**New API endpoint:**
- Determine domain: new file in `api/<domain>.py` or add to existing domain file
- Register: `app.include_router(<domain>.router)` in `main.py`
- Use `Depends(get_db_async)` for any DB access (not `Depends(get_db)` for new endpoints)
- Use `Depends(auth)` for all protected routes

**New DB model:**
- ORM model: `db/models/<table_name>.py` — inherit `Base` from `db/session.py`
- Schema: `db/schemas/<domain>.py` — Pydantic models for request/response
- Migration: `alembic revision --autogenerate -m "<description>"` then edit and run `alembic upgrade head`

**New fiqh pipeline stage:**
- Module: `modules/fiqh/<stage>.py` with `async def a<stage>()` function
- Sub-graph node: `async def _<stage>_node(state: FiqhState) -> dict:` in `agents/fiqh/fiqh_graph.py`
- Register: Add node + edge in `_fiqh_builder` builder at bottom of `agents/fiqh/fiqh_graph.py`
- Status event: Append `{"step": "fiqh_<stage>", "message": "..."}` to `state["status_events"]`

**New service:**
- File: `services/<domain>_service.py`
- Pattern: Plain functions (not class methods for simple cases); use `AsyncSession` for DB access
- Consume in routes via direct import: `from services import <domain>_service`

**Shared utility:**
- Format helpers: `core/utils.py`
- Prompt templates: `core/prompt_templates.py`
- Config values: `core/config.py` (loaded from `.env`)

## Special Directories

**`.planning/`:**
- Purpose: GSD workflow planning artifacts (phase plans, codebase analysis docs)
- Generated: Partially (by GSD commands)
- Committed: Yes

**`data/`:**
- Purpose: Runtime-generated binary/JSON artifacts not suitable for git
- Generated: Yes (by `scripts/ingest_fiqh.py --encoder-only` or Dockerfile)
- Committed: No — gitignored

**`venv/`:**
- Purpose: Python virtual environment
- Generated: Yes (by `python3 -m venv venv`)
- Committed: No — gitignored

**`alembic/versions/`:**
- Purpose: Committed migration scripts; each file is a versioned schema change
- Generated: Partially (`alembic revision --autogenerate` scaffolds, then hand-edited)
- Committed: Yes — always commit migration files

**`tests/__snapshots__/`:**
- Purpose: syrupy snapshot files for SSE event-order regression tests (`test_sse_event_order_snapshot.py`)
- Generated: Yes (on first run or `--snapshot-update`)
- Committed: Yes — snapshots are the regression baseline

---

*Structure analysis: 2026-05-09*
