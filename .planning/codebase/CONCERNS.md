# Codebase Concerns

**Analysis Date:** 2026-05-09

---

## Incomplete Async DB Migration (DEE-45 Follow-up)

**Routers still on sync `psycopg2` / `get_db()`:**

The DEE-45 migration moved the chat router to `asyncpg` + `AsyncSession`. All other routers remain on the sync engine and hold psycopg2 connections independently from the async pool — two independent connection pools to the same Supabase database.

| Router File | Route Prefix | Handler Style |
|---|---|---|
| `db/routers/lessons.py` | `/lessons` | 5 sync `def` handlers via `Depends(get_db)` |
| `db/routers/lesson_content.py` | `/lesson-content` | 5 sync `def` handlers via `Depends(get_db)` |
| `db/routers/users.py` | `/users` | 5 sync `def` handlers via `Depends(get_db)` |
| `db/routers/user_progress.py` | `/user-progress` | 5 sync `def` handlers via `Depends(get_db)` |
| `db/routers/hikmah_trees.py` | `/hikmah-trees` | 5 sync `def` handlers via `Depends(get_db)` |
| `api/hikmah.py` | `/hikmah` | 7 quiz endpoints via `Depends(get_db)` |
| `api/primers.py` | `/primers` | 3 endpoints via `Depends(get_db)` |
| `api/onboarding.py` | `/onboarding` | 2 sync `def` handlers via `Depends(get_db)` |
| `api/memory_admin.py` | `/admin/memory` | 4 sync `def` handlers via `Depends(get_db)` |
| `api/account.py` | `/account` | `DELETE /account/me` via `Depends(get_db)` |

- Impact: FastAPI runs sync route handlers in a threadpool, so they don't block the uvicorn event loop directly. However, two separate connection pools exist for the same Supabase DB — under gunicorn with `-w 2`, total potential connections = 2 workers × (sync 15 max + async 15 max) = 60 connections, which can exhaust Supabase plan limits.
- Fix approach: Migrate each router to `Depends(get_db_async)` + `AsyncSession` following the pattern in `api/chat.py`. Update sync `def` handlers to `async def` and replace ORM calls with async-compatible equivalents.

---

## Security: Auth Bypass in Development Mode

**`DevBypassBearer` skips JWT verification when `ENV=development`:**
- Files: `models/JWTBearer.py` (lines 76–97), `core/auth.py` (line 14)
- `auth = DevBypassBearer(jwks, env=ENV)` — when `ENV=development`, any request with any Bearer token returns mock claims `{"sub": "dev-user-001", "email": "dev@local.test"}`.
- Risk: `main.py` line 74 defaults `ENV` to `"development"` if unset. A misconfigured or missing `ENV` in production silently enables this bypass for all routes.
- Recommendation: Add a startup assertion that `ENV` is explicitly one of `{"development", "production"}`. Emit a loud WARNING log line at startup when bypass mode is active.

**`/_debug/db` and `/_routes` endpoints are unprotected in all environments:**
- File: `main.py` (lines 141–161)
- `GET /_debug/db` executes `SELECT version()` against the live database and returns the PostgreSQL version string.
- `GET /_routes` enumerates all registered routes and HTTP methods — a complete API map for attackers.
- Neither endpoint has `Depends(auth)` or an `ENV` guard.
- Fix: Add `Depends(auth)` to both, or guard with `if ENV == "development":` like the `/sentry-debug` endpoint at line 164.

**Commented-out router-level auth in `main.py`:**
- File: `main.py` (lines 94–97) — four `app.include_router(...)` calls with `dependencies=[Depends(auth)]` are commented out.
- Routes in `/references`, `/hikmah/*`, and `/account` rely solely on each handler individually declaring `credentials: ... = Depends(auth)`. Any new handler added to these routers without the dependency is silently unauthenticated.
- Fix: Reinstate router-level `dependencies=[Depends(auth)]` as the secure default.

