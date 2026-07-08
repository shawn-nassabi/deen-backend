---
phase: 260707-pxt
verified: 2026-07-07T00:00:00Z
status: passed
score: 6/6 must-haves verified (code inspection + Docker test run + offline migration DDL)
has_blocking_gaps: false
test_execution:
  deterministic: "docker compose run --rm -e REDIS_URL=redis://127.0.0.1:1/0 api pytest tests/test_reference_translations.py tests/test_translate_references.py -q -> 17 passed (user-confirmed in Docker)."
  migration_offline: "docker compose run --rm api alembic upgrade onboarding_profiles_001:head --sql -> clean transactional CREATE TABLE reference_translations with composite PK + nullable reviewed_at. Valid."
  migration_apply: "NOT applied to live DB — shared Supabase host unresolvable from local Docker (paused / IPv4-vs-pooler DNS). Applies at deploy via alembic upgrade head."
  batch_job: "scripts/translate_references.py NOT run (build-only by design; needs personal TRANSLATION_ANTHROPIC_API_KEY + live services)."
overrides_applied: 0
human_verification:
  - test: "Run `alembic upgrade head` against a reachable Postgres (e.g. Supabase) and then `alembic heads`"
    expected: "Migration `reference_translations_001` applies cleanly on top of `onboarding_profiles_001`; `alembic heads` resolves to exactly one head (`reference_translations_001`); `reference_translations` table exists with the 8 documented columns and composite PK `(ref_type, ref_key, language)`"
    why_human: "This environment has no reachable Postgres and no `alembic` package installed in the native venv (torch==2.6.0 wheel gap blocks a full `pip install -r requirements.txt` on this Intel Mac) -- migration apply could not be executed or observed directly. Static inspection confirms no other migration file declares `onboarding_profiles_001` as its `down_revision`, so the chain is structurally a single linear DAG, but this is not a substitute for actually running the migration."
  - test: "Run `pytest tests/test_reference_translations.py tests/test_translate_references.py -q` (17 tests expected) and separately `pytest tests -q --ignore=tests/db` to confirm no regressions"
    expected: "17/17 new tests pass; the pre-existing suite shows the same failures as the base commit (15 failures in test_agentic_streaming_pipeline.py, test_agentic_streaming_sse.py, test_async_concurrency_full.py, test_chat_agent_async.py, test_fiqh_integration.py, test_primer_service.py per SUMMARY.md), with no new failures introduced by this change"
    why_human: "`pytest` is not installed in this environment's native venv (`No module named pytest`) and no working venv with the full dependency set was available to this verifier. The executor's SUMMARY.md claims 17/17 passed using a separate worktree venv with a torch substitution, but per this task's adversarial-verification mandate that claim is not accepted as evidence -- it must be independently re-run and observed. Code inspection (below) confirms the test files exist, are syntactically valid (`py_compile` succeeded on all 8 modified/created .py files), and their assertions structurally match every behavior enumerated in the plan's `<behavior>` blocks for Task 2 and Task 3."
  - test: "POST /references?language=urdu against a live server with the reference_translations table populated (or empty) -- manually confirm text_translated is present in the JSON response and null when no row exists"
    expected: "Response items include text/text_ar unchanged plus text_translated (null pre-population) and translated_language='urdu'"
    why_human: "No running server/DB in this environment; this is the standard end-to-end confirmation of wiring that code inspection strongly supports but cannot fully replace."
---

# Quick Task 260707-pxt: DEE-67 reference-lookup selected-language translations Verification Report

**Task Goal:** Postgres sidecar table `reference_translations` + join-after-retrieval enrichment wired into `/references` and the SSE `hadith_references`/`quran_references` events with EN/AR fallback and a `language` input, plus an offline batch MT script (build-not-run) using a dedicated `TRANSLATION_ANTHROPIC_API_KEY` + `claude-sonnet-5` via the raw `anthropic` SDK.

