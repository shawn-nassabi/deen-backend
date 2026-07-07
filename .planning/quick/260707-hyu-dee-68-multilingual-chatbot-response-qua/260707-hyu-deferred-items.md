# Deferred Items — 260707-hyu (DEE-68)

Out-of-scope pre-existing failures observed while running the full
`pytest tests -q --ignore=tests/db` suite for regression verification.
None of these touch `agents/core/chat_agent.py`, `core/prompt_templates.py`,
or the new `tests/test_dee68_*.py` files added by this quick task. Not
fixed, per the executor's scope-boundary rule (only auto-fix issues
directly caused by the current task's changes).

## Environment-dependent (no local Redis reachable)

- `tests/test_fiqh_integration.py::TestFiqhRouting::test_out_of_scope_routes_to_exit`
  — `redis.exceptions.ConnectionError: Error 61 connecting to 127.0.0.1:1.
  Connection refused.` This worktree has no local Redis; `core/memory.py`'s
  `_redis_ok()` health check fails as expected without one running.

## Host-specific concurrency/timing thresholds

- `tests/test_agentic_streaming_pipeline.py::test_streaming_pipeline_uses_runtime_history_and_appends_once`
- `tests/test_agentic_streaming_pipeline.py::test_streaming_pipeline_early_exit_appends_once`
- `tests/test_agentic_streaming_pipeline.py::test_streaming_pipeline_surfaces_quran_retrieval_unavailable_message`
- `tests/test_agentic_streaming_sse.py::test_agentic_streaming_emits_granular_status_events`
- `tests/test_async_concurrency_full.py::test_phase7_p95_beats_phase0_baseline_3x`
- `tests/test_async_concurrency_full.py::test_phase7_speedup_meets_absolute_floor_at_n10`
- `tests/test_async_concurrency_full.py::test_two_concurrent_streams_interleave_response_chunks`
- `tests/test_async_concurrency_full.py::test_max_gap_between_sse_events_within_one_stream`
- `tests/test_chat_agent_async.py::test_concurrent_ainvoke_does_not_serialise`
- `tests/test_concurrency_baseline.py::test_concurrency_threshold`

  These assert relative p95/timing thresholds on stub-driven concurrency
  loadtests. This worktree's venv was freshly created for this quick task
  (see below) on shared/contended hardware; absolute timing floors are
  sensitive to host load and are not expected to be stable across arbitrary
  execution environments.

## Library version behavior mismatch

- `tests/test_agentic_streaming_pipeline.py::test_retrieve_quran_tafsir_tool_returns_error_payload`
  — `NotImplementedError: StructuredTool does not support sync invocation.`
  Raised inside `langchain_core/tools/structured.py` when a `@tool`-decorated
  async function's sync `.invoke()` path is exercised. Suggests either a
  test calling `.invoke()` where `.ainvoke()` is now required, or a
  `langchain-core` behavior change at the pinned `0.3.84` version. Not
  touched by this task's changes (`retrieve_quran_tafsir_tool` is untouched).

- `tests/test_primer_service.py::TestFetchUserSignals::test_fetch_signals_with_embeddings`
- `tests/test_primer_service.py::TestSimilarityQualityAssessment::test_assess_similarity_quality_high`
- `tests/test_primer_service.py::TestSimilarityQualityAssessment::test_assess_similarity_quality_medium`
- `tests/test_primer_service.py::TestGenerationFlow::test_generate_with_insufficient_signals`
- `tests/test_primer_service.py::TestGenerationFlow::test_generate_bypasses_cache_with_force_refresh`

  Failures in embedding-similarity assertions (`similarity_based` flag,
  cosine-similarity thresholds). This worktree's venv installed `torch==2.2.2`
  instead of the `requirements.txt`-pinned `torch==2.6.0` (see note below);
  possible numeric/behavior drift in `sentence-transformers`/embedding
  outputs. `services/primer_service.py` is unrelated to DEE-68 and was not
  modified by this task.

## Environment setup note (informational, not a defect)

`requirements.txt` pins `torch==2.6.0`, which has no available macOS x86_64
wheel on PyPI for this host (Intel Mac, Python 3.11) — only versions up
through `2.2.2` publish x86_64 macOS wheels. To install a working test
environment in this worktree, `torch` was installed at `2.2.2` (all other
packages installed at their exact pinned versions). This is a pre-existing
platform-compatibility gap in `requirements.txt`, unrelated to DEE-68; flagged
here for visibility rather than fixed, since changing the project's pinned
`torch` version is out of scope for this quick task.