**`/feedback` endpoint is completely unauthenticated:**
- File: `api/feedback.py` — `submit_feedback` has no `credentials` parameter and no `Depends(auth)`.
- Any unauthenticated caller can write to `feedback.csv` on disk.
- Risk: CSV injection, disk exhaustion from repeated posts, data pollution.
- Fix: Add `Depends(auth)` or at minimum add rate limiting before production.

---

## Security: Feedback Stored as Append-Only CSV on Container Disk

**`api/feedback.py` writes to a local CSV file with no concurrency control:**
- File: `api/feedback.py` (lines 15–44)
- `feedback.csv` is created at the process working directory by default (`FEEDBACK_CSV_PATH = Path(os.getenv("FEEDBACK_CSV_PATH", "feedback.csv"))`).
- Problems: (1) Not durable — the file is inside the Docker container; a restart or redeploy destroys all feedback. (2) Concurrent writes under gunicorn's `-w 2` worker model can corrupt the CSV — no file lock is used. (3) No disk-space guard — repeated posts can fill the container disk.
- Fix: Persist feedback to the PostgreSQL database via a `feedback` table (Alembic migration needed), or route to a cloud logging sink.

---

## Security: JWT Claims Logged in Account Endpoint

**`api/account.py` logs all JWT claims at INFO level on every account deletion:**
- File: `api/account.py` (lines 58–59)
- `logger.info(f"JWT Claims for user {user_id}: {credentials.claims}")` emits email, `sub`, and all other JWT payload fields to the structured log stream.
- The comment `# Debug: Log all JWT claims to identify available fields` confirms this was left from debugging.
- Fix: Remove the full-claims log line. The preceding line already logs `user_id` (line 57).

---

## Incomplete Feature: Response Translation Is a Silent Stub

**`translate_response_tool` always returns English text for all non-English targets:**
- File: `agents/tools/translation_tools.py` (lines 86–93)
- The tool returns `{"translated_text": text, "note": "Response translation not yet implemented, returning English"}` for every non-English target — a `# TODO: Implement reverse translation` comment is on line 89.
- The tool is registered in the agent's tool list and the agent system prompt instructs it to translate responses (`agents/prompts/agent_prompts.py`), but no translation ever occurs.
- Impact: Users requesting Arabic, Urdu, or French responses receive English answers with no user-visible indication that translation failed. The agent consumes tokens on a tool call with no effect.
- Fix: Implement `atranslate_from_english(text, target_language)` in `modules/translation/translator.py` and wire it into the tool, or remove the tool from the agent's tool list until implemented.

---

## Tech Debt: TF-IDF Sparse Embedder Fit-Per-Query

**`modules/embedding/embedder.py` calls `fit_transform` on a single query string on every request:**
- File: `modules/embedding/embedder.py` (line 29)
- `getSparseEmbedder().fit_transform([normalized_query])` fits the TF-IDF vocabulary from a single query document at runtime. A vectorizer fitted on one string produces a trivially small vocabulary that does not match the index-time IDF weights computed during corpus ingestion.
- This is the primary sparse embedder for all hadith/Quran retrieval — `modules/retrieval/retriever.py` (lines 28, 53, 79, 155). The fiqh subsystem uses a correctly pre-fitted BM25 encoder (`modules/fiqh/retriever.py`) as the contrast.
- Impact: Hadith and Quran sparse retrieval vectors are semantically misaligned with the Pinecone sparse index. Dense retrieval and reranking partially compensate, but result quality for sparse-dependent queries is degraded.
- Fix: Pre-fit the TF-IDF vectorizer on the full hadith corpus text (analogous to `scripts/ingest_fiqh.py --encoder-only`) and persist to `data/hadith_tfidf_encoder.json`. Load at startup and call `transform` instead of `fit_transform`.

---

## Tech Debt: Fiqh BM25 Encoder Missing on Fresh Clones

