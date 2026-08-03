# Quick Task 260707-pxt: DEE-67 reference-lookup selected-language translations - Context

**Gathered:** 2026-07-08
**Status:** Ready for planning

<domain>
## Task Boundary

DEE-67 (sub-issue of DEE-63). Extend reference lookup so each reference includes a
translation in the user's selected language, **alongside** the existing English and Arabic.
Translations live in a new Postgres sidecar table keyed on the reference IDs already present
in Pinecone metadata, joined in AFTER retrieval so the vector/retrieval path is untouched.
Affected surfaces: `POST /references` (`api/reference.py` → `core/pipeline.references_pipeline`)
and the `hadith_references` / `quran_references` SSE events (formatted in `core/utils.py`:
`format_references_as_json` @227, `format_quran_references_as_json` @268).

Storage decision is already SETTLED on the Linear ticket (Postgres sidecar, NOT Pinecone
metadata — 40 KB/vector limit). Review workflow is SETTLED per mentor: MT ships, team
sample-reviews in dev before go-live, environment-level gate, lightweight provenance columns.
See memory `dee63-translation-review-workflow`.
</domain>

<decisions>
## Implementation Decisions

### MT engine (LOCKED)
- Use a **dedicated/personal Claude API key on Sonnet 5 (`claude-sonnet-5`)** for the batch
  translation job — **NOT** the app's environment `ANTHROPIC_API_KEY`.
- The batch script must read its own credential from a **new, dedicated env var** (e.g.
  `TRANSLATION_ANTHROPIC_API_KEY`) and a configurable model (default `claude-sonnet-5`), so
  translation cost/usage stays isolated on the user's personal key and never touches the
  running app's key or `core.chat_models` app model.
- Document that the user sets `TRANSLATION_ANTHROPIC_API_KEY` before running the job.

### Batch MT scope (LOCKED)
- Build the machinery to translate the **ENTIRE reference corpus × 6 languages**, but **DO
  NOT run it** as part of this task. Deliver a re-runnable script + exact start-to-finish
  commands (in the README/CLAUDE.md commands block and the SUMMARY).
- Because the corpus won't be populated in this task, at request time most references will
  have no translation yet → the EN/AR fallback covers them. Full population is a separate
  offline ops run the user triggers later.
- Deterministic tests MUST mock translation — do not call the live MT API in tests.

### Fields to translate (LOCKED)
- Translate **hadith English text (`page_content_en` / `text`)**, **Quran translation
  (`quran_translation`)**, and **tafsir text (`tafsir_text` / tafsir `page_content_en`)**.
- The sidecar schema must therefore handle multiple reference types with different id schemes:
  hadith uses `hadith_id`; Quran/tafsir docs have no single obvious id (metadata has
  surah_name/chapter_number/verses_covered/author/collection/volume). **Planner/executor to
  design a stable key for Quran/tafsir** (e.g. a composite natural key or a synthesized
  deterministic id) — flag this explicitly in the plan.

### Review column (LOCKED)
- Columns: `source` (= `mt`), `translated_at`, `model` (translation model/version), and a
  **nullable `reviewed_at`** timestamp (spot-mark hedge). NOT a full per-row status/reviewer
  state machine.

### Claude's Discretion
- Exact table shape (single unified `reference_translations` table with a `ref_type`
  discriminator + `ref_key` + `language`, vs per-type tables) — planner decides, favoring the
  simplest design that cleanly handles both hadith and Quran/tafsir keys.
- How the batch job **enumerates the full corpus**: iterating the Pinecone indices (list/fetch
  by id) vs translating from an original source dataset if one exists in the repo — planner to
  determine the most reliable enumeration source.
- How `language` is supplied to `POST /references`: add a `language` query param mirroring the
  existing `sect`/`limit` params (`ReferenceRequest` currently only has `user_query`). The SSE
  chat path already carries `target_language` in `ChatState` — thread it into the format
  functions there.
- Alembic migration authored but coordinate the standard `alembic upgrade head` step.
</decisions>

<specifics>
## Specific Ideas

- Join-after-retrieval: keep `retriever` / Pinecone untouched; enrich the formatted reference
  dicts in `core/utils.py` (or a thin service the format functions call) with a keyed Postgres
  lookup of `(ref_key, language)` → translated text, added alongside `text` / `text_ar`.
- New response field naming: e.g. `text_translated` + `translated_language`, so the frontend
  gets EN + AR + selected-language without breaking the existing `text`/`text_ar` contract.
- Batch script lives under `scripts/` (mirrors `scripts/ingest_fiqh.py`); expose a
  `--languages`, `--limit`/`--dry-run`, and `--ref-type` style CLI so a small sample OR the
  full run is possible from the same entrypoint.
</specifics>

<canonical_refs>
## Canonical References

- Linear DEE-67 (storage + review decisions, success criteria).
- Memory `dee63-translation-review-workflow` (mentor's MT-ships / sample-review-in-dev call).
- Existing pattern: `scripts/ingest_fiqh.py` (batch corpus job), `db/models/*` + `alembic/versions/*`
  (model + migration pattern), `core/utils.py` format functions, `core/pipeline.references_pipeline`.
</canonical_refs>
