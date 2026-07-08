"""Join-after-retrieval translation lookup for DEE-67.

This is a Postgres sidecar lookup (`reference_translations` table), NOT a Pinecone
metadata field -- see CONTEXT.md for the storage decision (40 KB/vector Pinecone
metadata limit ruled out storing translations directly on vectors). Retrieval/ranking
is completely untouched; this service is called AFTER retrieval, from the formatter
layer in `core/utils.py`, to merge selected-language translation text onto the
already-formatted reference dicts.

`alookup_translations` has no FastAPI `Depends()` call site -- it's invoked both from
a route function (via `core/pipeline.py`) and from a plain async generator
(`core/pipeline_langgraph.py`), so it opens and closes its own short-lived
`AsyncSessionLocal()` context manager per call rather than accepting an injected
session.
"""
import logging
from typing import Iterable

from sqlalchemy import select

from db.async_session import AsyncSessionLocal
from db.models.reference_translations import ReferenceTranslation

logger = logging.getLogger(__name__)


async def alookup_translations(ref_type: str, ref_keys: Iterable[str], language: str) -> dict[str, str]:
    """Look up translated text for a batch of reference keys.

    Args:
        ref_type: One of "hadith", "quran_translation", "tafsir_text".
        ref_keys: Iterable of reference keys (hadith_id or Pinecone chunk_id).
        language: Target language (lowercase canonical string, e.g. "urdu").

    Returns:
        dict mapping ref_key -> translated_text for rows that exist. Missing keys
        are simply absent from the dict (callers fall back to None). Always returns
        a dict -- never raises -- so a DB error never breaks the surrounding
        request/response flow.
    """
    keys = sorted({str(k) for k in ref_keys if k not in (None, "", "N/A")})
    if not keys:
        return {}

    try:
        async with AsyncSessionLocal() as db:
            stmt = select(ReferenceTranslation).where(
                ReferenceTranslation.ref_type == ref_type,
                ReferenceTranslation.ref_key.in_(keys),
                ReferenceTranslation.language == language,
            )
            result = await db.execute(stmt)
            rows = result.scalars().all()
            return {row.ref_key: row.translated_text for row in rows}
    except Exception:
        logger.error(
            "alookup_translations failed for ref_type=%s language=%s",
            ref_type,
            language,
            exc_info=True,
        )
        return {}
