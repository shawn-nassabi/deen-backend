from langchain_core.documents import Document
import asyncio
import traceback
import base64
import gzip
import hashlib
from typing import Optional

from services import reference_translation_service

def compact_format_references(retrieved_docs: list, max_chars: int = 1500) -> str:
    """
    Formats retrieved hadiths and Quranic references for LLM-friendly Markdown output,
    aligned with the updated JSON structure used in `format_references_as_json`,
    in a short compact form to reduce LLM token usage.
    """
    print("INSIDE format_references")
    header = "\n\n**Retrieved References:**\n"
    if not retrieved_docs:
        return header + "\n(No relevant references were found in the database.)"

    lines = [header]

    grouped_docs = {
        "Shia Hadith Sources": [],
        "Sunni Hadith Sources": [],
        "Quran and Tafsir Sources": [],
    }

    for doc in retrieved_docs:
        metadata = doc.get("metadata", {}) if isinstance(doc, dict) else getattr(doc, "metadata", {}) or {}
        if _is_quran_doc(metadata):
            grouped_docs["Quran and Tafsir Sources"].append(doc)
            continue

        sect = str(metadata.get("sect", "")).strip().lower()
        if sect == "sunni":
            grouped_docs["Sunni Hadith Sources"].append(doc)
        else:
            grouped_docs["Shia Hadith Sources"].append(doc)

    reference_idx = 1
    for section_title, docs in grouped_docs.items():
        if not docs:
            continue

        lines.append(f"\n**{section_title}:**")
        for doc in docs:
            try:
                if isinstance(doc, dict):
                    metadata = doc.get("metadata", {}) or {}
                    page_content_en = doc.get("page_content_en", "") or ""
                    quran_translation = doc.get("quran_translation", "") or ""
                else:
                    metadata = getattr(doc, "metadata", {}) or {}
                    page_content_en = getattr(doc, "page_content_en", "") or getattr(doc, "page_content", "") or ""
                    quran_translation = getattr(doc, "quran_translation", "") or ""

                if _is_quran_doc(metadata):
                    block = _format_quran_reference(reference_idx, metadata, page_content_en, quran_translation, max_chars)
                else:
                    block = _format_hadith_reference(reference_idx, metadata, page_content_en, max_chars)

                lines.append("\n".join([ln for ln in block if ln is not None]))
                reference_idx += 1
            except Exception as e:
                print(f"Error formatting a reference: {e}")
                traceback.print_exc()
                lines.append("**Error formatting a reference. Skipping this item.**")

    return "\n".join(lines)


def _is_quran_doc(metadata):
    return metadata.get("Type") == "Tafsir" or "surah_name" in metadata


def _format_hadith_reference(idx, metadata, page_content_en, max_chars):
    # Token-cost DEE-60 Phase 2: citation-critical fields only. Dropped from
    # the LLM prompt (still in the frontend reference JSON): Hadith ID, URL,
    # Language, Grade (AR). The generator's citation contract needs book /
    # author / volume / book# / chapter / hadith# / reference / grade / sect.
    author         = metadata.get("author", "N/A")
    volume         = metadata.get("volume", "N/A")
    book_number    = metadata.get("book_number", "N/A")
    book_title     = metadata.get("book_title", "N/A")
    chapter_number = metadata.get("chapter_number", "N/A")
    chapter_title  = metadata.get("chapter_title", "N/A")
    collection     = metadata.get("collection", "N/A")
    grade_en       = metadata.get("grade_en", "N/A")
    hadith_no      = metadata.get("hadith_no", "N/A")
    sect           = metadata.get("sect", "N/A")
    reference      = metadata.get("reference", "N/A")

    text_en = page_content_en.strip() if page_content_en else "No text available"
    elipses = "...." if len(text_en) > max_chars else ""

    return [
        "---",
        f"**Reference {idx}:**",
        f"- **Book Title:** {book_title}",
        f"- **Author:** {author}",
        f"- **Volume:** {volume}",
        f"- **Book Number:** {book_number}",
        f"- **Chapter:** {chapter_number} — {chapter_title}",
        f"- **Collection:** {collection}",
        f"- **Hadith Number:** {hadith_no}",
        f"- **Reference:** {reference}",
        f"- **Grade:** {grade_en}",
        f"- **Sect:** {sect}",
        f"- **Text (EN):** \"{text_en[:max_chars] + elipses}\"",
        "---",
    ]


