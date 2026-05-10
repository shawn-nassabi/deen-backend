# Technology Stack

**Analysis Date:** 2026-05-09

## Languages

**Primary:**
- Python 3.11 — all application code (Dockerfile base: `python:3.11-slim`; system: 3.11.7)

**Secondary:**
- None — the project is pure Python

## Runtime

**Environment:**
- CPython 3.11 (system version: 3.11.7)
- Virtual environment: `venv/` at project root

**Package Manager:**
- `pip` — no Poetry or pipenv
- Lockfile: `requirements.txt` (pinned versions, committed)

## Frameworks

**HTTP / ASGI:**
- `fastapi==0.115.8` — route definitions, dependency injection, middleware (`main.py`)
- `starlette==0.45.3` — ASGI foundation; SSE streaming via `StreamingResponse`
- `uvicorn==0.34.0` — ASGI server for local dev (`uvicorn main:app --reload`)
- `gunicorn==23.0.0` — production process manager with 2 Uvicorn workers (`-w 2`, `UvicornWorker`)

**LLM / Agentic:**
- `langchain==0.3.27` — core LangChain framework; prompt templates, runnables, history
- `langchain-core==0.3.84` — base abstractions
- `langchain-anthropic==0.3.22` — `ChatAnthropic` bindings; **primary LLM provider** (migrated from OpenAI in DEE-42); initialized via `core/chat_models.py`
- `langchain-openai==0.3.25` — retained as transitive dependency; not used for active LLM calls
- `langchain-community==0.3.27` — `RedisChatMessageHistory` (sync fallback), `ChatMessageHistory`
- `langchain-pinecone==0.2.8` — `PineconeVectorStore` integration (`core/vectorstore.py`)
- `langchain-huggingface==0.1.2` — `HuggingFaceEmbeddings` for dense embedding (`modules/embedding/embedder.py`)
- `langchain-tests==0.3.20` — LangChain test utilities
- `langgraph==0.2.64` — agentic graph orchestration; active pipeline in `core/pipeline_langgraph.py`
- `langgraph-checkpoint==2.1.1` — LangGraph state checkpointing (`MemorySaver`)
- `langgraph-sdk==0.1.74` — LangGraph SDK utilities
- `langsmith==0.4.4` — tracing/observability; installed as transitive dep, no explicit API key configured

**Database / ORM:**
- `SQLAlchemy==2.0.41` — ORM + Core; sync engine in `db/session.py`, async engine in `db/async_session.py`
- `alembic==1.14.0` — schema migrations; config in `alembic.ini`, 11 migration files in `alembic/versions/`
- `psycopg2-binary==2.9.10` — sync PostgreSQL driver (`postgresql+psycopg2`); used by all non-chat routers
- `asyncpg==0.30.0` — async PostgreSQL driver (`postgresql+asyncpg`); used by chat persistence (DEE-45) via `db/async_session.py`
- `pgvector==0.3.6` — PostgreSQL vector extension; `Vector` columns in `db/models/embeddings.py`

**Validation / Settings:**
- `pydantic==2.10.6` — request/response models, config validation (`models/schemas.py`, `db/schemas/`)
- `pydantic-settings==2.10.1` — `BaseSettings` for `db/config.py`

**Testing:**
- `pytest==8.4.1` — test runner; config in `pytest.ini`
- `pytest-asyncio==0.26.0` — async test support
- `pytest-benchmark==5.1.0` — performance benchmarks
- `pytest-recording==0.13.4` — VCR cassette-based HTTP recording
- `pytest-socket==0.7.0` — network isolation for unit tests
- `pytest-codspeed==3.2.0` — CodSpeed CI performance profiling
- `vcrpy==7.0.0` — HTTP interaction recording/replay
- `syrupy==4.9.1` — snapshot testing (SSE event-order snapshots; `tests/test_sse_event_order_snapshot.py`)
- `fakeredis==2.26.1` — in-process Redis fake for test isolation (`tests/test_async_memory.py`)

## LLM Models