**Verified:** 2026-07-07 (code-inspection based; no live DB/pytest available in this environment)
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Sidecar model + migration exist, keyed for hadith + Quran/tafsir, provenance columns + nullable reviewed_at, NO status/reviewer state machine | VERIFIED | `db/models/reference_translations.py` defines exactly 8 columns: `ref_type, ref_key, language` (composite PK), `translated_text`, `source` (default `"mt"`), `translated_at` (server_default `func.now()`), `model`, `reviewed_at` (nullable). No `status`/`reviewer` columns anywhere. Migration `alembic/versions/20260707_create_reference_translations_table.py` mirrors the model exactly, `revision='reference_translations_001'`, `down_revision='onboarding_profiles_001'`. |
| 2 | Translation added ALONGSIDE existing text/text_ar (existing keys untouched), threaded via `language` on /references and `target_language` on SSE, EN/AR fallback when row absent | VERIFIED | `core/utils.py::aformat_references_as_json`/`aformat_quran_references_as_json` call the original sync formatters first (`base = format_references_as_json(...)`), never modify the sync functions, and only add new keys (`text_translated`, `translated_language`, `quran_translation_translated`, `tafsir_text_translated`). `api/reference.py` adds a `language: str = Query("english", ...)` param passed to `pipeline.references_pipeline(user_query, sect, limit, language)`. `core/pipeline_langgraph.py` lines 516/520 pass the pre-existing `target_language` into the new async formatters. Missing rows resolve to `None` via `dict.get()` (no KeyError), confirmed both in code and in `tests/test_reference_translations.py::test_language_urdu_calls_lookup_once_and_merges` (asserts `result[1]["text_translated"] is None` for an unmatched key). |
| 3 | Pinecone retrieval/vector search untouched -- translations joined AFTER retrieval only in the formatter layer | VERIFIED | `modules/retrieval/retriever.py` and `modules/reranking/reranker.py` show no diff in this change (git commit diffs only touch `api/reference.py`, `core/pipeline.py`, `core/pipeline_langgraph.py`, `core/utils.py`, `services/reference_translation_service.py`, `db/models/*`, `alembic/versions/*`, `scripts/translate_references.py`, `CLAUDE.md`, and the two new test files -- confirmed via `git show --stat` on all 3 task commits). The new async formatters call `format_references_as_json(retrieved_docs)` (the existing, unmodified sync formatter) before any DB lookup. |
| 4 | `scripts/translate_references.py` uses `TRANSLATION_ANTHROPIC_API_KEY` + `claude-sonnet-5` via raw `anthropic` SDK, does NOT import `core.chat_models` or `core.config.ANTHROPIC_API_KEY`, and is not auto-run anywhere | VERIFIED | `scripts/translate_references.py` imports `from anthropic import Anthropic` (raw SDK, not `langchain_anthropic`). `_get_translation_client()` reads only `os.getenv("TRANSLATION_ANTHROPIC_API_KEY")`, raises `ValueError` mentioning that var name if unset. `DEFAULT_MODEL = "claude-sonnet-5"`. Grep confirms zero occurrences of `chat_models` as an import and zero references to `core.config.ANTHROPIC_API_KEY` (only docstring/comment mentions of the bare string `ANTHROPIC_API_KEY` for isolation documentation). `grep -rln "scripts.translate_references\|scripts/translate_references"` across the repo (excluding the script itself and its test file) returns nothing -- no route, no startup hook, no CI config invokes it. `main()` only runs under `if __name__ == "__main__":`. |
| 5 | At request time most references have no matching row (migration not applied), so translated fields come back null and client falls back to EN/AR | VERIFIED (by design + code path) | Since `alembic upgrade head` was not run (confirmed: this is explicitly deferred, see human_verification below), the `reference_translations` table does not yet exist in any live DB touched by this task. `alookup_translations` is wrapped in `try/except Exception` and returns `{}` on any DB error (including "table does not exist"), so pre-migration behavior is a safe empty-dict fallback -- confirmed by `tests/test_reference_translations.py::test_returns_empty_dict_on_db_exception`. Post-migration-but-unpopulated behavior (table exists, zero rows) also correctly returns `{}` via the same `SELECT ... WHERE ... IN (...)` returning no rows. |
| 6 | Alembic heads resolves to a single head after this migration, chaining cleanly onto the current head (`onboarding_profiles_001`) | UNCERTAIN (static chain verified; live command not run) | Static inspection of all 12 files in `alembic/versions/` confirms a single linear chain: `initial_schema_001 -> userid_to_string -> a12c6d22b9d9 -> baseline_primers_001 -> personalized_primers_001 -> embeddings_001 -> page_quiz_001 -> chat_history_001 -> memory_agent_001 -> embeddings_002 -> onboarding_profiles_001 -> reference_translations_001`. No other file declares `down_revision = 'onboarding_profiles_001'` (grep confirmed exactly one match: the new migration itself), so there is no branch/fork. `alembic heads` itself could not be run in this environment (alembic not installed in the native venv; no reachable Postgres) -- routed to human_verification. |

