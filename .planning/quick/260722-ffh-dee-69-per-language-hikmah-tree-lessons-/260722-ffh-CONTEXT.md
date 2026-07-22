# Quick Task 260722-ffh: DEE-69 per-language hikmah tree lessons + quiz — Prior Investigation

**Gathered:** 2026-07-22
**Status:** Ready for planning — decisions LOCKED (do not revisit)

This is a **grounded prior_investigation** handed off from the grab-linear-task session.
The main agent already read the ticket, mapped the code paths, and locked the design
with the user via AskUserQuestion. Treat the decisions below as settled.

<domain>
## Task Boundary

Linear **DEE-69** (sub-issue of DEE-63): serve hikmah-tree lessons **and quiz pages** in
the user's selected language. This is the lesson/quiz sibling of **DEE-67**, which already
shipped the `reference_translations` Postgres sidecar for hadith/Quran/tafsir references.
Mirror that pattern for lesson + quiz + tree-navigation content.

Settled architecture (from the ticket, non-negotiable):
- **No per-language row duplication.** Translations live in a **sidecar table keyed on the
  stable source IDs**; language is applied as a **read-time projection (COALESCE → EN/AR
  fallback)**. Progress + quiz history stay attached to source IDs across language switches.
- MT ships as the production mechanism; review is **coarse + offline** (team sample-reviews
  in dev before go-live), gated at the **environment** level, not per-row. Provenance columns
  only — no per-row status/reviewer state machine. See memory `dee63-translation-review-workflow`.
</domain>

<decisions>
## Implementation Decisions (LOCKED via AskUserQuestion)

### 1. Sidecar schema — ONE field-level table
Single table **`lesson_translations`**, composite PK `(entity_type, entity_id, field, language)`,
one `translated_text` per row. Mirrors DEE-67's `reference_translations` exactly. Adding a new
field or language later is **data-only** (no migration).

Columns:
- `entity_type TEXT` — one of `lesson`, `lesson_content`, `quiz_question`, `quiz_choice`, `hikmah_tree`
- `entity_id BIGINT`
- `field TEXT` — e.g. `title`, `summary`, `content_body`, `prompt`, `explanation`, `choice_text`
- `language TEXT`
- `translated_text TEXT NOT NULL`
- `source TEXT NOT NULL DEFAULT 'mt'`
- `translated_at TIMESTAMP(timezone=True) NOT NULL DEFAULT now()`
- `model TEXT NOT NULL`
- `reviewed_at TIMESTAMP(timezone=True) NULL`
- `source_hash TEXT` — sha256 of the source text at translation time (staleness detection)
- PK: `(entity_type, entity_id, field, language)`

Migration `down_revision = 'reference_translations_001'` (current alembic head — verified by
tracing the revision chain). Add the SQLAlchemy model at `db/models/lesson_translations.py`
mirroring `db/models/reference_translations.py`.

### 2. Translatable surfaces
| entity_type    | source table                 | fields                 |
|----------------|------------------------------|------------------------|
| `lesson`       | `lessons`                    | `title`, `summary`     |
| `lesson_content` | `lesson_content`           | `title`, `content_body`|
| `quiz_question`| `lesson_page_quiz_questions` | `prompt`, `explanation`|
| `quiz_choice`  | `lesson_page_quiz_choices`   | `choice_text`          |
| `hikmah_tree`  | `hikmah_trees`               | `title`, `summary`     |

**EXCLUDED (follow-up):** `lesson_content.content_json` (structured JSONB) and the
`baseline_primer_*` JSONB fields. Do not attempt structured-JSON field-path translation.

### 3. Qur'an carve-out — HARD RULE (religious sensitivity)
Any Qur'anic text embedded in hikmah/lesson content must be **preserved verbatim in its
original script — never machine-translated** (mirrors DEE-67's Quran MT hold-out /
`DISABLED_REF_TYPES`, avoids Arabic→English→target double-translation). Two mechanisms:
1. **Exclude Quran-designated content** from the batch MT job. **PLANNING MUST INCLUDE a
   first task to enumerate the distinct `lesson_content.content_type` and `tags` values** to
   find how Quran content is marked (the main agent could not introspect the live DB). The
   exclusion filter keys on whatever marker that reveals. If no reliable marker exists,
   fall back to mechanism 2 only and note the risk in the SUMMARY.
2. **Harden the system prompt** so the translator preserves any embedded Qur'anic Arabic
   verbatim in its original script and translates only the surrounding prose.

### 4. Staleness / versioning — source_hash
Store `source_hash = sha256(source_text)` at translation time. A translation is **stale**
when `sha256(live source text) != stored source_hash`. The batch job is idempotent: unchanged
source → skip; changed source → re-translate (overwrites via `db.merge`). This satisfies the
ticket's "versioning/sync handled" success criterion cheaply, no extra table.

### 5. MT batch job — reuse the claude-CLI translation logic
New script **`scripts/translate_lessons.py`**. Key difference from
`scripts/translate_references_claude_cli.py`: that script enumerates source text from
**Pinecone**; lesson/quiz content lives in **Postgres**, so this job enumerates via
SQLAlchemy over the five source tables. It **reuses verbatim** the `translate_text()`
claude-CLI subprocess logic (`claude -p --model … --system-prompt … --safe-mode --tools ""
--no-session-persistence`, non-zero/empty-output handling, `CLAUDE_TIMEOUT_SECONDS`) and the
`TRANSLATION_SYSTEM_PROMPT` shape from that file, generalized from "hadith/Quran/tafsir" to
"Islamic educational lesson and quiz content" and hardened for the Qur'an carve-out (decision 3).
Flags mirror the reference script: `--dry-run`, `--limit`, `--languages`, `--model`, plus
`--entity-type {lesson,lesson_content,quiz_question,quiz_choice,hikmah_tree,all}`. Idempotent
`db.merge()` upsert keyed on the composite PK with provenance + `source_hash`. NEVER invoked by
app code/routes/CI — human-triggered only. `SUPPORTED_LANGUAGES = ["arabic","farsi","urdu",
"german","bahasa melayu","french"]` (same 6 as DEE-67).

