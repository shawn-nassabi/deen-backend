# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## MCP servers

Project-scoped MCP servers are declared in `.mcp.json` at the repo root (committed, so they
carry over to both local CLI and Claude Code on the web).

- **linear** — Linear's hosted MCP server (`https://mcp.linear.app/mcp`, streamable HTTP, OAuth 2.1).
  Issues are tracked in Linear (`DEE-*` tickets). After cloning, run `/mcp` once and complete the
  browser OAuth flow to authenticate; tools then cover finding/creating/updating Linear issues,
  projects, and comments.

## Commands

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head

# Run locally (http://127.0.0.1:8000)
uvicorn main:app --reload

# Run specific port
uvicorn main:app --port 8080 --reload --host 0.0.0.0

# Tests
pytest tests -q                             # primary suite (skips tests/db and -m real_llm by default)
pytest tests/db -q                          # DB compatibility (requires reachable Postgres)
pytest tests/test_fiqh_*.py -q              # FAIR-RAG fiqh subsystem tests
python agent_tests/test_memory_agent.py     # memory agent integration
pytest tests/test_agentic_streaming_sse.py -v -s
pytest tests/ -m real_llm -q                # opt-in: hits real Anthropic + Pinecone + Supabase
python scripts/loadtest_agentic.py --n 10   # in-process concurrency loadtest

# Fiqh corpus ingestion / encoder regeneration
python scripts/ingest_fiqh.py                  # full: parse PDF + embed + upsert to Pinecone (one-time)
python scripts/ingest_fiqh.py --encoder-only   # local-only: regenerate data/fiqh_bm25_encoder.json
                                                # (gitignored; required for fiqh queries to work locally)

# Reference translation batch job (DEE-67, personal key only -- do NOT run without setting TRANSLATION_ANTHROPIC_API_KEY)
export TRANSLATION_ANTHROPIC_API_KEY=sk-ant-...   # personal key, never the app's ANTHROPIC_API_KEY
python scripts/translate_references.py --dry-run --limit 5   # preview counts, no Anthropic/DB calls
python scripts/translate_references.py --ref-type hadith --languages urdu --limit 20   # small live sample
python scripts/translate_references.py   # full corpus x all 6 languages (only after sampling looks correct)
# Note: run `alembic upgrade head` once (creates the reference_translations table) before this script's writes will succeed.

# Docker
docker compose build --no-cache && docker compose up -d

