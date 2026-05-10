# Testing Patterns

**Analysis Date:** 2026-05-09

## Test Framework

**Runner:**
- `pytest==8.4.1`
- Config: `pytest.ini` at project root
- `pytest-asyncio==0.26.0` — async test support (all `@pytest.mark.asyncio` tests use this)

**Supplementary tools:**
- `syrupy==4.9.1` — snapshot testing for SSE event sequences
- `pytest-benchmark==5.1.0` — performance benchmarks
- `pytest-recording==0.13.4` — VCR cassette-based HTTP recording
- `pytest-socket==0.7.0` — network isolation for unit tests
- `vcrpy==7.0.0` — HTTP interaction recording/replay
- `fakeredis` — in-process Redis fake (used in `tests/test_async_memory.py`)
- `aiosqlite` / `sqlite+aiosqlite:///:memory:` — in-process async DB for `tests/test_chat_persistence_service.py`

**Run Commands:**
```bash
pytest tests -q                              # primary suite (real_llm tests skipped by default)
pytest tests/db -q                           # DB compatibility (requires live Postgres)
pytest tests/test_fiqh_*.py -q              # fiqh subsystem only
pytest tests/test_async_concurrency_full.py -q  # concurrency gates (DEE-46)
pytest tests/test_sse_event_order_snapshot.py -q  # SSE snapshot gates
pytest tests/test_sse_event_order_snapshot.py -q --snapshot-update  # refresh snapshots
pytest tests/ -m real_llm -q               # opt-in: real Anthropic + Pinecone + Redis
python agent_tests/test_memory_agent.py    # memory agent integration (run directly)
```

## Test File Organization

**Location:**
- Unit and integration tests: `tests/` (collected by default)
- DB compatibility tests: `tests/db/` (excluded from default collection — requires live Postgres)
- Legacy integration tests: `agent_tests/` (run directly as Python scripts, not via pytest)

**Naming:**
- Unit/integration: `test_<component>.py` — `test_chat_persistence_service.py`, `test_fiqh_classifier.py`
- Feature-area groups: `test_fiqh_*.py` for all fiqh subsystem tests
- Async migration gates: `test_async_concurrency_full.py`, `test_chain_astream_parity.py`, `test_chat_agent_async.py`, `test_async_memory.py`, `test_fiqh_async.py`
- Cross-cutting gates: `test_sse_event_order_snapshot.py`, `test_sentry_async_propagation.py`
- Opt-in perf suite: `test_real_llm_perf.py`

**Directory layout:**
```
tests/
├── conftest.py                     # env defaults, sys.path, pytest_plugins
├── conftest_async_stubs.py         # shared FakePlannerLLM, FakeGeneratorLLM, install_pipeline_stubs
├── __snapshots__/
│   └── test_sse_event_order_snapshot.ambr   # committed syrupy snapshot
├── test_agentic_streaming_pipeline.py       # ChatAgent unit tests (sync)
├── test_agentic_streaming_sse.py            # SSE parse/render helpers (can run standalone)
├── test_async_concurrency_full.py           # DEE-46 concurrency gates
├── test_async_memory.py                     # AsyncRedisChatMessageHistory parity (fakeredis)
├── test_chain_astream_parity.py             # chain.stream vs chain.astream token parity
├── test_chat_agent_async.py                 # ChatAgent async node contract tests
├── test_chat_persistence_service.py        # persistence service (aiosqlite in-memory)
├── test_concurrency_baseline.py             # phase baseline recorder
├── test_embedding_service.py               # EmbeddingService unit tests
├── test_fair_rag.py                         # run_fair_rag() unit tests
├── test_fiqh_async.py                       # fiqh async node/API contracts (DEE-44)
├── test_fiqh_classifier.py                  # fiqh classifier parametrize suite
├── test_fiqh_decomposer.py                  # fiqh decomposer unit tests
├── test_fiqh_filter.py                      # fiqh filter unit tests
├── test_fiqh_generator.py                   # fiqh generator unit tests
├── test_fiqh_graph_logging.py               # fiqh graph WARNING boundary tests
├── test_fiqh_integration.py                 # fiqh SSE path end-to-end (mock-based)
├── test_fiqh_refiner.py                     # fiqh refiner unit tests
├── test_fiqh_retriever.py                   # fiqh retriever unit tests
├── test_fiqh_sea.py                         # fiqh SEA (evidence assessment) unit tests
├── test_hikmah_quiz_service.py              # HikmahQuizService unit tests
├── test_ingest_fiqh.py                      # ingest_fiqh script unit tests
├── test_primer_service.py                   # PrimerService unit tests (sync + some async)
├── test_real_llm_perf.py                    # opt-in real-Anthropic perf gate
├── test_sentry_async_propagation.py         # Sentry scope isolation under asyncio
└── test_sse_event_order_snapshot.py         # syrupy snapshot for SSE event sequence
db/
├── test_baseline_primers_compatibility.py   # personalized_primers table schema checks
└── test_db_premiers_table.py               # exploratory DB schema script (not a real test)
agent_tests/
└── test_memory_agent.py                     # memory agent integration (run directly)
```

