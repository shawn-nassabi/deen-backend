---
phase: 260722-ffh
plan: 01
subsystem: api
tags: [translation, i18n, postgres-sidecar, lessons, quiz, hikmah-tree, batch-mt, deterministic-tests]

# Dependency graph
requires:
  - phase: 260707-pxt
    provides: reference_translations Postgres sidecar pattern (DEE-67) + reference_translation_service.py's defensive async lookup contract, mirrored here for lessons/quiz/hikmah-tree content
  - phase: 260708-ecy
    provides: DISABLED_REF_TYPES / hardened-prompt precedent for Qur'an MT hold-out reasoning
provides:
  - lesson_translations Postgres sidecar table (model + migration, chains onto reference_translations_001) keyed on (entity_type, entity_id, field, language)
  - services/lesson_translation_service.py -- sync lookup_lesson_translations() + apply_translations() overlay helpers, never raise
  - language query param on GET /lessons, GET /lessons/{id}, GET /lesson-content, GET /lesson-content/{id}, GET /hikmah-trees, GET /hikmah-trees/{id}, GET /hikmah/pages/{id}/quiz-questions
  - scripts/translate_lessons.py -- re-runnable, idempotent (source_hash staleness), human-triggered batch MT job reusing the claude-CLI translate_text() logic (NOT executed against any live service in this task)
  - core.utils.source_text_hash sha256 helper
