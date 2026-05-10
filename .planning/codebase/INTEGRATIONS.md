# External Integrations

**Analysis Date:** 2026-05-09

## APIs & External Services

**Anthropic (LLM Provider):**
- Used for: All active LLM generation, classification, translation, query enhancement
- SDK: `anthropic==0.92.0`, accessed via `langchain-anthropic==0.3.22`
- Auth env var: `ANTHROPIC_API_KEY` (fail-fast guard at import in `core/config.py`)
- Client factory: `core/chat_models.py` — `get_generator_model()`, `get_enhancer_model()`, `get_classifier_model()`, `get_translator_model()`
- Models: `LARGE_LLM` (default `claude-sonnet-4-6`), `SMALL_LLM` (default `claude-haiku-4-5-20251001`)
- All calls are async via `.ainvoke()` / `.astream()` (DEE-41, DEE-42)

**Pinecone (Vector Search):**
- Used for: Hybrid dense + sparse retrieval over Islamic texts (hadith, Quran, fiqh rulings)
- SDK: `pinecone==7.3.0`, `langchain-pinecone==0.2.8`, `pinecone-text==0.11.0`
- Auth env var: `PINECONE_API_KEY` (fail-fast guard at import in `core/config.py`)
- Client init: `core/vectorstore.py` — `Pinecone(api_key=...)`, `PineconeVectorStore`
- Async retrieval: `PineconeAsyncio.asimilarity_search_with_score` (DEE-42; `modules/retrieval/retriever.py`)
- Indexes:

| Env Var | Purpose | Namespace | Text Key |
|---------|---------|-----------|----------|
| `DEEN_DENSE_INDEX_NAME` | Dense hadith/general vectors | `ns1` | `text_en` |
| `DEEN_SPARSE_INDEX_NAME` | Sparse TF-IDF vectors for main pipeline | — | — |
| `QURAN_DENSE_INDEX_NAME` | Dense Quranic tafsir content | — | — |
| `DEEN_FIQH_DENSE_INDEX_NAME` | Dense fiqh rulings (Sistani corpus) | — | — |
| `DEEN_FIQH_SPARSE_INDEX_NAME` | Sparse BM25 fiqh vectors | — | — |

- Retrieval weighting: `DENSE_RESULT_WEIGHT` (default `0.8`), `SPARSE_RESULT_WEIGHT` (default `0.2`)
- Result count: `REFERENCE_FETCH_COUNT` (default `10`)
- Fiqh BM25 encoder: `pinecone-text==0.11.0` `BM25Encoder`; encoder state saved to `data/fiqh_bm25_encoder.json` (gitignored); regenerated at Docker build time via `scripts/ingest_fiqh.py --encoder-only`

**HuggingFace (Local Dense Embeddings):**
- Used for: Dense vector generation at query time and during corpus ingestion
- SDK: `langchain-huggingface==0.1.2`, `sentence-transformers==3.4.1`, `transformers==4.48.2`
- Model: `sentence-transformers/all-mpnet-base-v2` — 768 dimensions
- No external API call; model weights run locally via `modules/embedding/embedder.py`
- Configured via env: `EMBEDDING_MODEL` (default `sentence-transformers/all-mpnet-base-v2`), `EMBEDDING_DIMENSIONS` (default `768`)

## Data Storage

**Databases:**

**PostgreSQL (Supabase-hosted):**
- Used for: All structured data — users, chat sessions/messages, lessons, lesson content, user progress, hikmah trees, personalized primers, quiz questions/choices/attempts, memory profiles, memory events, note/lesson-chunk embeddings
- Driver (sync): `psycopg2-binary==2.9.10` via `postgresql+psycopg2` — `db/session.py`
  - Used by: all routers except chat (`Depends(get_db)`)
  - SSL: `connect_args={"sslmode": "require"}`
- Driver (async): `asyncpg==0.30.0` via `postgresql+asyncpg` — `db/async_session.py` (DEE-45)
  - Used by: chat router only (`Depends(get_db_async)`)
  - SSL: `connect_args={"ssl": "require"}`
- ORM: `SQLAlchemy==2.0.41`, models in `db/models/` (15 model files)
- Vector columns: `pgvector==0.3.6`; 768-dim `Vector` columns in `db/models/embeddings.py` (`note_embeddings`, `lesson_chunk_embeddings` tables)
- Connection env vars: `DATABASE_URL` / `ASYNC_DATABASE_URL` (full DSN preferred), or individual `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` (also accepts `POSTGRES_*` / `PG*` aliases via `db/config.py`)
- Migrations: `alembic==1.14.0`; config in `alembic.ini`; 11 versions in `alembic/versions/`; always run `alembic upgrade head` after pull

**File Storage:**
- Local filesystem only: `data/fiqh_bm25_encoder.json` (BM25 state, gitignored), `documentation/fiqh_related_docs/english-islamic-laws-4th-edition.pdf` (ingestion source)
- No object storage (S3, GCS, etc.) detected

**Caching:**
- Redis for conversation history (see Memory below)
- No application-level caching layer (no Memcached, no in-process LRU beyond module-level singletons)

## Authentication & Identity

**Supabase Auth:**
- Used for: JWT-based user authentication (Bearer token scheme)
- Auth env vars: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- JWKS endpoint fetched at startup (sync `requests.get`): `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`
- JWT verification: `models/JWTBearer.py` (`JWTBearer` class) — validates `kid`, verifies RS256 signature against public JWKS keys using `python-jose==3.5.0`
- Dev bypass: `DevBypassBearer` in `models/JWTBearer.py` — when `ENV=development`, skips JWKS verification and returns mock credentials (`sub: dev-user-001`)
- User identifier extracted from JWT claim: `sub` (Supabase UUID)
- Auth dependency: `auth = DevBypassBearer(jwks, env=ENV)` in `core/auth.py`; routers import `auth` directly

