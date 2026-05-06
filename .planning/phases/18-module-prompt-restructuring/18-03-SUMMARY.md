---
plan: 18-03
phase: 18-module-prompt-restructuring
status: complete
commit: ccea071
---

# Plan 18-03 Summary: Update Tests + Human Checkpoint

## What Was Built

**tests/test_agentic_streaming_pipeline.py:**
- Monkeypatch updated: `generator_prompt_template` (deleted) → `generator_messages` (new builder function)
- Lambda intercepts `generator_messages()` call and returns `chat_history` directly
- `fake_model_fn`: `payload["chat_history"]` → `payload` (receives list directly after refactor)
- `RunnableLambda` import retained (still used for `get_generator_model` mock)

**tests/test_fiqh_integration.py (3 SSEPath tests):**
- Removed `with patch("modules.fiqh.generator._prompt")` blocks — `_prompt` no longer exists
- Replaced `mock_prompt.__or__ = MagicMock(return_value=mock_chain)` with direct `mock_model_instance.stream.return_value = [...]`
- Updated `get_generator_model` patches to return `mock_model_instance` with `.stream()` configured

## Test Results

- `pytest tests/test_agentic_streaming_pipeline.py` → 7 passed
- `pytest tests/test_fiqh_integration.py::TestFiqhSSEPath` → 3 passed (previously failing)
- Pre-existing failures unrelated to Phase 18:
  - `TestFiqhRouting::test_out_of_scope_routes_to_exit` — routing logic regression, no `_prompt` reference
  - `tests/test_primer_service.py` (5 tests) — `lesson_crud` local import cannot be patched at module level; also `langchain_huggingface` missing

## Phase 18 Success Criteria

- `grep -rn 'ChatPromptTemplate.from_messages' modules/fiqh/ modules/classification/ modules/translation/ modules/generation/ core/pipeline_langgraph.py` → 0 results ✓
- `grep -c 'ChatPromptTemplate.from_messages' core/prompt_templates.py` → 2 (enhancers only) ✓
- `grep -c 'NOT refactored to make_cached_system_message' core/prompt_templates.py` → 1 ✓
- `git diff modules/enhancement/enhancer.py` → empty (untouched) ✓
- All tests that were passing before Phase 18 remain passing ✓

## Human Checkpoint

Plan 18-03 requires human verification per `autonomous: false` gate. See checkpoint in plan for verification commands.

## Self-Check: PASSED