## Test Markers

**`real_llm`** — opt-in marker for tests that hit real Anthropic, Pinecone, Redis, and Postgres:
```ini
# pytest.ini
markers =
    real_llm: opt-in tests that exercise real LLM/Pinecone/Redis (skipped by default)
addopts = -m "not real_llm"
```
Apply to a whole file with `pytestmark = pytest.mark.real_llm` (see `tests/test_real_llm_perf.py`).
Run explicitly with: `pytest tests/ -m real_llm -q`

**No other custom markers** are registered. All other tests in `tests/` run by default.

## Conftest and Shared Fixtures

**`tests/conftest.py`** — session-scoped environment bootstrap:
- Sets test-only env var defaults (`ANTHROPIC_API_KEY=test-anthropic-key`, `PINECONE_API_KEY=test-pinecone-key`, `REDIS_URL=redis://127.0.0.1:1/0`, `DB_*` placeholders) via `os.environ.setdefault()`
- The unreachable Redis URL causes `core/memory.py` to fall back to `EphemeralHistory` automatically
- Registers `tests.conftest_async_stubs` as a plugin

**`tests/conftest_async_stubs.py`** — shared deterministic pipeline stubs:
- `FakePlannerLLM` — stateless fake that scripts one tool-call turn then a no-tool-calls final turn; both `_generate` (sync) and `_agenerate` (async) implemented
- `FakeGeneratorLLM` — streaming-capable fake with configurable tokens and per-token sleep; implements `_stream`, `_astream`, `_generate`, `_agenerate`
- `StubConfig` — dataclass with latency knobs: `llm_sleep_s=0.2`, `retrieval_sleep_s=0.1`, `per_token_sleep_s=0.05`
- `install_pipeline_stubs(cfg)` — context manager that monkeypatches ChatAnthropic, generator model, sync/async retrieval functions, and fiqh classifier
- `run_pipeline_once()` / `run_pipeline_concurrent(n=N)` — async harness helpers returning wall-clock stats and raw SSE chunks
- Fixtures: `stub_config` (default `StubConfig`), `installed_stubs` (auto-installs stubs for one test)

## Test Structure

**Suite organization (most test files):**
```python
class TestFiqhClassifier:
    @pytest.mark.parametrize("category_str,expected", [...])
    def test_returns_correct_category_for_valid_llm_output(self, category_str, expected):
        ...

    def test_returns_out_of_scope_on_exception(self):
        ...
```
Some files use flat top-level functions (no class wrapper) — both patterns are acceptable.

**Setup and teardown:**
- `@pytest.fixture` with `yield` for resource cleanup (DB sessions, Sentry client teardown)
- `monkeypatch.setattr` preferred over `unittest.mock.patch` for module-level attribute patching in newer tests
- `unittest.mock.patch` context manager used in older fiqh tests and integration tests

**Assertions:**
- Plain `assert` throughout — no `unittest.TestCase` assert methods
- Error messages included in assertion failures: `assert x == y, f"Expected {y}, got {x}"`

