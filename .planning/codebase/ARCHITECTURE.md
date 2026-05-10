<!-- refreshed: 2026-05-09 -->
# Architecture

**Analysis Date:** 2026-05-09

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                          HTTP / SSE Layer                                │
│  main.py — ASGI app, CORS, CorrelationIdMiddleware, catch_exceptions_mw  │
├───────────┬──────────┬──────────┬──────────┬────────────┬───────────────┤
│  api/     │  api/    │  api/    │  api/    │  api/      │  db/routers/  │
│  chat.py  │reference │ hikmah.py│primers.py│ onboarding │  (CRUD)       │
│  /chat/*  │  .py     │ /hikmah/*│ /primers │ /onboarding│/users /lessons│
└─────┬─────┴────┬─────┴────┬─────┴──────────┴────────────┴───────────────┘
      │          │          │
      ▼          ▼          ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         Pipeline / Agent Layer                            │
│                                                                           │
│  core/pipeline_langgraph.py (active)       core/pipeline.py (legacy)    │
│  chat_pipeline_streaming_agentic()          chat_pipeline()              │
│  chat_pipeline_agentic()                   chat_pipeline_streaming()    │
│                │                            references_pipeline()        │
│                │                            hikmah_elaboration_...()     │
│                ▼                                                          │
│        agents/core/chat_agent.py                                         │
│        ChatAgent — LangGraph StateGraph(ChatState)                        │
│        7 nodes, compiled with MemorySaver checkpointer                   │
└────────────┬──────────────────────────────────────────────────────────────┘
             │
      ┌──────┴────────────────────────────────────────────────┐
      │                                                        │
      ▼                                                        ▼
┌─────────────────────────────┐              ┌────────────────────────────┐
│  Main Graph Tools (6)        │              │  Fiqh FAIR-RAG Sub-graph   │
│  agents/tools/               │              │  agents/fiqh/fiqh_graph.py │
│  - check_if_non_islamic_tool │              │  5 nodes: decompose →      │
│  - translate_to_english_tool │              │  retrieve → filter →       │
│  - enhance_query_tool        │              │  assess → [refine loop]    │
│  - retrieve_shia_documents_tool│            │  Max 3 iterations          │
│  - retrieve_sunni_documents_tool│           └──────────┬─────────────────┘
│  - retrieve_quran_tafsir_tool│                         │
└──────────┬──────────────────┘                         │
           │                                            │
           ▼                                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                            Modules Layer                                  │
│  modules/classification/classifier.py  aclassify_non_islamic_query()    │
│  modules/classification/classifier.py  aclassify_fiqh_query()           │
│  modules/enhancement/enhancer.py       aenhance_query()                  │
│  modules/translation/translator.py     atranslate_*()                    │
│  modules/retrieval/retriever.py        aretrieve_shia/sunni/quran()      │
│  modules/reranking/reranker.py         rerank_documents() [sync]         │
│  modules/embedding/embedder.py         getDenseEmbedder(), sparse        │
│  modules/fiqh/                         decomposer, retriever, filter,    │
│                                        sea, refiner, generator, classifier│
└──────────┬──────────────────────────────────────────────────────────────┘
           │
      ┌────┴──────────────────────────────────────────┐
      │                                               │
      ▼                                               ▼
┌────────────────────────┐          ┌────────────────────────────────────┐
│  core/vectorstore.py   │          │  core/memory.py                    │
│  PineconeVectorStore   │          │  AsyncRedisChatMessageHistory      │
│  (dense, sparse, fiqh) │          │  AsyncEphemeralHistory (fallback)  │
└────────────────────────┘          └────────────────────────────────────┘
           │                                               │
      ┌────┴───────────────────┐                    ┌──────┴──────────────┐
      ▼                        ▼                    ▼                     │
┌──────────┐  ┌─────────────────────────┐  ┌──────────────────────────┐  │
│ Pinecone │  │ services/               │  │ db/ (PostgreSQL/Supabase) │  │
│ (3 dense │  │ chat_persistence_svc.py │  │ db/async_session.py       │  │
│ indexes, │  │ memory_service.py       │  │   (asyncpg, chat router)  │  │
│ 2 sparse │  │ primer_service.py       │  │ db/session.py             │  │
│ indexes) │  │ hikmah_quiz_service.py  │  │   (psycopg2, all others)  │  │
└──────────┘  └─────────────────────────┘  │ 13 SQLAlchemy ORM models  │  │
                                           └──────────────────────────┘  │
                                                    Redis ◄───────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| App bootstrap | ASGI app, routers, middleware, lifespan | `main.py` |
| Chat routes | Parse request, drive pipeline, SSE output | `api/chat.py` |
| Reference routes | Semantic reference retrieval | `api/reference.py` |
| Hikmah routes | Elaboration, quiz endpoints | `api/hikmah.py` |
| Agentic pipeline | SSE assembly, token streaming, history persistence | `core/pipeline_langgraph.py` |
| Legacy pipeline | Sync chain for `/chat/` and `/references` | `core/pipeline.py` |
| ChatAgent | LangGraph StateGraph compilation and execution | `agents/core/chat_agent.py` |
| ChatState | TypedDict state schema for the main agent | `agents/state/chat_state.py` |
| FiqhState | TypedDict state schema for the fiqh sub-graph | `agents/state/fiqh_state.py` |
| Agent config | Pydantic config models (RetrievalConfig, ModelConfig, AgentConfig) | `agents/config/agent_config.py` |
| Fiqh sub-graph | FAIR-RAG iterative pipeline (compiled LangGraph) | `agents/fiqh/fiqh_graph.py` |
| Agent tools | LangGraph-bound `@tool async def` wrappers | `agents/tools/` |
| Classification module | Non-Islamic + fiqh category classification | `modules/classification/classifier.py` |
| Enhancement module | Query rewriting for retrieval improvement | `modules/enhancement/enhancer.py` |
| Translation module | Non-English query translation | `modules/translation/translator.py` |
| Retrieval module | Hybrid Pinecone search (dense + sparse, sect-filtered) | `modules/retrieval/retriever.py` |
| Reranking module | Merge and weight dense/sparse results | `modules/reranking/reranker.py` |
| Embedding module | Dense (HuggingFace all-mpnet-base-v2) + sparse TF-IDF | `modules/embedding/embedder.py` |
| Fiqh modules | Decompose, retrieve, filter, SEA, refine, generate | `modules/fiqh/` |
| Vectorstore | Pinecone client wrappers (dense PineconeVectorStore + raw sparse index) | `core/vectorstore.py` |
| Memory | Async Redis history; sync shim for legacy paths | `core/memory.py` |
| Chat persistence | ChatSession/ChatMessage DB rows, Redis hydration | `services/chat_persistence_service.py` |
| Memory service | UserMemoryProfile and MemoryEvent persistence | `services/memory_service.py` |
| Async DB session | asyncpg + AsyncSession for chat router | `db/async_session.py` |
| Sync DB session | psycopg2 + Session for all other routers | `db/session.py` |
| Auth | Supabase JWKS-validated JWT bearer; dev-bypass in dev | `core/auth.py`, `models/JWTBearer.py` |
| Correlation ID | Per-request UUID via ASGI middleware + ContextVar | `core/middleware.py`, `core/context.py` |
| Sentry | Optional error tracking and structured logs | `core/sentry.py` |
| LLM factories | Model constructors by role (generator, classifier, enhancer, translator) | `core/chat_models.py` |

## Pattern Overview

**Overall:** LangGraph agentic graph with FAIR-RAG fiqh sub-graph, sitting behind a FastAPI SSE streaming layer.

**Key Characteristics:**
- All LLM calls use Anthropic (Claude) via `langchain-anthropic`; provider-agnostic `.ainvoke()` / `.astream()` interface
- Main agent graph is end-to-end async; fiqh sub-graph is end-to-end async (DEE-41, DEE-44)
- Dual DB engine: asyncpg for chat routes, psycopg2 for all other routes — same Supabase PostgreSQL database
- Redis for short-term conversation context; PostgreSQL for persistent chat history
- Tools catch exceptions internally and return error dicts — graph continues even when tools fail
- `streaming_mode=True` skips the `generate_response` graph node; pipeline handles LLM streaming itself after graph completes

## Layers

**API Layer:**
- Purpose: HTTP routing, request parsing, auth dependency injection, SSE response assembly
- Location: `api/`
- Contains: `chat.py`, `reference.py`, `hikmah.py`, `primers.py`, `memory_admin.py`, `account.py`, `onboarding.py`, `feedback.py`
- Depends on: `core/pipeline_langgraph.py`, `core/pipeline.py`, `services/`
- Used by: FastAPI app via `main.py` router registration

**Pipeline Layer:**
- Purpose: Orchestrate agent execution; translate node events into SSE; manage streaming token loop; persist history
- Location: `core/pipeline_langgraph.py` (active), `core/pipeline.py` (legacy)
- Contains: `chat_pipeline_streaming_agentic()`, `chat_pipeline_agentic()`, `sse_event()`, SSE event routing logic
- Depends on: `agents/core/chat_agent.py`, `services/chat_persistence_service.py`, `core/memory.py`, `core/chat_models.py`
- Used by: `api/chat.py`, `api/reference.py`, `api/hikmah.py`

**Agent Layer:**
- Purpose: LangGraph graph definition, node execution, tool binding, state management
- Location: `agents/`
- Contains: `core/chat_agent.py`, `state/chat_state.py`, `state/fiqh_state.py`, `tools/`, `fiqh/fiqh_graph.py`, `config/agent_config.py`, `prompts/`
- Depends on: `modules/`, `core/memory.py`, `core/config.py`
- Used by: `core/pipeline_langgraph.py`

**Modules Layer:**
- Purpose: Discrete AI pipeline stages called by tools or the fiqh sub-graph
- Location: `modules/`
- Contains: `classification/`, `embedding/`, `retrieval/`, `reranking/`, `enhancement/`, `translation/`, `generation/`, `context/`, `fiqh/`
- Depends on: `core/vectorstore.py`, `core/config.py`, `core/chat_models.py`
- Used by: `agents/tools/`, `agents/fiqh/fiqh_graph.py`, `core/pipeline.py` (legacy)

**Services Layer:**
- Purpose: Business logic — DB persistence, memory management, primer generation
- Location: `services/`
- Contains: `chat_persistence_service.py`, `memory_service.py`, `consolidation_service.py`, `embedding_service.py`, `primer_service.py`, `hikmah_quiz_service.py`, `account_service.py`
- Depends on: `db/`, `core/memory.py`
- Used by: `api/`, `core/pipeline_langgraph.py`

**Database Layer:**
- Purpose: ORM models, schemas, repository pattern, CRUD helpers, session management
- Location: `db/`
- Contains: `models/` (13 SQLAlchemy ORM models), `schemas/`, `repositories/`, `routers/`, `crud/`, `session.py`, `async_session.py`, `config.py`
- Depends on: PostgreSQL (Supabase), `pydantic-settings`
- Used by: `services/`, `api/` (routers), `main.py`

**Core Utilities Layer:**
- Purpose: Shared primitives consumed across all layers
- Location: `core/`
- Contains: `config.py`, `auth.py`, `memory.py`, `vectorstore.py`, `chat_models.py`, `middleware.py`, `context.py`, `sentry.py`, `logging_config.py`, `utils.py`, `prompt_templates.py`
- Depends on: external services (Redis, Pinecone, Anthropic, Supabase Auth)
- Used by: all layers

## Data Flow

### Primary Path: `/chat/stream/agentic` (SSE streaming)

1. `POST /chat/stream/agentic` hits `api/chat.py:chat_pipeline_agentic_ep()` — `async def`, `Depends(get_db_async)`
2. `JWTBearer` / `DevBypassBearer` validates token; `correlation_id_ctx` set by `CorrelationIdMiddleware`
3. If authenticated user: `chat_persistence_service.hydrate_runtime_history_if_empty()` hydrates Redis from DB, then `persist_user_message()` writes user turn to PostgreSQL (`asyncpg`)
4. `pipeline_langgraph.chat_pipeline_streaming_agentic()` creates `ChatAgent(config)` and returns `StreamingResponse(response_generator())`
5. Inside `response_generator()` async generator:
   - Pre-flight `status` SSE event emitted immediately ("Checking query classification...")
   - `await agent.astream(user_query, session_id, ...)` loads Redis history via `amake_history().aget_messages()`, then drives `compiled_graph.astream()`
   - Graph nodes execute in order: `fiqh_classification` → route decision → `agent` (or `fiqh_subgraph`)
   - Per-node and per-tool `status` events yielded from the async for loop over `agent.astream()`
   - After graph completes: LLM token streaming via `chain.astream()` yields `response_chunk` events one token at a time
   - `chat_persistence_service.aappend_turn_to_runtime_history()` persists assistant turn to Redis + DB
   - Reference events (`hadith_references`, `quran_references`, or `fiqh_references`) emitted
   - `done` event emitted
6. If authenticated user: `wrap_streaming_response_for_persistence()` wraps the `StreamingResponse` to collect streamed bytes and persist assistant message to PostgreSQL after stream ends

### Fiqh FAIR-RAG Path (within step 5 above)

When `fiqh_classification` node detects `VALID_*` category:
1. `fiqh_subgraph` node calls `await fiqh_subgraph.ainvoke({...FiqhState...})`
2. Sub-graph executes: `decompose` → `retrieve` → `filter` → `assess` → conditional edge: if `SUFFICIENT` or iteration >= 3 → `END`; else → `refine` → `retrieve` (loop, max 3 iterations)
3. Each node appends `{"step": str, "message": str}` to `FiqhState["status_events"]`
4. Sub-graph result maps back to `ChatState` delta: `fiqh_filtered_docs`, `fiqh_sea_result`, `fiqh_status_events`
5. Pipeline replays `fiqh_status_events` as SSE `status` events in order
6. Pipeline streams fiqh answer via `fiqh_prompt | model | chain.astream()`, appending `FATWA_DISCLAIMER`

### Non-Agentic Paths (legacy)

- `POST /chat/` → `core/pipeline.py:chat_pipeline()` — sync chain, Redis history, no DB persistence
- `POST /chat/stream` → `core/pipeline.py:chat_pipeline_streaming()` — sync chain, `StreamingResponse`, optional DB persistence
- `POST /references` → `core/pipeline.py:references_pipeline()` — async (DEE-44), retrieves + reranks without LLM generation
- `POST /hikmah/elaborate/stream` → `core/pipeline.py:hikmah_elaboration_pipeline_streaming()` — async (DEE-44)

## LangGraph Graph Topology

### Main Agent Graph (`agents/core/chat_agent.py`)

```
ENTRY: fiqh_classification (async _fiqh_classification_node)
  │
  ├─[category in VALID_*]──► fiqh_subgraph (async _call_fiqh_subgraph_node)
  │                               │
  │                               └──► generate_fiqh_response (async) ──► END
  │
  ├─[category == UNETHICAL]──► check_early_exit (async) ──► END
  │
  └─[otherwise]──► agent (async _agent_node)
                     │
                     ├─[tool_calls present]──► tools (async _tool_node) ──► agent (loop)
                     │
                     ├─[ready_to_answer + streaming_mode=True]──► END
                     │      (pipeline streams tokens after graph completes)
                     │
                     ├─[ready_to_answer + streaming_mode=False]──► generate_response ──► END
                     │
                     ├─[is_non_islamic=True]──► check_early_exit ──► END
                     │
                     └─[should_end or no messages]──► END
```

**Routing functions (sync, pure):**
- `_route_after_fiqh_check()` — `Literal["fiqh", "exit", "continue"]`
- `_should_continue()` — `Literal["continue", "generate", "exit", "end"]`

**Checkpointer:** `MemorySaver` keyed by `thread_id=session_id` — in-memory, per-process, cleared on restart

### Fiqh Sub-Graph (`agents/fiqh/fiqh_graph.py`)

```
ENTRY: decompose (async _decompose_node)
  │
  └──► retrieve (async _retrieve_node)
         │
         └──► filter (async _filter_node)
                │
                └──► assess (async _assess_node)
                       │
                       ├─[verdict==SUFFICIENT or iteration>=3]──► END
                       │
                       └─[INSUFFICIENT + iteration<3]──► refine (async _refine_node)
                                                               │
                                                               └──► retrieve (loop)
```

**Checkpointer:** `False` — stateless per-invocation, no cross-request state leakage

### Tool Inventory (all `@tool async def`, bound via `.bind_tools()`)

| Tool | File | Module Delegate |
|------|------|-----------------|
| `check_if_non_islamic_tool` | `agents/tools/classification_tools.py` | `modules/classification/classifier.aclassify_non_islamic_query()` |
| `translate_to_english_tool` | `agents/tools/translation_tools.py` | `modules/translation/translator` |
| `enhance_query_tool` | `agents/tools/enhancement_tools.py` | `modules/enhancement/enhancer` |
| `retrieve_shia_documents_tool` | `agents/tools/retrieval_tools.py` | `modules/retrieval/retriever.aretrieve_shia_documents()` |
| `retrieve_sunni_documents_tool` | `agents/tools/retrieval_tools.py` | `modules/retrieval/retriever.aretrieve_sunni_documents()` |
| `retrieve_quran_tafsir_tool` | `agents/tools/retrieval_tools.py` | `modules/retrieval/retriever.aretrieve_quran_documents()` |

Note: `check_if_fiqh_tool` and `retrieve_combined_documents_tool` are defined in `agents/tools/` but NOT bound to the main agent — fiqh routing is handled by `_fiqh_classification_node` directly calling `modules/fiqh/classifier.aclassify_fiqh_query()`.

## Async Architecture

### End-to-End Async Paths

| Path | Async since |
|------|-------------|
| `/chat/stream/agentic` and `/chat/agentic` route handlers | Always async |
| `pipeline_langgraph.chat_pipeline_streaming_agentic()` | Always async |
| `ChatAgent.astream()` / `ainvoke()` | DEE-41 |
| All 6 bound `@tool` functions | DEE-41 |
| All 7 LangGraph graph nodes in main agent | DEE-41 |
| All 5 fiqh sub-graph nodes | DEE-44 |
| `fiqh_subgraph.ainvoke()` call from `_call_fiqh_subgraph_node` | DEE-44 |
| LLM calls (`.ainvoke()`, `.astream()`) inside nodes | DEE-41 / DEE-42 |
| Redis history (`amake_history`, `aget_messages`, `aadd_messages`) | DEE-43 |
| Pinecone dense search (`asimilarity_search_with_score`) | DEE-42 |
| Pinecone sparse query (offloaded via `asyncio.to_thread`) | DEE-42 |
| Reranking and sparse TF-IDF embedding (`asyncio.to_thread`) | DEE-42 |
| Chat DB persistence (asyncpg, `AsyncSession`) | DEE-45 |
| `chat_persistence_service.aappend_turn_to_runtime_history()` | DEE-45 |

### Sync-Only Paths (not yet migrated to async)

| Path | Reason / Notes |
|------|----------------|
| `POST /chat/` → `core/pipeline.py:chat_pipeline()` | Legacy path; sync Redis via `make_history()`, no async DB |
| `db/routers/` (lessons, users, lesson_content, user_progress, hikmah_trees) | `Depends(get_db)` — psycopg2 sync sessions; DEE-45 follow-up sub-issues |
| `api/hikmah.py` quiz CRUD routes | `Depends(get_db)` — psycopg2 sync sessions |
| `api/primers.py` | `Depends(get_db)` — psycopg2 sync sessions |
| `modules/reranking/reranker.py:rerank_documents()` | Always sync; called via `asyncio.to_thread` from async retrievers |
| `modules/embedding/embedder.py:generate_sparse_embedding()` | Sync; wrapped in `asyncio.to_thread` by async callers |

### Dual Database Engine Pattern

Both engines target the same Supabase PostgreSQL instance, differ only in driver and session type:

```
db/session.py          → engine (postgresql+psycopg2, sslmode=require)
                          SessionLocal, get_db() generator
                          Used by: all db/routers/, api/hikmah.py, api/primers.py

db/async_session.py    → async_engine (postgresql+asyncpg, ssl="require")
                          AsyncSessionLocal, get_db_async() async generator
                          Used by: api/chat.py ONLY (all /chat/* endpoints)
```

Both use `db/config.py:Settings` (pydantic-settings) to read `DB_*` env vars. `_build_async_database_url()` constructs a `postgresql+asyncpg://` URL from the same settings object.

## State Management

**Per-request graph state:**
- `ChatState` TypedDict passed between LangGraph nodes by value within a single `astream()`/`ainvoke()` call
- `create_initial_state()` in `agents/state/chat_state.py` is the canonical factory — never construct `ChatState` directly
- Key fields: `messages` (with `add_messages` reducer), `user_query`, `working_query`, `runtime_session_id`, `retrieved_docs`, `quran_docs`, `fiqh_filtered_docs`, `fiqh_status_events`, `errors`, `iterations`, `streaming_mode`
- `FiqhState` is created inline in `_call_fiqh_subgraph_node()` and is fully isolated per invocation

**In-memory graph checkpointing:**
- `MemorySaver` checkpointer in `ChatAgent`, keyed by `thread_id=session_id`
- Maintains graph state across node executions within one `astream()`/`ainvoke()` call
- Process-local: cleared on restart; not shared between workers or gunicorn processes

**Short-term conversation context (Redis):**
- `AsyncRedisChatMessageHistory` in `core/memory.py`, keyed by `{KEY_PREFIX}:{session_id}` or `{user_id}:{session_id}` for authenticated users
- TTL-capped (default 12,000 seconds) and message-count capped (`MAX_MESSAGES=30`)
- Loaded at start of each `ainvoke()`/`astream()` call via `_aload_runtime_messages()`
- Falls back to `AsyncEphemeralHistory` when Redis unreachable — per-process, per-session_id, evaporates on restart
- Sync shim `make_history()` retained for `POST /chat/` legacy path and `DELETE /chat/session/{id}`

**Long-term persistent history (PostgreSQL):**
- `chat_sessions` and `chat_messages` tables via `db/models/chat_sessions.py`, `db/models/chat_messages.py`
- `chat_persistence_service.py` handles: session upsert, user message persistence, Redis hydration on load, assistant message persistence after stream
- `wrap_streaming_response_for_persistence()` wraps `StreamingResponse` body to collect bytes post-stream and write assistant text to DB

**Long-term user memory (PostgreSQL):**
- `user_memory_profiles`, `memory_events`, `memory_consolidation` tables
- `services/memory_service.py` and `services/consolidation_service.py`
- Exposed via `GET /admin/memory`

## Early Exit Conditions

| Condition | Where detected | Node path | Result |
|-----------|----------------|-----------|--------|
| `fiqh_category == UNETHICAL` | `fiqh_classification` node | → `check_early_exit` → END | LLM-generated polite rejection, no retrieval |
| `is_non_islamic == True` | `agent` node (`_should_continue`) | → `check_early_exit` → END | Canned `EARLY_EXIT_NON_ISLAMIC` message |
| `fiqh_category in VALID_*` | `fiqh_classification` node | → `fiqh_subgraph` | FAIR-RAG pipeline, bypasses main agent |
| `iterations > max_iterations` | `agent` node | `should_end = True` → END | Pipeline shows retrieval-based error message |

## Error Handling

**Global middleware:** `catch_exceptions_mw` in `main.py` catches unhandled exceptions, logs traceback, returns `{"detail": "internal_error"}` HTTP 500. Sentry `capture_exception` if `SENTRY_ENABLED`. In `ENV=development`, includes `"error": str(e)` for debugging.

**Route handlers:** Explicit `try/except` blocks raising `HTTPException(500, "Internal Server Error")` to avoid leaking internals.

**Graph nodes:** Catch exceptions internally, append `f"...: {str(exc)}"` to `state["errors"]`, set `state["should_end"] = True`. Graph continues to termination; `pipeline_langgraph.py` checks `errors` for fallback messages.

**Tool functions:** Catch all exceptions, return error dicts `{"error": str(e), "documents": []}` — graph keeps running on partial retrieval failure. Callers check `"error"` key.

**Streaming error recovery:** If `assistant_text` was partially collected before an error in `response_generator()`, `pipeline_langgraph.py` still attempts `aappend_turn_to_runtime_history()` before emitting `error` SSE event.

## Cross-Cutting Concerns

**Logging:**
- `core/logging_config.py`: `setup_logging()` configures root logger with `ExtraFormatter`; `sqlalchemy.engine`, `sqlalchemy.pool`, `httpx` silenced at WARNING
- Format: `%(asctime)s [%(levelname)s] %(name)s - %(message)s`
- Pattern: `logger.info("...", extra={"correlation_id": correlation_id_ctx.get(), "session_id": ..., ...})`

**Correlation IDs:**
- `core/middleware.py:CorrelationIdMiddleware` (pure ASGI, not BaseHTTPMiddleware) generates UUID per request
- Stored in `core/context.py:correlation_id` ContextVar; returned as `X-Correlation-ID` response header
- Injected into all structured log records via `extra={"correlation_id": correlation_id_ctx.get()}`

**Observability:**
- `core/sentry.py`: opt-in via `SENTRY_ENABLED=true` + `SENTRY_DSN`; scrubs request body PII (`_scrub_pii`, GDPR Article 9)
- `bind_sentry_scope()` called in `api/chat.py` and `api/reference.py` to set per-request Sentry tags

**Authentication:**
- `core/auth.py` fetches Supabase JWKS at startup (sync, one-time `requests.get()`)
- `auth = DevBypassBearer(jwks, env=ENV)` — in development, passes all requests through; in production, validates JWT
- All routes use `Depends(auth)` with `JWTAuthorizationCredentials` parameter typed as optional — routes handle unauthenticated callers gracefully via `_extract_user_id()` returning `None`

## Architectural Constraints

- **Threading model:** Single-threaded asyncio event loop (uvicorn). Sync CPU-bound work (reranking, sparse TF-IDF embedding) offloaded via `asyncio.to_thread`.
- **Global state:** Module-level singletons at `core/vectorstore.py` (`pc = Pinecone(...)`), `core/memory.py` (`_async_redis_client`, `_ephemeral_async_registry`), and `agents/fiqh/fiqh_graph.py` (`fiqh_subgraph` compiled graph).
- **Circular imports avoided:** Lazy local imports inside async node functions (e.g., `from modules.fiqh.classifier import aclassify_fiqh_query` inside `_fiqh_classification_node`).
- **`streaming_mode` flag contract:** `True` → `_should_continue()` routes to `END` after retrieval (skips `generate_response` node); `False` → routes to `generate_response` node. The flag is set by `ChatAgent.astream()` and `ChatAgent.ainvoke()` callers.
- **Fiqh sub-graph isolation:** `checkpointer=False` ensures no state leaks between requests; `FiqhState` is always constructed fresh in `_call_fiqh_subgraph_node`.
- **DB migration state:** DEE-45 migrated only the chat router to asyncpg. All other routers (`db/routers/`, `api/hikmah.py`, `api/primers.py`, `api/onboarding.py`) still use psycopg2 sync sessions — marked for follow-up sub-issues.

## Anti-Patterns

### Sync DB sessions in async route handlers

**What happens:** `api/hikmah.py`, `api/primers.py`, `db/routers/` all use `Depends(get_db)` (psycopg2) in `async def` route handlers.

**Why it's wrong:** Sync SQLAlchemy I/O inside an async route runs in the thread pool and blocks the event loop at high concurrency.

**Do this instead:** Use `Depends(get_db_async)` from `db/async_session.py`, replacing `Session` with `AsyncSession` and using `await` on all DB operations (pattern from `api/chat.py`).

### `print()` instead of structured logging in modules

**What happens:** `modules/retrieval/retriever.py` uses `print()` for error and status output; some tools use `print(f"[tool_name] Error: {e}")`.

**Why it's wrong:** `print()` bypasses the centralized logging config — no correlation IDs, no Sentry capture, no level filtering.

**Do this instead:** `logger = logging.getLogger(__name__)` and `logger.error("...", exc_info=True, extra={"correlation_id": correlation_id_ctx.get()})`.

### Spurious empty AIMessage filtering

**What happens:** `_agent_node` in `agents/core/chat_agent.py` filters out `AIMessage(content="", tool_calls=None)` messages before passing history to the LLM.

**Why it's needed:** Claude occasionally emits these spurious empty messages in tool-calling sequences; without filtering, they corrupt LLM history context.

**Pattern to preserve:** Filter condition is `isinstance(msg, AIMessage) and msg.content == "" and not getattr(msg, "tool_calls", None)` — preserve `AIMessage(content="", tool_calls=[...])` which is a valid tool-call request.

---

*Architecture analysis: 2026-05-09*