**Large (planning, generation, classification, translation):**
- Default: `claude-sonnet-4-6` (env: `LARGE_LLM`)
- `get_generator_model()` — `max_tokens=4096`
- `get_classifier_model()` — `max_tokens=2048`
- `get_translator_model()` — `max_tokens=1024`, `temperature=0`
- All initialized via `core/chat_models.py` using `ChatAnthropic`

**Small (query enhancement):**
- Default: `claude-haiku-4-5-20251001` (env: `SMALL_LLM`)
- `get_enhancer_model()` — `max_tokens=512`
- Initialized via `core/chat_models.py`

**Provider:** Anthropic via `langchain-anthropic`. The `.ainvoke()` / `.astream()` interface is provider-agnostic. `langchain-openai` is retained as a dependency but unused for active LLM calls.

## Key Dependencies

**AI Pipeline (critical):**
- `anthropic==0.92.0` — underlying Anthropic SDK (used under LangChain)
- `openai==1.91.0` — retained as dependency; not used for active LLM generation
- `pinecone==7.3.0` — Pinecone SDK; async query via `PineconeAsyncio.asimilarity_search_with_score` (DEE-42; `modules/retrieval/retriever.py`)
- `pinecone-text==0.11.0` — `BM25Encoder` for fiqh sparse retrieval (`modules/fiqh/retriever.py`, `scripts/ingest_fiqh.py`)
- `sentence-transformers==3.4.1` — `all-mpnet-base-v2` loaded at startup; 768-dim dense embeddings (`modules/embedding/embedder.py`)
- `torch==2.6.0` — required by sentence-transformers
- `transformers==4.48.2` — HuggingFace transformers library
- `scikit-learn==1.6.1` — `TfidfVectorizer` for sparse embeddings in main pipeline (`modules/embedding/embedder.py`)
- `numpy==2.2.2` — vector math for sparse embedding generation

**Infrastructure:**
- `redis==6.4.0` — Redis client; async path via `redis.asyncio` in `core/memory.py` (DEE-43)
- `sentry-sdk[fastapi]==2.35.2` — error tracking; auto-enables `FastApiIntegration` + `StarletteIntegration`; `LoggingIntegration` configured explicitly (`core/sentry.py`); PII scrubbing via `before_send` hook
- `python-jose==3.5.0` — JWT decode and JWK verification for Supabase auth tokens (`models/JWTBearer.py`)
- `httpx==0.28.1` — async HTTP client
- `httpx-sse==0.4.1` — SSE client support (used in tests)
- `requests==2.32.3` — sync HTTP; JWKS endpoint fetch at startup (`core/auth.py`)
- `aiohttp==3.12.13` — async HTTP used by LangChain internals
- `orjson==3.10.18` — fast JSON serialization
- `ormsgpack==1.10.0` — MessagePack serialization
- `PyMuPDF==1.27.2.2` — PDF parsing for fiqh corpus ingestion (`scripts/ingest_fiqh.py` via `import fitz`)
- `nltk==3.9.3` — text preprocessing for BM25 encoder
- `tiktoken==0.9.0` — token counting
- `tenacity==9.1.2` — retry logic

## Configuration

**Environment:**
- All secrets and runtime config loaded via `python-dotenv==1.0.1` in `core/config.py`
- `.env` file at project root (gitignored, never committed)
- `db/config.py` uses `pydantic-settings` `BaseSettings` with env file loading; accepts `DB_*`, `POSTGRES_*`, and `PG*` aliases

**Startup guards:**
- `ANTHROPIC_API_KEY` and `PINECONE_API_KEY` raise `ValueError` at import time in `core/config.py`
- `DEEN_DENSE_INDEX_NAME` and `DEEN_SPARSE_INDEX_NAME` raise `ValueError` at import time
- `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` validated via `validate_supabase_config()` in `main.py` lifespan hook
- Missing `data/fiqh_bm25_encoder.json` logs a `WARNING` at startup with remediation command

**Required env vars:**
```
ANTHROPIC_API_KEY
PINECONE_API_KEY
DEEN_DENSE_INDEX_NAME
DEEN_SPARSE_INDEX_NAME
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
DATABASE_URL  (or DB_HOST + DB_PORT + DB_NAME + DB_USER + DB_PASSWORD)
ASYNC_DATABASE_URL  (or same individual vars)
```

