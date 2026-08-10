---
phase: 260707-pxt
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - db/models/reference_translations.py
  - alembic/versions/20260707_create_reference_translations_table.py
  - services/reference_translation_service.py
  - core/utils.py
  - core/pipeline.py
  - api/reference.py
  - core/pipeline_langgraph.py
  - tests/test_reference_translations.py
  - scripts/translate_references.py
  - tests/test_translate_references.py
  - CLAUDE.md
autonomous: true
requirements:
  - DEE-67
must_haves:
  truths:
    - "POST /references?language=<lang> returns each hadith reference with its existing text/text_ar fields unchanged, plus a new text_translated field populated from the reference_translations table when a row exists for that hadith_id+language, and null when it doesn't (fallback to EN/AR, per LOCKED decision)"
    - "The SSE hadith_references and quran_references events on POST /chat/stream/agentic carry the same selected-language translation fields, threaded from ChatState's existing target_language -- no new request field required"
    - "Pinecone retrieval/vector search is completely untouched -- translations are joined in AFTER retrieval, only inside the formatter layer (core/utils.py) via a Postgres sidecar lookup"
    - "A re-runnable scripts/translate_references.py exists that, given TRANSLATION_ANTHROPIC_API_KEY, can translate the entire hadith + quran_translation + tafsir_text corpus across all 6 languages into the reference_translations table -- but this task does NOT execute it against the full corpus or any live service"
    - "Because the corpus is not populated during this task, at request time most references have no matching row yet, so text_translated/quran_translation_translated/tafsir_text_translated come back null and the client falls back to the existing EN/AR fields"
    - "alembic heads resolves to a single head after this migration, chaining cleanly onto the current head (onboarding_profiles_001)"
  artifacts:
    - path: "db/models/reference_translations.py"
      provides: "ReferenceTranslation SQLAlchemy model: composite PK (ref_type, ref_key, language) + translated_text + provenance columns (source, translated_at, model, nullable reviewed_at)"
    - path: "alembic/versions/20260707_create_reference_translations_table.py"
      provides: "Migration creating reference_translations, revision reference_translations_001, down_revision onboarding_profiles_001"
    - path: "services/reference_translation_service.py"
      provides: "alookup_translations(ref_type, ref_keys, language) -> dict[str, str], self-contained async DB lookup usable from both FastAPI routes and non-route async generators"
    - path: "core/utils.py"
      provides: "aformat_references_as_json(retrieved_docs, language) and aformat_quran_references_as_json(quran_docs, language) -- async wrappers joining MT translations onto the existing sync formatters"
    - path: "scripts/translate_references.py"
      provides: "Offline batch MT job using a dedicated TRANSLATION_ANTHROPIC_API_KEY + claude-sonnet-5 (never core.chat_models / app ANTHROPIC_API_KEY), enumerating the full corpus via Pinecone list()/fetch()"
    - path: "tests/test_reference_translations.py"
      provides: "Deterministic mocked tests for the lookup service + async formatters + language threading through core.pipeline.references_pipeline"
    - path: "tests/test_translate_references.py"
      provides: "Deterministic mocked tests for the batch script (CLI parsing, translate_text, dry-run safety, upsert)"
  key_links:
    - from: "api/reference.py"
      to: "core/pipeline.py::references_pipeline"
      via: "new language Query(...) param passed through, mirroring the existing sect/limit pattern"
      pattern: "language:\\s*str\\s*=\\s*Query"
    - from: "core/pipeline.py::references_pipeline"
      to: "core/utils.py::aformat_references_as_json"
      via: "await utils.aformat_references_as_json(docs, language) replacing the sync call"
      pattern: "await utils\\.aformat_references_as_json"
    - from: "core/pipeline_langgraph.py"
      to: "core/utils.py::aformat_references_as_json / aformat_quran_references_as_json"
      via: "await call passing the existing in-scope target_language before yielding hadith_references/quran_references SSE events"
      pattern: "aformat_(references|quran_references)_as_json\\(.*target_language"
    - from: "core/utils.py"
      to: "services/reference_translation_service.py::alookup_translations"
      via: "join-after-retrieval lookup keyed by hadith_id (ref_type=hadith) or Pinecone chunk_id (ref_type=quran_translation / tafsir_text)"
      pattern: "reference_translation_service\\.alookup_translations"
    - from: "services/reference_translation_service.py"
      to: "db/models/reference_translations.py::ReferenceTranslation"
      via: "SQLAlchemy async select().where(ref_type=..., ref_key.in_(...), language=...)"
      pattern: "select\\(ReferenceTranslation\\)"
    - from: "scripts/translate_references.py"
      to: "db/models/reference_translations.py::ReferenceTranslation"
      via: "sync Session.merge() upsert keyed by the same composite PK"
      pattern: "db\\.merge\\(.*ReferenceTranslation"
---