def _format_quran_reference(idx, metadata, tafsir_text, quran_translation, max_chars):
    surah_name     = metadata.get("surah_name", "N/A")
    title          = metadata.get("title", "N/A")
    chapter_number = metadata.get("chapter_number", "N/A")
    verses_covered = metadata.get("verses_covered", "N/A")
    author         = metadata.get("author", "N/A")
    collection     = metadata.get("collection", "N/A")
    volume         = metadata.get("volume", "N/A")
    sect           = metadata.get("sect", "N/A")

    tafsir = tafsir_text.strip() if tafsir_text else "No tafsir text available"
    translation = quran_translation.strip() if quran_translation else ""

    # Token-cost DEE-60 Phase 2: cap combined verse+tafsir text at ~2,200
    # chars per doc (was up to 2 x max_chars = 3,000). Verses are quoted
    # verbatim in answers, so they get the smaller fixed share; tafsir is
    # paraphrased commentary and tolerates truncation better.
    translation_cap = 900
    tafsir_cap = 1300
    tafsir_elipses = "...." if len(tafsir) > tafsir_cap else ""

    block = [
        "---",
        f"**Reference {idx} (Quran/Tafsir):**",
        f"- **Surah:** {surah_name} ({title})",
        f"- **Chapter Number:** {chapter_number}",
        f"- **Verses:** {verses_covered}",
        f"- **Tafsir Collection:** {collection}",
        f"- **Author:** {author}",
        f"- **Volume:** {volume}",
        f"- **Sect:** {sect}",
    ]
    if translation:
        trans_elipses = "...." if len(translation) > translation_cap else ""
        block.append(f"- **Quran Translation:** \"{translation[:translation_cap] + trans_elipses}\"")
    block.append(f"- **Tafsir Text:** \"{tafsir[:tafsir_cap] + tafsir_elipses}\"")
    block.append("---")
    return block


def format_references(retrieved_docs: list) -> str:
    """
    Formats retrieved hadiths and Quranic references for LLM-friendly Markdown output,
    aligned with the updated JSON structure used in `format_references_as_json`.
    """
    print("INSIDE format_references")
    header = "\n\n**Retrieved References:**\n"
    if not retrieved_docs:
        return header + "\n(No relevant references were found in the database.)"

    lines = [header]

    for idx, doc in enumerate(retrieved_docs, start=1):
        try:
            # Accept either plain dicts or LangChain Documents
            if isinstance(doc, dict):
                metadata = doc.get("metadata", {}) or {}
                page_content_en = doc.get("page_content_en", "") or ""
                page_content_ar = doc.get("page_content_ar", "") or ""
            else:
                # Fallback for LangChain Document objects
                metadata = getattr(doc, "metadata", {}) or {}
                # Your pipeline seems to store bilingual content separately; keep that behavior
                page_content_en = getattr(doc, "page_content_en", "") or getattr(doc, "page_content", "") or ""
                page_content_ar = getattr(doc, "page_content_ar", "") or ""

            author         = metadata.get("author", "N/A")
            volume         = metadata.get("volume", "N/A")
            book_number    = metadata.get("book_number", "N/A")
            book_title     = metadata.get("book_title", "N/A")
            chapter_number = metadata.get("chapter_number", "N/A")
            chapter_title  = metadata.get("chapter_title", "N/A")
            collection     = metadata.get("collection", "N/A")
            grade_ar       = metadata.get("grade_ar", "N/A")
            grade_en       = metadata.get("grade_en", "N/A")
            hadith_id      = metadata.get("hadith_id", "N/A")
            hadith_no      = metadata.get("hadith_no", "N/A")
            hadith_url     = metadata.get("hadith_url", "N/A")
            lang           = metadata.get("lang", "N/A")
            sect           = metadata.get("sect", "N/A")
            reference      = metadata.get("reference", "N/A")

            text_en = page_content_en.strip() if page_content_en else "No text available"
            text_ar = page_content_ar.strip() if page_content_ar else "No Arabic text available"

            block = [
                "--------------------------------------",
                f"**Reference {idx}:**",
                f"- **Book Title:** {book_title}",
                f"- **Author:** {author}",
                f"- **Volume:** {volume}",
                f"- **Book Number:** {book_number}",
                f"- **Chapter Number:** {chapter_number}",
                f"- **Chapter Title:** {chapter_title}",
                f"- **Collection:** {collection}",
                f"- **Hadith Number:** {hadith_no}",
                f"- **Hadith ID:** {hadith_id}",
                f"- **Reference:** {reference}",
                f"- **Grade (EN):** {grade_en}",
                f"- **Grade (AR):** {grade_ar}",
                f"- **Language:** {lang}",
                f"- **Sect:** {sect}",
                f"- **URL:** {hadith_url}" if hadith_url and hadith_url != "N/A" else None,
                f"- **Text (EN):** \"{text_en}\"",
                f"- **Text (AR):** \"{text_ar}\"",
                "---------------------------------------------",
            ]
            # Filter out Nones (e.g., URL line when missing)
            lines.append("\n".join([ln for ln in block if ln is not None]))

        except Exception as e:
            print(f"Error formatting a reference: {e}")
            traceback.print_exc()
            lines.append("**Error formatting a reference. Skipping this item.**")

    return "\n".join(lines)