**`data/fiqh_bm25_encoder.json` is gitignored and required at runtime:**
- Files: `modules/fiqh/retriever.py` (line 30), `main.py` (lines 32–53), `scripts/ingest_fiqh.py`
- The encoder is regenerated at Docker build time by `Dockerfile`'s `RUN python scripts/ingest_fiqh.py --encoder-only`. A fresh clone running `uvicorn main:app --reload` directly will fall back to refusal answers for all fiqh queries — silently, from the user's perspective.
- Current mitigation: `main.py` lifespan emits a `WARNING` log when the file is missing (DEE-46).
- Remaining gap: The warning is only visible if the developer inspects server logs at startup. There is no startup failure, so the application appears healthy while fiqh queries silently fail.
- Fix: Consider a runtime assertion that fails the lifespan startup if `DEEN_FIQH_DENSE_INDEX_NAME` is configured but the encoder file is absent, converting a silent data failure into a hard startup failure.

---

## Tech Debt: `asyncio.run()` and `loop.run_until_complete()` in Background Callbacks

**Two paths create new event loops in background threads:**

1. `services/hikmah_quiz_service.py` (line 300): `asyncio.run(self._trigger_incorrect_quiz_memory_event(...))` is called from a sync `process_quiz_submission` method that is itself invoked as a `BackgroundTasks` callback. FastAPI runs background tasks in a threadpool, so `asyncio.run()` does not raise, but creates a fresh event loop per background task.

2. `modules/generation/stream_generator.py` (lines 183–194): A background thread for hikmah memory updates creates a new event loop via `asyncio.new_event_loop()` and calls `loop.run_until_complete()`.

- Impact: DB sessions and Redis connections opened inside ephemeral loops are not shared with the main asyncpg pool. Each invocation opens and closes its own connections, increasing Supabase connection churn. The pattern is fragile — if the main loop is inspectable from the thread (e.g., via `asyncio.get_event_loop()`), it may grab the wrong loop.
- Fix: Convert `process_quiz_submission_background` to `async def` and use `starlette.background.BackgroundTasks` with a native async callable. For the stream generator memory update, use `asyncio.ensure_future()` from within the existing async context.

---

## Tech Debt: LangGraph `MemorySaver` Does Not Survive Restarts or Multiple Workers

**`ChatAgent` uses in-process `MemorySaver` for LangGraph graph checkpointing:**
- File: `agents/core/chat_agent.py` (lines 57–58)
- `MemorySaver()` stores LangGraph graph execution state in-process Python memory. The object is local to each `ChatAgent` instance, which is constructed per-request in `core/pipeline_langgraph.py` (line 102: `agent = ChatAgent(agent_config)`).
- Under gunicorn with `-w 2`, two workers run independently. A session whose graph state was checkpointed by worker A is invisible to worker B.
- Current situation: Because `ChatAgent` is instantiated per-request, no state persists across requests regardless, making `MemorySaver` a no-op at present. The actual conversation history is held durably in Redis and PostgreSQL.
- Latent risk: If `ChatAgent` is ever promoted to a module-level singleton (a natural optimization to avoid re-building the graph on every request), the `MemorySaver` would accumulate unbounded state for all sessions in memory with no eviction.
- Fix for the singleton path: Replace `MemorySaver` with `AsyncPostgresSaver` from `langgraph-checkpoint-postgres`. Note `langgraph-checkpoint==2.1.1` is already in `requirements.txt`.

---

## Tech Debt: `print()` Calls in Production Hot Paths

**Multiple production files emit debug output via `print()` instead of the structured logger, bypassing Sentry:**