### 6. Read-time projection — SYNC service
New **`services/lesson_translation_service.py`**. IMPORTANT: unlike DEE-67's
`reference_translation_service.py` (which is **async**, called from the async chat pipeline),
the lesson/quiz/hikmah read paths are **SYNC** (`Depends(get_db)` / `SessionLocal`). So this
service must expose a **sync** batch lookup, e.g.
`lookup_lesson_translations(db, entity_type, entity_ids, language, fields=None) -> dict[(entity_id, field), str]`,
using the injected sync `Session`. Always returns a dict, never raises (log + return {} on error),
mirroring the DEE-67 service's defensive contract.

Apply projection at these read surfaces via an optional `language` query param (default
`"english"` → no projection, return source; canonical lowercase). Missing translation →
fall back to source text (EN/AR):
- `db/routers/lessons.py` — `get_lesson`, `list_lessons` (project `title`, `summary`)
- `db/routers/lesson_content.py` — `get_lesson_content`, `list_lesson_content` (project `title`, `content_body`)
- `db/routers/hikmah_trees.py` — `get_hikmah_tree`, `list_hikmah_trees` (project `title`, `summary`)
- `services/hikmah_quiz_service.py::get_questions_for_page` (LEARNER-facing only) — project
  `prompt`, `explanation`, and each choice `choice_text`. Do NOT translate the admin authoring
  views. Thread a `language` param through `api/hikmah.py`'s quiz-questions endpoint.

Since routers return SQLAlchemy models via `response_model`, the projection likely needs to
overlay translated values onto the returned objects/dicts before serialization (do not mutate
and commit — these are read paths). Choose the least-invasive approach per surface (e.g. build
response dicts, or set attributes on detached instances).

### Claude's Discretion
- Exact helper signatures, where the sha256 helper lives (`core/utils.py` has `decompress_text`;
  a `source_hash` helper could sit alongside), and how to overlay translations onto response
  models per surface.
- Whether to factor the shared `translate_text()` into a helper vs copy it into the new script.
  The repo's established convention is literal copies (the CLI script is itself "a copy of
  translate_references.py"), so **copying is acceptable and lowest-risk**; a shared helper is
  fine too if cleaner. Either way, do not change the reference scripts' behavior.
</decisions>

<specifics>
## Grounded code references (already verified)

- `db/models/lessons.py` — `Lesson`: `title`, `summary`, `language_code` (now = SOURCE lang), `hikmah_tree_id`
- `db/models/lesson_content.py` — `LessonContent`: `lesson_id`, `title`, `content_type`, `content_body`, `content_json`
- `db/models/lesson_page_quiz_questions.py` — `prompt`, `explanation`, `is_active`, `lesson_content_id`
- `db/models/lesson_page_quiz_choices.py` — `question_id`, `choice_key`, `choice_text`, `is_correct`
- `db/models/hikmah_trees.py` — `HikmahTree`: `title`, `summary`
- `db/models/reference_translations.py` + `alembic/versions/20260707_create_reference_translations_table.py` — the DEE-67 pattern to MIRROR (composite-PK sidecar, provenance cols)
- `services/reference_translation_service.py` — DEE-67 ASYNC lookup (mirror the defensive contract, but make the new one SYNC)
- `scripts/translate_references_claude_cli.py` — the claude-CLI `translate_text()` + `TRANSLATION_SYSTEM_PROMPT` + argparse/`run_batch`/`upsert_translation` shape to reuse (source is Pinecone there; use Postgres here)
- `services/hikmah_quiz_service.py::get_questions_for_page` / `_serialize_questions` / `_serialize_question` — learner-facing quiz serialization to project onto
- Router registration: `main.py` lines ~99–112 (lessons, lesson_content, hikmah_trees, hikmah routers)
- Alembic head verified = `reference_translations_001` (chain: … → onboarding_profiles_001 → reference_translations_001)

## Tests to add (mirror existing DEE-67 tests)
- Batch-job unit tests → mirror `tests/test_translate_references.py` (parse_args, entity-type resolution,
  `translate_text` claude-CLI subprocess mock, `upsert_translation` merge, dry-run, `--limit`, live path).
  Add a **Qur'an-preservation test** (Quran-marked content is skipped / not MT'd) and a **staleness test**
  (unchanged source_hash → skipped; changed → re-translated).
- Projection/fallback tests → mirror `tests/test_reference_translations.py` (lookup returns dict,
  missing key falls back to source, `language` threading through the read surfaces).
</specifics>

<canonical_refs>
## Canonical References
- Linear DEE-69: https://linear.app/deen-team/issue/DEE-69 (moved to In Progress this session)
- Sibling shipped work: DEE-67 (`reference_translations`) — the template for everything here
- Mentor decision memory: `dee63-translation-review-workflow` (MT ships; coarse offline dev review; lightweight provenance schema)
- CLAUDE.md religious-sensitivity constraints: never issue fatwas, keep Twelver Shia framing, faithful/literal translation only
</canonical_refs>
