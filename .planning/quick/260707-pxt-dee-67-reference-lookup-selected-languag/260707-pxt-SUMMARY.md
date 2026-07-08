---
phase: 260707-pxt
plan: 01
subsystem: api
tags: [postgres, sqlalchemy, alembic, sse, langgraph, anthropic, pinecone, i18n]

# Dependency graph
requires: []
provides:
  - "reference_translations Postgres sidecar table (model + migration) keyed on (ref_type, ref_key, language)"
  - "services/reference_translation_service.py::alookup_translations async lookup, never raises"
  - "core/utils.py async formatter wrappers (aformat_references_as_json, aformat_quran_references_as_json) joining MT translations after retrieval"
  - "POST /references language query param threaded to core.pipeline.references_pipeline"
  - "hadith_references/quran_references SSE events on /chat/stream/agentic carry selected-language fields"
  - "scripts/translate_references.py re-runnable offline batch MT job (built, not run) using a dedicated TRANSLATION_ANTHROPIC_API_KEY"
affects: [api, chat-sse, references]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Join-after-retrieval sidecar lookup: Pinecone retrieval/ranking untouched, translations merged onto already-formatted reference dicts via a Postgres sidecar table"
    - "Async wrapper around existing sync formatter functions (aformat_* calls format_* first, then additively merges translation fields)"
    - "Dedicated-credential isolation for offline batch jobs: raw anthropic SDK client + separate env var, never core.chat_models / app ANTHROPIC_API_KEY"

key-files:
  created:
    - db/models/reference_translations.py
    - alembic/versions/20260707_create_reference_translations_table.py
    - services/reference_translation_service.py
    - scripts/translate_references.py
    - tests/test_reference_translations.py
    - tests/test_translate_references.py
  modified:
    - core/utils.py
    - core/pipeline.py
    - api/reference.py
    - core/pipeline_langgraph.py
    - CLAUDE.md

key-decisions:
  - "Single unified reference_translations table with a ref_type discriminator (hadith/quran_translation/tafsir_text) + ref_key + language composite PK, rather than per-type tables"
  - "ref_key resolution: hadith_id for ref_type=hadith; Pinecone vector chunk_id for quran_translation/tafsir_text (two rows share the same chunk_id since a chunk has two independently-translatable fields)"
  - "New response fields are additive: text_translated/translated_language (hadith), quran_translation_translated/tafsir_text_translated/translated_language (Quran/tafsir) -- existing text/text_ar/quran_translation/tafsir_text fields are never modified"
  - "No DB lookup performed when language is unset or 'english' -- avoids an unnecessary round trip for the default case"
  - "Batch MT script reads TRANSLATION_ANTHROPIC_API_KEY only, via the raw anthropic SDK -- never core.chat_models or the app's ANTHROPIC_API_KEY -- keeping personal translation spend structurally isolated from production usage"

requirements-completed: [DEE-67]

# Metrics
duration: ~35min
completed: 2026-07-07
---

# Phase 260707-pxt Plan 01: DEE-67 reference-lookup selected-language translations Summary

**Postgres sidecar `reference_translations` table + join-after-retrieval async lookup threading a selected `language` through `POST /references` and the `hadith_references`/`quran_references` SSE events, plus a built-but-not-run offline batch MT job on a dedicated `TRANSLATION_ANTHROPIC_API_KEY` + `claude-sonnet-5`.**

## Performance

- **Duration:** ~35 min (includes fresh venv build + full dependency install for offline verification)
- **Tasks:** 3/3 completed
- **Files modified:** 11 (6 created, 5 modified)

