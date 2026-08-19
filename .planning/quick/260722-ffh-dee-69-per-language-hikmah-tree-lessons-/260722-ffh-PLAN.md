---
phase: 260722-ffh
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - db/models/lesson_translations.py
  - alembic/versions/20260722_create_lesson_translations_table.py
  - services/lesson_translation_service.py
  - db/routers/lessons.py
  - db/routers/lesson_content.py
  - db/routers/hikmah_trees.py
  - services/hikmah_quiz_service.py
  - api/hikmah.py
  - tests/test_lesson_translations.py
  - core/utils.py
  - scripts/translate_lessons.py
  - tests/test_translate_lessons.py
  - CLAUDE.md
autonomous: true
requirements:
  - DEE-69
must_haves:
  truths:
    - "GET /lessons/{id}, GET /lessons, GET /lesson-content/{id}, GET /lesson-content, GET /hikmah-trees/{id}, and GET /hikmah-trees accept a language query param (default 'english'); with a non-English selected language and a matching lesson_translations row, the response's title/summary/content_body fields carry the translated text; with no matching row, they fall back unchanged to the source (EN/AR) text"
    - "GET /hikmah/pages/{lesson_content_id}/quiz-questions accepts a language query param and projects prompt/explanation/choice_text into the selected language for the learner-facing response, falling back to source text when no translation row exists; the admin authoring endpoints (list/get/create/replace/patch/delete quiz questions) are untouched and never receive a language param"
    - "language='english' (or omitted) never triggers a lesson_translations lookup on any of the 4 read surfaces -- source text is returned as-is with zero added DB calls"
    - "Progress and quiz-attempt history remain keyed to source entity IDs (lessons.id, lesson_content.id, lesson_page_quiz_questions.id, lesson_page_quiz_choices.id, hikmah_trees.id) -- no per-language row duplication anywhere, and no existing table/column is altered"
    - "scripts/translate_lessons.py exists as a re-runnable, idempotent, human-triggered CLI batch job that can populate lesson_translations for all 5 entity types (lesson, lesson_content, quiz_question, quiz_choice, hikmah_tree) across the 6 canonical languages by shelling out to the local claude CLI (no Anthropic API credits) -- but this task does NOT execute it against the live DB"
    - "Re-running scripts/translate_lessons.py is idempotent: an item whose live source text is unchanged since its last translation (sha256 source_hash match) is skipped; an item whose source text changed is re-translated and the row is overwritten via db.merge()"
    - "Embedded Qur'anic Arabic verses are never machine-translated by scripts/translate_lessons.py -- enforced via a hardened TRANSLATION_SYSTEM_PROMPT instructing verbatim preservation, because Task 1's investigation established that lesson_content has no reliable row-level Qur'an marker (content_type is validator-constrained to {'text','quiz'}, no tags column) to key a structural exclusion filter on"
  artifacts:
    - path: "db/models/lesson_translations.py"
      provides: "LessonTranslation SQLAlchemy model: composite PK (entity_type, entity_id, field, language) + translated_text + provenance columns (source, translated_at, model, nullable reviewed_at) + nullable source_hash for staleness detection; docstring documents the Qur'an-marker investigation finding"
      contains: "class LessonTranslation(Base)"
    - path: "alembic/versions/20260722_create_lesson_translations_table.py"
      provides: "Migration creating lesson_translations, revision lesson_translations_001, down_revision reference_translations_001"
      contains: "down_revision = 'reference_translations_001'"
    - path: "services/lesson_translation_service.py"
      provides: "lookup_lesson_translations(db, entity_type, entity_ids, language, fields=None) -> dict[(entity_id, field), str] and apply_translations(db, entity_type, objects, fields, language, id_attr='id') -> None, both SYNC (injected Session), never raise"
      contains: "def lookup_lesson_translations"
    - path: "scripts/translate_lessons.py"
      provides: "Offline batch MT job enumerating the 5 source Postgres tables, reusing translate_references_claude_cli.py's claude-CLI translate_text() logic, hardened Qur'an-preservation system prompt, source_hash idempotency, never invoked by app code/routes/CI"
      contains: "def translate_text"
    - path: "tests/test_lesson_translations.py"
      provides: "Deterministic mocked tests for lookup_lesson_translations/apply_translations and language threading through the 4 read surfaces"
    - path: "tests/test_translate_lessons.py"
      provides: "Deterministic mocked tests for the batch script: parse_args, entity-type resolution, translate_text subprocess mock, upsert_translation merge, dry-run, --limit, Qur'an-preservation prompt content, and staleness skip/re-translate"
  key_links:
    - from: "db/routers/lessons.py"
      to: "services/lesson_translation_service.py::apply_translations"
      via: "new language Query(...) param on get_lesson/list_lessons, overlaying translated title/summary onto the returned ORM object(s) in place before response_model serialization"
      pattern: "lesson_translation_service\\.apply_translations"
    - from: "db/routers/lesson_content.py"
      to: "services/lesson_translation_service.py::apply_translations"
      via: "same pattern, entity_type='lesson_content', fields=['title','content_body']"
      pattern: "lesson_translation_service\\.apply_translations"
    - from: "db/routers/hikmah_trees.py"
      to: "services/lesson_translation_service.py::apply_translations"
      via: "same pattern, entity_type='hikmah_tree', fields=['title','summary']"
      pattern: "lesson_translation_service\\.apply_translations"
    - from: "api/hikmah.py::get_page_quiz_questions"
      to: "services/hikmah_quiz_service.py::HikmahQuizService.get_questions_for_page"
      via: "new language Query(...) param threaded into service.get_questions_for_page(lesson_content_id, language=language)"
      pattern: "get_questions_for_page\\(lesson_content_id,\\s*language"
    - from: "services/hikmah_quiz_service.py::get_questions_for_page"
      to: "services/lesson_translation_service.py::lookup_lesson_translations"
      via: "overlay onto the already-serialized question/choice dicts for entity_type='quiz_question' (prompt, explanation) and entity_type='quiz_choice' (choice_text)"
      pattern: "lesson_translation_service\\.lookup_lesson_translations"
    - from: "services/lesson_translation_service.py"
      to: "db/models/lesson_translations.py::LessonTranslation"
      via: "sync db.query(LessonTranslation).filter(entity_type=..., entity_id.in_(...), language=...)"
      pattern: "db\\.query\\(LessonTranslation\\)"
    - from: "scripts/translate_lessons.py"
      to: "db/models/lesson_translations.py::LessonTranslation"
      via: "sync Session.merge() upsert keyed by the composite PK, storing source_hash"
      pattern: "db\\.merge\\(.*LessonTranslation"
---

