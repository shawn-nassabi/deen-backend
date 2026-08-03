"""SQLAlchemy model for the `reference_translations` Postgres sidecar table (DEE-67).

Stores machine-translated text for hadith / Quran / tafsir references, keyed by a
composite primary key of (ref_type, ref_key, language). This is a join-after-retrieval
sidecar -- Pinecone metadata and the retrieval/ranking path are untouched; translations
are looked up separately by `services/reference_translation_service.py` and merged onto
the formatted reference dicts in `core/utils.py`.

`ref_key` resolution by `ref_type` (see CONTEXT.md "multiple reference types with
different id schemes" concern):
    - ref_type == "hadith"            -> ref_key is the hadith's `hadith_id`
                                          (already present in Pinecone hadith metadata)
    - ref_type == "quran_translation" -> ref_key is the Pinecone vector `chunk_id`
    - ref_type == "tafsir_text"       -> ref_key is the same Pinecone vector `chunk_id`

`quran_translation` and `tafsir_text` deliberately share the same `ref_key` (the chunk's
Pinecone vector id) but are stored as separate rows/ref_types, because a single Quran/
tafsir chunk has two independently-translatable fields (the Quran verse translation and
the tafsir commentary). Quran/tafsir chunks already have a stable, existing Pinecone
vector ID, so no synthesized composite key is needed.
"""
from sqlalchemy import Column, Text, TIMESTAMP
from sqlalchemy.sql import func

from ..session import Base


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