| File | Context |
|---|---|
| `modules/retrieval/retriever.py` | `print("INSIDE shia retrive_documents")` — 8 calls, every retrieval |
| `modules/embedding/embedder.py` | `print("INSIDE generate_sparse_embedding")` — on every query |
| `agents/tools/classification_tools.py` | `print(f"[check_if_non_islamic_tool] Error: {e}")` — error swallowed by print |
| `agents/tools/translation_tools.py` | `print(f"[translate_to_english_tool] Error: {e}")` — error swallowed by print |
| `agents/tools/enhancement_tools.py` | `print(f"[enhance_query_tool] Error: {e}")` — error swallowed by print |
| `core/utils.py` | 7 `print()` calls including `print("INSIDE format_references")` |
| `core/memory.py` | 3 `print()` calls on Redis connect/disconnect |
| `core/vectorstore.py` | `print(f"Error initializing PineconeVectorStore: {e}")` |
| `core/pipeline.py` | `print(f"[chat_pipeline_streaming] Translation failed: {e}")` |

- Impact: Error `print()` calls in tools are particularly harmful — `LoggingIntegration` in Sentry only captures `logger.*` calls. Tool errors printed to stdout are invisible to Sentry and to log aggregation. The INSIDE-trace prints fire on every hot-path request, adding stdout noise in production.
- Fix: Replace all `print()` in `agents/`, `core/`, and `modules/` with `logger.*`. Remove the `INSIDE ...` trace-style prints outright.

---

## Tech Debt: Missing Type Hints in Core Modules

**Several `modules/` files have no type annotations, preventing static analysis:**

| File | Untyped Functions |
|---|---|
| `modules/retrieval/retriever.py` | `retrieve_documents`, `retrieve_shia_documents`, `retrieve_sunni_documents`, `retrieve_quran_documents` (sync variants) |
| `modules/embedding/embedder.py` | `getSparseEmbedder`, `getDenseEmbedder` (also non-snake-case names) |
| `modules/reranking/reranker.py` | `rerank_documents`, `normalize_inplace`, `safe_sample_dense`, `safe_sample_sparse` |
| `modules/generation/generator.py` | `generate_response` uses bare `list` not `list[dict]` |

- Fix: Add `-> list[dict]` return types and parameter annotations. Apply snake_case to `getSparseEmbedder` and `getDenseEmbedder` as a follow-up (requires updating all callers in `modules/retrieval/retriever.py` and `modules/fiqh/retriever.py`).

---

## Tech Debt: Typos in File Names

**Two misspelled file names are now load-bearing imports:**

- `modules/embedding/proprecessor.py` — should be `preprocessor.py`. Imported as `from modules.embedding import proprecessor` in `modules/embedding/embedder.py` (line 3). Renaming requires updating the import.
- `db/models/__int__.py` — should be `__init__.py`. Python may or may not auto-discover this as the package init on case-sensitive filesystems (Linux Docker). If it is not recognized as `__init__.py`, the model imports inside it (`from .lessons import Lesson`, etc.) silently fail and the `db.models` package appears empty.
- `db/schemas/__int__.py` — same typo in the schemas package.

- Fix: Rename files in a single commit and update all imports. Verify `db/models` and `db/schemas` still import correctly on Linux after the rename.

---

## Tech Debt: Hardcoded `"gpt-4o"` Model Name in API Docstring

**`api/chat.py` shows a GPT-4o example in the `/chat/stream/agentic` endpoint docstring:**
- File: `api/chat.py` (line 150): `"agent_model": "gpt-4o"` appears in the example request body.
- The runtime model is `claude-sonnet-4-6` (from `LARGE_LLM` env var, loaded in `agents/config/agent_config.py`). `ChatAnthropic` does not accept GPT model IDs.
- Impact: A developer or API consumer following the example will receive a runtime error from `ChatAnthropic`.
- Fix: Update the docstring example to `"agent_model": "claude-sonnet-4-6"` and add a note that only Anthropic model IDs are accepted.

---

## Tech Debt: Orphaned Sample/Test Files in Non-Test Directories

**Files that should be in `tests/` or deleted are in production package directories:**

| File | Issue |
|---|---|
| `db/sample_api_usage.py` | Sample usage file, not imported anywhere |
| `db/sample_main.py` | Alternate `main.py` stub, not used |
| `db/test_user_progress_api.py` | Test file inside `db/` package with stale `cognito` user ID string |