## Mocking Strategies

**Three patterns in use:**

**1. `unittest.mock.patch` + `MagicMock` (most common in fiqh unit tests):**
```python
with patch("modules.fiqh.classifier.chat_models.get_classifier_model",
           return_value=_mock_classifier_model(category_str)):
    result = classify_fiqh_query("test query")
```
Used in: `test_fiqh_classifier.py`, `test_fiqh_decomposer.py`, `test_fiqh_filter.py`, `test_fiqh_sea.py`, `test_fiqh_integration.py`, `test_fair_rag.py`.

**2. `monkeypatch.setattr` (preferred in newer tests):**
```python
monkeypatch.setattr(ChatAgent, "_create_llm_with_tools", lambda self: _FakeLLM())
```
Used in: `test_agentic_streaming_pipeline.py`, `test_async_memory.py`, `test_chat_agent_async.py`, `test_fiqh_async.py`.

**3. `conftest_async_stubs.install_pipeline_stubs()` context manager (concurrency/SSE tests):**
```python
with install_pipeline_stubs(cfg):
    asyncio.run(run_pipeline_once())
    result = asyncio.run(run_pipeline_concurrent(n=10))
```
Stubs the entire pipeline end-to-end: planner LLM, generator LLM, all three retrieval functions (sync + async), and fiqh classifier.

**What to mock:**
- All LLM calls (Anthropic, OpenAI) — never hit real APIs in default suite
- All Pinecone retrieval calls — use canned doc fixtures
- Redis — use `fakeredis` (in `test_async_memory.py`) or rely on `EphemeralHistory` fallback (all other tests)
- PostgreSQL — use `sqlite+aiosqlite:///:memory:` (in `test_chat_persistence_service.py`) or mock `Session` (service unit tests)

**What NOT to mock:**
- The SSE parsing/rendering logic (`test_sse_event_order_snapshot.py`, `test_agentic_streaming_sse.py`)
- `asyncio` primitives and event loop behavior
- `sentry_sdk.isolation_scope()` — the point of `test_sentry_async_propagation.py` is testing real scope behavior

## Fixtures and Factories

**DB session mocks (service unit tests):**
```python
@pytest.fixture
def mock_db():
    db = Mock(spec=Session)
    db.query = Mock(return_value=Mock())
    db.add = Mock()
    db.commit = Mock()
    return db
```
Used in: `tests/test_primer_service.py`, `tests/test_embedding_service.py`, `tests/test_hikmah_quiz_service.py`.

**In-memory async DB (persistence tests):**
```python
async def _make_db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    # Creates chat_sessions and chat_messages tables inline
    ...
    return session_local()
```
File: `tests/test_chat_persistence_service.py`

**Fakeredis shared store (async memory parity):**
```python
@pytest.fixture
def fake_redis_clients(monkeypatch):
    server = fakeredis.FakeServer()
    sync_client = fakeredis.FakeRedis(server=server)
    async_client = fakeredis.aioredis.FakeRedis(server=server)
    # patches both redis.from_url and core.memory._get_async_redis
    ...
    yield sync_client, async_client
```
File: `tests/test_async_memory.py`

**Fiqh document helper:**
```python
def _make_fiqh_doc(ruling_number: str = "100") -> dict:
    return {
        "chunk_id": f"ruling_{ruling_number}_chunk0",
        "metadata": {
            "source_book": "Islamic Laws",
            "chapter": "Chapter of Purity",
            "ruling_number": ruling_number,
            "text_en": f"Ruling {ruling_number} text",
        },
        "page_content": f"Ruling {ruling_number} text",
    }
```
Used across `test_fiqh_integration.py` and `test_fair_rag.py`.

**Snapshot file location:** `tests/__snapshots__/test_sse_event_order_snapshot.ambr`

## Async Test Patterns

**`@pytest.mark.asyncio` decorator** — applied per-test function for async tests:
```python
@pytest.mark.asyncio
async def test_persist_and_query_saved_chat():
    db = await _make_db_session()
    try:
        await chat_persistence_service.persist_user_message(...)
    finally:
        await db.close()
```

