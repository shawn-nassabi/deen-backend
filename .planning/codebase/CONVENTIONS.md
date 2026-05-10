# Coding Conventions

**Analysis Date:** 2026-05-09

## Naming Patterns

**Files and Modules:**
- All lowercase with underscores: `chat_persistence_service.py`, `pipeline_langgraph.py`, `hikmah_quiz_service.py`
- Module directories: short lowercase, domain-scoped — `api/`, `agents/`, `core/`, `modules/`, `services/`, `db/`
- One historical exception: `models/JWTBearer.py` uses PascalCase (class-named-as-file — do not replicate)

**Classes:**
- `PascalCase` throughout: `ChatAgent`, `HikmahQuizService`, `PrimerService`, `CRUDBase`, `ExtraFormatter`, `JWTBearer`
- SQLAlchemy models follow the same rule: `User`, `ChatSession`, `ChatMessage`, `LessonPageQuizQuestion`

**Functions:**
- `snake_case` for all functions: `generate_response`, `retrieve_shia_documents`, `build_runtime_session_id`
- Private helpers prefixed with underscore: `_extract_user_id`, `_require_user_id`, `_looks_like_sse_stream`, `_extract_agentic_sse_answer_text`, `_make_db_session`, `_build_graph`
- Async variants of sync functions are prefixed with `a`: `retrieve_shia_documents` → `aretrieve_shia_documents`, `classify_fiqh_query` → `aclassify_fiqh_query`, `make_history` → `amake_history`. This pairing is a load-bearing contract — both must be maintained together.
- LangGraph tool names are descriptive verb phrases: `enhance_query_tool`, `retrieve_shia_documents_tool`, `check_if_non_islamic_tool`

**Variables:**
- `snake_case`: `user_query`, `session_id`, `target_language`, `runtime_session_id`
- Module-level constants: `UPPER_SNAKE_CASE` — `OPENAI_API_KEY`, `REDIS_URL`, `REFERENCES_MARKER`, `DEFAULT_FORMAT`, `MAX_MESSAGES`
- SQLAlchemy model attributes match the DB column name: `created_at`, `updated_at`, `is_active`, `display_name`

## Code Style

**Formatting:**
- No enforced auto-formatter (no `.prettierrc`, `.flake8`, `ruff.toml`, or `pyproject.toml` in project root)
- Indentation: 4 spaces consistently (enforced by convention, not tooling)
- Line length: not strictly enforced; some lines in `modules/generation/stream_generator.py` exceed 100 chars
- No formatter is run in CI — diffs should be reviewed by eye for consistency

**Linting:**
- No linter configured (no `.flake8`, `.pylintrc`, or `ruff.toml`)
- `type: ignore` comments are minimal and intentional: `chat_agent_mod.ChatAnthropic = _planner_factory  # type: ignore[assignment]` in `tests/conftest_async_stubs.py`

## Import Organization

**Order (followed in well-maintained files):**
1. Standard library (`os`, `sys`, `re`, `json`, `asyncio`, `datetime`)
2. Third-party (`fastapi`, `langchain`, `sqlalchemy`, `pydantic`, `redis`)
3. Local application (`from core import ...`, `from agents import ...`, `from services import ...`)

**Examples of correct order:** `services/chat_persistence_service.py`, `agents/core/chat_agent.py`

**Exception — test files:** Use `sys.path.insert(0, ...)` at the top to allow running as scripts:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
```
This is an accepted pattern in `tests/` only.

**Path Aliases:**
- No path aliases configured; all imports are absolute from project root

## Error Handling

**Route Handlers — catch all exceptions, raise `HTTPException`:**
```python
try:
    ai_response = pipeline.chat_pipeline(user_query, session_id)
    return {"response": ai_response}
except Exception:
    raise HTTPException(status_code=500, detail="Internal Server Error")
```
Generic 500 message is intentional — no internal details leaked to client. File: `api/chat.py`.

**Input Validation — raise `HTTPException(400)` directly:**
```python
if not user_query:
    return {"response": "Please provide an appropriate query."}
if not session_id:
    raise HTTPException(status_code=400, detail="Missing session_id")
```

**Domain Errors — raise typed Python exceptions:**
```python
raise LookupError(f"LessonContent {lesson_content_id} not found")
raise ValueError("Exactly one choice must be marked as correct")
```
Used in `services/hikmah_quiz_service.py` and similar service-layer code.

**LangGraph Tool Functions — return error dicts, never raise:**
```python
except Exception as e:
    return {
        "documents": [],
        "count": 0,
        "source": "shia",
        "error": str(e),
    }