def format_references_as_json(retrieved_docs: list):
    """
    Formats retrieved hadiths and Quranic references into JSON format
    """
    print("INSIDE format_references_as_json")
    result = {"references": []}
    formatted_references = []
    try:
        if not retrieved_docs:
            return result

        for doc in retrieved_docs:
            reference = {
                "author": doc['metadata'].get("author", "N/A"),
                "volume": doc['metadata'].get("volume", "N/A"),
                "book_number": doc['metadata'].get("book_number", "N/A"),
                "book_title": doc['metadata'].get("book_title", "N/A"),
                "chapter_number": doc['metadata'].get("chapter_number", "N/A"),
                "chapter_title": doc['metadata'].get("chapter_title", "N/A"),
                "collection": doc['metadata'].get("collection", "N/A"),
                "grade_ar": doc['metadata'].get("grade_ar", "N/A"),
                "grade_en": doc['metadata'].get("grade_en", "N/A"),
                "hadith_id": doc['metadata'].get("hadith_id", "N/A"),
                "hadith_no": doc['metadata'].get("hadith_no", "N/A"),
                "hadith_url": doc['metadata'].get("hadith_url", "N/A"),
                "lang": doc['metadata'].get("lang", "N/A"),
                "sect": doc['metadata'].get("sect", "N/A"),
                "reference": doc['metadata'].get("reference", "N/A"),
                "text": doc.get('page_content_en', '').strip() if doc.get('page_content_en') else "No text available",
                "text_ar": doc.get('page_content_ar', '').strip() if doc.get('page_content_ar') else "No Arabic text available"
            }
            formatted_references.append(reference)
    except Exception as e:
        print(f"Error formatting references: {e}")
        traceback.print_exc()
        return result

    result = formatted_references

    return result

def format_quran_references_as_json(quran_docs: list) -> list:
    """
    Formats Quran/Tafsir documents into JSON with their native fields.
    Used to produce the separate quran_references SSE event.
    """
    result = []
    try:
        for doc in quran_docs:
            md = doc.get("metadata", {}) or {}
            result.append({
                "surah_name": md.get("surah_name", "N/A"),
                "title": md.get("title", "N/A"),
                "chapter_number": md.get("chapter_number", "N/A"),
                "verses_covered": md.get("verses_covered", "N/A"),
                "starting_verse": md.get("starting_verse", "N/A"),
                "ending_verse": md.get("ending_verse", "N/A"),
                "author": md.get("author", "N/A"),
                "collection": md.get("collection", "N/A"),
                "volume": md.get("volume", "N/A"),
                "sect": md.get("sect", "N/A"),
                "quran_translation": doc.get("quran_translation", ""),
                "tafsir_text": doc.get("page_content_en", ""),
            })
    except Exception as e:
        print(f"Error formatting Quran references: {e}")
        traceback.print_exc()
    return result