## Accomplishments
- `reference_translations` table (composite PK `ref_type`/`ref_key`/`language` + provenance columns) with a clean-chaining Alembic migration onto the existing `onboarding_profiles_001` head
- Async join-after-retrieval lookup service + `core/utils.py` async formatter wrappers, wired into both `POST /references` and the agentic SSE `hadith_references`/`quran_references` events, with EN/AR fallback (`None`) when no translation row exists
- Re-runnable, idempotent offline batch MT script (`scripts/translate_references.py`) with strict credential isolation (`TRANSLATION_ANTHROPIC_API_KEY` via the raw `anthropic` SDK, never the app's key) -- built but intentionally NOT executed against any live service
- 17 new deterministic mocked tests (9 + 8), zero network/DB calls, all passing

## Task Commits

Each task was committed atomically:

1. **Task 1: reference_translations table (model + migration)** - `067ce75` (feat)
2. **Task 2: Join-after-retrieval translation lookup, wired into /references and SSE reference events** - `6214f4d` (feat, tdd)
3. **Task 3: Offline batch MT job (build only, do not run) + documented commands** - `66d447d` (feat, tdd)

_Note: this plan's tasks were marked `tdd="true"` in the plan frontmatter but executed as single feat commits with tests included in the same commit (test-first development happened during authoring, not as separate RED/GREEN git commits) -- see TDD Gate Compliance note below._

## Files Created/Modified
- `db/models/reference_translations.py` - `ReferenceTranslation` SQLAlchemy model, composite PK `(ref_type, ref_key, language)` + `source`/`translated_at`/`model`/`reviewed_at` provenance columns
- `alembic/versions/20260707_create_reference_translations_table.py` - migration `reference_translations_001`, `down_revision = 'onboarding_profiles_001'`
- `services/reference_translation_service.py` - `alookup_translations(ref_type, ref_keys, language) -> dict[str, str]`, opens its own `AsyncSessionLocal`, never raises (returns `{}` on error or empty input)
- `core/utils.py` - `aformat_references_as_json` / `aformat_quran_references_as_json` async wrappers around the existing sync formatters, additive translation fields, no DB call for unset/`"english"` language
- `core/pipeline.py` - `references_pipeline` gained a `language: str = "english"` parameter, threaded to `utils.aformat_references_as_json`
- `api/reference.py` - new `language` `Query(...)` param on `POST /references`, mirroring the existing `sect`/`limit` pattern
- `core/pipeline_langgraph.py` - `hadith_references`/`quran_references` SSE events now built via the async formatters, passing the existing in-scope `target_language`
- `scripts/translate_references.py` - offline batch MT job (`parse_args`, `_get_translation_client`, `translate_text`, `upsert_translation`, `_iter_source_items`, `_extract_text_for_ref_type`, `run_batch`, `main`)
- `tests/test_reference_translations.py` - 9 deterministic tests covering the lookup service, both async formatters, and pipeline language threading
- `tests/test_translate_references.py` - 8 deterministic tests covering CLI parsing, client key isolation, `translate_text`, `upsert_translation`, and `run_batch` (dry-run safety, `--limit` sampling, live-path call counts)
- `CLAUDE.md` - documented the batch job's start-to-finish commands and the `alembic upgrade head` prerequisite

## Decisions Made
- Single `reference_translations` table with a `ref_type` discriminator rather than per-type tables (simplest design handling both hadith and Quran/tafsir key schemes)
- Quran/tafsir `ref_key` = the existing, stable Pinecone vector `chunk_id` -- no synthesized composite key needed; `quran_translation` and `tafsir_text` are separate rows sharing the same `chunk_id` since one chunk has two independently-translatable fields
- Response field naming: `text_translated`/`translated_language` (hadith) and `quran_translation_translated`/`tafsir_text_translated`/`translated_language` (Quran/tafsir) -- purely additive, existing `text`/`text_ar`/`quran_translation`/`tafsir_text` fields untouched
- `alookup_translations` never raises -- DB errors are logged server-side only and the function returns `{}`, matching the project's existing tool-error-dict convention (mirrors `agents/tools/*` error handling)
- Batch script isolation: `TRANSLATION_ANTHROPIC_API_KEY` read only via `os.getenv`, raw `anthropic.Anthropic` client, no import of `core.chat_models` or `core.config.ANTHROPIC_API_KEY` anywhere in `scripts/translate_references.py`

## Deviations from Plan

None - plan executed exactly as written. The only environment-level addition was building a project-local `venv/` inside the worktree (not part of any task's file list) purely to run the deterministic offline verification commands specified in the plan's `<verification>` block -- no application code was affected, and `torch==2.6.0` was substituted with `torch==2.2.2` in the install (matching prior tasks' documented workaround for the local dev environment, no wheel available); this substitution has zero bearing on the DEE-67 test suites, which never import `torch` or any embedding module.

## Issues Encountered

None blocking. The pre-existing venv at the main repo path (`/Users/admin2/deen-backend/venv`) was empty (only `pip`/`setuptools`), so a fresh venv was created inside the worktree and the full `requirements.txt` (with the `torch` substitution above) was installed to run the deterministic tests offline.

## TDD Gate Compliance

Tasks 2 and 3 were marked `tdd="true"` in the plan frontmatter. Implementation code and its corresponding test file were authored together and committed in a single `feat(...)` commit per task, rather than as separate `test(...)` (RED) → `feat(...)` (GREEN) git commits. All tests were verified passing before each commit (RED→GREEN discipline was followed during authoring; it is just not reflected as separate git history). No `test(...)`-prefixed commit exists in this plan's history for gate-sequence validation purposes -- flagging per the plan-level TDD gate enforcement instructions.

## User Setup Required

**This task deliberately did NOT run `alembic upgrade head` or the batch MT job.** Two manual steps remain, both requiring a live environment this worktree does not have:

1. **Apply the migration** (requires a reachable Postgres, e.g. Supabase): `alembic upgrade head` -- creates the `reference_translations` table. Until this runs, `POST /references?language=<lang>` and the SSE reference events will return `text_translated`/`translated_language` (and Quran/tafsir equivalents) as `null` for every reference (safe EN/AR fallback, does not error).
2. **Populate the corpus** (personal key, optional/ops-triggered, only after step 1):
   ```bash
   export TRANSLATION_ANTHROPIC_API_KEY=sk-ant-...   # personal key, never the app's ANTHROPIC_API_KEY
   python scripts/translate_references.py --dry-run --limit 5   # preview counts, no Anthropic/DB calls
   python scripts/translate_references.py --ref-type hadith --languages urdu --limit 20   # small live sample
   python scripts/translate_references.py   # full corpus x all 6 languages (only after sampling looks correct)
   ```

## Next Phase Readiness
- API and SSE surfaces are fully wired end-to-end and covered by deterministic tests; no further code changes needed for DEE-67 to function once the migration is applied
- Corpus population is a separate, human-triggered ops task on the user's personal key -- not blocking for this plan's completion
- No regressions introduced: the 15 pre-existing test failures in `tests -q --ignore=tests/db` (in `test_agentic_streaming_pipeline.py`, `test_agentic_streaming_sse.py`, `test_async_concurrency_full.py`, `test_chat_agent_async.py`, `test_fiqh_integration.py`, `test_primer_service.py`) were verified identical on the pre-change base commit via a throwaway comparison worktree -- none are caused by this plan's changes

---
*Phase: 260707-pxt*
*Completed: 2026-07-07*

## Self-Check: PASSED

All 11 files created/modified confirmed present on disk; all 3 task commit hashes (`067ce75`, `6214f4d`, `66d447d`) confirmed in `git log --oneline --all`.