- Fix: Delete `db/sample_api_usage.py` and `db/sample_main.py`. Move `db/test_user_progress_api.py` to `tests/db/` or delete if the coverage is redundant.

---

## Scaling Concern: Two Independent DB Connection Pools

**The sync and async engines have separate pools with SQLAlchemy defaults:**
- Files: `db/session.py` (sync, psycopg2), `db/async_session.py` (async, asyncpg)
- Neither engine configures `pool_size` or `max_overflow`. SQLAlchemy defaults: pool_size=5, max_overflow=10 per engine.
- Under gunicorn with 2 workers: 2 × (sync 15 max + async 15 max) = up to 60 connections from one server deployment.
- Supabase connection limits vary by plan; this configuration can exhaust them under moderate load without any evidence in application metrics.
- Fix: Set `pool_size=3, max_overflow=5` explicitly on both engines in `db/session.py` and `db/async_session.py`. Consider Supabase Supavisor in transaction mode as a connection pooler.

---

## Scaling Concern: No Rate Limiting on Any Endpoint

**No rate limiting or request throttling exists anywhere:**
- No `slowapi`, `fastapi-limiter`, or middleware-level throttling in `main.py` or `api/`.
- Impact: A single client can exhaust Pinecone query quota, Anthropic token budget, or Redis connection slots by rapid-firing `/chat/stream/agentic`. The unauthenticated `/feedback` endpoint is an open append-to-disk vector.
- Fix: Add `slowapi` (or a Redis-backed limiter) to `requirements.txt`. Apply per-IP limits to unauthenticated endpoints and per-user limits to authenticated chat endpoints.

---

## Fragile Area: Pinecone Namespace Hardcoded as `"ns1"`

**All Pinecone sparse and dense queries hardcode `namespace="ns1"`:**
- Files: `modules/retrieval/retriever.py` (lines 32, 57, 83, 160), `modules/fiqh/retriever.py` (lines 115, 126, 183, 190)
- If a Pinecone index is re-ingested under a different namespace (or the namespace is different per environment), retrieval silently returns zero results with no error raised.
- Fix: Add `PINECONE_NAMESPACE=ns1` to `core/config.py` and replace all hardcoded `"ns1"` strings with the config value.

---

## Fragile Area: JWKS Fetched Synchronously at Module Import

**`core/auth.py` makes a blocking HTTP request at import time:**
- File: `core/auth.py` (lines 6–9)
- `requests.get(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")` blocks the startup thread until Supabase responds. If Supabase is unreachable during deployment (cold start, network blip), the application fails to start with an unhandled exception rather than a clean error.
- Fix: Wrap in a retry loop with exponential backoff (e.g., `tenacity`), or move JWKS loading to the `lifespan` hook in `main.py` where startup errors produce cleaner log messages.

---

## Missing Test Coverage

**Areas with no automated test files:**

| Area | Files | Risk |
|---|---|---|
| `api/onboarding.py` endpoints | `api/onboarding.py` | Regressions in upsert idempotency undetected |
| `api/feedback.py` write path | `api/feedback.py` | Concurrency / disk-full bugs undetected |
| `api/memory_admin.py` dashboard | `api/memory_admin.py` | HTML dashboard and JSON endpoints untested |
| `api/account.py` deletion flow | `api/account.py` | Multi-step DB → Redis → Supabase Auth deletion untested end-to-end |
| `db/routers/*` CRUD endpoints | `db/routers/` (5 routers) | All 25+ CRUD handler variations have no test files |
| TF-IDF sparse embedder correctness | `modules/embedding/embedder.py` | `fit_transform`-per-query bug not caught by any test |
| Legacy pipeline | `core/pipeline.py` | `POST /chat/` and `POST /chat/stream` have no unit tests |

---

*Concerns audit: 2026-05-09*
