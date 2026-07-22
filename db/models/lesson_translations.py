"""SQLAlchemy model for the `lesson_translations` Postgres sidecar table (DEE-69).

Stores machine-translated text for hikmah-tree lessons, lesson content pages, and
quiz questions/choices, keyed by a composite primary key of
(entity_type, entity_id, field, language). This is a field-level sidecar mirroring
DEE-67's `db/models/reference_translations.py` pattern exactly: read-time projection
(COALESCE -> EN/AR fallback), no per-language row duplication, progress/quiz-attempt
history stays attached to the source entity IDs across language switches.

`entity_type` / `entity_id` / `field` resolution (the LOCKED translatable-surfaces
table -- see `.planning/quick/260722-ffh-.../260722-ffh-CONTEXT.md` decision 2):
    - entity_type == "lesson"         -> entity_id is `lessons.id`,            field in {"title", "summary"}
    - entity_type == "lesson_content" -> entity_id is `lesson_content.id`,     field in {"title", "content_body"}
    - entity_type == "quiz_question"  -> entity_id is `lesson_page_quiz_questions.id`, field in {"prompt", "explanation"}
    - entity_type == "quiz_choice"    -> entity_id is `lesson_page_quiz_choices.id`,    field == "choice_text"
    - entity_type == "hikmah_tree"    -> entity_id is `hikmah_trees.id`,       field in {"title", "summary"}

`source_hash` is written and read ONLY by `scripts/translate_lessons.py` for
staleness detection (sha256 hex of the source text at translation time; a
translation is stale when the live source text's hash no longer matches). The
read-time projection service (`services/lesson_translation_service.py`) never reads
this column.

Qur'an-marker investigation finding (DEE-69 Task 1, required before any structural
exclusion filter could be considered -- see LOCKED decision 3's fallback clause):
there is NO reliable row-level marker to key a Qur'an-content exclusion filter on at
the `lesson_content` grain. Evidence: `scripts/hikmah_generation/upsert_hikmah_tree.py`
defines `VALID_CONTENT_TYPES = {"text", "quiz"}` -- the ingestion validator only ever
permits these two `content_type` values, with no `"quran"` or similar designation.
`LessonContent` (this table's `lesson_content` entity_type) has NO `tags` column at
all -- only `lessons.tags` and `hikmah_trees.tags` exist, and those are topic-level
tags on the PARENT lesson/tree (e.g. `["tajweed", "quran"]`), not a per-row marker of
embedded Qur'anic text within a specific page's `content_body`. Qur'anic verses are
generated inline within `content_body`/`explanation` prose (mixed with surrounding
commentary), not isolated in dedicated rows. Consequently, mechanism 1 (structural
exclusion) is NOT APPLICABLE here; mechanism 2 -- a hardened translator system prompt
instructing verbatim preservation of embedded Qur'anic Arabic (see
`scripts/translate_lessons.py`'s `TRANSLATION_SYSTEM_PROMPT`) -- is the SOLE operative
Qur'an-preservation safeguard for this job. This is a documented residual risk, not a
structural guarantee (T-ffh-03 in this plan's threat model).
"""
from sqlalchemy import BigInteger, Column, Text, TIMESTAMP
from sqlalchemy.sql import func

from ..session import Base


class LessonTranslation(Base):
    __tablename__ = "lesson_translations"

    entity_type = Column(Text, primary_key=True, nullable=False)
    entity_id = Column(BigInteger, primary_key=True, nullable=False)
    field = Column(Text, primary_key=True, nullable=False)
    language = Column(Text, primary_key=True, nullable=False)
    translated_text = Column(Text, nullable=False)
    source = Column(Text, nullable=False, server_default="mt")
    translated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    model = Column(Text, nullable=False)
    reviewed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    source_hash = Column(Text, nullable=True)