# Verify agentic endpoint
curl -X POST http://127.0.0.1:8000/chat/stream/agentic ...
```

## Architecture

**FastAPI backend for an AI-powered Islamic education platform.**

The AI pipeline flows: HTTP request → `api/` → `core/pipeline_langgraph.py` → `agents/` → `modules/` pipeline stages → response.

### Layer responsibilities

- **`api/`** — Thin route handlers. Business logic belongs in `services/`, `core/`, or `modules/`.
- **`core/`** — Shared utilities: `pipeline_langgraph.py` (active agentic pipeline), `pipeline.py` (legacy), `auth.py` (JWT via AWS Cognito), `memory.py` (Redis), `vectorstore.py` (Pinecone init), `config.py` (env loader).
- **`agents/`** — LangGraph agent orchestration. `core/chat_agent.py` drives the graph; `tools/` wraps pipeline stages as LangGraph-compatible tools; `state/chat_state.py` manages agent state; `config/agent_config.py` controls behavior.
- **`modules/`** — Discrete AI pipeline stages: classification → embedding (dense + sparse) → retrieval (Pinecone) → reranking → generation (OpenAI) → translation/enhancement.
- **`services/`** — Business services consumed by routes and agents: chat persistence, embedding management, primer generation, memory consolidation.
- **`db/`** — SQLAlchemy models, Pydantic schemas, repository pattern (data access), routers (CRUD endpoints), `session.py` (sync engine), `config.py` (Pydantic DB settings).
- **`alembic/`** — DB migrations. Always run `alembic upgrade head` after pulling.

### Chat endpoints (key paths)

| Endpoint | Description |
|---|---|
| `POST /chat/stream/agentic` | Streaming agentic chat (SSE), primary endpoint |
| `POST /chat/agentic` | Non-streaming agentic chat |
| `GET /references` | Semantic reference lookup with sect filtering |
| `POST /hikmah/elaborate` | Hikmah tree elaboration |
| `GET /primers` | Personalized primer retrieval |
| `POST /onboarding`, `GET /onboarding/me` | User onboarding profile |
| `POST /feedback` | User feedback capture |
| `GET /admin/memory` | Memory admin dashboard |

### Key environment variables

```
ANTHROPIC_API_KEY, LARGE_LLM, SMALL_LLM
PINECONE_API_KEY, DEEN_DENSE_INDEX_NAME, DEEN_SPARSE_INDEX_NAME, QURAN_DENSE_INDEX_NAME
REDIS_URL, REDIS_KEY_PREFIX, REDIS_TTL_SECONDS, REDIS_MAX_MESSAGES
DATABASE_URL, ASYNC_DATABASE_URL
SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
COGNITO_REGION, COGNITO_POOL_ID
CORS_ALLOW_ORIGINS
ENV (development/production)
```

Current LLM defaults: `LARGE_LLM=claude-sonnet-4-6`, `SMALL_LLM=claude-haiku-4-5-20251001`. Provider is Anthropic via `langchain-anthropic`; the `.ainvoke()` / `.astream()` interface is provider-agnostic, so the pipeline does not depend on Anthropic specifically.

### Agentic pipeline (LangGraph)

`core/pipeline_langgraph.py` implements the active pipeline as a LangGraph graph. The agent uses 9 tools (across `agents/tools/`: 4 retrieval, 2 classification, 2 translation, 1 enhancement) bound to the LLM via `.bind_tools()`. Key early-exit conditions: `non_islamic` classification and `fiqh` routing — when fiqh is detected, control hands off to the FAIR-RAG subsystem (see below). When adding new agentic behavior, write tests around tool-selection outcomes and these early-exit paths.

All graph nodes and bound tools are now natively async (DEE-41/DEE-42); `agent.astream()` is the streaming entry point and never blocks the event loop on LLM, Pinecone, or Redis I/O. Per-token streaming uses `chain.astream()` (DEE-40) inside an `async def` generator.

### Fiqh subsystem (FAIR-RAG)

The fiqh path is a separate, dedicated graph — not just a tool on the main agent. When `check_if_fiqh_tool` detects a Twelver Shia fiqh question, the main agent routes out and `agents/fiqh/fiqh_graph.py` runs a 5-node iterative pipeline (decompose → retrieve → filter → assess → refine, looping up to 3 times). The pipeline stages live in `modules/fiqh/`:

- `decomposer.py` — splits multi-part questions into atomic sub-queries
- `retriever.py` — Pinecone search against the dedicated fiqh indices
- `filter.py` — relevance filtering of retrieved passages
- `sea.py` — sufficiency / evidence assessment (decides whether to refine or exit)
- `refiner.py` — query refinement for the next iteration
- `generator.py` — final grounded answer synthesis (refuses rather than speculates)
- `fair_rag.py` — `run_fair_rag(query)` is the synchronous entry point used outside LangGraph
- `classifier.py` — fiqh-specific topical classification

Fiqh subgraph nodes (`_decompose_node`, `_retrieve_node`, etc. in `agents/fiqh/fiqh_graph.py`) are now natively async (DEE-44); the `asyncio.to_thread` wrapper from Phase 2 has been removed. The main agent invokes the subgraph via `await fiqh_subgraph.ainvoke(...)`.

Corpus ingestion lives in `scripts/ingest_fiqh.py` and populates separate Pinecone indices (do not reuse the main hadith/Quran indices). Fiqh tests are `tests/test_fiqh_*.py` covering each stage individually plus integration (`test_fiqh_integration.py`) and graph-level logging (`test_fiqh_graph_logging.py`). Honour the religious-sensitivity constraints from the Project section: never issue fatwas, always include disclaimers, refuse rather than speculate.

**Local DX gotcha (DEE-46):** `data/fiqh_bm25_encoder.json` is **gitignored** and regenerated at Docker image build time by `Dockerfile`'s `RUN python scripts/ingest_fiqh.py --encoder-only`. Fresh clones running `uvicorn main:app --reload` directly will silently fall back to refusal answers for fiqh queries because sparse retrieval throws inside `_get_bm25_encoder`. `main.py`'s lifespan hook now logs a WARNING with the remediation command (`python scripts/ingest_fiqh.py --encoder-only`) when the file is missing.

### Async architecture (DEE-36 — closed)

The streaming hot path is end-to-end async; see `documentation/async_baseline.md` for per-phase concurrency snapshots (phase-0 → phase-7 = ≥3× p95 improvement at N=10, deterministic stub-driven).

- `core/pipeline_langgraph.py` uses `chain.astream()` end-to-end (DEE-40).
- ChatAgent nodes and all 9 `@tool` functions are `async def` (DEE-41).
- LLM modules + Pinecone retrieval are natively async — `aclassify_*`, `aenhance_query`, `atranslate_*`, `PineconeAsyncio.asimilarity_search_with_score` (DEE-42).
- Redis chat history uses `AsyncRedisChatMessageHistory` from `core/memory.py` (DEE-43).
- Fiqh subgraph and `/references`, `/hikmah/elaborate` routes are natively async (DEE-44).
- Chat persistence runs on `asyncpg` + `AsyncSession` (DEE-45). The chat router uses `Depends(get_db_async)` from `db/async_session.py`; other routers (primer, lessons, hikmah, etc.) stay on sync `Depends(get_db)` and migrate in follow-up sub-issues.
- Final automated gate suite landed in DEE-46: concurrency p95 ≥3× phase-0 baseline (`tests/test_async_concurrency_full.py`), SSE event-order snapshots via syrupy (`tests/test_sse_event_order_snapshot.py`), per-coroutine Sentry scope isolation under asyncio (`tests/test_sentry_async_propagation.py`), plus the opt-in real-Anthropic perf suite (`tests/test_real_llm_perf.py`, marker `-m real_llm`).

### Memory system

Redis stores per-user conversation history (`REDIS_KEY_PREFIX` namespaced). `services/memory_service.py` and `services/consolidation_service.py` handle memory operations; `core/memory.py` provides low-level Redis access. Memory admin is exposed at `/admin/memory`.

Redis access is fully async (DEE-43): `core/memory.py` exposes `amake_history(...)` returning a custom `AsyncRedisChatMessageHistory` wrapper that loads, appends, and trims via `redis.asyncio`. The wrapper is wire-compatible with `langchain-community`'s sync version, and the sync `make_history(...)` shim is retained only for legacy code paths.

### Database

SQLAlchemy models in `db/models/`. 11 Alembic migrations in `alembic/versions/` (always run `alembic upgrade head` after pulling). The project uses both sync (`db/session.py`) and async (`ASYNC_DATABASE_URL`) database sessions.

## Coding conventions

- `snake_case` for modules/functions/variables; `PascalCase` for classes; `UPPER_SNAKE_CASE` for constants.
- Add type hints to new/changed functions.
- `pytest` with `pytest-asyncio` for async tests. Mock-based unit tests go in `tests/`; environment-dependent integration tests go in `tests/db/` or `agent_tests/`.
- Commit style: short imperative subjects, e.g. `feat: add primer cache invalidation`.

## PR checklist

Include: purpose, impacted endpoints (especially `/chat/stream/agentic`), migration notes (`alembic/versions/...`), env var changes, test evidence.

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Deen Backend — Fiqh Agentic RAG**

An enhancement to the Deen Islamic education platform's chatbot agent that enables it to answer Twelver Shia fiqh questions grounded in Ayatollah Sistani's published rulings. The system implements a FAIR-RAG (Faithful Agentic Iterative Retrieval-Augmented Generation) pipeline that iteratively retrieves, verifies, and synthesizes evidence from Sistani's "Islamic Laws" (4th edition) before generating any answer — ensuring the chatbot never derives its own conclusions or issues fatwas.

**Core Value:** Every fiqh answer must be strictly grounded in retrieved evidence from Ayatollah Sistani's published rulings — the system refuses to answer rather than hallucinate or speculate.

### Constraints

- **Tech Stack**: Must integrate with existing FastAPI + LangGraph + Pinecone + Redis stack
- **LLM Provider**: OpenAI models — gpt-4.1 (large) and gpt-4o-mini (small) for dynamic allocation
- **Retrieval**: Pinecone for both dense and sparse indices (separate from existing hadith/Quran indices)
- **Iterations**: Max 3 retrieval iterations per query (research shows diminishing returns beyond 3)
- **Religious Sensitivity**: Never issue fatwas, always include disclaimers, refuse rather than speculate
- **Streaming**: Must emit SSE status events compatible with existing frontend protocol
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Summary
## Languages
- Python 3.11 (Dockerfile base image: `python:3.11-slim`) — all application code
- None — the project is pure Python
## Runtime
- CPython 3.11 (system version: 3.11.4)
- Virtual environment: `venv/` at project root
- `pip` — no Poetry or pipenv
- Lockfile: `requirements.txt` (pinned versions, committed)
## Frameworks
- `fastapi==0.115.8` — HTTP framework, route definitions, dependency injection
- `starlette==0.45.3` — ASGI foundation; SSE streaming via `StreamingResponse`
- `uvicorn==0.34.0` — ASGI server for local dev (`uvicorn main:app --reload`)
- `gunicorn==23.0.0` — production process manager with Uvicorn workers (`-w 2`)
- `langchain==0.3.27` — core LangChain framework; prompt templates, runnables, history
- `langchain-core==0.3.74` — base abstractions
- `langchain-openai==0.3.25` — OpenAI chat model bindings via `init_chat_model`
- `langchain-community==0.3.27` — `RedisChatMessageHistory`, `ChatMessageHistory`
- `langchain-pinecone==0.2.8` — `PineconeVectorStore` integration
- `langchain-huggingface==0.1.2` — `HuggingFaceEmbeddings` for dense embedding
- `langgraph==0.2.64` — agentic graph orchestration; active pipeline in `core/pipeline_langgraph.py`
- `langgraph-checkpoint==2.1.1` — LangGraph state checkpointing
- `langgraph-sdk==0.1.74` — LangGraph SDK utilities
- `langsmith==0.4.4` — tracing/observability for LangChain runs
- `SQLAlchemy==2.0.41` — ORM + Core; both sync (`db/session.py`) and async (`ASYNC_DATABASE_URL`) sessions
- `alembic==1.14.0` — schema migrations (`alembic/versions/`, 7 migration files)
- `psycopg2-binary==2.9.10` — sync PostgreSQL driver
- `asyncpg==0.30.0` — async PostgreSQL driver
- `pgvector==0.3.6` — PostgreSQL vector extension support
- `pydantic==2.10.6` — request/response models, config validation
- `pydantic-settings==2.10.1` — `BaseSettings` for `db/config.py`
- `pytest==8.4.1` — test runner
- `pytest-asyncio==0.26.0` — async test support
- `pytest-benchmark==5.1.0` — performance benchmarks
- `pytest-recording==0.13.4` — VCR cassette-based HTTP recording
- `pytest-socket==0.7.0` — network isolation for unit tests
- `vcrpy==7.0.0` — HTTP interaction recording/replay
- `syrupy==4.9.1` — snapshot testing
- `langchain-tests==0.3.20` — LangChain test utilities
## Key Dependencies
- `openai==1.91.0` — direct OpenAI client (also used under LangChain)
- `pinecone==7.3.0` — Pinecone SDK for vector index operations
- `sentence-transformers==3.4.1` — HuggingFace sentence-transformer models; `all-mpnet-base-v2` loaded at startup via `modules/embedding/embedder.py`
- `torch==2.6.0` — required by sentence-transformers
- `transformers==4.48.2` — HuggingFace transformers library
- `scikit-learn==1.6.1` — `TfidfVectorizer` for sparse embeddings
- `tiktoken==0.9.0` — OpenAI token counting
- `numpy==2.2.2` — vector math for sparse embedding generation
- `redis==6.4.0` — Redis client for conversation history persistence (`core/memory.py`)
- `python-jose==3.5.0` — JWT decode and JWK verification for AWS Cognito tokens (`models/JWTBearer.py`)
- `httpx==0.28.1` — async HTTP client
- `httpx-sse==0.4.1` — SSE client support
- `requests==2.32.3` — sync HTTP (used for JWKS endpoint fetch at startup)
- `aiohttp==3.12.13` — async HTTP (used by LangChain internals)
- `orjson==3.10.18` — fast JSON
- `ormsgpack==1.10.0` — MessagePack serialization
## Configuration
- All secrets and runtime config loaded via `python-dotenv==1.0.1` in `core/config.py`
- `.env` file at project root (not committed)
- `db/config.py` uses `pydantic-settings` `BaseSettings` with env file loading
- `Dockerfile` — `python:3.11-slim` base, installs `requirements.txt`, runs as non-root `appuser`
- `docker-compose.yml` — defines `api` service (this app) and `caddy` reverse proxy service
- No build step required; Python is interpreted
## Platform Requirements
- Python 3.11
- Redis (optional; falls back to in-process ephemeral history if unreachable)
- PostgreSQL with SSL (`sslmode=require` in `db/session.py`)
- Pinecone account with 3 indexes (dense Deen, sparse Deen, dense Quran)
- OpenAI API access
- Docker + Docker Compose
- Caddy 2 (reverse proxy with automatic HTTPS via `caddy:2` image)
- External Redis, PostgreSQL, Pinecone, OpenAI, AWS Cognito
- Hostname: `deen-fastapi.duckdns.org` (configured in `caddy/Caddyfile`)
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Summary
## Naming Patterns
- All lowercase with underscores: `chat_persistence_service.py`, `pipeline_langgraph.py`, `hikmah_quiz_service.py`
- Module directories use short lowercase names: `api/`, `agents/`, `core/`, `modules/`, `services/`, `db/`
- One exception: `models/JWTBearer.py` uses PascalCase (class-name-as-filename)
- `PascalCase` throughout: `ChatAgent`, `HikmahQuizService`, `PrimerService`, `CRUDBase`, `ExtraFormatter`, `JWTBearer`
- SQLAlchemy models follow this: `User`, `ChatSession`, `ChatMessage`, `LessonPageQuizQuestion`
- `snake_case` for all functions: `generate_response`, `retrieve_shia_documents`, `build_runtime_session_id`
- Private helpers prefixed with underscore: `_extract_user_id`, `_require_user_id`, `_looks_like_sse_stream`, `_extract_agentic_sse_answer_text`, `_make_db_session`, `_build_graph`
- LangGraph tool names are descriptive verb phrases: `enhance_query_tool`, `retrieve_shia_documents_tool`, `check_if_non_islamic_tool`
- `snake_case`: `user_query`, `session_id`, `target_language`, `runtime_session_id`
- Module-level constants use `UPPER_SNAKE_CASE`: `OPENAI_API_KEY`, `REDIS_URL`, `REFERENCES_MARKER`, `DEFAULT_FORMAT`, `MAX_MESSAGES`
- `snake_case` matching the database column name: `created_at`, `updated_at`, `is_active`, `display_name`
## Code Style
- No enforced formatter detected (no `.prettierrc`, `.flake8`, `pyproject.toml`, or `ruff.toml` in project root)
- Indentation is 4 spaces consistently
- Line length is not strictly enforced; some lines in `modules/generation/stream_generator.py` exceed 100 chars
- Standard library imports first, then third-party, then local — this order is followed in well-maintained files (e.g., `services/chat_persistence_service.py`, `agents/core/chat_agent.py`) but not everywhere
- Local path manipulation with `sys.path.insert(0, ...)` appears at the top of test files to allow running them as scripts:
- `from __future__ import annotations` used in `services/chat_persistence_service.py` for forward references
## Type Annotations
- All functions in `services/` layer carry type hints: return types, parameter types
- `db/crud/base.py` uses `Generic[ModelType, ...]` with `TypeVar`
- `agents/` layer: function signatures in `chat_agent.py` and tools are fully typed
- `core/chat_persistence_service.py`: fully annotated including `Optional`, `List`, `Dict`, `Callable`, `AsyncIterator`
- `modules/retrieval/retriever.py`: `retrieve_documents(query, no_of_docs=10)` — no type hints
- `modules/embedding/embedder.py`: `getSparseEmbedder()` — no type hints, non-snake-case name
- `modules/generation/generator.py`: `generate_response(query: str, retrieved_docs: list)` — `list` not parameterized
- `modules/reranking/reranker.py`: `rerank_documents(dense_results, sparse_results, no_of_docs)` — no types
## Error Handling Patterns
- Catch all exceptions in route handlers and raise `HTTPException`:
- Generic 500 error message intentional — no internal details leaked to client
- Input validation raises `HTTPException(status_code=400, ...)` directly (not from Pydantic)
- `traceback` is imported and used in `api/chat.py`; not all routes use it uniformly
- Raise domain-appropriate errors: `ValueError` for invalid inputs, `LookupError` for not-found resources
- Example from `services/hikmah_quiz_service.py`: `raise LookupError(f"LessonContent {lesson_content_id} not found")`
- Example: `raise ValueError("Exactly one choice must be marked as correct")`
- Wrap DB operations in `try/except` and log errors before re-raising or returning fallback
- Tools return error payloads instead of raising — callers check for `"error"` key in result:
- This keeps the LangGraph graph running even when individual tools fail
- A catch-all HTTP middleware logs the traceback and returns a generic JSON 500:
## Logging Conventions
- Centralized in `core/logging_config.py` via `setup_logging()` and `get_memory_logger()`
- Format: `%(asctime)s [%(levelname)s] %(name)s - %(message)s` with colorized level names
- Extra dict keys on log records appended as `key=value` pairs by `ExtraFormatter`
- Noisy libraries silenced: `sqlalchemy.engine`, `sqlalchemy.pool`, `httpx` set to `WARNING`
- Used in `api/chat.py`, `agents/tools/retrieval_tools.py`, `modules/generation/generator.py`, and scattered throughout older code
- `print()` calls with `[CONTEXT]`-style prefixes appear in tools: `print(f"[retrieve_shia_documents_tool] Error: {e}")`
- Rule: Prefer `logger.*` over `print()` in new code
## Module Design and Pydantic Schemas
- API request/response schemas in `models/schemas.py`: `ChatRequest`, `ElaborationRequest`, `PersonalizedPrimerResponse`, `QuizQuestionCreateRequest`
- DB schemas in `db/schemas/`: `lessons.py`, `users.py`, `user_progress.py`, `personalized_primers.py`
- `model_validator(mode="after")` used for cross-field validation in `QuizQuestionCreateRequest`
- Inherit from `Base` imported from `db/session.py`
- `__tablename__` always defined as a plain string
- Timestamps use `TIMESTAMP(timezone=True)` with `server_default=func.now()`
- `db/crud/base.py` provides generic `CRUDBase[ModelType, CreateSchema, UpdateSchema]`
- Specialized CRUD classes in `db/crud/` extend it: `db/crud/lessons.py`, `db/crud/users.py`, etc.
## Common Patterns
- Streaming responses use `fastapi.responses.StreamingResponse` with `media_type="text/event-stream"`
- SSE format: `event: <name>\ndata: <json>\n\n`
- Events emitted: `status`, `response_chunk`, `response_end`, `hadith_references`, `quran_references`, `done`, `error`
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Summary
## High-Level Pattern
```
```
## Layers and Responsibilities
- Creates the FastAPI `app`, registers all routers, adds CORS and exception-catching middleware.
- Auth dependency (`JWTBearer`) is defined here but currently commented out on most routers (optional auth via `Depends(optional_auth)` in individual routes).
- Exposes `/_debug/db` and `/_routes` debug endpoints.
- One file per feature domain: `chat.py`, `reference.py`, `hikmah.py`, `primers.py`, `memory_admin.py`, `account.py`.
- Responsibility: parse request, extract optional JWT user ID, call into `core/` pipeline or `services/`, return response.
- No business logic lives here; handler bodies are 10–30 lines.
- DB sessions are injected via `Depends(get_db)` from `db/session.py`.
- Auth is optional (`JWTBearer(jwks, auto_error=False)`); authenticated paths get user-scoped Redis history hydration.
- The primary path for all `/chat/stream/agentic` and `/chat/agentic` traffic.
- Instantiates `ChatAgent`, drives it via `agent.astream()` (streaming) or `agent.invoke()` (non-streaming).
- Translates LangGraph node events into SSE events: `status`, `response_chunk`, `response_end`, `hadith_references`, `quran_references`, `error`, `done`.
- Handles the streaming generation step itself (post-retrieval LLM token streaming via `chain.stream()`), since LangGraph hands back retrieved docs before generation.
- Calls `chat_persistence_service.append_turn_to_runtime_history()` after every completed turn.
- Sequential, synchronous pipeline still used by `POST /chat/`, `POST /chat/stream`, and `POST /references`.
- Steps: classify → translate → enhance → retrieve (Shia + Sunni) → generate/stream.
- Returns `StreamingResponse` for streaming variant.
- Defines the `ChatAgent` class: builds a `StateGraph(ChatState)` with 5 nodes and compiles it with `MemorySaver` checkpointing.
- Graph nodes: `fiqh_classification`, `agent`, `tools`, `generate_response`, `check_early_exit`.
- The LLM (`LARGE_LLM`, defaults to `claude-sonnet-4-6`) is bound to 9 tools via `.bind_tools()`.
- Routing decisions (`_should_continue`, `_route_after_fiqh_check`) are pure functions over `ChatState`.
- Loads conversation history from Redis via `core.memory.make_history()` at the start of each `invoke`/`astream` call.
- `ChatState` is a `TypedDict` carrying all state through the graph.
- Key fields: `messages` (LangGraph `add_messages` reducer), `user_query`, `working_query`, `retrieved_docs`, `quran_docs`, `source_coverage`, `early_exit_message`, `errors`, `iterations`.
- `create_initial_state()` is the canonical state factory; always call this — never construct `ChatState` directly.
- `classification_tools.py`: `check_if_non_islamic_tool`, `check_if_fiqh_tool`
- `translation_tools.py`: `translate_to_english_tool`, `translate_response_tool`
- `enhancement_tools.py`: `enhance_query_tool`
- `retrieval_tools.py`: `retrieve_shia_documents_tool`, `retrieve_sunni_documents_tool`, `retrieve_combined_documents_tool`, `retrieve_quran_tafsir_tool`
- All decorated with `@tool` (LangChain). Tool docstrings are consumed by the LLM to decide when to call each tool.
- Each tool delegates directly to the corresponding `modules/` function.
- Pydantic models: `RetrievalConfig`, `ModelConfig`, `AgentConfig`.
- Controls doc counts per source, model/temperature, max iterations, and feature flags (enable_classification, enable_translation, enable_enhancement).
- `DEFAULT_AGENT_CONFIG = AgentConfig()` used when no per-request config is provided.
- Clients can override via the `config` field in the `ChatRequest` body.
- `classification/classifier.py`: Classifies queries as non-Islamic or fiqh using the LLM.
- `embedding/embedder.py`: Dense embeddings (OpenAI `text-embedding-3-small`) and sparse embeddings for hybrid search.
- `retrieval/retriever.py`: Hybrid Pinecone search (dense + sparse) with metadata filtering by `sect` (`shia`/`sunni`). Quran uses a dense-only dedicated index.
- `reranking/reranker.py`: Reranks merged dense+sparse results using configurable weights (`DENSE_RESULT_WEIGHT`, `SPARSE_RESULT_WEIGHT`).
- `enhancement/enhancer.py`: Rewrites the user query to improve retrieval quality.
- `translation/translator.py`: Translates non-English queries to English.
- `generation/generator.py` + `generation/stream_generator.py`: LLM response generation (used by legacy pipeline).
- `context/`: Context assembly utilities.
- `chat_persistence_service.py`: Manages `ChatSession` and `ChatMessage` DB rows, hydrates Redis history from DB on session load, wraps streaming responses to collect and persist assistant text after stream completes.
- `memory_service.py`: Coordinates `UserMemoryProfile` and `MemoryEvent` persistence (structured long-term memory, separate from Redis chat history).
- `consolidation_service.py`: Periodic memory consolidation logic.
- `embedding_service.py`: Generates and stores embeddings for user memory notes.
- `primer_service.py`: Generates baseline and personalized lesson primers, caches results in `personalized_primers` table.
- `hikmah_quiz_service.py`: Hikmah elaboration and quiz logic.
- `account_service.py`: Account management.
- `models/`: SQLAlchemy ORM models (13 tables).
- `schemas/`: Pydantic schemas for API request/response validation.
- `repositories/`: Repository pattern classes wrapping raw SQLAlchemy queries (e.g., `MemoryProfileRepository`, `MemoryEventRepository`).
- `routers/`: CRUD FastAPI routers for `users`, `lessons`, `lesson_content`, `user_progress`, `hikmah_trees` — registered directly in `main.py`.
- `crud/`: Thin CRUD helpers (e.g., `lesson_crud`).
- `session.py`: Sync SQLAlchemy engine (`postgresql+psycopg2`) with SSL, `get_db()` dependency.
- `config.py`: Pydantic `Settings` reading `DB_*` env vars; builds `DATABASE_URL` via `sqlalchemy.engine.URL.create`.
- `make_history(session_id)` returns `RedisChatMessageHistory` when Redis is reachable, falls back to in-process `EphemeralHistory`.
- Keys are namespaced: `{REDIS_KEY_PREFIX}:{session_id}`.
- `trim_history()` enforces `MAX_MESSAGES` cap to prevent unbounded growth.
- `with_redis_history()` wraps a LangChain chain with session-aware history (used by legacy pipeline).
- `_get_vectorstore(index_name)`: Returns `PineconeVectorStore` for dense similarity search.
- `_get_sparse_vectorstore(index_name)`: Returns raw `Pinecone.Index` for sparse or direct vector queries.
- Used exclusively by `modules/retrieval/retriever.py`.
- Loads AWS Cognito JWKS at startup by fetching `/.well-known/jwks.json`.
- `JWTBearer` (in `models/JWTBearer.py`) is a FastAPI `HTTPBearer` dependency that validates JWT signatures against the loaded keys.
- `auth` (strict) and `optional_auth` (permissive) instances used across `api/` routes.
## Data Flow: Agentic Chat (Primary Path)
```
```
## State Management
- `ChatState` TypedDict passed between LangGraph nodes by value within a single request.
- LangGraph `MemorySaver` checkpointer maintains graph state across node executions within one `invoke`/`astream` call, keyed by `thread_id=session_id`.
- Redis `RedisChatMessageHistory` keyed by `{REDIS_KEY_PREFIX}:{session_id}` (or `{user_id}:{session_id}` for authenticated users).
- TTL-capped (default 12,000 seconds) and message-count capped (`MAX_MESSAGES=30`).
- Loaded at the start of each `invoke`/`astream` as `initial_messages`.
- PostgreSQL via SQLAlchemy: `chat_sessions`, `chat_messages` tables store full conversation history.
- `user_memory_profiles` and `memory_events` tables store structured user learning notes.
- `personalized_primers` table caches primer generation results.
## Async vs Sync Patterns
- **FastAPI route handlers** are `async def` throughout.
- **Agentic pipeline streaming** (`chat_pipeline_streaming_agentic`) is fully async: `async for event in agent.astream(...)`, returns `StreamingResponse` with an `AsyncGenerator`.
- **LangGraph graph execution** uses `compiled_graph.astream()` (async) and `compiled_graph.ainvoke()` (async). The legacy sync `compiled_graph.invoke()` path is retained for the legacy pipeline only.
- **LLM calls inside graph nodes** are async (`.ainvoke()`, `.astream()`). The streaming token loop in `pipeline_langgraph.py` uses `chain.astream()` inside an `async def` generator (DEE-40).
- **Database access** is split (DEE-45): the chat router runs on `asyncpg` + `AsyncSession` via `db/async_session.py` (`Depends(get_db_async)`); all other routers still use sync SQLAlchemy via `db/session.py` (`Depends(get_db)`, `psycopg2` driver). Both engines target the same Supabase database — they're built from the same `db/config.py` settings, just different drivers. Per-router migrations to async DB are tracked in DEE-45 follow-up sub-issues.
- **Redis** is accessed asynchronously via the in-house `AsyncRedisChatMessageHistory` wrapper backed by `redis.asyncio` (DEE-43); the sync `RedisChatMessageHistory` from `langchain_community` is kept only for legacy code paths.
## Early Exit Conditions
## Error Handling
- **Global middleware** in `main.py` (`catch_exceptions_mw`) catches all unhandled exceptions, logs the traceback, and returns `{"detail": "internal_error"}` with HTTP 500.
- **Route handlers** have explicit try/except blocks, logging to stdout and raising `HTTPException(500)`.
- **LangGraph nodes** catch exceptions internally, append to `state["errors"]`, and set `state["should_end"] = True` rather than raising.
- **Tool functions** (`agents/tools/`) catch exceptions and return error dicts (`{"error": str(e), "documents": []}`) rather than raising, preventing graph termination on retrieval failure.
- **Streaming error recovery**: if `assistant_text` was partially collected before an error, `pipeline_langgraph.py` still attempts to persist it to Redis history.
## Key Architectural Decisions
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