## Memory & Session Storage

**Redis:**
- Used for: Per-user conversation history with TTL-based expiry
- SDK: `redis==6.4.0`; async path via `redis.asyncio` (DEE-43)
- Connection env var: `REDIS_URL` (default `redis://localhost:6379/0`)
- Key scheme: `{REDIS_KEY_PREFIX}:{session_id}` — prefix controlled by `REDIS_KEY_PREFIX` (default `dev:chat`)
- TTL: `REDIS_TTL_SECONDS` (default `12000` seconds)
- Max messages per session: `REDIS_MAX_MESSAGES` (default `30`); enforced by `core/memory.py:atrim_history()`
- Async API: `AsyncRedisChatMessageHistory` in `core/memory.py` — wire-compatible with sync `RedisChatMessageHistory`; backed by `redis.asyncio`
- Sync API: `make_history()` in `core/memory.py` — retained for legacy code paths
- Fallback: If Redis unreachable at startup ping, `core/memory.py` falls back to `AsyncEphemeralHistory` (in-process, non-persistent) keyed by `session_id`
- Admin: session inspection at `GET /admin/memory` via `api/memory_admin.py`

## Monitoring & Observability

**Sentry:**
- SDK: `sentry-sdk[fastapi]==2.35.2`
- Init: `core/sentry.py` — side-effect import in `main.py`
- Activation: requires both `SENTRY_ENABLED=true` AND `SENTRY_DSN` set; absence of either is fully silent
- Integrations auto-enabled by `sentry-sdk[fastapi]`: `FastApiIntegration`, `StarletteIntegration`
- Explicit: `LoggingIntegration(level=INFO, event_level=ERROR, sentry_logs_level=INFO)` in `core/sentry.py`
- PII scrubbing: `before_send` hook (`_scrub_pii`) drops `request.data` from all error events (GDPR Article 9)
- Per-request tagging: `core/sentry.py:bind_sentry_scope()` sets `correlation_id`, `endpoint`, `session_id`, `user_id` tags on the isolation scope

**Correlation IDs:**
- `core/middleware.py:CorrelationIdMiddleware` — generates server-side UUID4 per request, propagates via `ContextVar` (`core/context.py`), injects as `X-Correlation-ID` response header
- Implemented as pure ASGI middleware (not `BaseHTTPMiddleware`) to ensure `ContextVar` propagation works for sync route handlers in thread-pool executor

**Logging:**
- Custom `ExtraFormatter` in `core/logging_config.py`: format `%(asctime)s [%(levelname)s] %(name)s - %(message)s` with ANSI color
- `sqlalchemy.engine`, `sqlalchemy.pool`, `httpx` set to `WARNING` to reduce noise
- No external log aggregation service configured

**LangSmith:**
- `langsmith==0.4.4` installed as transitive LangChain dependency
- No `LANGSMITH_API_KEY` or `LANGCHAIN_TRACING_V2` configuration detected; tracing is effectively disabled

## CI/CD & Deployment

**GitHub Actions:**
- Pipeline: `.github/workflows/deploy-dev.yml` (DEE-47)
- Trigger: manual `workflow_dispatch` only (ref input, optional `--no-cache` flag)
- Concurrency: `group: deploy-dev`, `cancel-in-progress: false` (serialized deploys)
- Runner: self-hosted, label `dev-deploy` on Hetzner dev box
- Steps: checkout → write `.env` from GitHub Secrets → `docker compose build` → `docker compose down && up -d` → `/health` polling (30×2s = 60s budget) → container status

**Hosting:**
- Self-hosted on Hetzner (dev environment)
- Caddy 2 reverse proxy (`caddy:2` image) handles TLS termination
- Domain: `deen-fastapi.duckdns.org` (configured in `caddy/Caddyfile`)
- HTTPS: automatic via Caddy's Let's Encrypt integration

## Webhooks & Callbacks

**Incoming:**
- None — no webhook receiver endpoints detected

**Outgoing:**
- None — no outbound webhook calls detected

## Environment Configuration

**Required env vars (server will not start without these):**
```
ANTHROPIC_API_KEY          # Anthropic LLM access
PINECONE_API_KEY           # Pinecone vector DB
DEEN_DENSE_INDEX_NAME      # Main dense index name
DEEN_SPARSE_INDEX_NAME     # Main sparse index name
SUPABASE_URL               # Supabase project URL (Auth JWKS + DB host)
SUPABASE_SERVICE_ROLE_KEY  # Supabase admin key
DATABASE_URL               # PostgreSQL sync DSN (or individual DB_* vars)
ASYNC_DATABASE_URL         # PostgreSQL async DSN (or individual DB_* vars)
```

**Optional env vars with defaults:**
```
QURAN_DENSE_INDEX_NAME          # Quran tafsir index
DEEN_FIQH_DENSE_INDEX_NAME      # Fiqh dense index
DEEN_FIQH_SPARSE_INDEX_NAME     # Fiqh sparse index
LARGE_LLM=claude-sonnet-4-6
SMALL_LLM=claude-haiku-4-5-20251001
REDIS_URL=redis://localhost:6379/0
REDIS_KEY_PREFIX=dev:chat
REDIS_TTL_SECONDS=12000
REDIS_MAX_MESSAGES=30
SENTRY_DSN=                     # Sentry disabled if absent
SENTRY_ENABLED=false
CORS_ALLOW_ORIGINS=https://deen-frontend.vercel.app
ENV=development
```

**Secrets storage:**
- Development: `.env` file at project root (gitignored)
- Production: GitHub Secrets injected into `.env` by `deploy-dev.yml` workflow step (written with `umask 077`, mode 600)

---

*Integration audit: 2026-05-09*
