"""Sync read-time projection lookup for DEE-69.

This is the lesson/quiz/hikmah-tree sibling of `services/reference_translation_service.py`
(DEE-67), mirroring its defensive "never raise, always return a dict/no-op" contract.
Unlike that service, this one is SYNC using an injected `Session` -- the
lessons/lesson_content/hikmah_trees/hikmah routers all use `Depends(get_db)`, not an
async session.

Called from the read-time projection call sites (`db/routers/lessons.py`,
`db/routers/lesson_content.py`, `db/routers/hikmah_trees.py`,
`services/hikmah_quiz_service.py::get_questions_for_page`) AFTER the source rows have
already been fetched -- translations are overlaid onto the returned objects/dicts in
place, never written back to the database.
"""
import logging
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from db.models.lesson_translations import LessonTranslation

logger = logging.getLogger(__name__)


def lookup_lesson_translations(
    db: Session,
    entity_type: str,
    entity_ids: Iterable[int],
    language: str,
    fields: Optional[Iterable[str]] = None,
) -> Dict[Tuple[int, str], str]:
    """Look up translated text for a batch of entity ids.

    Returns a dict mapping (entity_id, field) -> translated_text for rows that
    exist. Missing keys are simply absent from the dict (callers fall back to the
    source value). Always returns a dict -- never raises -- so a DB error never
    breaks the surrounding request/response flow.
    """
    ids = sorted({int(entity_id) for entity_id in entity_ids if entity_id is not None})
    if not ids:
        return {}

    try:
        query = db.query(LessonTranslation).filter(
            LessonTranslation.entity_type == entity_type,
            LessonTranslation.entity_id.in_(ids),
            LessonTranslation.language == language,
        )
        if fields is not None:
            query = query.filter(LessonTranslation.field.in_(list(fields)))
        rows = query.all()
        return {(row.entity_id, row.field): row.translated_text for row in rows}
    except Exception:
        logger.error(
            "lookup_lesson_translations failed for entity_type=%s language=%s",
            entity_type,
            language,
            exc_info=True,
        )
        return {}


def apply_translations(
    db: Session,
    entity_type: str,
    objects: List,
    *,
    fields: Iterable[str],
    language: str = "english",
    id_attr: str = "id",
) -> None:
    """Overlay translated field values onto `objects` in place via `setattr`.

    No-op (zero DB calls) when `language` is empty/"english" or `objects` is
    empty -- this is the zero-added-DB-calls guarantee for the default/English
    case. Missing translation rows leave the object's existing source value
    untouched (the EN/AR fallback).
    """
    normalized = (language or "").strip().lower()
    if not normalized or normalized == "english" or not objects:
        return

    fields = list(fields)
    ids = [getattr(obj, id_attr) for obj in objects]
    translations = lookup_lesson_translations(db, entity_type, ids, normalized, fields=fields)
    if not translations:
        return

    for obj in objects:
        obj_id = getattr(obj, id_attr)
        for field in fields:
            value = translations.get((obj_id, field))
            if value is not None:
                setattr(obj, field, value)