<objective>
Implement DEE-69: serve hikmah-tree lessons, lesson content pages, and quiz pages (question/explanation/choices) in the user's selected language -- the lesson/quiz sibling of DEE-67, which already shipped the `reference_translations` sidecar for hadith/Quran/tafsir. Mirror that pattern: a single field-level Postgres sidecar table (`lesson_translations`) keyed on the 5 stable source entity types, applied as a read-time projection (COALESCE -> EN/AR fallback) at 4 read surfaces, with no per-language row duplication so progress/quiz history stays attached to source IDs across language switches. Build (but do not run) a re-runnable offline batch MT job that reuses the already-shipped claude-CLI translation logic, hardened with an explicit Qur'an-preservation instruction because this task's first investigation establishes there is no reliable row-level structural marker to exclude Qur'anic content by.

Purpose: Learners currently see hikmah-tree lessons and quiz content only in the source language regardless of their selected chat language. This closes that gap for lesson/quiz surfaces (DEE-67 already closed it for hadith/Quran/tafsir references) without duplicating rows or touching progress/attempt history.

Output:
- `lesson_translations` Postgres table + SQLAlchemy model + Alembic migration (chains onto DEE-67's `reference_translations_001` head)
- `services/lesson_translation_service.py` -- sync lookup + overlay-application helpers
- Read-time projection wired into `db/routers/lessons.py`, `db/routers/lesson_content.py`, `db/routers/hikmah_trees.py`, and `services/hikmah_quiz_service.py` (learner-facing quiz endpoint only)
- `scripts/translate_lessons.py` -- re-runnable, idempotent, human-triggered batch MT job (not executed in this task)
- Deterministic mocked tests covering the lookup/overlay service, language threading through all 4 read surfaces, and the batch script (no live network/DB calls in tests)
</objective>

<execution_context>
@/Users/admin2/.claude/plugins/cache/gsd-plugin/gsd/4.0.2/workflows/execute-plan.md
@/Users/admin2/.claude/plugins/cache/gsd-plugin/gsd/4.0.2/templates/summary.md
</execution_context>

<context>
@/Users/admin2/deen-backend/.planning/STATE.md
@/Users/admin2/deen-backend/CLAUDE.md
@/Users/admin2/deen-backend/.planning/quick/260722-ffh-dee-69-per-language-hikmah-tree-lessons-/260722-ffh-CONTEXT.md

<!-- Key interfaces the executor needs -- extracted from codebase. Use directly, no exploration. -->
<interfaces>
From `db/models/reference_translations.py` and `alembic/versions/20260707_create_reference_translations_table.py` (DEE-67 pattern to mirror exactly for the new table's shape, minus the ref_type/ref_key naming which becomes entity_type/entity_id/field):
```python
class ReferenceTranslation(Base):
    __tablename__ = "reference_translations"
    ref_type = Column(Text, primary_key=True, nullable=False)
    ref_key = Column(Text, primary_key=True, nullable=False)
    language = Column(Text, primary_key=True, nullable=False)
    translated_text = Column(Text, nullable=False)
    source = Column(Text, nullable=False, server_default="mt")
    translated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    model = Column(Text, nullable=False)
    reviewed_at = Column(TIMESTAMP(timezone=True), nullable=True)
```
Migration style: `revision = 'reference_translations_001'`, `down_revision = 'onboarding_profiles_001'`, `op.create_table(...)` with 3 `primary_key=True` columns for the composite PK, `op.drop_table(...)` in `downgrade()`. Verified alembic head chain: `... -> onboarding_profiles_001 -> reference_translations_001` (no migration file currently declares `reference_translations_001` as its `down_revision` -- confirmed via grep across `alembic/versions/*.py`).

From `services/reference_translation_service.py` (DEE-67 ASYNC lookup -- mirror the defensive "never raise, always return a dict/no-op" contract, but the new service is SYNC using an injected `Session`, not its own `AsyncSessionLocal`):
```python
async def alookup_translations(ref_type: str, ref_keys: Iterable[str], language: str) -> dict[str, str]:
    keys = sorted({str(k) for k in ref_keys if k not in (None, "", "N/A")})
    if not keys:
        return {}
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(ReferenceTranslation).where(...)
            result = await db.execute(stmt)
            return {row.ref_key: row.translated_text for row in result.scalars().all()}
    except Exception:
        logger.error(..., exc_info=True)
        return {}
```

From `scripts/translate_references_claude_cli.py` (the claude-CLI logic to reuse verbatim -- source there is Pinecone, source here is Postgres):
```python
CLAUDE_TIMEOUT_SECONDS = 600
DEFAULT_MODEL = "sonnet"

def translate_text(*, model: str, text: str, language: str) -> str:
    system_prompt = TRANSLATION_SYSTEM_PROMPT.format(language=language)
    result = subprocess.run(
        ["claude", "-p", "--model", model, "--system-prompt", system_prompt,
         "--safe-mode", "--tools", "", "--no-session-persistence"],
        input=text, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI exited {result.returncode}: {result.stderr.strip()[:500]}")
    translated = result.stdout.strip()
    if not translated:
        raise RuntimeError("claude CLI returned empty output")
    return translated

def _preflight_claude_cli() -> None:
    if shutil.which("claude") is None:
        raise RuntimeError("The `claude` CLI was not found on PATH...")
```
`upsert_translation(session_factory, *, ref_type, ref_key, language, translated_text, model_name)` opens `with session_factory() as db:`, builds the row, calls `db.merge(row)` then `db.commit()`. `run_batch(...)` returns a nested `{ref_type: {language: count}}` summary dict, wraps each item/language in try/except that logs and continues. `parse_args` uses `argparse` with `--languages` (comma-separated, default all 6), `--dry-run` (`store_true`), `--limit` (`type=int`), `--model` (default `DEFAULT_MODEL`). `SUPPORTED_LANGUAGES = ["arabic", "farsi", "urdu", "german", "bahasa melayu", "french"]` -- reuse this exact list/casing.

Grounded evidence already confirmed for the Qur'an-marker investigation (Task 1) -- do NOT re-derive, use directly: `scripts/hikmah_generation/upsert_hikmah_tree.py` line 47 defines `VALID_CONTENT_TYPES = {"text", "quiz"}` -- the ingestion validator only ever permits these two `content_type` values, no `"quran"` or similar. `db/models/lesson_content.py`'s `LessonContent` model has NO `tags` column at all (only `lessons.tags` and `hikmah_trees.tags` exist, and those are topic-level tags on the PARENT lesson/tree, e.g. `["tajweed","quran"]`, not a per-row marker of embedded Qur'anic text within a page). `scripts/hikmah_generation/generate_hikmah_tree.py`'s generation prompt (~line 62, 97-98) instructs Qur'anic verses to be preserved inline within `content_body` as bold/italic markdown, mixed with surrounding prose -- confirming Qur'anic text is embedded WITHIN otherwise-translatable rows, not isolated in dedicated rows. A live DB introspection was attempted during planning (`SELECT DISTINCT content_type FROM lesson_content` etc. via `db/session.py`'s `SessionLocal`/psycopg2 against `DATABASE_URL`) and the host was unreachable from this environment (DNS resolution failure) -- Task 1 must re-attempt this live query (the executor's environment may have real connectivity) and use its result if reachable, but the documented static-code conclusion above is the grounded fallback either way.

From `db/models/lessons.py`, `db/models/lesson_content.py`, `db/models/hikmah_trees.py`, `db/models/lesson_page_quiz_questions.py`, `db/models/lesson_page_quiz_choices.py`: all use `id = Column(BigInteger, primary_key=True, autoincrement=True)`. Translatable fields per the LOCKED surfaces table: `Lesson.title/summary`, `LessonContent.title/content_body`, `LessonPageQuizQuestion.prompt/explanation`, `LessonPageQuizChoice.choice_text`, `HikmahTree.title/summary`.

From `db/session.py`: `SessionLocal = sessionmaker(...)`, `Base = declarative_base()`, `def get_db(): db = SessionLocal(); try: yield db; finally: db.close()`. `SessionLocal()` (and the class itself) supports use as a context manager (`with SessionLocal() as db:`), same as `db/session.py`'s existing consumers.

From `db/schemas/lessons.py`, `db/schemas/lesson_content.py`, `db/schemas/hikmah_trees.py`: `LessonRead`/`LessonContentRead`/`HikmahTreeRead` all declare `class Config: from_attributes = True` -- FastAPI/Pydantic will serialize either the returned ORM instance OR a plain dict against these `response_model`s. Setting attributes in-place on an ORM instance returned by `db.get(...)`/`.query().all()` (without calling `db.commit()`) is safe -- it only mutates the in-memory Python object for this response; no write reaches the DB, and `get_db()`'s `finally: db.close()` discards the session afterward.

From `db/routers/lessons.py` (current, ~lines 15-52): `list_lessons(db, q, tag, status, language_code, ...)` returns `query.offset(skip).limit(limit).all()`. **Note the existing unrelated `language_code` filter param is the lesson's SOURCE-language filter (an existing DB column on `Lesson`) -- do not confuse it with the NEW `language` query param this plan adds, which selects the TARGET display language for projection.** `get_lesson(lesson_id, db)` returns `lesson_crud.get(db, lesson_id)` or raises 404.

From `db/routers/lesson_content.py` (current, ~lines 15-33): `list_lesson_content(db, lesson_id, skip, limit)` returns `q.offset(skip).limit(limit).all()`. `get_lesson_content(content_id, db)` returns `lesson_content_crud.get(db, content_id)` or raises 404.

From `db/routers/hikmah_trees.py` (current, ~lines 17-43): `list_hikmah_trees(db, q, tag, skill_level, skip, limit)` returns `query.offset(skip).limit(limit).all()`. `get_hikmah_tree(tree_id, db)` returns `hikmah_tree_crud.get(db, tree_id)` or raises 404. `hikmah_tree_crud.get`/`lesson_content_crud.get`/`lesson_crud.get` all resolve to `CRUDBase.get`: `return db.get(self.model, id)`.

From `services/hikmah_quiz_service.py` (current, ~lines 27-37, 482-538) -- the ONLY method to change is `get_questions_for_page`; do NOT touch `list_questions_for_page_admin`/`get_question_for_page`/`create_question`/`replace_question`/`patch_question`/`delete_question` (admin authoring views, LOCKED to stay untranslated):
```python
def get_questions_for_page(self, lesson_content_id: int) -> Dict[str, Any]:
    questions = self._list_questions_for_page_models(lesson_content_id=lesson_content_id, include_inactive=False)
    return {"lesson_content_id": lesson_content_id, "questions": self._serialize_questions(questions, include_admin_fields=False)}
```
`_serialize_question` returns a dict shaped `{"id": int, "prompt": str, "order_position": int, "choices": [{"id": int, "choice_key": str, "choice_text": str, "order_position": int}, ...], "correct_choice_id": int, "explanation": Optional[str]}` (plus `lesson_content_id`/`tags`/`is_active` only when `include_admin_fields=True`, which the learner path never sets). `self.db` is the service's injected sync `Session` (set in `__init__`).

From `api/hikmah.py` (current, ~lines 92-113): imports `from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status` -- no `typing` import yet, add `from typing import Optional`.
```python
@hikmah_router.get("/pages/{lesson_content_id}/quiz-questions", response_model=LessonPageQuizQuestionsResponse)
async def get_page_quiz_questions(lesson_content_id: int, credentials=Depends(auth), db: Session = Depends(get_db)):
    service = HikmahQuizService(db)
    return service.get_questions_for_page(lesson_content_id)
```

From `models/schemas.py` (~lines 52-70): `QuizChoiceResponse{id, choice_key, choice_text, order_position}`, `QuizQuestionResponse{id, prompt, order_position, choices, correct_choice_id, explanation}`, `LessonPageQuizQuestionsResponse{lesson_content_id, questions}`. No schema changes needed -- projection overlays existing string fields, the shape is unchanged.

From `core/utils.py` (current, ~lines 1-8, 390-403): top imports are `Document`, `asyncio`, `traceback`, `base64`, `gzip`, `Optional`, plus `from services import reference_translation_service`. `compress_text`/`decompress_text` live at the bottom of the file (~lines 390-403) -- add the new `source_text_hash` helper immediately after `decompress_text`, using a new `import hashlib` at the top.

From `api/reference.py` (~line 28): existing precedent for a language `Query(...)` param: `language: str = Query("english", description="Selected language for translated reference text (e.g. 'arabic', 'farsi', 'urdu', 'german', 'bahasa melayu', 'french'). Defaults to English -- no translation join performed.")` -- mirror this exact default/description style (string default `"english"`, not `Optional[None]`) on all 4 new read-surface params.

From `main.py` (~lines 99-112): all 4 routers already registered (`reference.ref_router`, `hikmah.hikmah_router`, `lessons_router.router`, `lesson_content_router.router`, `hikmah_trees_router.router`) -- no `main.py` changes needed.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Qur'an-marker investigation + lesson_translations table (model + migration)</name>
  <files>db/models/lesson_translations.py, alembic/versions/20260722_create_lesson_translations_table.py</files>
  <action>
First, investigate whether a reliable row-level Qur'an-content marker exists (LOCKED decision 3 requires this before any exclusion filter can be built). Attempt a live query via `db/session.py`'s `SessionLocal` (or a short-lived raw connection) against the configured `DATABASE_URL`: `SELECT DISTINCT content_type FROM lesson_content`, `SELECT DISTINCT unnest(tags) FROM lessons WHERE tags IS NOT NULL`, `SELECT DISTINCT unnest(tags) FROM hikmah_trees WHERE tags IS NOT NULL`. Wrap the attempt in try/except -- if the host is unreachable (confirmed unreachable from the planning environment via DNS failure; the executor's environment may differ), fall back to the grounded static-code evidence already gathered (see `<interfaces>` above): `scripts/hikmah_generation/upsert_hikmah_tree.py`'s `VALID_CONTENT_TYPES = {"text", "quiz"}` validator constrains `content_type` to exactly two values (no Qur'an-specific type), and `LessonContent` has no `tags` column at all. Either way (live-confirmed or static-fallback), the conclusion is: there is NO reliable per-row marker to key a structural Qur'an-exclusion filter on at the `lesson_content` grain -- `lessons.tags`/`hikmah_trees.tags` only mark topical "about Quran" lessons at the PARENT level, not per-row presence/absence of embedded Qur'anic verses within a specific page's `content_body`/`explanation`. Per decision 3's explicit fallback clause, this means mechanism 1 (structural exclusion) is NOT APPLICABLE here, and mechanism 2 (a hardened translator system prompt, built in Task 3) is the sole operative Qur'an-preservation safeguard for this job -- a documented residual risk, not a structural guarantee.

Create `db/models/lesson_translations.py` defining `LessonTranslation(Base)` (import `Base` from `..session`, mirroring `db/models/reference_translations.py`'s import style). Give the module a docstring explaining: (a) this is the DEE-69 field-level sidecar, one row per (entity_type, entity_id, field, language), mirroring DEE-67's `reference_translations` pattern; (b) the Qur'an-marker investigation finding from above, verbatim enough that `scripts/translate_lessons.py` (Task 3) can reference it directly without re-deriving. Columns, matching the LOCKED schema exactly:
- `entity_type` (Text, primary_key=True, nullable=False) -- one of `"lesson"`, `"lesson_content"`, `"quiz_question"`, `"quiz_choice"`, `"hikmah_tree"`
- `entity_id` (BigInteger, primary_key=True, nullable=False) -- the source table's `id`
- `field` (Text, primary_key=True, nullable=False) -- e.g. `"title"`, `"summary"`, `"content_body"`, `"prompt"`, `"explanation"`, `"choice_text"`
- `language` (Text, primary_key=True, nullable=False)
- `translated_text` (Text, nullable=False)
- `source` (Text, nullable=False, server_default="mt")
- `translated_at` (TIMESTAMP(timezone=True), nullable=False, server_default=`func.now()`)
- `model` (Text, nullable=False)
- `reviewed_at` (TIMESTAMP(timezone=True), nullable=True)
- `source_hash` (Text, nullable=True) -- sha256 hex of the source text at translation time, written and read ONLY by `scripts/translate_lessons.py` for staleness detection (decision 4); the read-time projection service in Task 2 never reads this column

Create `alembic/versions/20260722_create_lesson_translations_table.py` mirroring the style of `alembic/versions/20260707_create_reference_translations_table.py`: `revision = 'lesson_translations_001'`, `down_revision = 'reference_translations_001'` (the current verified head -- confirm no other migration file already declares this as its `down_revision` before writing, matching the check already done for this plan). `upgrade()` calls `op.create_table('lesson_translations', ...)` with the same 9 columns/types/defaults as the model (composite PK via 4 `primary_key=True` columns). `downgrade()` calls `op.drop_table('lesson_translations')`. No extra indexes -- the composite PK covers the `(entity_type, entity_id IN (...), language)` query pattern used by Task 2's lookup, and the `(entity_type, entity_id, field, language)` exact-match pattern used by Task 3's staleness check.

Do NOT run `alembic upgrade head` as part of this task -- author the migration only.
  </action>
  <verify>
    <automated>cd /Users/admin2/deen-backend && python -c "
from db.models.lesson_translations import LessonTranslation
cols = {c.name for c in LessonTranslation.__table__.columns}
required = {'entity_type','entity_id','field','language','translated_text','source','translated_at','model','reviewed_at','source_hash'}
assert required <= cols, f'missing columns: {required - cols}'
pk = {c.name for c in LessonTranslation.__table__.primary_key.columns}
assert pk == {'entity_type','entity_id','field','language'}, f'unexpected PK: {pk}'
print('model OK:', sorted(cols))
" && grep -c "VALID_CONTENT_TYPES" db/models/lesson_translations.py && alembic heads
</automated>
  </verify>
  <done>
    - `db/models/lesson_translations.py` defines `LessonTranslation` with the 10 columns above and a 4-column composite primary key
    - The model's docstring documents the Qur'an-marker investigation finding (references `VALID_CONTENT_TYPES`), establishing that mechanism 2 (hardened prompt) is the sole Qur'an safeguard
    - `alembic/versions/20260722_create_lesson_translations_table.py` exists with `down_revision = 'reference_translations_001'`, and `alembic heads` resolves to exactly one head (the new migration)
    - No existing migration file is broken or renumbered
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Sync translation lookup/overlay service, wired into all 4 read surfaces</name>
  <files>services/lesson_translation_service.py, db/routers/lessons.py, db/routers/lesson_content.py, db/routers/hikmah_trees.py, services/hikmah_quiz_service.py, api/hikmah.py, tests/test_lesson_translations.py</files>
  <behavior>
    - `lookup_lesson_translations(db, "lesson", [1, 2], "urdu")` returns `{(1, "title"): "...", (1, "summary"): "...", ...}` keyed by `(entity_id, field)` tuples, using a mocked sync `Session` (`db.query(...).filter(...).all()` chain, matching `tests/test_hikmah_quiz_service.py`'s `_build_query` mocking convention) -- and returns `{}` (never raises) when `entity_ids` is empty, or when the mocked query raises an exception
    - `lookup_lesson_translations(db, "lesson_content", [5], "urdu", fields=["title"])` adds an extra `.filter()` call restricting to the given fields subset
    - `apply_translations(db, "lesson", [obj], fields=["title", "summary"], language="english")` and `apply_translations(db, "lesson", [obj], fields=["title", "summary"], language="")` are both no-ops -- `obj`'s attributes are unchanged and no `db.query` call happens at all
    - `apply_translations(db, "lesson", [obj], fields=["title", "summary"], language="urdu")` with a lookup result containing `(obj.id, "title")` sets `obj.title` to the translated value and leaves `obj.summary` unchanged (fallback) when no `(obj.id, "summary")` entry exists
    - `HikmahQuizService.get_questions_for_page(lesson_content_id, language="urdu")` overlays translated `prompt`/`explanation` (entity_type `"quiz_question"`) and `choice_text` (entity_type `"quiz_choice"`) onto the serialized response dict, falling back to source values for any (question, field) or (choice, field) pair with no matching translation row; `language="english"`/unset performs zero lookup calls and returns the existing serialized shape unchanged
    - `list_questions_for_page_admin`, `get_question_for_page`, `create_question`, `replace_question`, `patch_question`, `delete_question` are unmodified -- none accept or use a `language` parameter
  </behavior>
  <action>
Create `services/lesson_translation_service.py`. Module docstring: this is the DEE-69 sync read-time projection lookup, mirroring `services/reference_translation_service.py`'s defensive "never raise" contract, but SYNC using an injected `Session` (the lesson/lesson_content/hikmah_trees/hikmah routers all use `Depends(get_db)`, not an async session). Import `logging`, `Dict`, `Iterable`, `List`, `Optional`, `Tuple` from `typing`, `Session` from `sqlalchemy.orm`, and `LessonTranslation` from `db.models.lesson_translations`. Define `logger = logging.getLogger(__name__)`. Implement two functions:

`def lookup_lesson_translations(db: Session, entity_type: str, entity_ids: Iterable[int], language: str, fields: Optional[Iterable[str]] = None) -> Dict[Tuple[int, str], str]:` -- normalize `entity_ids` to a deduplicated sorted list of ints, skipping `None`; return `{}` immediately if empty (no query). Otherwise, wrapped in `try/except Exception:` (log via `logger.error(..., exc_info=True)` with `entity_type`/`language` in the message, return `{}` on any error -- matches `alookup_translations`'s convention): build `query = db.query(LessonTranslation).filter(LessonTranslation.entity_type == entity_type, LessonTranslation.entity_id.in_(ids), LessonTranslation.language == language)`; if `fields` is given, add `.filter(LessonTranslation.field.in_(list(fields)))`; `rows = query.all()`; return `{(row.entity_id, row.field): row.translated_text for row in rows}`. Use `db.query(...).filter(...)` (the legacy SQLAlchemy Query API), NOT `select()`/`db.execute()` -- this deliberately matches the dominant sync convention already used throughout `db/routers/*.py` and `services/hikmah_quiz_service.py` in this part of the codebase, even though DEE-67's async sibling used `select()`.

`def apply_translations(db: Session, entity_type: str, objects: List, *, fields: Iterable[str], language: str = "english", id_attr: str = "id") -> None:` -- overlay translated field values onto `objects` in place via `setattr`. Normalize `normalized = (language or "").strip().lower()`; if `not normalized or normalized == "english" or not objects`: return immediately (no DB call -- this is the zero-added-DB-calls guarantee for the default/English case). Otherwise: `ids = [getattr(obj, id_attr) for obj in objects]`; `translations = lookup_lesson_translations(db, entity_type, ids, normalized, fields=fields)`; if `not translations: return`; for each `obj` in `objects`, for each `field` in `fields`, look up `translations.get((getattr(obj, id_attr), field))` and `setattr(obj, field, value)` only when a non-`None` value is found (missing key -> leave the object's existing source value untouched, the EN/AR fallback).

In `db/routers/lessons.py`: add `from services import lesson_translation_service` import. Add `language: str = Query("english", description="Selected display language (e.g. 'arabic', 'farsi', 'urdu', 'german', 'bahasa melayu', 'french'). Defaults to English -- no translation lookup performed. NOT the same as the existing language_code filter, which selects the lesson's SOURCE language.")` as a new parameter on both `get_lesson` and `list_lessons` (mirroring the existing `sect`/`limit` `Query(...)` pattern in `api/reference.py`). In `get_lesson`, after the 404 check, call `lesson_translation_service.apply_translations(db, "lesson", [obj], fields=["title", "summary"], language=language)` before `return obj`. In `list_lessons`, capture `results = query.offset(skip).limit(limit).all()`, call `lesson_translation_service.apply_translations(db, "lesson", results, fields=["title", "summary"], language=language)`, then `return results`.

In `db/routers/lesson_content.py`: same pattern -- add the import, add the `language` `Query(...)` param (same description, without the `language_code` caveat) to `get_lesson_content` and `list_lesson_content`, and call `lesson_translation_service.apply_translations(db, "lesson_content", <obj-or-results>, fields=["title", "content_body"], language=language)` before returning in each.

In `db/routers/hikmah_trees.py`: same pattern -- add the import, add the `language` `Query(...)` param to `get_hikmah_tree` and `list_hikmah_trees`, and call `lesson_translation_service.apply_translations(db, "hikmah_tree", <obj-or-results>, fields=["title", "summary"], language=language)` before returning in each.

In `services/hikmah_quiz_service.py`: add `from services import lesson_translation_service` import. Change `get_questions_for_page`'s signature to `def get_questions_for_page(self, lesson_content_id: int, language: Optional[str] = None) -> Dict[str, Any]:`. After building `serialized = self._serialize_questions(questions, include_admin_fields=False)`, call a new private helper `self._apply_quiz_translations(serialized, language)`, then `return {"lesson_content_id": lesson_content_id, "questions": serialized}`. Add `def _apply_quiz_translations(self, serialized_questions: List[Dict[str, Any]], language: Optional[str]) -> None:` -- normalize language the same way as `apply_translations`; if empty/`"english"`/no questions, return (no-op). Otherwise: `question_ids = [q["id"] for q in serialized_questions]`; `choice_ids = [c["id"] for q in serialized_questions for c in q["choices"]]`; `question_translations = lesson_translation_service.lookup_lesson_translations(self.db, "quiz_question", question_ids, normalized, fields=["prompt", "explanation"])`; `choice_translations = lesson_translation_service.lookup_lesson_translations(self.db, "quiz_choice", choice_ids, normalized, fields=["choice_text"]) if choice_ids else {}`; then for each `q` in `serialized_questions`: overlay `q["prompt"]` from `question_translations.get((q["id"], "prompt"))` if present, overlay `q["explanation"]` from `question_translations.get((q["id"], "explanation"))` if present, and for each `c` in `q["choices"]` overlay `c["choice_text"]` from `choice_translations.get((c["id"], "choice_text"))` if present. Do NOT modify `list_questions_for_page_admin`, `get_question_for_page`, `create_question`, `replace_question`, `patch_question`, or `delete_question` -- these authoring/admin methods stay untranslated per the LOCKED decision.

In `api/hikmah.py`: add `from typing import Optional` to imports. Add `language: str = Query("english", description="Selected display language for learner-facing quiz content. Defaults to English.")` as a new parameter on `get_page_quiz_questions` (do NOT add it to any other endpoint in this file). Change the call to `return service.get_questions_for_page(lesson_content_id, language=language)`.

Create `tests/test_lesson_translations.py` implementing every case in `<behavior>` above. For `lookup_lesson_translations`/`apply_translations` tests, mock `db` with `unittest.mock.Mock()` and a `db.query.return_value` chain (`.filter.return_value = query`, `.all.return_value = [...]`), matching `tests/test_hikmah_quiz_service.py`'s `_build_query` helper style -- build fake `LessonTranslation`-shaped rows via `types.SimpleNamespace(entity_id=..., field=..., translated_text=...)`. For the quiz overlay tests, instantiate `HikmahQuizService(db)` with a mocked `db` the same way `tests/test_hikmah_quiz_service.py` does (`db.get.return_value = page`, `db.query.side_effect = [...]` for the questions/choices queries), then additionally mock `services.hikmah_quiz_service.lesson_translation_service.lookup_lesson_translations` (via `monkeypatch` or `unittest.mock.patch`) to return controlled translation dicts and assert the returned `get_questions_for_page(..., language="urdu")` payload reflects the overlay, while `language=None`/`"english"` returns the untouched serialized payload with zero calls to `lookup_lesson_translations`.
  </action>
  <verify>
    <automated>cd /Users/admin2/deen-backend && python -m pytest tests/test_lesson_translations.py -q -x 2>&1 | tail -30</automated>
  </verify>
  <done>
    - `services/lesson_translation_service.py::lookup_lesson_translations` and `apply_translations` exist, both sync, both never raise (return `{}`/no-op on error)
    - `GET /lessons`, `GET /lessons/{id}`, `GET /lesson-content`, `GET /lesson-content/{id}`, `GET /hikmah-trees`, `GET /hikmah-trees/{id}` all accept a `language` query param defaulting to `"english"` and project the LOCKED fields when set to a non-English value
    - `GET /hikmah/pages/{lesson_content_id}/quiz-questions` accepts `language` and projects `prompt`/`explanation`/`choice_text`; all admin quiz-question endpoints are unmodified and untranslated
    - `language="english"`/unset triggers zero `lookup_lesson_translations` calls on every surface
    - `pytest tests/test_lesson_translations.py -q` passes with zero network/DB calls
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Offline batch MT job (build only, do not run) + CLAUDE.md commands</name>
  <files>core/utils.py, scripts/translate_lessons.py, tests/test_translate_lessons.py, CLAUDE.md</files>
  <behavior>
    - `source_text_hash("some text")` returns a stable sha256 hex string; the same input always returns the same output; different input returns a different output; empty/`None` input returns a deterministic hash of the empty string (never raises)
    - `parse_args([])` returns defaults: `languages == "arabic,farsi,urdu,german,bahasa melayu,french"`, `entity_type == "all"`, `dry_run is False`, `model == DEFAULT_MODEL`, `limit is None`
    - `_resolve_enabled_entity_types("all")` returns all 5 keys of `ENTITY_FIELD_MAP` in table order (`lesson, lesson_content, quiz_question, quiz_choice, hikmah_tree`); `_resolve_enabled_entity_types("hikmah_tree")` returns `["hikmah_tree"]`
    - `translate_text(model="sonnet", text="...", language="urdu")` calls `subprocess.run` with a command list containing `"claude"`, `"-p"`, `"--model"`, `"sonnet"`, `"--system-prompt"`, `"--safe-mode"`, `"--tools"`, `""`, `"--no-session-persistence"`; the `--system-prompt` value contains `"urdu"` AND contains an explicit Qur'an-preservation instruction (assert a substring like `"Qur'an"` or `"Qur’anic"` and `"verbatim"`/`"EXACTLY"` both appear); raises `RuntimeError` on non-zero `returncode`; raises `RuntimeError` on empty stripped stdout; returns the stripped stdout on success
    - `upsert_translation(fake_session_factory, entity_type="lesson_content", entity_id=5, field="content_body", language="urdu", translated_text="...", model_name="sonnet", source_hash="abc123")` constructs a `LessonTranslation` row with all given fields plus `source="mt"` and a timezone-aware `translated_at`, then calls `db.merge(row)` and `db.commit()` on the fake session
    - `run_batch(..., dry_run=True, ...)` against a fake SQLAlchemy session (stubbed `.query(model_cls).order_by(...).limit(...).all()` returning fake rows, and a stubbed staleness-check query returning `None` for "no existing row") NEVER calls `translate_text` or `upsert_translation` (patched and asserted `not called`), but returns a summary dict with correct per-entity-type/per-language counts of items that WOULD be translated
    - `run_batch(..., limit=1, dry_run=True, ...)` processes only 1 source row per entity_type even when the fake session has more rows available
    - Staleness: `run_batch(..., dry_run=False, ...)` with a fake staleness-check that returns a `source_hash` EQUAL to the freshly computed hash for a given item+language SKIPS it (does not call `translate_text`/`upsert_translation`, does not increment that item's count); an item+language whose existing hash DIFFERS (or has no existing row) IS translated and upserted
    - `run_batch(..., dry_run=False, ...)` live path calls `translate_text` and `upsert_translation` once per (row, field, language) combination that needed translation, and `upsert_translation` is always called with a `source_hash` matching what was computed from that row's source text
  </behavior>
  <action>
In `core/utils.py`: add `import hashlib` to the top-level imports (alongside the existing `base64`, `gzip`). Immediately after `decompress_text` (~line 403), add:
```python
def source_text_hash(text: str) -> str:
    """Deterministic sha256 hex digest of source text, used by scripts/translate_lessons.py
    (DEE-69) to detect when a translated row is stale relative to its live source text.
    Never raises -- falsy input hashes as the empty string."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
```
Do not modify `compress_text`/`decompress_text`/any other existing function in this file.

Create `scripts/translate_lessons.py`, structured like `scripts/translate_references_claude_cli.py` (module docstring, `project_root = Path(__file__).parent.parent; sys.path.insert(0, str(project_root))`, `setup_logging()` + module `logger`, pure/testable top-level functions -- nothing inlined in `main()`). Import `SessionLocal` from `db.session`; `Lesson` from `db.models.lessons`; `LessonContent` from `db.models.lesson_content`; `LessonPageQuizQuestion` from `db.models.lesson_page_quiz_questions`; `LessonPageQuizChoice` from `db.models.lesson_page_quiz_choices`; `HikmahTree` from `db.models.hikmah_trees`; `LessonTranslation` from `db.models.lesson_translations`; `source_text_hash` from `core.utils`. Do NOT import Pinecone or Anthropic-related modules -- this job's source is entirely Postgres.

Module docstring must state explicitly (referencing Task 1's finding): "Unlike DEE-67's `DISABLED_REF_TYPES` structural exclusion, this job has NO reliable per-row Qur'an marker to key a structural exclusion filter on (see `db/models/lesson_translations.py`'s docstring: `lesson_content.content_type` is constrained to `{'text','quiz'}` by `scripts/hikmah_generation/upsert_hikmah_tree.py`'s `VALID_CONTENT_TYPES` validator, has no `tags` column, and embedded Qur'anic verses are inlined within `content_body`/`explanation` prose rather than isolated in dedicated rows). Qur'an preservation is therefore enforced SOLELY via the hardened `TRANSLATION_SYSTEM_PROMPT` below (mechanism 2) -- a documented residual risk, not a structural guarantee; flagged for the team's coarse offline dev sample-review process (see memory `dee63-translation-review-workflow`) before enabling any language in production."

Module-level constants:
- `SUPPORTED_LANGUAGES = ["arabic", "farsi", "urdu", "german", "bahasa melayu", "french"]`
- `ENTITY_FIELD_MAP = {"lesson": (Lesson, ["title", "summary"]), "lesson_content": (LessonContent, ["title", "content_body"]), "quiz_question": (LessonPageQuizQuestion, ["prompt", "explanation"]), "quiz_choice": (LessonPageQuizChoice, ["choice_text"]), "hikmah_tree": (HikmahTree, ["title", "summary"])}` -- the exact LOCKED translatable-surfaces table
- `ENTITY_TYPE_CHOICES = list(ENTITY_FIELD_MAP.keys())`
- `DEFAULT_MODEL = "sonnet"`
- `CLAUDE_TIMEOUT_SECONDS = 600`
- `TRANSLATION_SYSTEM_PROMPT` -- a format-string constant with a `{language}` placeholder, generalized from `translate_references_claude_cli.py`'s prompt: faithful literal translation of "Islamic educational lesson and quiz content for Twelver Shia learners" into `{language}`; preserve all meaning, terminology, honorifics, Twelver Shia theological framing; do not add interpretation/commentary/opinion/fatwa-like guidance; do not omit or summarize; return ONLY the translated text with no preamble. PLUS an additional, clearly-delimited paragraph: "CRITICAL RELIGIOUS-SENSITIVITY RULE: if the source text contains any Qur'anic verses (Ayat) quoted in Arabic script, you MUST preserve that Qur'anic Arabic text EXACTLY character-for-character in its original script -- NEVER translate, transliterate, paraphrase, or alter it in any way. Translate only the surrounding prose, explanation, and commentary into {language}. This rule is absolute and takes priority over completeness of translation."

`def parse_args(argv=None) -> argparse.Namespace:` -- `--languages` (default `",".join(SUPPORTED_LANGUAGES)`), `--entity-type` (choices `ENTITY_TYPE_CHOICES + ["all"]`, default `"all"`), `--dry-run` (`action="store_true"`), `--limit` (`type=int`, default `None`, help "cap number of source rows enumerated per entity_type, for sampling"), `--model` (default `DEFAULT_MODEL`).

`def _resolve_enabled_entity_types(entity_type_arg: str) -> list[str]:` -- `return ENTITY_TYPE_CHOICES if entity_type_arg == "all" else [entity_type_arg]`. Add a comment noting this deliberately has no `DISABLED_*` filtering step (unlike the reference script's `DISABLED_REF_TYPES`), because the Qur'an carve-out here operates at the prompt level (mechanism 2), not by excluding whole entity types.

`def translate_text(*, model: str, text: str, language: str) -> str:` -- copy the subprocess-call body verbatim from `scripts/translate_references_claude_cli.py`'s `translate_text` (same argument list shape, same `capture_output`/`text`/`timeout` kwargs, same non-zero/empty-output error handling), using this file's `TRANSLATION_SYSTEM_PROMPT`.

`def _preflight_claude_cli() -> None:` -- copy verbatim from the reference CLI script.

`def _iter_source_rows(session, entity_type: str, *, limit: Optional[int] = None):` -- generator yielding `(entity_id, field, text)` tuples. Look up `model_cls, fields = ENTITY_FIELD_MAP[entity_type]`; build `query = session.query(model_cls).order_by(model_cls.id.asc())`; apply `.limit(limit)` if `limit is not None`; for each `row` in `query.all()`, for each `field` in `fields`: `text = getattr(row, field, None)`; skip (continue) if falsy; else `yield (row.id, field, text)`.

`def _existing_source_hash(session, entity_type: str, entity_id: int, field: str, language: str) -> Optional[str]:` -- `return session.query(LessonTranslation.source_hash).filter(LessonTranslation.entity_type == entity_type, LessonTranslation.entity_id == entity_id, LessonTranslation.field == field, LessonTranslation.language == language).scalar()` (returns `None` when no row exists).

`def upsert_translation(session_factory, *, entity_type: str, entity_id: int, field: str, language: str, translated_text: str, model_name: str, source_hash: str) -> None:` -- `from datetime import datetime, timezone`; `with session_factory() as db:` construct `row = LessonTranslation(entity_type=entity_type, entity_id=entity_id, field=field, language=language, translated_text=translated_text, source="mt", translated_at=datetime.now(timezone.utc), model=model_name, source_hash=source_hash)`; `db.merge(row)`; `db.commit()`.

`def run_batch(*, languages: list[str], entity_types: list[str], limit: Optional[int], dry_run: bool, model_name: str, session_factory) -> dict:` -- returns nested `{entity_type: {language: count}}` (count = items actually translated or, on dry-run, that WOULD be translated -- items skipped as already-up-to-date are NOT counted). For each `entity_type` in `entity_types`: `summary[entity_type] = {lang: 0 for lang in languages}`; `with session_factory() as session:` iterate `_iter_source_rows(session, entity_type, limit=limit)`; for each `(entity_id, field, text)`: `computed_hash = source_text_hash(text)`; for each `language` in `languages`, wrapped in `try/except Exception:` that logs (`entity_type`, `entity_id`, `field`, `language`) and continues on any single-item failure: `existing_hash = _existing_source_hash(session, entity_type, entity_id, field, language)`; if `existing_hash == computed_hash`: `continue` (idempotent skip, decision 4); `summary[entity_type][language] += 1`; if `dry_run`: `continue`; `translated = translate_text(model=model_name, text=text, language=language)`; `upsert_translation(session_factory, entity_type=entity_type, entity_id=entity_id, field=field, language=language, translated_text=translated, model_name=model_name, source_hash=computed_hash)`. Note in a comment: unlike the Pinecone-sourced reference script, `--dry-run` here still performs real (read-only) Postgres queries to enumerate rows and check staleness -- Postgres IS the source, so a dry-run with zero DB reads is not possible; only `translate_text` (claude CLI) and `upsert_translation` (writes) are skipped.

`def main() -> None:` -- `args = parse_args()`; `languages = [l.strip().lower() for l in args.languages.split(",") if l.strip()]`; `entity_types = _resolve_enabled_entity_types(args.entity_type)`; if `not args.dry_run: _preflight_claude_cli()`; `summary = run_batch(languages=languages, entity_types=entity_types, limit=args.limit, dry_run=args.dry_run, model_name=args.model, session_factory=SessionLocal)`; `logger.info("Batch complete: %s", summary)`. Guard with `if __name__ == "__main__": main()`.

Create `tests/test_translate_lessons.py` implementing every case in `<behavior>` above, modeled on `tests/test_translate_references.py`'s structure and module docstring (mocked, no network/DB). Build a fake SQLAlchemy session/query chain for `_iter_source_rows`/`_existing_source_hash` (a `Mock()` with `.query(...).order_by(...).limit(...).all()` returning `SimpleNamespace(id=..., title=..., ...)` fake rows for the enumeration query, and a separate `.query(...).filter(...).scalar()` chain for the staleness check -- use `db.query.side_effect` to return the correct fake query object per call, matching `tests/test_hikmah_quiz_service.py`'s pattern) and a fake `session_factory` context-manager callable whose fake session records `.merge()`/`.commit()` calls (mirroring `tests/test_translate_references.py`'s `_FakeSession`). Patch `subprocess.run` for the `translate_text` tests. Do not add any new third-party dependency (`hashlib` is stdlib).

Finally, update `CLAUDE.md`'s "## Commands" fenced bash block: immediately after the existing "# Reference translation batch job (DEE-67...)" section (before "# Docker"), add:
```
# Lesson/quiz/hikmah translation batch job (DEE-69, human-triggered only -- uses local `claude` CLI, no Anthropic API key/credits)
python scripts/translate_lessons.py --dry-run --limit 5   # preview per-entity-type/per-language counts from Postgres; no claude CLI calls, no writes
python scripts/translate_lessons.py --entity-type lesson_content --languages urdu --limit 5   # small live sample
python scripts/translate_lessons.py   # full corpus x all 5 entity types x all 6 languages (only after sampling looks correct)
# Note: run `alembic upgrade head` once (creates the lesson_translations table) before this script's writes will succeed.
# Qur'an-preservation relies solely on the hardened system prompt (no reliable per-row Quran marker exists in lesson_content -- see db/models/lesson_translations.py docstring). Sample-review translated content_body/explanation fields for embedded Qur'anic verses before enabling any language in production, per dee63-translation-review-workflow.
```
  </action>
  <verify>
    <automated>cd /Users/admin2/deen-backend && python -m py_compile scripts/translate_lessons.py && python scripts/translate_lessons.py --help >/dev/null && python -m pytest tests/test_translate_lessons.py -q -x 2>&1 | tail -30</automated>
  </verify>
  <done>
    - `core/utils.py::source_text_hash` exists, deterministic, never raises
    - `scripts/translate_lessons.py` exists, is syntactically valid, and is re-runnable/idempotent (`upsert_translation` uses `Session.merge()` keyed by the composite PK; `run_batch` skips items whose `source_hash` is unchanged)
    - `TRANSLATION_SYSTEM_PROMPT` contains an explicit, unambiguous instruction to preserve embedded Qur'anic Arabic verbatim
    - `--dry-run` never calls `translate_text` or `upsert_translation` (proven by mocked tests)
    - `CLAUDE.md` documents the exact commands (dry-run, small sample, full run) and the `alembic upgrade head` prerequisite, plus the Qur'an-preservation residual-risk note
    - `pytest tests/test_translate_lessons.py -q` passes with zero network/DB calls
    - This task does NOT execute `scripts/translate_lessons.py` against any live service
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client `language` query param -> Postgres lookup | User-supplied string flows into `services/lesson_translation_service.py`'s `.filter(LessonTranslation.language == language)` across 4 read surfaces |
| client `language` -> HTTP response body | Selected-language translation text (MT-sourced, from the sidecar table) is returned to the client alongside EN/AR source, on lesson/lesson-content/hikmah-tree/quiz endpoints |
| lesson/quiz source text (Postgres) -> local `claude` CLI subprocess | `scripts/translate_lessons.py` pipes stored content as stdin to a subprocess; content originates from authoring tools (`scripts/hikmah_generation/`), not end users |
| batch script -> Postgres (`db/session.py` sync engine) | Offline, human-triggered write path; no HTTP surface |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-ffh-01 | Tampering | `language` query param used in `LessonTranslation.language == language` filters | mitigate | SQLAlchemy ORM `.query().filter()` uses parameter binding -- no raw string SQL is ever constructed from the query param |
| T-ffh-02 | Information Disclosure | `lookup_lesson_translations` DB errors | mitigate | Exceptions caught, logged server-side only (`logger.error(..., exc_info=True)`), function returns `{}` -- no internal DB error detail ever reaches the HTTP response |
| T-ffh-03 | Tampering (religious-sensitivity) | Embedded Qur'anic Arabic mistranslated/altered by the MT job | mitigate + accept | Mitigate via the hardened `TRANSLATION_SYSTEM_PROMPT` (mechanism 2, explicit verbatim-preservation instruction); accept the residual risk that no structural per-row exclusion filter exists (Task 1 finding: no reliable marker at the `lesson_content` grain) -- flagged in the SUMMARY, gated by the team's coarse offline dev sample-review process (`dee63-translation-review-workflow`) before any language goes live |
| T-ffh-04 | Tampering (subprocess/prompt injection) | Lesson/quiz source text piped as stdin to the local `claude -p` subprocess | mitigate | `--tools ""` disables all tool execution and `--safe-mode` skips CLAUDE.md/skills/plugins/hooks, matching the exact isolation already shipped in `translate_references_claude_cli.py`; command passed as an argument list (no `shell=True`), no shell-injection surface |
| T-ffh-05 | Denial of Service (cost/scope) | Accidental full-corpus live run of the batch job | mitigate | `--dry-run`/`--limit` are the documented safe default entry points in `CLAUDE.md`; the script is never invoked by application code, a route, or CI -- human-triggered CLI tool only, and this plan's tasks never execute it live |
| T-ffh-06 | Repudiation/Integrity | MT-translated lesson/quiz text served to learners with no per-row review gate | accept | Mentor-approved workflow (memory `dee63-translation-review-workflow`): MT ships by default, `reviewed_at`/`source` provide a coarse provenance hedge, no per-row reviewer state machine |
| T-ffh-SC | Tampering | npm/pip/cargo installs | accept | No new third-party dependencies added anywhere in this plan -- `hashlib` is Python stdlib; `sqlalchemy`/`alembic` already pinned in `requirements.txt` |
</threat_model>

<verification>
Run the new deterministic suites plus a broader regression check:

```bash
cd /Users/admin2/deen-backend && python -m pytest tests/test_lesson_translations.py tests/test_translate_lessons.py -q -x 2>&1 | tail -40
cd /Users/admin2/deen-backend && python -m pytest tests -q 2>&1 | tail -40
```

Confirm the migration chains cleanly onto DEE-67's head (static check, no live DB required):

```bash
cd /Users/admin2/deen-backend && alembic heads
```

Confirm the batch script is syntactically valid and never touches a live service in its own tests:

```bash
cd /Users/admin2/deen-backend && python -m py_compile scripts/translate_lessons.py
```
</verification>

<success_criteria>
- `GET /lessons`, `GET /lessons/{id}`, `GET /lesson-content`, `GET /lesson-content/{id}`, `GET /hikmah-trees`, `GET /hikmah-trees/{id}` accept `language` and project title/summary/content_body when a translation exists, falling back to source (EN/AR) when it doesn't
- `GET /hikmah/pages/{lesson_content_id}/quiz-questions` accepts `language` and projects prompt/explanation/choice_text for learners only; admin authoring endpoints are unmodified
- `language="english"`/unset never triggers a translation lookup on any surface
- No per-language row duplication anywhere; progress/quiz-attempt history stays keyed to source entity IDs
- `lesson_translations` table exists via a clean-chaining Alembic migration (model + migration match exactly, chains onto `reference_translations_001`)
- `scripts/translate_lessons.py` is a complete, re-runnable, idempotent (source_hash-gated) batch job reusing the claude-CLI subprocess logic -- but is NOT executed against any live service as part of this task
- Embedded Qur'anic Arabic is protected solely via a hardened system prompt (documented residual risk, no structural marker exists) -- explicitly noted in `CLAUDE.md` and this plan's SUMMARY
- `CLAUDE.md` documents exact start-to-finish commands for the new batch job
- All new tests are deterministic (mocked, no network/DB) and pass; no regressions in `pytest tests -q`
- No new third-party dependencies added
</success_criteria>

<output>
Create `.planning/quick/260722-ffh-dee-69-per-language-hikmah-tree-lessons-/260722-ffh-SUMMARY.md` when done.
</output>