```
This keeps the LangGraph graph running even when individual tools fail. Callers check for the `"error"` key. File: `agents/tools/retrieval_tools.py`.

**Database Operations:**
- Wrap in `try/except`, log error, then re-raise or return fallback
- `services/chat_persistence_service.py` catches DB errors and falls back to no-op persistence

**Global Exception Middleware (in `main.py`):**
- `catch_exceptions_mw` catches all unhandled exceptions, logs traceback, returns `{"detail": "internal_error"}` with HTTP 500

## Logging Conventions

**Framework:**
- `logging` module via centralized setup at `core/logging_config.py`
- Call `setup_logging()` at app startup (invoked from `main.py`)
- `get_memory_logger()` returns a dedicated `"memory"` logger for Redis/history components

**Logger instantiation (preferred pattern):**
```python
import logging
logger = logging.getLogger(__name__)
```
Used in `api/chat.py`, `agents/tools/retrieval_tools.py`, `modules/generation/generator.py`.

**Log format:** `%(asctime)s [%(levelname)s] %(name)s - %(message)s`
Extra dict keys appended as `key=value` pairs by `ExtraFormatter` in `core/logging_config.py`.

**Extra context (preferred pattern for structured logging):**
```python
logger.error("Retrieval error", exc_info=True, extra={
    "correlation_id": correlation_id_ctx.get(),
    "error": str(e),
})
```

**Silenced libraries:** `sqlalchemy.engine`, `sqlalchemy.pool`, `httpx` set to `WARNING` level.

**Known violation — `print()` in hot-path modules:**
Several older modules still use `print()` instead of `logger.*`:
- `modules/retrieval/retriever.py`: multiple `print(f"INSIDE ...")`
- `modules/enhancement/enhancer.py`: `print("INSIDE enhance_query")`, `print("Generated enhanced query:", ...)`
- `modules/embedding/embedder.py`: `print("INSIDE generate_sparse_embedding")`
- `agents/tools/classification_tools.py`: `print(f"[check_if_non_islamic_tool] Error: {e}")`
- `agents/tools/enhancement_tools.py`: `print(f"[enhance_query_tool] Error: {e}")`
- `agents/tools/translation_tools.py`: two `print(f"[...] Error: {e}")` calls
- `modules/translation/translator.py`: two `print(f"[...] error: {e}")` calls

**Rule: Prefer `logger.*` over `print()` in all new code.**

## Type Annotations

**Well-annotated layers:**
- `services/` layer: all public functions carry full type hints including return types, `Optional`, `List`, `Dict`, `Callable`, `AsyncIterator`
- `agents/` layer: `agents/core/chat_agent.py` and all tool functions are fully typed
- `db/crud/base.py`: uses `Generic[ModelType, ...]` with `TypeVar`
- `services/chat_persistence_service.py`: uses `from __future__ import annotations` for forward references

**Under-annotated modules (do not follow these as examples):**
- `modules/retrieval/retriever.py`: `retrieve_documents(query, no_of_docs=10)` — no type hints on parameters
- `modules/embedding/embedder.py`: `getSparseEmbedder()` — no type hints, non-snake-case name (legacy)
- `modules/generation/generator.py`: `generate_response(query: str, retrieved_docs: list)` — `list` not parameterized
- `modules/reranking/reranker.py`: `rerank_documents(dense_results, sparse_results, no_of_docs)` — no types

**Rule for new code:** Add type hints to all new or changed functions. Use parameterized generics (`List[str]`, `Dict[str, Any]`, `Optional[str]`).

## Async/Sync Pairing Convention

Every sync function that touches an LLM, Redis, or Pinecone must have a paired async variant using the `a`-prefix:

```python
# Sync (kept for legacy callers only)
def classify_fiqh_query(query: str) -> str: ...

# Async (required for all new call sites inside the event loop)
async def aclassify_fiqh_query(query: str) -> str: ...
```

Files following this pattern: `modules/fiqh/classifier.py`, `modules/fiqh/retriever.py`, `modules/fiqh/filter.py`, `modules/fiqh/decomposer.py`, `modules/fiqh/refiner.py`, `modules/fiqh/sea.py`, `modules/retrieval/retriever.py`, `modules/classification/classifier.py`, `modules/enhancement/enhancer.py`, `modules/translation/translator.py`.

**Never call the sync variant from inside an `async def`** — this blocks the event loop.

## Module Design and Pydantic Schemas

**API schemas** in `models/schemas.py`: `ChatRequest`, `ElaborationRequest`, `PersonalizedPrimerResponse`, `QuizQuestionCreateRequest`

**DB schemas** in `db/schemas/`: `lessons.py`, `users.py`, `user_progress.py`, `personalized_primers.py`
- Use `model_validator(mode="after")` for cross-field validation (see `QuizQuestionCreateRequest`)

**SQLAlchemy models:**
- Inherit from `Base` imported from `db/session.py`
- `__tablename__` always defined as a plain string
- Timestamps: `TIMESTAMP(timezone=True)` with `server_default=func.now()`

**CRUD pattern:**
- `db/crud/base.py` provides `CRUDBase[ModelType, CreateSchema, UpdateSchema]`
- Specialized CRUD classes in `db/crud/` extend it: `db/crud/lessons.py`, `db/crud/users.py`

## SSE Event Format Convention

Streaming responses use `fastapi.responses.StreamingResponse` with `media_type="text/event-stream"`.
SSE format: `event: <name>\ndata: <json>\n\n`

Valid event types (new code must use these exact names):
- `status` — pipeline step progress (`{"step": "<step_name>", "message": "<human label>"}`)
- `response_chunk` — one streaming token (`{"token": "<text>"}`)
- `response_end` — stream finished (`{}`)
- `hadith_references` — hadith metadata (`{"references": [...]}`)
- `quran_references` — Quran/Tafsir metadata (`{"references": [...]}`)
- `fiqh_references` — Sistani ruling citations (`{"references": [...]}`)
- `done` — close signal, **must be the last event** (`{}`)
- `error` — error occurred (`{"message": "<text>"}`)

## Commit Style

Short imperative subjects with Linear issue prefix: `feat(DEE-47): add deploy-dev workflow`

---

*Convention analysis: 2026-05-09*