<objective>
Implement DEE-67: extend reference lookup so each hadith/Quran/tafsir reference can include a translation in the user's selected language, alongside the existing English (`text`/`page_content_en`/`quran_translation`/`tafsir_text`) and Arabic (`text_ar`) fields. Translations live in a new Postgres sidecar table (`reference_translations`) keyed on the reference IDs already present in Pinecone metadata (`hadith_id`) or the Pinecone vector ID itself (`chunk_id` for Quran/tafsir), joined in AFTER retrieval so the vector/retrieval path is completely untouched. Thread a `language` selector through `POST /references` and the `hadith_references`/`quran_references` SSE events. Build (but do not run) a re-runnable offline batch MT job that uses a dedicated personal Anthropic key + `claude-sonnet-5` to populate the full corpus across 6 languages later.

Purpose: Users viewing reference citations currently only see EN/AR text regardless of their selected chat language. This closes that gap without touching the retrieval/ranking path, and without coupling translation cost/usage to the app's production Anthropic key.

Output:
- `reference_translations` Postgres table + SQLAlchemy model + Alembic migration
- `services/reference_translation_service.py` async lookup service
- `core/utils.py` async formatter wrappers wired into `/references` and the SSE `hadith_references`/`quran_references` events, with EN/AR fallback when a translation row doesn't exist yet
- `scripts/translate_references.py` — re-runnable, not executed in this task — plus documented start-to-finish commands in `CLAUDE.md`
- Deterministic mocked tests covering the lookup service, async formatters, language threading, and the batch script (no live network/DB calls in tests)
</objective>

<execution_context>
@/Users/admin2/.claude/plugins/cache/gsd-plugin/gsd/4.0.2/workflows/execute-plan.md
@/Users/admin2/.claude/plugins/cache/gsd-plugin/gsd/4.0.2/templates/summary.md
</execution_context>

<context>
@/Users/admin2/deen-backend/.planning/STATE.md
@/Users/admin2/deen-backend/CLAUDE.md
@/Users/admin2/deen-backend/.planning/quick/260707-pxt-dee-67-reference-lookup-selected-languag/260707-pxt-CONTEXT.md

<!-- Key interfaces the executor needs -- extracted from codebase. Use directly, no exploration. -->
<interfaces>
From `core/utils.py` (current, unchanged sync functions to build on top of -- do NOT modify their internals):
- `format_references_as_json(retrieved_docs: list) -> list` (~line 227): iterates `retrieved_docs`, each item is a dict with a `metadata` key (containing `hadith_id`, etc.) and `page_content_en`/`page_content_ar` keys (already decompressed by the reranker). Returns a list of dicts with keys `author, volume, book_number, book_title, chapter_number, chapter_title, collection, grade_ar, grade_en, hadith_id, hadith_no, hadith_url, lang, sect, reference, text, text_ar`. Output list preserves 1:1 order/length with `retrieved_docs`.
- `format_quran_references_as_json(quran_docs: list) -> list` (~line 268): iterates `quran_docs` inside a single try/except wrapping the WHOLE loop (not per-item) -- on any exception the returned list may be shorter than `quran_docs`. Each output dict has keys `surah_name, title, chapter_number, verses_covered, starting_verse, ending_verse, author, collection, volume, sect, quran_translation, tafsir_text`. Does NOT include `chunk_id` in its output -- read `chunk_id` from the original `quran_docs` input instead.
- Module currently imports only `Document`, `traceback`, `base64`, `gzip` -- no `asyncio`, no `typing`.

From `modules/retrieval/retriever.py` (source of the `quran_docs` list passed to the formatter -- both `retrieve_quran_documents` and `aretrieve_quran_documents`):
- Each Quran/tafsir doc dict has top-level keys: `chunk_id` (the Pinecone vector/match `.id` -- a stable, already-existing identifier), `metadata`, `page_content_en` (decompressed tafsir text, from raw Pinecone metadata field `text_chunk`), `quran_translation` (decompressed, from raw Pinecone metadata field `english_quran_translation`).
- Raw hadith Pinecone metadata (see `modules/reranking/reranker.py` ~lines 68-107): `hadith_id` (plain), `text_en` (gzip+base64 compressed, decompress via `core.utils.decompress_text`), `text_ar` (same compression).

From `core/pipeline.py` (current `references_pipeline`, ~lines 88-110):
- `async def references_pipeline(user_query: str, sect: str, limit: int = REFERENCE_FETCH_COUNT):` -- classifies, enhances, then `asyncio.gather`s `retriever.aretrieve_shia_documents` / `aretrieve_sunni_documents`, then for each `(label, docs)` does `results[label] = utils.format_references_as_json(docs)`. Only handles hadith docs (no Quran retrieval on this path today).

From `api/reference.py` (current route, ~lines 22-28):
- `sect: str = Query("both", enum=["sunni", "shia", "both"])` and `limit: int = Query(10, ge=1, le=50, ...)` are the exact pattern to mirror for the new `language` param. Route calls `await pipeline.references_pipeline(user_query, sect, limit)`.

From `core/pipeline_langgraph.py` (SSE path, ~lines 149/515-521):
- `target_language: str = "english"` is already a parameter in scope in the generator function that emits SSE events.
- Current code: `if hadith_docs: hadith_json = utils.format_references_as_json(hadith_docs); yield sse_event("hadith_references", {"references": hadith_json})` and the analogous block for `quran_docs` / `format_quran_references_as_json` / `quran_references`. This whole function is `async def` and already uses `await` extensively elsewhere in the same block -- safe to `await` the new async formatters here.