**Score:** 5/6 truths VERIFIED by direct code inspection, 1/6 UNCERTAIN pending a live `alembic heads` run (structurally sound but unexecuted).

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `db/models/reference_translations.py` | `ReferenceTranslation` model, composite PK + provenance columns | VERIFIED | Exists, exact column set matches LOCKED schema, no extra columns |
| `alembic/versions/20260707_create_reference_translations_table.py` | Migration, `reference_translations_001` / `down_revision=onboarding_profiles_001` | VERIFIED | Exists, matches model exactly, `downgrade()` drops the table |
| `services/reference_translation_service.py` | `alookup_translations(ref_type, ref_keys, language) -> dict` | VERIFIED | Exists, self-contained `AsyncSessionLocal()` per call, never raises (broad `try/except` returns `{}`) |
| `core/utils.py` | `aformat_references_as_json` / `aformat_quran_references_as_json` async wrappers | VERIFIED | Both exist immediately after the sync formatters, additive-only field merging, skip DB call when language unset/"english" |
| `api/reference.py` | `language` Query param threaded to `references_pipeline` | VERIFIED | `Query("english", ...)` param added, passed positionally to `pipeline.references_pipeline` |
| `core/pipeline.py` | `references_pipeline(..., language="english")` threading to `aformat_references_as_json` | VERIFIED | Signature updated, `await utils.aformat_references_as_json(docs, language)` replaces the old sync call |
| `core/pipeline_langgraph.py` | SSE `hadith_references`/`quran_references` built via new async formatters with `target_language` | VERIFIED | Lines 516/520 confirmed `await utils.aformat_references_as_json(hadith_docs, target_language)` / `await utils.aformat_quran_references_as_json(quran_docs, target_language)` |
| `scripts/translate_references.py` | Offline batch MT job, dedicated key, raw SDK, build-not-run | VERIFIED | Exists, `py_compile` clean, `TRANSLATION_ANTHROPIC_API_KEY`-only credential path, `Session.merge()` idempotent upsert, `--dry-run`/`--limit` safety flags, never invoked elsewhere in the repo |
| `tests/test_reference_translations.py` | Deterministic mocked tests | VERIFIED (existence + content); NOT independently executed | 9 tests, all behaviors from the plan's `<behavior>` block are present and structurally correct (fake async session, fake result/scalars, patch targets match real call sites) |
| `tests/test_translate_references.py` | Deterministic mocked tests for batch script | VERIFIED (existence + content); NOT independently executed | 8 tests (`parse_args`, `_get_translation_client` x2, `translate_text`, `upsert_translation`, `run_batch` x3), fake Pinecone index/session objects, patch targets match real function names |
| `CLAUDE.md` | Start-to-finish run commands for batch job + `alembic upgrade head` step | VERIFIED | New "# Reference translation batch job (DEE-67...)" block added to the `## Commands` fenced bash section with all 4 documented commands plus a note that `alembic upgrade head` must run first |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `api/reference.py` | `core/pipeline.py::references_pipeline` | `language: str = Query(...)` | WIRED | Confirmed by grep: `language: str = Query(` present, call site passes `language` positionally |
| `core/pipeline.py::references_pipeline` | `core/utils.py::aformat_references_as_json` | `await utils.aformat_references_as_json(docs, language)` | WIRED | Confirmed at line 112 |
| `core/pipeline_langgraph.py` | `core/utils.py::aformat_references_as_json` / `aformat_quran_references_as_json` | `await ...(docs, target_language)` before SSE yield | WIRED | Confirmed at lines 516, 520; `target_language` already in scope from function signature (line 149) |
| `core/utils.py` | `services/reference_translation_service.py::alookup_translations` | join-after-retrieval lookup keyed by `hadith_id` / `chunk_id` | WIRED | `from services import reference_translation_service` imported at top of `core/utils.py`; both async formatters call `reference_translation_service.alookup_translations(...)` |
| `services/reference_translation_service.py` | `db/models/reference_translations.py::ReferenceTranslation` | `select(ReferenceTranslation).where(...)` | WIRED | Confirmed `select(ReferenceTranslation).where(ReferenceTranslation.ref_type == ..., ReferenceTranslation.ref_key.in_(keys), ReferenceTranslation.language == language)` |
| `scripts/translate_references.py` | `db/models/reference_translations.py::ReferenceTranslation` | `db.merge(row)` upsert | WIRED | Confirmed `upsert_translation()` constructs `ReferenceTranslation(...)`, calls `db.merge(row)` then `db.commit()` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|---------------------|--------|
| `aformat_references_as_json` | `text_translated` | `reference_translation_service.alookup_translations("hadith", hadith_ids, language)` -> real `SELECT` against `ReferenceTranslation` | Yes (real SQLAlchemy query, not a static stub) -- returns empty dict pre-migration/pre-population, which is documented and expected behavior, not a hollow/hardcoded stub | FLOWING (empty pending migration + corpus population, by design) |
| `aformat_quran_references_as_json` | `quran_translation_translated`, `tafsir_text_translated` | Same lookup service, two concurrent `alookup_translations` calls via `asyncio.gather` | Same as above | FLOWING (empty pending migration + corpus population, by design) |
| `scripts/translate_references.py::run_batch` | translated text | `translate_text()` -> real `client.messages.create()` call (Anthropic SDK), not a static return | Yes (only exercised live when `--dry-run` is absent) | N/A -- correctly gated by `dry_run`, intentionally not executed in this task |