**`asyncio.run()` in sync tests** — used for concurrency/perf tests that must control the event loop directly:
```python
def test_phase7_p95_beats_phase0_baseline_3x():
    with install_pipeline_stubs(cfg):
        asyncio.run(run_pipeline_once())  # warmup
        result = asyncio.run(run_pipeline_concurrent(n=10))
    assert speedup >= 3.0
```
Files: `tests/test_async_concurrency_full.py`, `tests/test_sentry_async_propagation.py`, `tests/test_sse_event_order_snapshot.py`.

**Async node contract test pattern:**
```python
@pytest.mark.asyncio
async def test_every_node_is_async():
    from agents.core.chat_agent import ChatAgent
    for name in ["_fiqh_classification_node", "_agent_node", "_tool_node", ...]:
        method = getattr(ChatAgent, name)
        assert asyncio.iscoroutinefunction(method), f"ChatAgent.{name} must be async def"
```
Files: `tests/test_chat_agent_async.py`, `tests/test_fiqh_async.py`.

**Concurrency regression pattern:**
```python
@pytest.mark.asyncio
async def test_concurrent_ainvoke_does_not_serialise(installed_stubs):
    n = 5
    agent = ChatAgent(DEFAULT_AGENT_CONFIG)
    started = time.perf_counter()
    results = await asyncio.gather(*[agent.ainvoke(...) for i in range(n)])
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"agent.ainvoke serialised: wall={elapsed:.3f}s"
```
File: `tests/test_chat_agent_async.py`

**Error recovery pattern:**
```python
with pytest.raises(RuntimeError, match="stream interrupted"):
    await _collect_streaming_response(wrapped)
# Then assert partial content was still persisted
detail = await chat_persistence_service.get_session_with_messages(...)
assert detail["messages"][-1]["content"] == "Partial answer"
```
File: `tests/test_chat_persistence_service.py`

## SSE Snapshot Testing

Uses `syrupy` to lock the event-type sequence emitted by the agentic pipeline:

```python
def test_hadith_path_event_type_sequence_matches_snapshot(snapshot):
    with install_pipeline_stubs(cfg):
        asyncio.run(run_pipeline_once())
        elapsed, chunks = asyncio.run(run_pipeline_once(session_id="hadith-snapshot"))
    enriched = _event_type_with_status_step_sequence(sse_text)
    collapsed = [...]  # deduplicate adjacent identical types
    assert collapsed == snapshot
```

The committed snapshot (`tests/__snapshots__/test_sse_event_order_snapshot.ambr`) captures:
```
['status:starting', 'status:agent', 'status:retrieve_shia_documents_tool',
 'status:agent', 'status:generate_response', 'response_chunk',
 'response_end', 'hadith_references', 'done']
```

To update: `pytest tests/test_sse_event_order_snapshot.py -q --snapshot-update`

File: `tests/test_sse_event_order_snapshot.py`

## Coverage

**Requirements:** No coverage percentage target enforced in `pytest.ini` or CI.

**View coverage:**
```bash
pytest tests -q --cov=. --cov-report=html
```
(requires `pytest-cov` — not listed in `requirements.txt`, install separately if needed)

**Effective coverage by layer:**

| Layer | Coverage | Notes |
|-------|----------|-------|
| `modules/fiqh/` | High | All 7 stages have dedicated test files; async variants tested via `test_fiqh_async.py` |
| `services/chat_persistence_service.py` | High | Full async CRUD round-trip via in-memory aiosqlite |
| `services/hikmah_quiz_service.py` | High | 12 unit tests covering CRUD, submission, memory trigger |
| `services/primer_service.py` | High | Unit tests with mock DB |
| `services/embedding_service.py` | High | Unit tests with mock HuggingFace embedder |
| `agents/core/chat_agent.py` | Medium | Routing logic, tool defaults, async node contracts |
| `core/memory.py` | High (async path) | Wire-compat parity tests via fakeredis |
| `core/pipeline_langgraph.py` | Medium | Fiqh SSE path via mock; concurrency via stubs |
| `modules/retrieval/retriever.py` | Low | No dedicated test file; only stubbed in integration tests |
| `modules/reranking/reranker.py` | Low | No dedicated test file |
| `api/` routes | Low | No `TestClient`-based route handler tests |
| `db/routers/` | None | No router tests |
| `core/auth.py` | None | No JWT validation unit tests |