affects: [dee-69, dee-63, lessons-api, hikmah-quiz-api, translation-batch-jobs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Field-level Postgres sidecar (composite PK entity_type/entity_id/field/language) applied as a read-time projection overlay onto already-fetched ORM objects/dicts, mirrored 1:1 from DEE-67's reference_translations pattern but SYNC (injected Session) instead of async"
    - "Zero-added-DB-calls guarantee for the default/English case, enforced by an early return before any db.query() call in apply_translations()"
    - "Qur'an preservation via hardened system-prompt instruction only (mechanism 2) when no reliable structural per-row marker exists -- documented residual risk pattern, reusable for future MT jobs over unmarked mixed-content fields"

key-files:
  created:
    - db/models/lesson_translations.py
    - alembic/versions/20260722_create_lesson_translations_table.py
    - services/lesson_translation_service.py
    - scripts/translate_lessons.py
    - tests/test_lesson_translations.py
    - tests/test_translate_lessons.py
  modified:
    - db/routers/lessons.py
    - db/routers/lesson_content.py
    - db/routers/hikmah_trees.py
    - services/hikmah_quiz_service.py
    - api/hikmah.py
    - core/utils.py
    - CLAUDE.md

key-decisions:
  - "No reliable per-row Qur'an marker exists at the lesson_content grain (VALID_CONTENT_TYPES = {text,quiz}; LessonContent has no tags column) -- mechanism 1 (structural exclusion) is not applicable; Qur'an preservation relies solely on the hardened TRANSLATION_SYSTEM_PROMPT (mechanism 2), a documented residual risk gated by the team's dee63-translation-review-workflow before any language ships to production"
  - "lookup_lesson_translations uses db.query(...).filter(...) (legacy SQLAlchemy Query API) rather than select()/db.execute(), matching the dominant sync convention already used throughout db/routers/*.py and services/hikmah_quiz_service.py, even though DEE-67's async sibling used select()"
  - "Read-time projection applies to the already-fetched ORM instance/list via setattr() in place, without db.commit() -- never persisted, discarded when the request-scoped session closes"

requirements-completed: [DEE-69]

# Metrics
duration: ~25min
completed: 2026-07-22
---

# Phase 260722-ffh Plan 01: DEE-69 Per-Language Hikmah Tree Lessons + Quiz Summary

**`lesson_translations` Postgres sidecar (composite PK entity_type/entity_id/field/language) with a sync read-time projection service wired into 4 read surfaces (lessons, lesson-content, hikmah-trees, learner quiz-questions), plus an offline claude-CLI batch MT job hardened for Qur'an-verbatim preservation via system prompt (no structural marker exists) -- built but not executed.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-22T18:20:00Z (approx.)
- **Completed:** 2026-07-22T18:42:00Z
- **Tasks:** 3 completed
- **Files modified:** 13 (6 created, 7 modified)

## Accomplishments
- Investigated the Qur'an-marker question (LOCKED decision 3): confirmed via static code evidence (`VALID_CONTENT_TYPES = {"text","quiz"}` validator, `LessonContent` has no `tags` column) that no reliable row-level marker exists to key a structural exclusion filter on at the `lesson_content` grain; live-DB introspection was not attempted since the executor environment has no route to the configured Postgres host (documented static fallback used per the plan's explicit fallback clause)
- Added `lesson_translations` sidecar table (model + Alembic migration chaining cleanly onto `reference_translations_001`, `alembic heads` resolves to exactly one head)
- Added `services/lesson_translation_service.py`: `lookup_lesson_translations()` (batch dict lookup, never raises) and `apply_translations()` (in-place overlay with EN/AR fallback, zero DB calls for the default/English case)
- Threaded a `language` query param through `GET /lessons`, `GET /lessons/{id}`, `GET /lesson-content`, `GET /lesson-content/{id}`, `GET /hikmah-trees`, `GET /hikmah-trees/{id}`, and `GET /hikmah/pages/{lesson_content_id}/quiz-questions` (learner-facing only); all 6 admin quiz-authoring endpoints in `api/hikmah.py` are unmodified and never accept a `language` param
- Added `scripts/translate_lessons.py`: re-runnable, idempotent (`source_hash`-gated) batch job reusing `translate_text()`'s claude-CLI subprocess logic, hardened `TRANSLATION_SYSTEM_PROMPT` with an explicit Qur'an-verbatim-preservation clause; NOT executed against any live service in this task
- Added `core.utils.source_text_hash` (sha256 helper) and documented the exact `translate_lessons.py` command sequence (dry-run/sample/full-run + `alembic upgrade head` prerequisite + Qur'an residual-risk note) in `CLAUDE.md`
- 27 new deterministic tests (12 in `tests/test_lesson_translations.py`, 15 in `tests/test_translate_lessons.py`), all mocked, zero network/DB calls

## Task Commits

Each task was committed atomically:

1. **Task 1: Qur'an-marker investigation + lesson_translations table (model + migration)** - `d072273` (feat)
2. **Task 2: Sync translation lookup/overlay service, wired into all 4 read surfaces** - `cb05ca1` (feat)
3. **Task 3: Offline batch MT job (build only, do not run) + CLAUDE.md commands** - `a73dd3c` (feat)

**Plan metadata:** committed separately by the orchestrator (not by this executor)

## Files Created/Modified
- `db/models/lesson_translations.py` - `LessonTranslation` model, composite PK, docstring documents the Qur'an-marker investigation finding
- `alembic/versions/20260722_create_lesson_translations_table.py` - migration, `down_revision = 'reference_translations_001'`
- `services/lesson_translation_service.py` - sync `lookup_lesson_translations()` + `apply_translations()`
- `db/routers/lessons.py` - `language` param on `get_lesson`/`list_lessons`, overlay via `apply_translations(..., fields=["title","summary"])`
- `db/routers/lesson_content.py` - `language` param on `get_lesson_content`/`list_lesson_content`, overlay `fields=["title","content_body"]`
- `db/routers/hikmah_trees.py` - `language` param on `get_hikmah_tree`/`list_hikmah_trees`, overlay `fields=["title","summary"]`
- `services/hikmah_quiz_service.py` - `get_questions_for_page(lesson_content_id, language=None)` + new `_apply_quiz_translations()` private helper overlaying `prompt`/`explanation`/`choice_text`
- `api/hikmah.py` - `language` param on `get_page_quiz_questions` only; no `typing.Optional` import added (unused, per plan-checker fixup)
- `core/utils.py` - added `import hashlib` + `source_text_hash()` helper after `decompress_text`
- `scripts/translate_lessons.py` - batch MT job (new file)
- `CLAUDE.md` - documents `scripts/translate_lessons.py` command sequence
- `tests/test_lesson_translations.py` - 12 tests (lookup/overlay service + quiz-service language threading)
- `tests/test_translate_lessons.py` - 15 tests (parse_args, entity-type resolution, translate_text, upsert_translation, run_batch dry-run/limit/staleness/live-path, source_text_hash)

## Decisions Made
- Qur'an preservation relies solely on the hardened system prompt (mechanism 2) since no reliable per-row structural marker exists (mechanism 1 not applicable) -- this is a documented residual risk, not a structural guarantee, gated by the team's coarse offline dev sample-review process (`dee63-translation-review-workflow`) before any language ships to production
- Kept `lookup_lesson_translations` on the legacy `db.query(...).filter(...)` API (not `select()`) to match the dominant sync convention already used throughout `db/routers/*.py` and `services/hikmah_quiz_service.py`, deliberately diverging from DEE-67's async `select()`-based sibling
- `run_batch` in `scripts/translate_lessons.py` still performs real read-only Postgres queries during `--dry-run` (enumeration + staleness check) since Postgres is the source of truth here (unlike DEE-67's Pinecone-sourced script) -- only `translate_text` (claude CLI) and `upsert_translation` (writes) are skipped

## Deviations from Plan

None - plan executed exactly as written, including both plan-checker fixups (skip unused `typing.Optional` import in `api/hikmah.py`; Task 2's 7-file scope accepted as specified).

## Issues Encountered
- The initial `_build_query` test helper in `tests/test_lesson_translations.py` didn't chain `.order_by()`, causing `HikmahQuizService._serialize_questions` to receive a `Mock` instead of an iterable list when testing `get_questions_for_page`. Fixed by adding `query.order_by.return_value = query` to the helper (test-only fix, not a Rule 1-3 deviation against application code).
- `python -c "import api.hikmah"` (a manual sanity check, not part of the plan's verify commands) fails in this offline environment because `core/auth.py` performs a live JWKS fetch at module import time against the Supabase host -- this is pre-existing behavior unrelated to this task's changes (no test in the repo imports `api.hikmah` directly either) and does not affect `pytest tests/test_lesson_translations.py` or the plan's specified verify commands, which all pass.
- Running the full `pytest tests -q` regression suite surfaced 16 pre-existing failures, all unrelated to this plan's files: concurrency-timing-sensitive tests (`test_agentic_streaming_pipeline.py`, `test_async_concurrency_full.py`, `test_chat_agent_async.py`, `test_concurrency_baseline.py`, `test_agentic_streaming_sse.py`, `test_fiqh_integration.py::test_out_of_scope_routes_to_exit`) and a pre-existing `patch('services.primer_service.lesson_crud')` target mismatch in `tests/test_primer_service.py` (the real import is function-local, not a module-level attribute, in `services/primer_service.py` -- a file this plan never touched). None of these files were created or modified by this plan.
- Running the full suite also appended a benchmark entry to `documentation/async_baseline.md` as a side effect of `tests/test_async_concurrency_full.py`; reverted with `git checkout -- documentation/async_baseline.md` since it is out of this plan's scope.

## User Setup Required

None for this task as delivered -- `scripts/translate_lessons.py` was built but NOT executed. Before it can be run for real:
1. Run `alembic upgrade head` once to create the `lesson_translations` table (not run in this task, per the plan's explicit instruction).
2. Ensure the local `claude` CLI is installed and logged in to a Claude Code subscription (`claude -p "hi"` to verify) before any non-`--dry-run` invocation.
3. Follow the `dee63-translation-review-workflow` coarse offline dev sample-review process (checking `content_body`/`explanation` fields for embedded Qur'anic verses) before enabling any language in production, given the residual Qur'an-preservation risk documented above.

## Next Phase Readiness
- Migration is authored and verified to chain cleanly (`alembic heads` -> `lesson_translations_001`) but has not been applied to any live database
- `scripts/translate_lessons.py --dry-run --limit 5` is the recommended first live-environment step once `alembic upgrade head` has run, to sample counts before any real translation
- No blockers for DEE-69; the read-time projection surfaces are live in code (behind the `language` query param, default `"english"` = no-op) and ready to serve translated content as soon as the sidecar table is populated

---
*Phase: 260722-ffh*
*Completed: 2026-07-22*

## Self-Check: PASSED

All claimed files and commits verified present:
- FOUND: db/models/lesson_translations.py
- FOUND: alembic/versions/20260722_create_lesson_translations_table.py
- FOUND: services/lesson_translation_service.py
- FOUND: scripts/translate_lessons.py
- FOUND: tests/test_lesson_translations.py
- FOUND: tests/test_translate_lessons.py
- FOUND: db/routers/lessons.py
- FOUND: db/routers/lesson_content.py
- FOUND: db/routers/hikmah_trees.py
- FOUND: services/hikmah_quiz_service.py
- FOUND: api/hikmah.py
- FOUND: core/utils.py
- FOUND: CLAUDE.md
- FOUND: .planning/quick/260722-ffh-dee-69-per-language-hikmah-tree-lessons-/260722-ffh-SUMMARY.md
- FOUND: d072273
- FOUND: cb05ca1
- FOUND: a73dd3c