No hollow props or hardcoded-empty-return anti-patterns found; the `None`/`{}` fallbacks are explicit, intentional, and match the LOCKED "MT ships later, EN/AR fallback until then" decision in CONTEXT.md.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 8 modified/created Python files compile | `python -m py_compile scripts/translate_references.py db/models/reference_translations.py services/reference_translation_service.py core/utils.py core/pipeline.py api/reference.py core/pipeline_langgraph.py alembic/versions/20260707_create_reference_translations_table.py` | "ALL COMPILE OK" | PASS |
| `pytest tests/test_reference_translations.py tests/test_translate_references.py -q` | attempted | `No module named pytest` (native venv has no pytest; torch==2.6.0 wheel gap on this Intel Mac blocks a full `pip install -r requirements.txt`, matching the documented environment limitation) | SKIP -> routed to human_verification |
| `alembic heads` | attempted | `alembic not found` (not installed in native venv; no live Postgres reachable either) | SKIP -> routed to human_verification |
| `chunk_id` field genuinely exists in retrieval output (not a hallucinated key name) | `grep -n "chunk_id" modules/retrieval/retriever.py` | Two matches, both `"chunk_id": match.id` (Pinecone match id) | PASS -- confirms the `ref_key` mapping documented in the model docstring and used by `aformat_quran_references_as_json` is grounded in real data |
| Migration chain has no fork/branch onto `onboarding_profiles_001` | `grep -rln "down_revision = 'onboarding_profiles_001'" alembic/versions/` | Exactly one match: the new migration file itself | PASS |
| `scripts/translate_references.py` not invoked anywhere else in the repo | `grep -rln "scripts.translate_references\|scripts/translate_references" --include="*.py" .` (excluding the script + its test) | No matches | PASS |

### Probe Execution

Not applicable -- no `scripts/*/tests/probe-*.sh` convention used by this task; PLAN.md declares no probes.

### Requirements Coverage

This is a quick-task workflow (no `.planning/REQUIREMENTS.md` phase mapping in this repo). Requirement `DEE-67` is declared in `260707-pxt-PLAN.md` frontmatter and traced end-to-end through the truths/artifacts/key-links above.

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| DEE-67 | 260707-pxt-PLAN.md | Selected-language reference translations, sidecar table + join-after-retrieval + offline batch job | SATISFIED (code-level; live migration/test-run pending) | See truths 1-6 above |

### Anti-Patterns Found

None. No `TODO`/`FIXME`/`XXX`/`HACK`/`PLACEHOLDER` markers, no empty-handler stubs, no hardcoded-empty returns that bypass real logic, in any of the 11 created/modified files.

### Human Verification Required

See YAML frontmatter `human_verification` section. Summary:

1. **Run `alembic upgrade head` + `alembic heads`** against a reachable Postgres to confirm the migration actually applies and the head resolves to exactly one revision. This environment has no live DB and no `alembic` package installed.
2. **Run `pytest tests/test_reference_translations.py tests/test_translate_references.py -q`** (expect 17 passed) and **`pytest tests -q --ignore=tests/db`** to independently confirm the SUMMARY.md's "17 passed, 15 pre-existing unrelated failures" claim. This environment has no `pytest` installed in the native venv (documented torch==2.6.0 wheel gap on Intel Mac) and no alternate working venv was available to this verifier.
3. **Manually hit `POST /references?language=urdu`** (and the SSE `/chat/stream/agentic` path) against a running server to visually confirm `text_translated`/`translated_language` appear in the JSON with the documented `null` fallback pre-population.

### Gaps Summary

No code-level gaps found. Every must-have artifact, truth, and key link is present, correctly implemented, and consistent with both the PLAN.md must_haves and the LOCKED decisions in CONTEXT.md. The task's own design intentionally defers two operational steps (migration apply, corpus population) to a live environment with Postgres access, which this verifier does not have. The only reason this report is not `passed` is that (a) the SUMMARY.md's test-pass claim cannot be independently reproduced in this sandbox (pytest not installed) and (b) `alembic heads` cannot be independently run (alembic not installed, no DB) -- both are routed to human_verification per the environment note rather than failed, since code inspection gives no reason to doubt them and the plan explicitly scoped migration-apply as a deferred manual step.

---

*Verified: 2026-07-07*
*Verifier: Claude (gsd-verifier)*