## Test Types

**Unit Tests (majority):**
- Scope: single function or class in isolation
- Mocking: all external dependencies mocked via `patch` or `monkeypatch`
- Async: `@pytest.mark.asyncio` where the function under test is async
- Location: `tests/test_<module>.py`

**Integration Tests (mock-based):**
- Scope: multiple components wired together but all external I/O mocked
- Key examples:
  - `tests/test_fiqh_integration.py` — full fiqh SSE path from `chat_pipeline_streaming_agentic` to `event: done`
  - `tests/test_agentic_streaming_pipeline.py` — ChatAgent + pipeline_langgraph wired together
  - `tests/test_chat_persistence_service.py` — real async SQLAlchemy against in-memory SQLite

**Concurrency / Performance Tests:**
- Scope: full in-process pipeline end-to-end with deterministic stubs
- Location: `tests/test_async_concurrency_full.py`, `tests/test_concurrency_baseline.py`
- Assertions: wall-clock ratios and p95 speedup gates (≥3x phase-0 baseline, ≥5x serial speedup at N=10)

**Snapshot Tests:**
- Scope: SSE event-type sequence stability
- Location: `tests/test_sse_event_order_snapshot.py`
- Assertion: event sequence matches committed `.ambr` file

**Observability Tests:**
- `tests/test_sentry_async_propagation.py` — Sentry `isolation_scope()` does not leak tags across concurrent coroutines; CorrelationIdMiddleware stamps unique IDs
- `tests/test_fiqh_graph_logging.py` — WARNING log events fire at correct FAIR-RAG failure boundaries (`caplog` fixture)

**DB Compatibility Tests (require live Postgres):**
- Location: `tests/db/`
- Run: `pytest tests/db -q`
- Checks: `personalized_primers` table column existence and properties

**Opt-in Real-LLM Tests:**
- Location: `tests/test_real_llm_perf.py`
- Marker: `pytestmark = pytest.mark.real_llm`
- Requires: valid `.env`, running server at `REAL_LLM_PERF_URL` (default `http://127.0.0.1:8000`)
- Assertions: p50 latency ≤ 30s, concurrent p95 ≤ 60s (configurable via env vars)

## Coverage Gaps

**`api/` route handlers** — no `TestClient` tests:
- `api/chat.py` (402 lines): no tests for auth error handling, session creation, SSE streaming from the HTTP layer
- `api/hikmah.py`, `api/primers.py`, `api/memory_admin.py`, `api/account.py`: untested
- Impact: regressions in HTTP-layer error handling, header processing, or auth logic will not be caught

**`modules/retrieval/retriever.py`** — no dedicated test file:
- Hybrid Pinecone search logic, sparse/dense weighting, metadata filtering untested at unit level
- Only exercised via stub replacement in integration/concurrency tests

**`modules/reranking/reranker.py`** — no dedicated test file:
- `rerank_documents`, `normalize_inplace`, `safe_sample_dense` untested

**`core/auth.py`** — no JWT validation unit tests:
- `JWTBearer` dependency and JWKS verification logic untested

**Fiqh SSE path — fiqh-forcing stub not yet implemented:**
- `test_sse_event_order_snapshot.py` only covers the hadith (non-fiqh) agentic path
- A fiqh-path SSE snapshot requires a stub configuration that returns `IN_SCOPE_FIQH` from the classifier — noted as a follow-up in the DEE-46 PR description

**`services/memory_service.py` and `services/consolidation_service.py`** — not directly tested:
- Memory consolidation logic covered only via `agent_tests/test_memory_agent.py` (integration, not pytest)

---

*Testing analysis: 2026-05-09*