**Optional env vars (defaults shown):**
```
LARGE_LLM=claude-sonnet-4-6
SMALL_LLM=claude-haiku-4-5-20251001
QURAN_DENSE_INDEX_NAME
DEEN_FIQH_DENSE_INDEX_NAME
DEEN_FIQH_SPARSE_INDEX_NAME
REDIS_URL=redis://localhost:6379/0
REDIS_KEY_PREFIX=dev:chat
REDIS_TTL_SECONDS=12000
REDIS_MAX_MESSAGES=30
DENSE_RESULT_WEIGHT=0.8
SPARSE_RESULT_WEIGHT=0.2
REFERENCE_FETCH_COUNT=10
EMBEDDING_MODEL=sentence-transformers/all-mpnet-base-v2
EMBEDDING_DIMENSIONS=768
NOTE_FILTER_THRESHOLD=0.4
SIGNAL_QUALITY_THRESHOLD=0.5
CORS_ALLOW_ORIGINS=https://deen-frontend.vercel.app
ENV=development
SENTRY_DSN=
SENTRY_ENABLED=false
```

**Build:**
- No build step; Python is interpreted
- `Dockerfile` — `python:3.11-slim` base, `pip install -r requirements.txt`, runs BM25 encoder generation (`RUN python scripts/ingest_fiqh.py --encoder-only`), non-root `appuser`, exposes port 8000
- `docker-compose.yml` — `api` service (this app) + `caddy` reverse proxy (`caddy:2` image)
- `caddy/Caddyfile` — reverse proxies `api:8000`, hostname: `deen-fastapi.duckdns.org`, gzip encoding

## Async Architecture (DEE-40 through DEE-46)

All async migrations are complete for the agentic chat path:

| Component | Mechanism | File |
|-----------|-----------|------|
| LLM streaming | `chain.astream()` (DEE-40) | `core/pipeline_langgraph.py` |
| Graph execution | `compiled_graph.astream()` / `.ainvoke()` | `core/pipeline_langgraph.py` |
| ChatAgent nodes + `@tool` functions | `async def` (DEE-41) | `agents/core/chat_agent.py`, `agents/tools/` |
| LLM modules | `.ainvoke()` / `.astream()` (DEE-42) | `modules/classification/`, `modules/enhancement/`, etc. |
| Pinecone retrieval | `PineconeAsyncio.asimilarity_search_with_score` (DEE-42) | `modules/retrieval/retriever.py` |
| Redis history | `redis.asyncio` + `AsyncRedisChatMessageHistory` (DEE-43) | `core/memory.py` |
| Fiqh subgraph | `fiqh_subgraph.ainvoke()` (DEE-44) | `agents/fiqh/fiqh_graph.py` |
| Chat DB persistence | `asyncpg` + `AsyncSession`, `Depends(get_db_async)` (DEE-45) | `db/async_session.py` |
| Other DB routes | `psycopg2` + sync `Session`, `Depends(get_db)` | `db/session.py` |

## Platform Requirements

**Development:**
- Python 3.11
- Redis optional; falls back to in-process `AsyncEphemeralHistory` / `EphemeralHistory`
- PostgreSQL with SSL (`sslmode=require` / `ssl="require"`)
- Pinecone account with 5 indexes (dense Deen, sparse Deen, dense Quran, dense Fiqh, sparse Fiqh)
- Anthropic API access
- Run `python scripts/ingest_fiqh.py --encoder-only` to generate `data/fiqh_bm25_encoder.json` (gitignored, required for fiqh queries)

**Production:**
- Docker + Docker Compose
- Caddy 2 reverse proxy with automatic HTTPS (DuckDNS hostname)
- Gunicorn with 2 Uvicorn workers
- Self-hosted GitHub Actions runner on Hetzner (label: `dev-deploy`); deploy via `.github/workflows/deploy-dev.yml` (manual `workflow_dispatch`, DEE-47)
- External: Redis, PostgreSQL (Supabase-hosted), Pinecone, Anthropic, Supabase Auth

---

*Stack analysis: 2026-05-09*