async def aformat_references_as_json(retrieved_docs: list, language: Optional[str] = None) -> list:
    """Async wrapper around `format_references_as_json` that additionally joins in a
    selected-language translation (DEE-67), sourced from the `reference_translations`
    Postgres sidecar table -- NOT from Pinecone metadata. Existing `text`/`text_ar`
    fields are left untouched; the new `text_translated`/`translated_language` fields
    are additive.

    When `language` is unset or "english", no DB lookup is performed -- both new
    fields are simply set to None.
    """
    base = format_references_as_json(retrieved_docs)
    normalized_language = (language or "").strip().lower()

    if not normalized_language or normalized_language == "english":
        for ref in base:
            ref["text_translated"] = None
            ref["translated_language"] = None
        return base

    hadith_ids = [ref.get("hadith_id") for ref in base]
    translations = await reference_translation_service.alookup_translations(
        "hadith", hadith_ids, normalized_language
    )
    for ref in base:
        ref["text_translated"] = translations.get(str(ref.get("hadith_id")))
        ref["translated_language"] = normalized_language
    return base


async def aformat_quran_references_as_json(quran_docs: list, language: Optional[str] = None) -> list:
    """Async wrapper around `format_quran_references_as_json` that additionally joins
    in selected-language translations (DEE-67) for both the Quran verse translation
    and the tafsir commentary, keyed by the Pinecone vector `chunk_id`.

    Because the underlying sync formatter's single try/except wraps its whole loop
    (it can return a shorter list than `quran_docs` on error), `chunk_ids` is built
    with a defensive slice to keep it aligned 1:1 with `base`.
    """
    base = format_quran_references_as_json(quran_docs)
    chunk_ids = [doc.get("chunk_id") for doc in (quran_docs or [])[: len(base)]]
    normalized_language = (language or "").strip().lower()

    if not normalized_language or normalized_language == "english":
        for ref in base:
            ref["quran_translation_translated"] = None
            ref["tafsir_text_translated"] = None
            ref["translated_language"] = None
        return base

    translation_lookup, tafsir_lookup = await asyncio.gather(
        reference_translation_service.alookup_translations("quran_translation", chunk_ids, normalized_language),
        reference_translation_service.alookup_translations("tafsir_text", chunk_ids, normalized_language),
    )
    for ref, chunk_id in zip(base, chunk_ids):
        ref["quran_translation_translated"] = translation_lookup.get(str(chunk_id))
        ref["tafsir_text_translated"] = tafsir_lookup.get(str(chunk_id))
        ref["translated_language"] = normalized_language
    return base


def format_fiqh_references_as_json(fiqh_docs: list) -> list:
    """
    Formats fiqh documents into citation JSON for the fiqh_references SSE event.
    Each entry carries book, chapter, section, and ruling_number from chunk metadata.
    Used by pipeline_langgraph.py after streaming a fiqh answer.
    """
    result = []
    try:
        for doc in fiqh_docs:
            md = doc.get("metadata", {}) or {}
            result.append({
                "book": md.get("source_book", "Islamic Laws"),
                "chapter": md.get("chapter", ""),
                "section": md.get("section", ""),
                "ruling_number": md.get("ruling_number", ""),
            })
    except Exception as e:
        print(f"Error formatting fiqh references: {e}")
        traceback.print_exc()
    return result


def stream_message(message: str):
    """
    A simple generator that yields the given message.
    """
    yield message


def compress_text(text: str) -> str:
    """Compress and encode text using gzip and base64."""
    if not text:
        return ""
    compressed = gzip.compress(text.encode("utf-8"))
    return base64.b64encode(compressed).decode("utf-8")


def decompress_text(compressed_text: str) -> str:
    """Decode and decompress base64-encoded gzip text."""
    if not compressed_text:
        return ""
    compressed_bytes = base64.b64decode(compressed_text.encode("utf-8"))
    return gzip.decompress(compressed_bytes).decode("utf-8")


def source_text_hash(text: str) -> str:
    """Deterministic sha256 hex digest of source text, used by scripts/translate_lessons.py
    (DEE-69) to detect when a translated row is stale relative to its live source text.
    Never raises -- falsy input hashes as the empty string."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
