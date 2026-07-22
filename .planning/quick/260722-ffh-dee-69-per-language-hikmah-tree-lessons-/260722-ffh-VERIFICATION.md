---
phase: 260722-ffh
verified: 2026-07-22T19:15:00Z
status: passed
score: 7/7 must-haves verified
has_blocking_gaps: false
overrides_applied: 0
---

# Quick Task 260722-ffh: DEE-69 Per-Language Hikmah Tree Lessons + Quiz Verification Report

**Task Goal:** Serve hikmah-tree lessons, lesson-content pages, and learner-facing quiz pages in the user's selected language via a field-level translation sidecar (`lesson_translations`) applied as a SYNC read-time projection with EN/AR fallback; plus an offline claude-CLI batch MT job (built, not run) with `source_hash` staleness and a hardened Qur'an-preservation prompt. Mirrors the shipped DEE-67 `reference_translations` sidecar.

**Verified:** 2026-07-22T19:15:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 6 read endpoints (`GET /lessons`, `/lessons/{id}`, `/lesson-content`, `/lesson-content/{id}`, `/hikmah-trees`, `/hikmah-trees/{id}`) accept `language` (default `"english"`); non-English + matching row → translated text; no match → source fallback | VERIFIED | Read `db/routers/lessons.py`, `lesson_content.py`, `hikmah_trees.py` — all 6 handlers declare `language: str = Query("english", ...)` and call `lesson_translation_service.apply_translations(db, entity_type, obj-or-results, fields=[...], language=language)` before returning. `apply_translations` (read in `services/lesson_translation_service.py`) overlays `translations.get((obj_id, field))` via `setattr` only when non-`None`, otherwise the source attribute is untouched (fallback). Confirmed by `tests/test_lesson_translations.py::TestApplyTranslations::test_overlays_translated_field_and_falls_back_for_missing` (passing). |
| 2 | `GET /hikmah/pages/{id}/quiz-questions` accepts `language`, projects prompt/explanation/choice_text for learners; admin authoring endpoints (list/get/create/replace/patch/delete) untouched, no `language` param | VERIFIED | `api/hikmah.py::get_page_quiz_questions` has `language: str = Query("english", ...)`, calls `service.get_questions_for_page(lesson_content_id, language=language)`. `services/hikmah_quiz_service.py::get_questions_for_page` calls new `_apply_quiz_translations(serialized, language)`, which overlays `prompt`/`explanation` (entity_type `quiz_question`) and `choice_text` (entity_type `quiz_choice`) with fallback. Grepped all 6 admin endpoints in `api/hikmah.py` (`create_page_quiz_question`, `list_page_quiz_questions_admin`, `get_page_quiz_question`, `replace_page_quiz_question`, `patch_page_quiz_question`, `delete_page_quiz_question`) — none declare a `language` param, none call translation code. Confirmed programmatically by `tests/test_lesson_translations.py::TestGetQuestionsForPageTranslation::test_admin_methods_do_not_accept_language_param` (uses `inspect.signature` to assert `"language" not in sig.parameters` for all 6 admin methods) — passing. |
| 3 | `language="english"`/unset triggers zero `lesson_translations` lookups on all 4 read surfaces | VERIFIED | `apply_translations` and `_apply_quiz_translations` both normalize `language` and `return` immediately (before any `db.query` call) when empty or `"english"`. Confirmed by 4 passing tests asserting `db.query.assert_not_called()` / `mock_lookup.assert_not_called()`: `test_noop_when_language_english`, `test_noop_when_language_empty`, `test_language_none_returns_untouched_payload_with_zero_lookup_calls`, `test_language_english_returns_untouched_payload_with_zero_lookup_calls`. |
| 4 | No per-language row duplication; no existing table/column altered | VERIFIED | Migration `alembic/versions/20260722_create_lesson_translations_table.py` contains only `op.create_table('lesson_translations', ...)` / `op.drop_table('lesson_translations')` — no `op.alter_column`/`op.add_column` on any existing table. `lesson_translations` is keyed on source entity IDs (`entity_id` = `lessons.id`/`lesson_content.id`/etc.), never duplicating source rows. Projection is applied via in-memory `setattr` on already-fetched ORM objects, never `db.commit()`ed (per `apply_translations`'s docstring and code — no commit call present). |
| 5 | `scripts/translate_lessons.py` exists as a re-runnable, idempotent, human-triggered CLI batch job covering all 5 entity types x 6 languages via local `claude` CLI; NOT executed against the live DB by this task | VERIFIED | File exists, `py_compile` succeeds, `--help` prints correct argparse usage. `ENTITY_FIELD_MAP` covers all 5 entity types (`lesson`, `lesson_content`, `quiz_question`, `quiz_choice`, `hikmah_tree`). `SUPPORTED_LANGUAGES` has the 6 canonical languages. `translate_text()` shells out to `claude -p --model ... --system-prompt ... --safe-mode --tools "" --no-session-persistence` (no Anthropic API). Grepped the entire repo for any import of `scripts.translate_lessons` / `from scripts import translate_lessons` outside of `tests/test_translate_lessons.py` — zero matches; the script is never wired into app code, routes, or CI. Git history (`git log`) shows no execution artifacts; only 3 atomic `feat:` commits building the code. |
| 6 | Re-running the batch job is idempotent: unchanged `source_hash` → skip; changed → re-translate + `db.merge()` overwrite | VERIFIED | `run_batch()` computes `computed_hash = source_text_hash(text)`, compares to `_existing_source_hash(...)`, `continue`s (skip, no count increment) when equal, else increments count and (non-dry-run) calls `translate_text` + `upsert_translation` (which does `db.merge(row)` + `db.commit()`, row keyed by the composite PK). Confirmed by passing tests `test_unchanged_source_hash_is_skipped` and `test_changed_source_hash_is_retranslated`. |
| 7 | Embedded Qur'anic Arabic never machine-translated — enforced via hardened `TRANSLATION_SYSTEM_PROMPT`, since no reliable row-level Qur'an marker exists | VERIFIED | `TRANSLATION_SYSTEM_PROMPT` in `scripts/translate_lessons.py` contains an explicit "CRITICAL RELIGIOUS-SENSITIVITY RULE" paragraph instructing verbatim, character-for-character preservation of Qur'anic Arabic and prohibiting translation/transliteration/paraphrase of it. `db/models/lesson_translations.py`'s docstring documents the investigation finding (`VALID_CONTENT_TYPES = {"text","quiz"}`, no `tags` column on `LessonContent`) establishing mechanism 1 (structural exclusion) is not applicable, matching the LOCKED decision's explicit fallback clause. Confirmed by passing test `test_calls_subprocess_with_expected_command_and_returns_stripped_output`, which asserts the `--system-prompt` value contains `"urdu"` AND (`"Qur'an"`/`"Qur'an"`) AND (`"verbatim"`/`"EXACTLY"`). |

**Score:** 7/7 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `db/models/lesson_translations.py` | `LessonTranslation` model, composite PK, docstring w/ Qur'an-marker finding | VERIFIED | All 10 columns present, PK = `{entity_type, entity_id, field, language}` (matches plan exactly); docstring documents investigation finding referencing `VALID_CONTENT_TYPES`. |
| `alembic/versions/20260722_create_lesson_translations_table.py` | Migration, `revision='lesson_translations_001'`, `down_revision='reference_translations_001'` | VERIFIED | Confirmed via file read; `alembic heads` resolves to exactly one head: `lesson_translations_001 (head)`. Grepped all migration files' `down_revision` — no other file declares `reference_translations_001` as its parent, confirming a clean single chain. |
| `services/lesson_translation_service.py` | `lookup_lesson_translations` + `apply_translations`, sync, never raise | VERIFIED | Both functions present with exact signatures from plan; `lookup_lesson_translations` wraps its query in `try/except Exception` returning `{}`; `apply_translations` no-ops for empty/English/empty-objects. |
| `scripts/translate_lessons.py` | Offline batch job, reuses claude-CLI logic, hardened prompt, source_hash idempotency, never invoked by app code | VERIFIED | All required functions present (`parse_args`, `_resolve_enabled_entity_types`, `translate_text`, `_preflight_claude_cli`, `_iter_source_rows`, `_existing_source_hash`, `upsert_translation`, `run_batch`, `main`). Confirmed zero imports from application code via repo-wide grep. |
| `tests/test_lesson_translations.py` | 12 deterministic mocked tests | VERIFIED | 12 test functions present, all passing, covering lookup/overlay behavior + quiz-service language threading + admin-method signature guard. |
| `tests/test_translate_lessons.py` | 15 deterministic mocked tests | VERIFIED | 15 test functions present, all passing, covering `source_text_hash`, `parse_args`, entity-type resolution, `translate_text` (incl. system-prompt content), `upsert_translation`, `run_batch` dry-run/limit/staleness/live-path. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `db/routers/lessons.py` | `lesson_translation_service.apply_translations` | Query param overlay before response | VERIFIED | Grep confirms 2 call sites (`get_lesson`, `list_lessons`), each preceded by `language: str = Query("english", ...)`. |
| `db/routers/lesson_content.py` | `lesson_translation_service.apply_translations` | Same pattern, `entity_type='lesson_content'` | VERIFIED | 2 call sites, `fields=["title","content_body"]`. |
| `db/routers/hikmah_trees.py` | `lesson_translation_service.apply_translations` | Same pattern, `entity_type='hikmah_tree'` | VERIFIED | 2 call sites, `fields=["title","summary"]`. |
| `api/hikmah.py::get_page_quiz_questions` | `HikmahQuizService.get_questions_for_page` | `language` threaded through | VERIFIED | `return service.get_questions_for_page(lesson_content_id, language=language)` confirmed present. |
| `services/hikmah_quiz_service.py::get_questions_for_page` | `lesson_translation_service.lookup_lesson_translations` | Overlay onto serialized dicts | VERIFIED | `_apply_quiz_translations` calls `lookup_lesson_translations` twice (quiz_question, quiz_choice), confirmed at lines 564/568-570. |
| `services/lesson_translation_service.py` | `db/models/lesson_translations.py::LessonTranslation` | `db.query(LessonTranslation).filter(...)` | VERIFIED | Confirmed at line 44. |
| `scripts/translate_lessons.py` | `db/models/lesson_translations.py::LessonTranslation` | `Session.merge()` upsert w/ `source_hash` | VERIFIED | `upsert_translation()` constructs `LessonTranslation(...)` and calls `db.merge(row)` + `db.commit()`; `source_hash` always passed from `run_batch`'s `computed_hash`. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|---------------------|--------|
| `db/routers/*.py` list/get handlers | `results`/`obj` returned to client | Real SQLAlchemy `db.query(Model)...all()` / `crud.get()`, then overlaid in-place by `apply_translations` which queries the real `lesson_translations` table via `db.query(LessonTranslation).filter(...)` | Not runtime-verified (no reachable Postgres in this environment, consistent with the SUMMARY's documented DNS-unreachable finding for DEE-69 and the same disposition as DEE-67 before it) | CODE-TRACE VERIFIED — no static/hardcoded returns found; the query is genuinely parameterized and executed against the real table; fallback path (leave source value untouched) is proven correct in mocked tests. Live-data flow requires a reachable DB, out of scope for this offline verification. |
| `services/hikmah_quiz_service.py::_apply_quiz_translations` | `serialized_questions` dict overlay | Real `lesson_translation_service.lookup_lesson_translations` call (not stubbed/hardcoded) | Same as above | CODE-TRACE VERIFIED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Model + migration shape (executor's own verify command) | `python -c "from db.models.lesson_translations import LessonTranslation; ..."` (columns/PK assertions) | Re-derived manually via file read — columns and PK match required set exactly | PASS |
| `alembic heads` resolves to single head | `venv/bin/alembic heads` | `lesson_translations_001 (head)` | PASS |
| New deterministic test suites pass | `venv/bin/python -m pytest tests/test_lesson_translations.py tests/test_translate_lessons.py -q` | `27 passed, 1 warning in 8.81s` (warning is an unrelated pre-existing numpy/torch runtime warning) | PASS |
| Batch script compiles and `--help` runs | `venv/bin/python -m py_compile scripts/translate_lessons.py && venv/bin/python scripts/translate_lessons.py --help` | Compile OK; correct argparse usage text printed (a pre-existing numpy/torch import warning appears in stderr, unrelated to this task) | PASS |
| All touched app files compile | `py_compile` on all 10 created/modified `.py` files | `ALL COMPILE OK` | PASS |
| Script never imported by app code | `grep -rn "import translate_lessons\|from scripts.translate_lessons\|from scripts import translate_lessons"` | Only `tests/test_translate_lessons.py` imports it | PASS |

### Probe Execution

Not applicable — no `scripts/*/tests/probe-*.sh` convention used by this task; verification is via pytest + static grep checks as specified in the plan's own `<verify>` blocks.

### Requirements Coverage

This is a `/gsd:quick` task (no `.planning/REQUIREMENTS.md` entry structure); the single requirement `DEE-69` is declared in the PLAN frontmatter and tracked in Linear. All plan `must_haves` mapping to DEE-69 are SATISFIED per the truths table above.

### Anti-Patterns Found

None. Scanned all 10 created/modified application files (`db/models/lesson_translations.py`, `alembic/versions/20260722_create_lesson_translations_table.py`, `services/lesson_translation_service.py`, `db/routers/lessons.py`, `db/routers/lesson_content.py`, `db/routers/hikmah_trees.py`, `services/hikmah_quiz_service.py`, `api/hikmah.py`, `core/utils.py`, `scripts/translate_lessons.py`) plus both test files for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER` — zero matches. No stub returns (`return null`/`return {}`/`return []`), no hardcoded empty-data props, no console.log-only implementations found in any of these files.

### Human Verification Required

None. All must-haves are backend logic (Postgres sidecar, sync service, router wiring, offline CLI script) fully verifiable via static code inspection and deterministic automated tests — no UI, real-time, or external-service behavior requiring human judgment in this task's scope.

### Gaps Summary

No gaps. All 7 observable truths, all 5 required artifacts, and all 6 key links verified against the actual codebase (not just SUMMARY claims). `alembic heads` resolves to a single clean head chaining onto DEE-67's `reference_translations_001`. All 27 new deterministic tests pass with zero network/DB calls. `scripts/translate_lessons.py` is confirmed never imported by any application code, route, or the 3 git commits show no live execution. The pre-existing ~16 failures in the full `pytest tests -q` suite (concurrency-timing-sensitive tests + an unrelated `primer_service` mock-patch mismatch) are confirmed unrelated: none of the 16 failing test files were created or modified by this task's `files_modified` list, so they are out of scope for this verification per the task instructions.

---

*Verified: 2026-07-22T19:15:00Z*
*Verifier: Claude (gsd-verifier)*