From `db/session.py`: `Base = declarative_base()`, sync `engine`/`SessionLocal` (used by the batch script). From `db/async_session.py`: `AsyncSessionLocal = async_sessionmaker(...)` already configured with pooling -- used by the new lookup service.

From `alembic/versions/` head chain: the current head is `onboarding_profiles_001` (`20260414_create_user_onboarding_profiles.py`) -- no other migration lists it as `down_revision`. Migration style to mirror (see that file): `revision = '...'`, `down_revision = '...'`, `op.create_table(...)` with `sa.Column(..., primary_key=True, nullable=False)` for composite keys, `sa.TIMESTAMP(timezone=True)` with `server_default=sa.func.now()`.

From `core/config.py`: `PINECONE_API_KEY`, `DEEN_DENSE_INDEX_NAME`, `QURAN_DENSE_INDEX_NAME` already validated at import (fail-fast). `ANTHROPIC_API_KEY` is the APP key -- the batch script MUST NOT use it.

From `core/chat_models.py`: shows the pattern to explicitly AVOID for the batch script (it wraps the app's `ANTHROPIC_API_KEY` via `langchain_anthropic.ChatAnthropic`). The batch script must instead use the raw `anthropic` SDK (`anthropic==0.92.0`, already in `requirements.txt`) with `TRANSLATION_ANTHROPIC_API_KEY`.

From `scripts/ingest_fiqh.py` -- the batch-job shape to mirror: `argparse` CLI in `main()`, `project_root` sys.path insert, `setup_logging()` + module logger, pure/testable helper functions (not inlined in `main()`), Pinecone client init via `Pinecone(api_key=...)`.

From `tests/conftest.py`: sets test-only env defaults (`ANTHROPIC_API_KEY`, `PINECONE_API_KEY`, `DEEN_*_INDEX_NAME`, `DB_USER/PASSWORD/HOST/PORT/NAME`, etc.) via `os.environ.setdefault`, so importing `db.async_session` / `db.session` / `core.config` at module level in tests never touches a real network or DB connection unless a test explicitly does so.

Canonical 6-language list already established in this codebase (DEE-68, `tests/test_dee68_multilingual_generation.py`): `["arabic", "farsi", "urdu", "german", "bahasa melayu", "french"]` -- lowercase free-text strings, NOT ISO codes, matching `ChatState["target_language"]` convention. Reuse this exact list/casing for `language` everywhere in this plan (no enum validation at the Pydantic/Query layer, matching how `target_language`/`ChatRequest.language` are plain `str` today).
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: reference_translations table (model + migration)</name>
  <files>db/models/reference_translations.py, alembic/versions/20260707_create_reference_translations_table.py</files>
  <action>
Create `db/models/reference_translations.py` defining `ReferenceTranslation(Base)` (import `Base` from `..session`) with `__tablename__ = "reference_translations"` and these columns, matching the LOCKED schema decision exactly (no extra reviewer-state columns):
- `ref_type` (Text, primary_key=True, nullable=False) -- one of `"hadith"`, `"quran_translation"`, `"tafsir_text"`. `quran_translation` and `tafsir_text` deliberately share the same `ref_key` (the Pinecone chunk_id) but are separate rows/ref_types, because a single Quran/tafsir chunk has two independently-translatable fields.
- `ref_key` (Text, primary_key=True, nullable=False) -- `hadith_id` for `ref_type="hadith"`; the Pinecone vector `chunk_id` for the other two ref_types. Document this mapping in a docstring/comment on the model, since it's the resolution to the "multiple reference types with different id schemes" concern flagged in CONTEXT.md -- Quran/tafsir chunks already have a stable, existing Pinecone vector ID (`chunk_id`), so no synthesized composite key is needed.
- `language` (Text, primary_key=True, nullable=False) -- one of the 6 canonical language strings (see `<interfaces>`), lowercase.
- `translated_text` (Text, nullable=False)
- `source` (Text, nullable=False, server_default="mt")
- `translated_at` (TIMESTAMP(timezone=True), nullable=False, server_default=`func.now()`)
- `model` (Text, nullable=False) -- the translation model/version string, e.g. `"claude-sonnet-5"`
- `reviewed_at` (TIMESTAMP(timezone=True), nullable=True) -- spot-review hedge, no per-row status/reviewer state machine

Create `alembic/versions/20260707_create_reference_translations_table.py` mirroring the style of `alembic/versions/20260414_create_user_onboarding_profiles.py`: `revision = 'reference_translations_001'`, `down_revision = 'onboarding_profiles_001'` (the current head -- verify no other migration file already declares this as its `down_revision` before writing). `upgrade()` calls `op.create_table('reference_translations', ...)` with the same 8 columns/types/defaults as the model above (composite primary key via three `primary_key=True` columns). `downgrade()` calls `op.drop_table('reference_translations')`. Do not add extra indexes -- the composite PK on `(ref_type, ref_key, language)` already covers the query pattern (`ref_type` + `ref_key IN (...)` + `language` equality) used by the lookup service in Task 2.

Do NOT run `alembic upgrade head` as part of this task -- author the migration only; running it against the real database is a separate step the user performs (document the exact command in Task 3's CLAUDE.md update).
  </action>
  <verify>
    <automated>cd /Users/admin2/deen-backend && python -c "
from db.models.reference_translations import ReferenceTranslation
cols = {c.name for c in ReferenceTranslation.__table__.columns}
required = {'ref_type','ref_key','language','translated_text','source','translated_at','model','reviewed_at'}
assert required <= cols, f'missing columns: {required - cols}'
pk = {c.name for c in ReferenceTranslation.__table__.primary_key.columns}
assert pk == {'ref_type','ref_key','language'}, f'unexpected PK: {pk}'
print('model OK:', sorted(cols))
" && alembic heads
</automated>
  </verify>
  <done>
    - `db/models/reference_translations.py` defines `ReferenceTranslation` with the 8 columns above and a 3-column composite primary key
    - `alembic/versions/20260707_create_reference_translations_table.py` exists with `down_revision = 'onboarding_profiles_001'`, and `alembic heads` resolves to exactly one head (the new migration)
    - No existing migration file is broken or renumbered
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Join-after-retrieval translation lookup, wired into /references and SSE reference events</name>
  <files>services/reference_translation_service.py, core/utils.py, core/pipeline.py, api/reference.py, core/pipeline_langgraph.py, tests/test_reference_translations.py</files>
  <behavior>
    - `alookup_translations("hadith", ["h1", "h2"], "urdu")` returns `{"h1": "...", "h2": "..."}` when matching rows exist, using a mocked/fake AsyncSession (no real DB) -- and returns `{}` (not raising) when the DB call raises, or when `ref_keys` is empty
    - `aformat_references_as_json(docs, language=None)` and `aformat_references_as_json(docs, language="english")` both return the unmodified base list (from `format_references_as_json`) plus `text_translated=None` and `translated_language=None` on every item, WITHOUT calling `alookup_translations` at all
    - `aformat_references_as_json(docs, language="urdu")` calls `alookup_translations("hadith", <hadith_ids>, "urdu")` exactly once and merges results onto `text_translated`; hadith_ids with no matching translation get `text_translated=None` (fallback) while `translated_language="urdu"` is still set on every item
    - `aformat_quran_references_as_json(quran_docs, language="urdu")` calls `alookup_translations` twice (once with `ref_type="quran_translation"`, once with `ref_type="tafsir_text"`, both keyed by `chunk_id`) and merges results onto `quran_translation_translated` / `tafsir_text_translated` respectively; existing `quran_translation`/`tafsir_text` fields are unchanged
    - `core.pipeline.references_pipeline(user_query, sect, limit, language="urdu")` passes `language` through to `utils.aformat_references_as_json`, proven via a mocked pipeline call asserting the language argument reaches the formatter
  </behavior>
  <action>
Create `services/reference_translation_service.py`. Add module docstring explaining this is the join-after-retrieval lookup for DEE-67 (Postgres sidecar, not Pinecone metadata -- see CONTEXT.md). Import `AsyncSessionLocal` from `db.async_session`, `ReferenceTranslation` from `db.models.reference_translations`, `select` from `sqlalchemy`, `logging`, and `Iterable` from `typing`. Define `logger = logging.getLogger(__name__)`. Implement:

`async def alookup_translations(ref_type: str, ref_keys: Iterable[str], language: str) -> dict[str, str]:` -- normalize `ref_keys` to a deduplicated list of non-empty strings (skip `None`, `""`, `"N/A"`); return `{}` immediately if the list is empty (no DB round trip for empty input). Otherwise open `async with AsyncSessionLocal() as db:`, build `stmt = select(ReferenceTranslation).where(ReferenceTranslation.ref_type == ref_type, ReferenceTranslation.ref_key.in_(keys), ReferenceTranslation.language == language)`, `result = await db.execute(stmt)`, `rows = result.scalars().all()`, return `{row.ref_key: row.translated_text for row in rows}`. Wrap the whole DB block in `try/except Exception:` -- on any exception, `logger.error(..., exc_info=True)` with `ref_type`/`language` in the message, and return `{}` so callers always get a safe, empty-dict fallback rather than a raised exception (matches the project's tool-error-dict convention in `agents/tools/`).

This function has no FastAPI `Depends()` call site (it's invoked from both a route function and a plain async generator in `core/pipeline_langgraph.py`), so it must open and close its own short-lived `AsyncSessionLocal()` context manager per call -- do not try to inject a session parameter.

In `core/utils.py`: add `import asyncio` and `from typing import Optional` to the top-level imports (alongside the existing `Document`, `traceback`, `base64`, `gzip`). Add a top-level `from services import reference_translation_service` import (no circular-import risk -- confirmed no `services/*.py` module imports `core.utils`). Then add two new async functions immediately after `format_quran_references_as_json` (do not modify `format_references_as_json` or `format_quran_references_as_json` themselves):

`async def aformat_references_as_json(retrieved_docs: list, language: Optional[str] = None) -> list:` -- call `base = format_references_as_json(retrieved_docs)` first (reuse, don't duplicate). Normalize `normalized_language = (language or "").strip().lower()`. If `not normalized_language or normalized_language == "english"`: set `ref["text_translated"] = None` and `ref["translated_language"] = None` on every `ref` in `base`, then `return base` (no DB call). Otherwise: build `hadith_ids = [ref.get("hadith_id") for ref in base]`, call `translations = await reference_translation_service.alookup_translations("hadith", hadith_ids, normalized_language)`, then for each `ref` in `base` set `ref["text_translated"] = translations.get(str(ref.get("hadith_id")))` and `ref["translated_language"] = normalized_language`; `return base`.

`async def aformat_quran_references_as_json(quran_docs: list, language: Optional[str] = None) -> list:` -- call `base = format_quran_references_as_json(quran_docs)` first. Because that sync formatter's single try/except wraps its whole loop (can return a shorter list on error -- see `<interfaces>`), build `chunk_ids = [doc.get("chunk_id") for doc in (quran_docs or [])[: len(base)]]` (defensive slice to keep alignment). Normalize language the same way. If no translation needed: set `ref["quran_translation_translated"] = None`, `ref["tafsir_text_translated"] = None`, `ref["translated_language"] = None` on every `ref` in `base`; return `base`. Otherwise: run both lookups concurrently with `asyncio.gather`: `translation_lookup, tafsir_lookup = await asyncio.gather(reference_translation_service.alookup_translations("quran_translation", chunk_ids, normalized_language), reference_translation_service.alookup_translations("tafsir_text", chunk_ids, normalized_language))`; then `for ref, chunk_id in zip(base, chunk_ids): ref["quran_translation_translated"] = translation_lookup.get(str(chunk_id)); ref["tafsir_text_translated"] = tafsir_lookup.get(str(chunk_id)); ref["translated_language"] = normalized_language`; `return base`.

In `core/pipeline.py`: change `async def references_pipeline(user_query: str, sect: str, limit: int = REFERENCE_FETCH_COUNT):` to add a `language: str = "english"` parameter (keep it last, after `limit`, to avoid breaking positional-arg call sites -- but update `api/reference.py`'s call site below to pass it explicitly by position anyway). Replace the loop body `results[label] = utils.format_references_as_json(docs)` with `results[label] = await utils.aformat_references_as_json(docs, language)`. Do NOT touch the separate legacy sync `chat_pipeline_streaming` function (line ~43-84) -- it is out of scope for this task (not in DEE-67's affected-surfaces list).

In `api/reference.py`: add `language: str = Query("english", description="Selected language for translated reference text (e.g. 'arabic', 'farsi', 'urdu', 'german', 'bahasa melayu', 'french'). Defaults to English -- no translation join performed.")` as a new parameter on `references_pipeline`, mirroring the existing `sect`/`limit` `Query(...)` pattern (no `enum=` restriction, matching the free-text convention already used for `target_language` elsewhere). Update the call `results = await pipeline.references_pipeline(user_query, sect, limit)` to `results = await pipeline.references_pipeline(user_query, sect, limit, language)`.

In `core/pipeline_langgraph.py`: at the two call sites near lines 515-521, change `hadith_json = utils.format_references_as_json(hadith_docs)` to `hadith_json = await utils.aformat_references_as_json(hadith_docs, target_language)`, and `quran_json = utils.format_quran_references_as_json(quran_docs)` to `quran_json = await utils.aformat_quran_references_as_json(quran_docs, target_language)`. `target_language` is already an in-scope parameter of the enclosing function -- no new parameter threading needed here.

Create `tests/test_reference_translations.py` implementing every case in `<behavior>` above, plus: a fake async-context-manager `AsyncSession` stub (with a fake `execute()` returning an object whose `.scalars().all()` returns a list of simple row objects carrying `.ref_key`/`.translated_text` attributes) patched onto `services.reference_translation_service.AsyncSessionLocal`, to test `alookup_translations` directly against realistic SQLAlchemy-shaped return values without a real database; and a test that a raised exception inside the fake session's `execute()` still returns `{}` from `alookup_translations` (no exception propagates). Use `@pytest.mark.asyncio` throughout (already a project dependency, see `pytest-asyncio==0.26.0` in `requirements.txt`). Follow the module docstring / import style of `tests/test_dee68_multilingual_generation.py` (mocked, no network).
  </action>
  <verify>
    <automated>cd /Users/admin2/deen-backend && python -m pytest tests/test_reference_translations.py -q -x 2>&1 | tail -30</automated>
  </verify>
  <done>
    - `services/reference_translation_service.py::alookup_translations` exists, opens its own `AsyncSessionLocal`, and never raises (returns `{}` on error)
    - `core/utils.py::aformat_references_as_json` and `aformat_quran_references_as_json` exist, both skip the DB call entirely when `language` is unset/`"english"`, and both preserve every existing field from the sync formatters unchanged
    - `POST /references` accepts a `language` query param and threads it to `core.pipeline.references_pipeline` -> `utils.aformat_references_as_json`
    - `core/pipeline_langgraph.py`'s SSE `hadith_references`/`quran_references` events are built via the new async formatters, passing the existing `target_language`
    - `pytest tests/test_reference_translations.py -q` passes with zero network/DB calls
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Offline batch MT job (build only, do not run) + documented commands</name>
  <files>scripts/translate_references.py, tests/test_translate_references.py, CLAUDE.md</files>
  <behavior>
    - `parse_args([])` (no CLI args) returns defaults: `languages == "arabic,farsi,urdu,german,bahasa melayu,french"`, `ref_type == "all"`, `dry_run is False`, `model == "claude-sonnet-5"`, `limit is None`
    - `_get_translation_client()` raises `ValueError` (mentioning `TRANSLATION_ANTHROPIC_API_KEY`) when that env var is unset; when set, it constructs and returns an `anthropic.Anthropic` client using that key (proven via a patched `anthropic.Anthropic` class, asserting it was called with `api_key=<the env var value>`) -- never reads `ANTHROPIC_API_KEY`
    - `translate_text(fake_client, model="claude-sonnet-5", text="...", language="urdu")` calls `fake_client.messages.create(model=..., system=<system prompt containing "urdu">, messages=[{"role": "user", "content": "..."}], max_tokens=...)` and returns the stripped text from the mocked response's `content[0].text`
    - `run_batch(..., dry_run=True, ...)` against a fake Pinecone client/index (stubbed `.list()`/`.fetch()`) NEVER calls `translate_text` or `upsert_translation` (patched and asserted `not called`), but returns a summary dict with correct per-ref_type/per-language counts of items that WOULD be translated
    - `run_batch(..., limit=1, dry_run=True, ...)` processes only 1 source item even when the fake index has more available IDs
    - `upsert_translation(fake_session_factory, ref_type="hadith", ref_key="h1", language="urdu", translated_text="...", model_name="claude-sonnet-5")` constructs a `ReferenceTranslation` row with `source="mt"`, a timezone-aware `translated_at`, and the given `model`/`ref_type`/`ref_key`(as `str`)/`language`/`translated_text`, then calls `db.merge(row)` and `db.commit()` on the fake session
  </behavior>
  <action>
Create `scripts/translate_references.py`, structured like `scripts/ingest_fiqh.py` (module docstring with usage examples, `project_root` sys.path insert, `setup_logging()` + module `logger`, pure/testable top-level functions -- nothing inlined in `main()`). Import `Anthropic` from `anthropic` (NOT `langchain_anthropic`, NOT `core.chat_models`). Import `Pinecone` from `pinecone`. Import `SessionLocal` from `db.session`, `ReferenceTranslation` from `db.models.reference_translations`, `decompress_text` from `core.utils`, and `PINECONE_API_KEY`, `DEEN_DENSE_INDEX_NAME`, `QURAN_DENSE_INDEX_NAME` from `core.config`. Do NOT import `ANTHROPIC_API_KEY` from `core.config` anywhere in this file -- this is the LOCKED isolation requirement.

Module-level constants: `SUPPORTED_LANGUAGES = ["arabic", "farsi", "urdu", "german", "bahasa melayu", "french"]` (the exact canonical list from `<interfaces>`); `REF_TYPE_CHOICES = ["hadith", "quran_translation", "tafsir_text"]`; `DEFAULT_MODEL = "claude-sonnet-5"`; `TRANSLATION_SYSTEM_PROMPT` -- a format-string constant (with a `{language}` placeholder) instructing: faithful, literal translation into `{language}` of a Twelver Shia Islamic reference text (hadith/Quran translation/tafsir); preserve all meaning, terminology, honorifics, and the Twelver Shia theological framing; do not add interpretation, commentary, opinion, or fatwa-like guidance; do not omit or summarize; return ONLY the translated text with no preamble or explanation (this operationalizes the CLAUDE.md religious-sensitivity hard rule for this MT job).

`def parse_args(argv=None) -> argparse.Namespace:` -- `--languages` (default `",".join(SUPPORTED_LANGUAGES)`, comma-separated string), `--ref-type` (choices `REF_TYPE_CHOICES + ["all"]`, default `"all"`), `--dry-run` (`action="store_true"`), `--limit` (`type=int`, `default=None`, help "cap number of source items enumerated per ref_type, for sampling"), `--model` (default `DEFAULT_MODEL`). Return `parser.parse_args(argv)`.

`def _get_translation_client() -> Anthropic:` -- `api_key = os.getenv("TRANSLATION_ANTHROPIC_API_KEY")`; if falsy, `raise ValueError("TRANSLATION_ANTHROPIC_API_KEY is not set. This batch job requires a dedicated personal Claude API key, separate from the app's ANTHROPIC_API_KEY, so translation cost/usage never touches the running app's key. Set TRANSLATION_ANTHROPIC_API_KEY before running.")`; otherwise `return Anthropic(api_key=api_key)`. Only called when `not args.dry_run`, so `--dry-run` never requires this env var.

`def translate_text(client, *, model: str, text: str, language: str) -> str:` -- calls `client.messages.create(model=model, max_tokens=2048, system=TRANSLATION_SYSTEM_PROMPT.format(language=language), messages=[{"role": "user", "content": text}])`, returns `response.content[0].text.strip()`.

`def upsert_translation(session_factory, *, ref_type: str, ref_key: str, language: str, translated_text: str, model_name: str) -> None:` -- `from datetime import datetime, timezone`; `with session_factory() as db:` construct `row = ReferenceTranslation(ref_type=ref_type, ref_key=str(ref_key), language=language, translated_text=translated_text, source="mt", translated_at=datetime.now(timezone.utc), model=model_name)`; `db.merge(row)`; `db.commit()` (SQLAlchemy `Session.merge()` performs an insert-or-update keyed by primary key, which is exactly the upsert semantics needed here for re-runnable idempotent execution).

Enumeration helpers (pure, index-agnostic so they're testable with a fake Pinecone index object exposing `.list(namespace=...)` -- a generator yielding lists of id strings -- and `.fetch(ids=..., namespace=...)` -- returning an object with a `.vectors` dict mapping id -> object with a `.metadata` dict):

`def _iter_source_items(pc_index, *, namespace: str = "ns1", limit: Optional[int] = None):` -- generator yielding `(item_id, metadata_dict)` tuples by iterating `pc_index.list(namespace=namespace)` pages, calling `pc_index.fetch(ids=page_ids, namespace=namespace)` per page, and yielding from `fetched.vectors.items()` as `(vector_id, vector.metadata)`; stop (via a running counter) once `limit` items have been yielded, if `limit` is not `None`.

`def _extract_text_for_ref_type(ref_type: str, metadata: dict) -> Optional[str]:` -- for `ref_type == "hadith"`: `decompress_text(metadata.get("text_en", "") or "")` or `None` if empty; for `ref_type == "quran_translation"`: `decompress_text(metadata.get("english_quran_translation", "") or "")`; for `ref_type == "tafsir_text"`: `decompress_text(metadata.get("text_chunk", "") or "")`.

`def _index_name_for_ref_type(ref_type: str) -> str:` -- `DEEN_DENSE_INDEX_NAME` for `"hadith"`, `QURAN_DENSE_INDEX_NAME` for `"quran_translation"`/`"tafsir_text"`.

`def run_batch(*, languages: list[str], ref_types: list[str], limit: Optional[int], dry_run: bool, model_name: str, translation_client, pc_client, session_factory) -> dict:` -- returns a nested summary dict `{ref_type: {language: count}}`. For each `ref_type` in `ref_types`: get `pc_index = pc_client.Index(_index_name_for_ref_type(ref_type))`; for each `(item_id, metadata)` in `_iter_source_items(pc_index, limit=limit)`: `text = _extract_text_for_ref_type(ref_type, metadata)`; skip if falsy; for each `language` in `languages`: increment `summary[ref_type][language]`; if `dry_run`: continue (no translate/upsert call at all); else: `translated = translate_text(translation_client, model=model_name, text=text, language=language)` then `upsert_translation(session_factory, ref_type=ref_type, ref_key=item_id, language=language, translated_text=translated, model_name=model_name)`. Wrap the per-item/per-language body in `try/except Exception:` that logs and continues (one bad item/language must not abort the whole run), matching the project's error-handling convention.

`def main() -> None:` -- `args = parse_args()`; `languages = [l.strip().lower() for l in args.languages.split(",") if l.strip()]`; `ref_types = REF_TYPE_CHOICES if args.ref_type == "all" else [args.ref_type]`; `translation_client = None if args.dry_run else _get_translation_client()`; `pc_client = Pinecone(api_key=PINECONE_API_KEY)`; call `run_batch(...)` with `session_factory=SessionLocal`; `logger.info("Batch complete: %s", summary)`. Guard with `if __name__ == "__main__": main()`.

Create `tests/test_translate_references.py` implementing every case in `<behavior>` above, modeled on `tests/test_ingest_fiqh.py`'s structure (module docstring stating these are mocked/no-network/no-DB tests). Build small fake classes for the Pinecone index (`.list()` yielding one or two pages of id lists, `.fetch()` returning a `SimpleNamespace(vectors={...})` where each vector is `SimpleNamespace(metadata={...})` with `core.utils.compress_text`-compressed sample text so `_extract_text_for_ref_type` round-trips correctly) and for the SQLAlchemy session factory (a context-manager-returning callable whose fake session records `.merge()`/`.commit()` calls). Patch `anthropic.Anthropic` for the `_get_translation_client` tests. Do not add `langdetect` or any other new third-party dependency.

Finally, update `CLAUDE.md`: in the existing "## Commands" fenced bash block, after the "# Fiqh corpus ingestion / encoder regeneration" section, add a new commented section "# Reference translation batch job (DEE-67, personal key only -- do NOT run without setting TRANSLATION_ANTHROPIC_API_KEY)" with these exact example commands: `export TRANSLATION_ANTHROPIC_API_KEY=sk-ant-...   # personal key, never the app's ANTHROPIC_API_KEY`, `python scripts/translate_references.py --dry-run --limit 5   # preview counts, no Anthropic/DB calls`, `python scripts/translate_references.py --ref-type hadith --languages urdu --limit 20   # small live sample`, `python scripts/translate_references.py   # full corpus x all 6 languages (only after sampling looks correct)`, and a one-line note that `alembic upgrade head` must be run once (after Task 1's migration is authored) before this script's writes will succeed.
  </action>
  <verify>
    <automated>cd /Users/admin2/deen-backend && python -m py_compile scripts/translate_references.py && python -m pytest tests/test_translate_references.py -q -x 2>&1 | tail -30</automated>
  </verify>
  <done>
    - `scripts/translate_references.py` exists, is syntactically valid, and is re-runnable/idempotent (`upsert_translation` uses `Session.merge()` keyed by the composite PK)
    - The script never imports or reads `ANTHROPIC_API_KEY` / `core.chat_models` -- only `TRANSLATION_ANTHROPIC_API_KEY` via the raw `anthropic` SDK
    - `--dry-run` never calls the Anthropic client or writes to the database (proven by mocked tests)
    - `CLAUDE.md` documents the exact start-to-finish commands (dry-run, small sample, full run) and the `alembic upgrade head` prerequisite
    - `pytest tests/test_translate_references.py -q` passes with zero network/DB calls
    - This task does NOT execute `scripts/translate_references.py` against any live service
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client `language` query param -> Postgres lookup | User-supplied string flows into `services/reference_translation_service.py`'s `select().where(..., ReferenceTranslation.language == language)` |
| client `language` / `target_language` -> SSE response body | Selected-language translation text (MT-sourced, from the sidecar table) is returned to the client alongside EN/AR |
| operator's personal `TRANSLATION_ANTHROPIC_API_KEY` -> `scripts/translate_references.py` | Dedicated credential, isolated from the app's `ANTHROPIC_API_KEY`, read only from the environment |
| batch script -> Postgres (`db/session.py` sync engine) | Offline, human-triggered write path; no HTTP surface |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-pxt-01 | Tampering | `language` query param used in `ReferenceTranslation.language == language` | mitigate | SQLAlchemy ORM `select().where()` uses parameter binding -- no raw string SQL is ever constructed from user input, so standard SQL injection is structurally not possible here |
| T-pxt-02 | Information Disclosure | `alookup_translations` DB errors | mitigate | Exceptions are caught, logged server-side only (`logger.error(..., exc_info=True)`), and the function returns `{}` -- no internal DB error detail is ever surfaced to the HTTP/SSE response, matching the project's existing tool-error-dict convention |
| T-pxt-03 | Tampering (secrets) | `TRANSLATION_ANTHROPIC_API_KEY` handling in `scripts/translate_references.py` | mitigate | Read only via `os.getenv`, never logged, never written to the DB or any file; the app's `ANTHROPIC_API_KEY`/`core.chat_models` are never imported into this script, keeping the two credentials structurally isolated |
| T-pxt-04 | Denial of Service (cost) | Accidental full-corpus live run of the batch job | mitigate | `--dry-run` and `--limit` are the documented default-safe entry points in `CLAUDE.md`; the script is never invoked by application code, a route, or CI -- it is a manually-triggered, human-run CLI tool only, and this task does not execute it |
| T-pxt-05 | Tampering (content fidelity) | MT-translated religious reference text served to end users | accept | Mentor-approved workflow (see CONTEXT.md / memory `dee63-translation-review-workflow`): MT ships by default, `reviewed_at` provides a nullable spot-review hedge, and the `TRANSLATION_SYSTEM_PROMPT` explicitly instructs faithful literal translation with no added interpretation/fatwa language, per the CLAUDE.md religious-sensitivity hard rule |
| T-pxt-SC | Tampering | npm/pip/cargo installs | accept | No new third-party dependencies added anywhere in this plan -- `anthropic`, `sqlalchemy`, `pinecone`, `pytest-asyncio` are all already pinned in `requirements.txt` |
</threat_model>

<verification>
Run the new deterministic suites plus a broader regression check:

```bash
cd /Users/admin2/deen-backend && python -m pytest tests/test_reference_translations.py tests/test_translate_references.py -q -x 2>&1 | tail -40
cd /Users/admin2/deen-backend && python -m pytest tests -q --ignore=tests/db 2>&1 | tail -40
```

Confirm the migration chains cleanly (requires local `.env` DB settings, matching the existing `alembic upgrade head` setup step already documented in `CLAUDE.md`):

```bash
cd /Users/admin2/deen-backend && alembic heads
```

Confirm the batch script is syntactically valid and its tests never touch a live service:

```bash
cd /Users/admin2/deen-backend && python -m py_compile scripts/translate_references.py
```
</verification>

<success_criteria>
- `POST /references?language=<lang>` returns hadith references with `text`/`text_ar` unchanged plus `text_translated`/`translated_language`, falling back to `null` when no translation row exists yet
- SSE `hadith_references`/`quran_references` events on `POST /chat/stream/agentic` carry the same selected-language fields, driven by the existing `target_language`
- `reference_translations` table exists via a clean-chaining Alembic migration (model + migration match exactly)
- `scripts/translate_references.py` is a complete, re-runnable, idempotent batch job using a dedicated `TRANSLATION_ANTHROPIC_API_KEY` + configurable model (default `claude-sonnet-5`) -- but is NOT executed against any live service as part of this task
- `CLAUDE.md` documents exact start-to-finish commands for the batch job
- All new tests are deterministic (mocked, no network/DB) and pass; no regressions in `pytest tests -q --ignore=tests/db`
- No new third-party dependencies added
- Pinecone retrieval/vector search code paths are unmodified
</success_criteria>

<output>
Create `.planning/quick/260707-pxt-dee-67-reference-lookup-selected-languag/260707-pxt-SUMMARY.md` when done.
</output>
