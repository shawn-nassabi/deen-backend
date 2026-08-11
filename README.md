# Deen Backend - AI-Powered Islamic Education Platform

This is the backend service for the **Deen AI platform**, built with **FastAPI**. It provides intelligent API endpoints for Islamic education, featuring a RAG-powered chatbot, reference lookup system, and AI-driven learning courses (Hikmah Trees) with adaptive memory capabilities.

## Features

- **AI Chatbot** - Conversational AI with RAG pipeline for Islamic Q&A
- **Reference Lookup** - Semantic search across Islamic texts (Shia & Sunni sources)
- **Hikmah Trees** - AI-powered courses and lessons with interactive elaboration
- **Universal Memory Agent** - Intelligent system that learns from user interactions
- **Streaming Responses** - Real-time AI response streaming for better UX
- **Multi-language Support** - Translation capabilities for global accessibility

## Quick Start

### Prerequisites

- **Python 3.11** (matches `Dockerfile` and CI; 3.13 may work but `requirements.txt` versions aren't pinned to 3.13 wheels)
- Supabase account (Postgres + Auth)
- Pinecone account (for vector search) — 5 indices: hadith dense/sparse, Quran dense, fiqh dense/sparse
- Anthropic API key
- Redis server (optional — falls back to in-process ephemeral history if unreachable)

### 1. Clone and Setup Virtual Environment

```bash
# Clone the repository
git clone <repository-url>
cd deen-backend

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On macOS/Linux
venv\Scripts\activate      # On Windows
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the root directory by copying the template:

```bash
cp .env.example .env
# Edit .env and fill in your real values.
# See the "Environment Variables" section below for descriptions of each variable.
```

### 4. Run Database Migrations

```bash
alembic upgrade head
```

### 5. Generate the fiqh BM25 encoder (first-time only)

```bash
python scripts/ingest_fiqh.py --encoder-only
```

`data/fiqh_bm25_encoder.json` is **gitignored** and regenerated either at Docker build time (`Dockerfile`) or via this command on a fresh local clone. Without it, fiqh queries silently fall back to the polished refusal message because sparse retrieval throws inside `_get_bm25_encoder`. `main.py`'s lifespan logs a WARNING with the exact remediation command if the file is missing, so you'll see this in the server log if you skip it.

This step does **not** touch Pinecone — it just parses the local PDF and fits BM25 weights. Takes 1–2 minutes.

### 6. Start the development server

```bash
uvicorn main:app --port 8080 --reload --host 0.0.0.0
```

The server will start at `http://127.0.0.1:8080`. Set `ENV=development` in `.env` to enable `DevBypassBearer` — every protected route accepts requests with no `Authorization` header during local testing (mock user `dev-user-001`). Set `ENV=production` to enforce strict JWT validation.

### 7. Access API Documentation

- **Swagger UI**: `http://127.0.0.1:8080/docs` (with `ENV=development`, every endpoint is callable without clicking Authorize)
- **ReDoc**: `http://127.0.0.1:8080/redoc`
- **Memory Admin Dashboard**: `http://127.0.0.1:8080/admin/memory/dashboard`
- **Route list**: `http://127.0.0.1:8080/_routes`
- **DB ping**: `http://127.0.0.1:8080/_debug/db`
- **Health check**: `http://127.0.0.1:8080/health`

## Setting Up a New Supabase Project

Use this when provisioning a new environment (e.g. staging → prod). The steps below recreate the database schema and auth configuration from scratch.

### 1. Create the Supabase project

Create a new project in the [Supabase dashboard](https://supabase.com/dashboard). Once provisioned, collect the following from **Project Settings → API**:

- **Project URL** → `SUPABASE_URL`
- **`service_role` key** → `SUPABASE_SERVICE_ROLE_KEY`
- **DB password** (set during project creation)
- **Connection string** → Database → Connection string → URI (use port **5432**)

### 2. Configure environment variables

```bash
cp .env.example .env
# Fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, DATABASE_URL, ASYNC_DATABASE_URL
```

#### Choosing the right Supabase connection string

Supabase exposes three ways to connect to Postgres. Pick one based on your environment:

| Mode | Host | Port | IPv4? | Notes |
|---|---|---|---|---|
| Direct | `db.<ref>.supabase.co` | `5432` | No (IPv6 only in most regions) | Avoid on Hetzner / Docker |
| **Session Pooler** | `aws-0-<region>.pooler.supabase.com` | `5432` | **Yes** | Recommended for Hetzner / Docker |
| Transaction Pooler | `aws-0-<region>.pooler.supabase.com` | `6543` | Yes | Incompatible with asyncpg / Alembic |

**Hetzner servers and Docker do not have IPv6 enabled by default.** If you use the direct `db.<ref>.supabase.co` host, connections will time out or fail with a "Network is unreachable" error. Use the **Session Pooler** (port `5432` on the pooler host) instead — it is IPv4-compatible and behaves identically to a direct connection for SQLAlchemy and asyncpg.

The Session Pooler URL looks like this (copy it from **Supabase Dashboard → Project Settings → Database → Connection string → Session pooler**):

```
DATABASE_URL=postgresql://postgres.xxxx:password@aws-0-us-east-1.pooler.supabase.com:5432/postgres
ASYNC_DATABASE_URL=postgresql+asyncpg://postgres.xxxx:password@aws-0-us-east-1.pooler.supabase.com:5432/postgres
```

> **Do not use port `6543`** (Transaction Pooler). It does not support prepared statements, which asyncpg and Alembic require.

### 3. Run database migrations

```bash
source venv/bin/activate
alembic upgrade head
```

This runs all migrations in order and creates all 13 tables. The command is idempotent — safe to re-run.

### 4. Configure Supabase Auth

The backend validates JWTs only — no manual key configuration is needed. The JWKS endpoint is fetched automatically at startup from `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`.

In the Supabase dashboard → **Authentication → Providers**:

- Enable **Email** (or whichever providers the frontend uses)
- Set redirect URLs and JWT expiry to match your environment

### Full sequence

```bash
cp .env.example .env          # fill in prod values
alembic upgrade head           # create all tables
docker compose up -d           # or: uvicorn main:app --reload
```

## Architecture Overview

The Deen backend follows a modular, end-to-end async architecture with clear separation of concerns. As of DEE-36 (closed), the streaming agentic chat hot path is fully non-blocking from HTTP boundary down to LLM, Pinecone, Redis, and Postgres I/O.

```
deen-backend/
├── api/              # FastAPI route handlers (thin, async)
├── core/             # Pipeline orchestration, auth, memory, vectorstore, sentry
├── modules/          # AI pipeline stages: classification, embedding, retrieval,
│                     # reranking, generation, translation, fiqh subsystem
├── agents/           # LangGraph agent + tools + state + fiqh subgraph
├── db/               # SQLAlchemy models, sync session, async session, Pydantic
│                     # config, repositories, CRUD routers
├── services/         # Business services (chat persistence, memory, primers, ...)
├── scripts/          # Operational scripts (fiqh ingest, loadtest, reembed)
├── tests/            # Unit + integration + concurrency + SSE-snapshot tests
└── alembic/          # 11 sync DB migrations (asyncpg migrations not supported)
```

### Request flow — `POST /chat/stream/agentic`

```
HTTP request
  │
  ▼
api/chat.py  (async route, Depends(get_db_async) -> AsyncSession on Supabase)
  │
  ├── chat_persistence_service.hydrate_runtime_history_if_empty()
  │     └── async Redis (AsyncRedisChatMessageHistory) + async Postgres backfill
  ├── chat_persistence_service.persist_user_message()
  │
  ▼
core/pipeline_langgraph.chat_pipeline_streaming_agentic()
  │
  ▼
agents/core/chat_agent.ChatAgent.astream()    (LangGraph, all nodes async)
  │
  ├── fiqh_classification_node     (await aclassify_fiqh_query)
  ├── agent_node                   (await llm.ainvoke -> tool_calls)
  ├── tools_node                   (concurrent tool invocations)
  │     ├── retrieve_shia_documents_tool       (PineconeAsyncio)
  │     ├── retrieve_sunni_documents_tool      (PineconeAsyncio)
  │     ├── retrieve_quran_tafsir_tool         (PineconeAsyncio)
  │     ├── enhance_query_tool                 (await aenhance_query)
  │     └── ...
  ├── (conditional fiqh_subgraph) (5-node decompose -> retrieve -> filter ->
  │                                 assess -> refine, all async)
  └── generate_response_node       (chain.astream(): per-token SSE streaming)
  │
  ▼
SSE events: status, response_chunk, response_end, hadith_references,
            quran_references, fiqh_references, done
  │
  ▼
chat_persistence_service.wrap_streaming_response_for_persistence()
  └── awaits persist_assistant_message() on AsyncSession after stream completes
```

### Async architecture (DEE-36 — closed)

The migration shipped across phases DEE-39 through DEE-46. Concurrency benchmarks live in [`documentation/async_baseline.md`](documentation/async_baseline.md) — at N=10 in-process concurrent requests with deterministic stub latencies, p95 dropped from **3.44s** (phase-0 baseline, sync) to **0.94s** (phase-7 close-out) — a >3× win on top of the speedup the underlying parallelism gives.

| Phase | Linear | What it changed |
|-------|--------|-----------------|
| 0 | DEE-39 | Concurrency baseline + shared deterministic stubs (`tests/conftest_async_stubs.py`) + loadtest CLI |
| 1 | DEE-40 | `chain.stream` → `chain.astream` in agentic streaming generators |
| 2 | DEE-41 | All ChatAgent nodes + `@tool` functions converted to `async def` |
| 3 | DEE-42 | Native async LLM modules + Pinecone retrieval (`PineconeAsyncio`) |
| 4 | DEE-43 | `AsyncRedisChatMessageHistory` over `redis.asyncio` |
| 5 | DEE-44 | `/references`, `/hikmah/elaborate`, fiqh subgraph natively async |
| 6 | DEE-45 | Async DB (asyncpg + `AsyncSession`) for chat persistence; chat router on `Depends(get_db_async)` |
| 7 | DEE-46 | Automated verification gates (`tests/test_async_concurrency_full.py`, `test_sse_event_order_snapshot.py`, `test_sentry_async_propagation.py`); opt-in real-Anthropic perf gate |

What's still synchronous (deliberately):
- Routers other than `chat.*` — primer, lessons, hikmah, onboarding, account, memory_admin — keep `Depends(get_db)`. Each migrates atomically in its own DEE-45 follow-up sub-issue.
- Alembic migrations stay on the sync engine (recommended; SQLAlchemy async migrations are still rough).

### Token-cost architecture (DEE-60 — closed)

Input-token spend on the agentic path was cut **~56% per answer (−83% raw input tokens)** with answer quality blind-judged equal-or-better at every step. Full narrative: [`documentation/DEE-60-token-cost-changes.md`](documentation/DEE-60-token-cost-changes.md); raw per-phase bench snapshots: [`documentation/token_baseline.md`](documentation/token_baseline.md).

| Phase | What it changed | Kill-switch (env, default on) |
|-------|-----------------|-------------------------------|
| 0 | Per-call-site token telemetry (`core/token_telemetry.py`) + 32-question live bench with blind A/B judge (`scripts/token_bench.py`) | — |
| 1 | Fiqh streaming + `fiqh_references` restoration; redundant classifier tool unbound; doc-count clamps; `max_iterations` 3; prompt trims | — |
| 2 | Payload diet: metadata whitelists (compressed blobs eliminated), compact planner ToolMessages, read-side history budgets | `TOOLMSG_COMPACT`, `HISTORY_BUDGETS` |
| 3 | Prompt-cache architecture: append-only agent loop (system every iteration, rolling breakpoints), cache-aware generator prompt | `AGENT_CACHE_V2` |
| 4 | Fiqh: single decompose per query (all sub-queries now retrieve), ≤30-doc filter cap, retries 18 → 6 | `FIQH_V2_RETRIEVAL` |
| 5 | Long-chat background Haiku summaries past the history budget | `HISTORY_SUMMARY` |

Bench anytime: start the server with `TOKEN_BENCH_DEBUG=1`, then `python scripts/token_bench.py --label <name>`; compare quality with `python scripts/token_bench.py --judge phase-4 <name>`.

For the deeper component breakdown, see [Architecture Documentation](documentation/ARCHITECTURE.md), [AI Pipeline](documentation/AI_PIPELINE.md), and [Chatbot](documentation/CHATBOT.md).

## Core Features Documentation

### AI & RAG Pipeline

- [**Chatbot**](documentation/CHATBOT.md) - RAG-powered conversational AI with query classification and context-aware responses
- [**Reference Lookup**](documentation/REFERENCE_LOOKUP.md) - Semantic search across Islamic texts with sect filtering
- [**AI Pipeline**](documentation/AI_PIPELINE.md) - Detailed breakdown of classification, embedding, retrieval, and generation modules

### Learning Platform

- [**Hikmah Trees**](documentation/HIKMAH_TREES.md) - AI-powered courses and lessons with interactive elaboration
- [**Memory Agent**](documentation/MEMORY_AGENT.md) - Universal memory system that learns from user interactions

### Technical Documentation

- [**Database**](documentation/DATABASE.md) - PostgreSQL schema, models, and migrations
- [**API Reference**](documentation/API_REFERENCE.md) - Complete API endpoint documentation
- [**Authentication**](documentation/AUTHENTICATION.md) - Supabase Auth JWT authentication setup (v1.1+)
- [**Deployment**](#production-deployment-hetzner) - Hetzner production deployment (see README above)

## Tooling and Tech Stack

| Layer | Library / Service | Notes |
|-------|------------------|-------|
| Web framework | `fastapi==0.115.8`, `starlette==0.45.3` | Async route handlers; SSE via `StreamingResponse` |
| ASGI server | `uvicorn==0.34.0` (dev), `gunicorn==23.0.0` w/ `UvicornWorker` (prod) | |
| Agent framework | `langgraph==0.2.64` | Active pipeline in `core/pipeline_langgraph.py`; fiqh subgraph in `agents/fiqh/fiqh_graph.py` |
| LLM SDK | `anthropic==0.92.0` via `langchain-anthropic==0.3.22` | `LARGE_LLM=claude-sonnet-4-6`, `SMALL_LLM=claude-haiku-4-5-20251001` |
| Vector DB | `pinecone==7.3.0` (async via `PineconeAsyncio`), `langchain-pinecone==0.2.8` | 5 indices: hadith dense/sparse, Quran dense, fiqh dense/sparse |
| Embeddings | `sentence-transformers==3.4.1` (`all-mpnet-base-v2`, 768-dim) for memory; OpenAI `text-embedding-3-small` for hadith dense | |
| Cache / history | `redis==6.4.0` (async via `redis.asyncio`) | `AsyncRedisChatMessageHistory` wrapper in `core/memory.py` |
| Auth | Supabase Auth (JWT) via `python-jose==3.5.0` | Dev bypass when `ENV=development` (see `models/JWTBearer.py:DevBypassBearer`) |
| Database | `SQLAlchemy==2.0.41` + `asyncpg==0.30.0` (async) + `psycopg2-binary==2.9.10` (sync) + `pgvector==0.3.6` | Same Supabase DB target via both engines; 11 Alembic migrations |
| Observability | `sentry-sdk` (FastApi auto-integration) + `langsmith==0.4.4` | Per-request `correlation_id` via `core/middleware.CorrelationIdMiddleware`; `bind_sentry_scope` per route |
| Test runner | `pytest==8.4.1`, `pytest-asyncio==0.26.0` | Custom marker `real_llm` opt-in; per-test `@pytest.mark.asyncio` decoration |
| Test fixtures | `fakeredis`, `aiosqlite==0.20.0`, `syrupy==4.9.1` (snapshot), `pytest-socket==0.7.0` (network isolation) | |
| Reverse proxy | `caddy:2` Docker image | Auto-HTTPS via Let's Encrypt |
| Container | `python:3.11-slim` base | Non-root `appuser`; fiqh BM25 encoder generated at build time

## Environment Variables

Copy `.env.example` to `.env` and fill in the real values. All variables are described below.

> **Upgrading from v1.0?** Remove `COGNITO_REGION` and `COGNITO_POOL_ID` from your `.env` — these are no longer used. Add `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` instead.

### Anthropic

| Variable            | Required | Description                                                                                     |
| ------------------- | -------- | ----------------------------------------------------------------------------------------------- |
| `ANTHROPIC_API_KEY` | Yes      | Anthropic API key. Get from [console.anthropic.com](https://console.anthropic.com)              |
| `LARGE_LLM`         | Yes      | Large model ID for generation, filtering, refinement. Default: `claude-sonnet-4-6`              |
| `SMALL_LLM`         | Yes      | Small model ID for classification, routing, decomposition. Default: `claude-haiku-4-5-20251001` |

### Pinecone

| Variable                      | Required | Description                                                                                      |
| ----------------------------- | -------- | ------------------------------------------------------------------------------------------------ |
| `PINECONE_API_KEY`            | Yes      | Pinecone API key. Get from [app.pinecone.io](https://app.pinecone.io)                            |
| `DEEN_DENSE_INDEX_NAME`       | Yes      | Dense vector index for hadith/Islamic content                                                    |
| `DEEN_SPARSE_INDEX_NAME`      | Yes      | Sparse vector index for hadith/Islamic content                                                   |
| `QURAN_DENSE_INDEX_NAME`      | No       | Dense vector index for Quran tafsir                                                              |
| `DEEN_FIQH_DENSE_INDEX_NAME`  | No\*     | Dense vector index for Sistani fiqh rulings. \*Required for fiqh queries                         |
| `DEEN_FIQH_SPARSE_INDEX_NAME` | No\*     | Sparse vector index for Sistani fiqh rulings. \*Required for fiqh queries                        |
| `DENSE_RESULT_WEIGHT`         | No       | Weight for dense retrieval results (default: `0.8`). Must sum to 1.0 with `SPARSE_RESULT_WEIGHT` |
| `SPARSE_RESULT_WEIGHT`        | No       | Weight for sparse retrieval results (default: `0.2`)                                             |
| `REFERENCE_FETCH_COUNT`       | No       | Number of references to fetch per query (default: `10`)                                          |

### Supabase

| Variable                    | Required | Description                                                                           |
| --------------------------- | -------- | ------------------------------------------------------------------------------------- |
| `SUPABASE_URL`              | Yes      | Project URL. Supabase Dashboard → Project Settings → API                              |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes      | Service role secret key. Supabase Dashboard → Project Settings → API → `service_role` |

### Database

Provide either `DATABASE_URL` / `ASYNC_DATABASE_URL` directly, or provide all `DB_*` components and the app will build the URL.

On Hetzner or Docker (IPv4-only), use the **Session Pooler** URL (port `5432` on `pooler.supabase.com`). Do **not** use port `6543` (Transaction Pooler) — it is incompatible with asyncpg and Alembic. See [Choosing the right Supabase connection string](#choosing-the-right-supabase-connection-string) for details.

| Variable             | Required | Description                                                     |
| -------------------- | -------- | --------------------------------------------------------------- |
| `DATABASE_URL`       | Yes\*    | Sync PostgreSQL connection string (`postgresql://...`)          |
| `ASYNC_DATABASE_URL` | Yes\*    | Async PostgreSQL connection string (`postgresql+asyncpg://...`) |
| `DB_HOST`            | Yes\*    | Database host (alternative to `DATABASE_URL`)                   |
| `DB_PORT`            | No       | Database port (default: `5432`)                                 |
| `DB_NAME`            | Yes\*    | Database name (alternative to `DATABASE_URL`)                   |
| `DB_USER`            | Yes\*    | Database user (alternative to `DATABASE_URL`)                   |
| `DB_PASSWORD`        | Yes\*    | Database password (alternative to `DATABASE_URL`)               |

_Either `DATABASE_URL` + `ASYNC_DATABASE_URL`, or all `DB\__` components must be provided.

### Redis

| Variable             | Required | Description                                                                                                           |
| -------------------- | -------- | --------------------------------------------------------------------------------------------------------------------- |
| `REDIS_URL`          | No       | Redis connection URL (default: `redis://localhost:6379/0`). Falls back to in-process ephemeral history if unreachable |
| `REDIS_KEY_PREFIX`   | No       | Namespace prefix for Redis keys (default: `dev:chat`)                                                                 |
| `REDIS_TTL_SECONDS`  | No       | Conversation TTL in seconds (default: `12000` ~3.3 hours)                                                             |
| `REDIS_MAX_MESSAGES` | No       | Max messages kept per session (default: `30`)                                                                         |

### Memory / Personalization

| Variable                   | Required | Description                                                                                                                                                           |
| -------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `EMBEDDING_MODEL`          | No       | HuggingFace embedding model for user memory note vectors (default: `sentence-transformers/all-mpnet-base-v2`). Must match the dimension count of the pgvector columns |
| `EMBEDDING_DIMENSIONS`     | No       | Vector dimension count matching `EMBEDDING_MODEL` (default: `768`)                                                                                                    |
| `NOTE_FILTER_THRESHOLD`    | No       | Minimum cosine similarity score (0.0-1.0) for a memory note to be injected into context (default: `0.4`)                                                              |
| `SIGNAL_QUALITY_THRESHOLD` | No       | Minimum quality score (0.0-1.0) required before a memory signal is persisted (default: `0.5`)                                                                         |

### App

| Variable             | Required | Description                                                                                       |
| -------------------- | -------- | ------------------------------------------------------------------------------------------------- |
| `ENV`                | No       | Runtime environment. `development` enables auth bypass for local testing (default: `development`) |
| `CORS_ALLOW_ORIGINS` | No       | Comma-separated list of allowed CORS origins (default: `*`)                                       |

## Development Tools

### Memory Admin Dashboard

Access the interactive developer dashboard to inspect and debug the memory agent:

```
http://localhost:8080/admin/memory/dashboard
```

Features:

- View user memory profiles
- Browse notes by category (learning, knowledge, interest, behavior, preference)
- Inspect memory events and processing status
- View consolidation history

See [Memory Agent Documentation](documentation/MEMORY_AGENT.md) for details.

### Embedding Backfill

`scripts/reembed_pgvector.py` regenerates pgvector embeddings for lesson chunks and user memory notes using the current embedding model (HuggingFace `all-mpnet-base-v2`, 768-dim).

**When to run this:**

- **After switching the embedding model** — the embedding tables are dropped and recreated empty when vector dimensions change (e.g., the Phase 10 migration from OpenAI 1536-dim to HuggingFace 768-dim). Run this script immediately after `alembic upgrade head` to repopulate them.
- **On a fresh database with existing lesson content** — if you restore a DB snapshot that has lessons but empty embedding tables, run this to regenerate.
- **`lesson_chunk_embeddings` table is empty** — the primers and memory personalization features depend on this table. If it's empty, similarity search will return no results.

The script is safe to re-run at any time — it uses content hashing to skip rows that haven't changed.

```bash
# Check current embedding counts before running
python scripts/reembed_pgvector.py --stats-only

# Backfill everything (lesson chunks + user memory note embeddings)
python scripts/reembed_pgvector.py

# Backfill only lesson chunk embeddings
python scripts/reembed_pgvector.py --lessons-only

# Backfill only user memory note embeddings
python scripts/reembed_pgvector.py --notes-only

# Backfill notes for a single user
python scripts/reembed_pgvector.py --notes-only --user-id <user_id>

# Tune commit batch size (default: 50 lessons / 100 notes)
python scripts/reembed_pgvector.py --batch-size 25
```

**Prerequisites:** `DATABASE_URL` must be set in `.env`. The HuggingFace model (`all-mpnet-base-v2`) downloads automatically on first use (~420 MB) and is cached locally for subsequent runs.

### Health Check Endpoints

```bash
# General health check
curl http://localhost:8080/health

# Database connection check
curl http://localhost:8080/_debug/db

# List all routes
curl http://localhost:8080/_routes
```

## Production Deployment (Hetzner)

The backend runs on a **Hetzner Cloud** server with Docker. Caddy handles TLS termination and reverse-proxies to the FastAPI container.

```
Internet → api.thedeenfoundation.com (Caddy :443) → FastAPI container (:8000)
```

### Server Details

| Item      | Value                                    |
| --------- | ---------------------------------------- |
| Provider  | Hetzner Cloud                            |
| Server IP | `87.99.140.169`                          |
| OS        | Ubuntu 24.04                             |
| SSH user  | `root` (key-based auth only)             |
| Domain    | `api.thedeenfoundation.com`              |
| DNS       | GoDaddy — A record pointing to server IP |

### SSH into the Server

```bash
ssh -i ~/.ssh/deen-prod-keygen root@87.99.140.169
```

Or if you've added the SSH config entry:

```bash
ssh deen
```

<details>
<summary>SSH config (~/.ssh/config)</summary>

```
Host deen
    HostName 87.99.140.169
    User root
    IdentityFile ~/.ssh/deen-prod-keygen
```

</details>

### Updating the Backend (Repeatable Steps)

This is the standard process whenever you push new code and want to deploy it:

```bash
# 1. SSH into the server
ssh deen

# 2. Navigate to project
cd ~/deen-backend

# 3. Pull latest code
git pull

# 4. Rebuild
docker compose down
docker compose build --no-cache

# 5. Run database migrations BEFORE starting the new version — new code must
#    never race a missing table (e.g. DEE-67's reference_translations)
docker compose run --rm api alembic upgrade head

# 6. Start
docker compose up -d

# 7. Verify deployment
docker ps                                              # containers running?
docker logs --tail=50 deen-backend                     # no startup errors?
curl http://127.0.0.1:8000/health                      # container healthy (loopback publish)?
curl https://api.thedeenfoundation.com/health          # responding via Caddy?
```

**Connection-budget invariant (DEE-59):** the Dockerfile's gunicorn `-w 2` is
coupled to the SQLAlchemy pool caps — per worker, sync (2+1) + async (2+1) = 6
pooled connections, so 2 workers = 12 of the 15-client Supabase session-mode
cap. If you change the worker count, recompute the pool sizes in
`db/session.py` and `db/async_session.py` first, or production will hit
`EMAXCONNSESSION` pooler-exhaustion errors again.

**Feature rollback (DEE-60 kill switches):** the token-cost phases can each be
reverted without a redeploy by adding the matching flag to `.env` with value
`0` (`TOOLMSG_COMPACT`, `HISTORY_BUDGETS`, `AGENT_CACHE_V2`,
`FIQH_V2_RETRIEVAL`, `HISTORY_SUMMARY`) and recreating the container
(see below — `restart` alone will not pick up `.env` changes).

### Quick Reference Commands

```bash
# View logs
docker logs -f deen-backend              # follow live logs
docker logs --tail=200 deen-backend      # last 200 lines
docker logs --tail=100 deen-caddy        # Caddy/TLS logs

# Apply a .env change without rebuilding — the container must be RECREATED;
# `docker compose restart` reuses the old environment and will NOT pick it up
docker compose up -d --force-recreate api

# Restart without rebuilding (process bounce only — does NOT re-read .env)
docker compose restart

# Full clean rebuild (if disk is tight)
docker compose down
docker system prune -af
docker compose build --no-cache
docker compose up -d

# Enter container for debugging
docker exec -it deen-backend bash

# Check resource usage
docker stats

# Check running containers
docker ps
```

### First-Time Server Setup

<details>
<summary>Only needed when provisioning a brand new server</summary>

#### 1. Create the Hetzner server

In [Hetzner Cloud Console](https://console.hetzner.cloud):

- **Location**: Ashburn (us-east) or nearest to your users
- **Image**: Ubuntu 24.04
- **Type**: Dedicated > CCX13 (2 vCPU, 8 GB RAM) or larger
- **SSH key**: Add your public key (`~/.ssh/deen-prod-keygen.pub`)
- **Firewall**: Allow TCP 22 (SSH), 80 (HTTP), 443 (HTTPS)
- **Backups**: Enable

#### 2. Initial server setup

```bash
# SSH in as root
ssh -i ~/.ssh/deen-prod-keygen root@SERVER_IP

# Update system
apt update && apt upgrade -y
reboot
# Reconnect after ~30 seconds

# Install Docker
curl -fsSL https://get.docker.com | sh
docker compose version   # verify

# Install Git
apt install -y git

# Enable automatic security updates
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
```

#### 3. Clone and configure

```bash
cd ~
git clone <repository-url> deen-backend
cd deen-backend

# Create .env with production values
nano .env
```

#### 4. DNS setup (GoDaddy)

Add an **A record** in GoDaddy DNS for `thedeenfoundation.com`:

| Type | Name | Value       | TTL |
| ---- | ---- | ----------- | --- |
| A    | api  | `SERVER_IP` | 600 |

This creates `api.thedeenfoundation.com → your server`. Caddy auto-provisions the TLS certificate.

#### 5. Build and start

```bash
docker compose build --no-cache
docker compose run --rm api alembic upgrade head   # migrations BEFORE first start
docker compose up -d
```

</details>

### Rollback

```bash
# SSH into server
ssh deen
cd ~/deen-backend

# Check current and recent commits
git log --oneline -5

# Revert to a previous commit
git checkout <COMMIT_HASH>

# Rebuild and restart
docker compose down
docker compose build --no-cache
docker compose up -d

# If a migration needs reverting
docker exec -it deen-backend alembic downgrade -1
```

## Testing

Pytest is configured via `pytest.ini`. Default `pytest tests` skips:
- `tests/db/` (those tests require a reachable Postgres at `DATABASE_URL`; run them explicitly with `pytest tests/db -q`)
- The `real_llm` marker (opt-in real-Anthropic suite; see below)

### Default suite

```bash
pytest tests -q                                    # primary suite (in-process stubs, no external deps)
pytest tests -q -v                                 # verbose
pytest tests/test_chat_persistence_service.py -q   # async persistence (aiosqlite)
pytest tests/test_fiqh_*.py -q                     # fiqh subsystem
pytest tests/test_agentic_streaming_sse.py -v -s   # full agentic SSE replay
```

### DEE-46 verification gates

These three files are the closing automated gate suite for the DEE-36 async migration. They run as part of the default `pytest tests` sweep — included here for visibility into what each one guards.

```bash
pytest tests/test_async_concurrency_full.py -q          # multi-N loadtest gates
pytest tests/test_sse_event_order_snapshot.py -q        # SSE event-order locked via syrupy
pytest tests/test_sentry_async_propagation.py -q        # per-coroutine Sentry scope isolation
```

Specifics:

- **`test_async_concurrency_full.py`** — drives in-process `chat_pipeline_streaming_agentic` at N=1, 5, 10, 25 with deterministic stub latencies. Asserts: (a) p95 at N=10 ≥ 3× the DEE-39 phase-0 baseline (`documentation/async_baseline.md`), (b) speedup_vs_serial ≥ 5× at N=10, (c) two concurrent in-process streams interleave their `response_chunk` events, (d) longest silence between any two SSE events on a single stream stays under 0.6s.
- **`test_sse_event_order_snapshot.py`** — syrupy-managed snapshot of the agentic event-type sequence (`status:agent`, `status:retrieve_shia_documents_tool`, `response_chunk`, …, `done`) for the hadith path. Refresh with `pytest tests/test_sse_event_order_snapshot.py --snapshot-update` after intentional contract changes.
- **`test_sentry_async_propagation.py`** — installs an in-memory `sentry_sdk.transport.Transport` and fires 5 concurrent coroutines that each open their own `isolation_scope()`, set a unique `correlation_id` tag, and capture an exception. Asserts each captured event carries exactly one CID — no scope leakage between coroutines (the regression that would happen if the async migration accidentally shared a Hub or scope across tasks).

### Concurrency loadtest CLI

`scripts/loadtest_agentic.py` is the underlying driver for the gates above. Run it standalone to capture a phase snapshot:

```bash
python scripts/loadtest_agentic.py --n 10                                        # quick check
python scripts/loadtest_agentic.py --n 10 --label "phase-N description" \         # append
                                   --emit-snapshot documentation/async_baseline.md
python scripts/loadtest_agentic.py --n 25 --llm-sleep 0.3 --retrieval-sleep 0.2  # custom latencies
```

### Opt-in real-Anthropic perf gate

`tests/test_real_llm_perf.py` hits real Anthropic + real Pinecone + real Supabase via a locally running server. **Skipped by default** because it costs LLM tokens and depends on external services. Run it locally before/after perf-sensitive changes, or pin to a scheduled job:

```bash
# 1. Start local server in a separate terminal (with .env loaded; ENV=development for dev bypass)
uvicorn main:app --reload

# 2. In another terminal, run the opt-in suite
pytest tests/ -m real_llm -q

# Override budgets for a slower / faster setup:
REAL_LLM_PERF_P50_BUDGET_S=45 REAL_LLM_PERF_P95_BUDGET_S=90 pytest tests/ -m real_llm -q
```

The suite asserts p50 ≤ 30s for sequential agentic requests and p95 ≤ 60s for 3-way concurrent requests. Catches the kind of real-LLM regression that stub-based gates can't see (multi-second silent pauses during agent reasoning turns, sequential tool calls that should be parallel, etc.).

### Manual smoke tests

```bash
# Memory agent integration (long-running; loads a HuggingFace model)
python agent_tests/test_memory_agent.py

# Database connectivity (requires reachable DB)
python agent_tests/test_db_connection.py

# Hikmah memory integration
python agent_tests/test_hikmah_memory_integration.py
```

The historical `python tests/test_agentic_streaming_sse.py` write-to-markdown helper still works for visual inspection; it accepts `AGENTIC_TEST_QUERY`, `AGENTIC_TEST_SESSION`, `AGENTIC_TEST_OUTPUT` env vars.

## API Examples

### Chat with the AI

```bash
curl -X POST "http://localhost:8080/chat/stream" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "user_query": "What is the concept of Imamate in Shia Islam?",
    "session_id": "user123:thread-1",
    "language": "english"
  }'
```

### Look Up References

```bash
curl -X POST "http://localhost:8080/references?sect=shia&limit=5" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "user_query": "Justice in Islam"
  }'
```

### Request Elaboration on a Lesson

```bash
curl -X POST "http://localhost:8080/hikmah/elaborate/stream" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "selected_text": "What is Taqwa?",
    "context_text": "Full lesson context...",
    "hikmah_tree_name": "Foundations of Faith",
    "lesson_name": "Understanding Piety",
    "lesson_summary": "This lesson covers...",
    "user_id": "user123"
  }'
```

## Project Structure

```
deen-backend/
├── api/                                  # FastAPI route handlers (thin, async)
│   ├── account.py                       # /account
│   ├── chat.py                          # /chat/* (uses Depends(get_db_async), DEE-45)
│   ├── feedback.py                      # /feedback
│   ├── hikmah.py                        # /hikmah/* (async pipeline calls, DEE-44)
│   ├── memory_admin.py                  # /admin/memory
│   ├── onboarding.py                    # /onboarding
│   ├── primers.py                       # /primers
│   └── reference.py                     # /references (async, DEE-44)
├── agents/                               # LangGraph agent + tools + state
│   ├── core/chat_agent.py               # StateGraph (5 nodes), all async (DEE-41)
│   ├── tools/                           # 9 LangChain @tool functions (all async)
│   ├── state/chat_state.py              # ChatState TypedDict + factory
│   ├── config/agent_config.py           # Pydantic config models
│   └── fiqh/fiqh_graph.py               # FAIR-RAG sub-graph, all nodes async (DEE-44)
├── core/                                 # Pipeline orchestration + utilities
│   ├── pipeline_langgraph.py            # Active agentic pipeline (chain.astream end-to-end)
│   ├── pipeline.py                      # Legacy non-agentic pipeline
│   ├── memory.py                        # AsyncRedisChatMessageHistory (DEE-43)
│   ├── chat_models.py                   # LLM factory (Anthropic via langchain-anthropic)
│   ├── prompt_templates.py              # Builder functions for prompts
│   ├── auth.py                          # JWKS fetch + DevBypassBearer wiring
│   ├── config.py                        # .env loader
│   ├── context.py                       # correlation_id ContextVar
│   ├── middleware.py                    # CorrelationIdMiddleware
│   ├── sentry.py                        # Sentry init + bind_sentry_scope
│   └── vectorstore.py                   # Pinecone client init
├── modules/                              # AI pipeline stages (every fn has async variant)
│   ├── classification/classifier.py     # aclassify_*
│   ├── embedding/embedder.py            # dense + sparse embedders
│   ├── enhancement/enhancer.py          # aenhance_query
│   ├── retrieval/retriever.py           # aretrieve_* via PineconeAsyncio (DEE-42)
│   ├── reranking/reranker.py            # RRF + weighted blending
│   ├── generation/                      # streaming + non-streaming generators
│   ├── translation/translator.py        # atranslate_*
│   └── fiqh/                            # decomposer, retriever (BM25 + dense),
│                                         # filter, sea, refiner, generator, classifier
├── db/                                   # Database layer
│   ├── session.py                       # SYNC engine (psycopg2) + Base
│   ├── async_session.py                 # ASYNC engine (asyncpg) + AsyncSessionLocal (DEE-45)
│   ├── config.py                        # Pydantic Settings (DB_USER/DB_HOST/...)
│   ├── models/                          # 13 SQLAlchemy models
│   ├── schemas/                         # Pydantic request/response schemas
│   ├── repositories/                    # Data-access layer (memory profiles/events)
│   ├── routers/                         # CRUD routers (lessons, users, etc.) — sync
│   └── crud/                            # Generic CRUDBase + per-model helpers
├── services/                             # Business services
│   ├── chat_persistence_service.py      # Async (DEE-45); chat sessions + messages
│   ├── memory_service.py                # User memory profile + event CRUD
│   ├── consolidation_service.py         # Periodic memory consolidation
│   ├── embedding_service.py             # User memory note embedding generation
│   ├── primer_service.py                # Personalized primer generation
│   ├── hikmah_quiz_service.py           # Hikmah elaboration + quiz logic
│   └── account_service.py               # Account management
├── scripts/                              # Operational + ingestion scripts
│   ├── ingest_fiqh.py                   # Sistani PDF -> Pinecone fiqh indices
│   │                                     # Use --encoder-only for local-only encoder regen
│   ├── loadtest_agentic.py              # Concurrency loadtest CLI (drives DEE-46 gates)
│   └── reembed_pgvector.py              # Backfill pgvector embeddings
├── tests/
│   ├── conftest.py                      # Test env defaults
│   ├── conftest_async_stubs.py          # Shared LLM/Pinecone/fiqh stubs (DEE-39)
│   ├── test_async_concurrency_full.py   # DEE-46 concurrency gates (multi-N, p95, max-gap)
│   ├── test_sse_event_order_snapshot.py # DEE-46 SSE event-type snapshot via syrupy
│   ├── test_sentry_async_propagation.py # DEE-46 per-coroutine scope isolation
│   ├── test_real_llm_perf.py            # DEE-46 opt-in real-Anthropic perf (-m real_llm)
│   ├── test_chat_persistence_service.py # DEE-45 async DB tests (aiosqlite)
│   ├── test_async_memory.py             # DEE-43 async Redis history tests
│   ├── test_fiqh_*.py                   # FAIR-RAG fiqh subsystem
│   ├── test_agentic_streaming_*.py      # End-to-end streaming pipeline
│   └── db/                              # DB-required tests (excluded by pytest.ini)
├── documentation/
│   ├── async_baseline.md                # Per-phase concurrency snapshots (DEE-36)
│   ├── async_migration_manual_tests.md  # Manual smoke checklist
│   ├── ARCHITECTURE.md, AI_PIPELINE.md, CHATBOT.md, ...
│   └── fiqh_related_docs/               # Sistani PDF + FAIR-RAG implementation guide
├── alembic/                              # 11 sync DB migrations (asyncpg not used)
├── pytest.ini                            # marker registration + tests/db excluded by default
├── Dockerfile                            # Python 3.11-slim + fiqh encoder build step
├── docker-compose.yml                    # api + caddy services
└── caddy/Caddyfile                       # TLS termination + reverse proxy
```

## Contributing

When contributing to this project:

1. Follow the existing code structure
2. Add type hints to all functions
3. Update documentation for new features
4. Write tests for new functionality
5. Ensure all tests pass before submitting

## Local Development Gotchas

A handful of things that bite developers on fresh clones — bake them into your setup ritual.

| # | Symptom | Cause | Fix |
|---|---------|-------|-----|
| 1 | Fiqh queries always return *"I was unable to retrieve relevant rulings…"* | `data/fiqh_bm25_encoder.json` is gitignored and absent on fresh clones; sparse retrieval throws inside `_get_bm25_encoder` | `python scripts/ingest_fiqh.py --encoder-only` |
| 2 | `403 Not authenticated` on protected endpoints in Swagger | `ENV` is missing or set to `production` — `DevBypassBearer` only bypasses when `ENV=development` | Add `ENV=development` to `.env`, restart uvicorn (`--reload` does not pick up `.env` changes) |
| 3 | `SSL: CERTIFICATE_VERIFY_FAILED` from asyncpg connecting to Supabase | Default Python trust store on Windows doesn't include Supabase's CA chain | Already handled in `db/async_session.py` via `connect_args={"ssl": "require"}` (encrypt without verify, mirrors sync `sslmode=require`) |
| 4 | `pytest tests` interrupts during collection on local Postgres | `tests/db/` requires a real DB; without one, collection fails | Resolved by `pytest.ini`'s `norecursedirs = tests/db`. Run those explicitly with `pytest tests/db -q` when a DB is available |
| 5 | `pytest` not found after activating venv on Windows cmd | Wrong activation script | Use `venv\Scripts\activate.bat` in cmd (the `.ps1` script is PowerShell-only). Or run as a module: `venv\Scripts\python.exe -m pytest tests -q` |
| 6 | `--reload` doesn't pick up `.env` changes | `core/config.py` reads env at import time; uvicorn reload only re-imports on code change | Hard-restart uvicorn (Ctrl+C, run again) after editing `.env` |
| 7 | Direct Supabase host `db.<ref>.supabase.co` times out from Hetzner / Docker | Hetzner / Docker default to IPv4-only; direct host resolves to IPv6 | Use the Session Pooler URL (`aws-0-<region>.pooler.supabase.com:5432`). **Do not** use port 6543 (Transaction Pooler) — it breaks Alembic and asyncpg |

## Troubleshooting

### Common Issues

**Database Connection Errors**

- Verify `.env` file has correct database credentials
- Ensure PostgreSQL is running
- Check database exists: `psql -l`

**"Network is unreachable" / connection timeout on Hetzner or Docker**

Supabase's direct database host (`db.<ref>.supabase.co`) resolves to an IPv6 address. Hetzner Cloud servers and Docker environments do not have IPv6 enabled by default, so connections fail silently.

Switch to the **Session Pooler** connection string (port `5432` on `pooler.supabase.com`) — see [Choosing the right Supabase connection string](#choosing-the-right-supabase-connection-string) above. Do **not** use port `6543` (Transaction Pooler); it breaks Alembic migrations and asyncpg.

**Redis Connection Errors**

- Verify Redis is running: `redis-cli ping`
- Check `REDIS_URL` in `.env`

**Authentication Errors**

- Verify JWT token is valid
- Check `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are set in `.env`
- Verify the Supabase JWT signing key is asymmetric (RS256/ES256): `curl <SUPABASE_URL>/auth/v1/keys` should return a non-empty `keys` array

**Memory Agent Not Working**

- Check database consolidation: See `updates_documentation/DATABASE_CONFIG_CONSOLIDATION.md`
- Verify background thread logs in console

For more troubleshooting help, see `updates_documentation/TROUBLESHOOTING.md`.

## License

[Your License Here]

## Support

For questions or issues, please contact the development team or open an issue in the repository.

---

**Documentation Last Updated**: May 2026 (DEE-36 async migration close-out — DEE-46)
