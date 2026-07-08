"""
Offline batch MT job for DEE-67: translate the hadith + quran_translation + tafsir_text
reference corpus into the `reference_translations` Postgres sidecar table, across the
6 canonical languages.

This is a re-runnable, idempotent, human-triggered CLI tool -- it is NEVER invoked by
application code, a route, or CI. It uses a DEDICATED personal Anthropic API key
(`TRANSLATION_ANTHROPIC_API_KEY`), never the app's `ANTHROPIC_API_KEY` / `core.chat_models`,
so translation cost/usage is fully isolated from the running app's key.

Usage:
    export TRANSLATION_ANTHROPIC_API_KEY=sk-ant-...   # personal key, never the app's ANTHROPIC_API_KEY
    python scripts/translate_references.py --dry-run --limit 5   # preview counts, no Anthropic/DB calls
    python scripts/translate_references.py --ref-type hadith --languages urdu --limit 20   # small live sample
    python scripts/translate_references.py   # full corpus x all 6 languages (only after sampling looks correct)

`alembic upgrade head` must be run once (after the reference_translations_001 migration
is authored) before this script's writes will succeed.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

# Add project root to sys.path (required for local imports)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from anthropic import Anthropic
from pinecone import Pinecone

from core.config import DEEN_DENSE_INDEX_NAME, PINECONE_API_KEY, QURAN_DENSE_INDEX_NAME
from core.logging_config import setup_logging
from core.utils import decompress_text
from db.models.reference_translations import ReferenceTranslation
from db.session import SessionLocal

setup_logging()
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #

SUPPORTED_LANGUAGES = ["arabic", "farsi", "urdu", "german", "bahasa melayu", "french"]
REF_TYPE_CHOICES = ["hadith", "quran_translation", "tafsir_text"]
DEFAULT_MODEL = "claude-sonnet-5"

TRANSLATION_SYSTEM_PROMPT = (
    "You are a faithful, literal translator of Twelver Shia Islamic reference texts "
    "(hadith, Quran translations, and tafsir commentary) into {language}. "
    "Preserve all meaning, terminology, honorifics, and the Twelver Shia theological "
    "framing of the source text exactly. Do not add interpretation, commentary, "
    "opinion, or fatwa-like guidance of your own. Do not omit or summarize any part "
    "of the text. Return ONLY the translated text, with no preamble, explanation, or "
    "additional commentary."
)


# ------------------------------------------------------------------ #
# CLI / client setup
# ------------------------------------------------------------------ #

def parse_args(argv=None) -> argparse.Namespace:
    """Parse CLI arguments for the batch translation job."""
    parser = argparse.ArgumentParser(
        description="Batch-translate the hadith/Quran/tafsir reference corpus into reference_translations"
    )
    parser.add_argument(
        "--languages",
        default=",".join(SUPPORTED_LANGUAGES),
        help="Comma-separated list of target languages (default: all 6 canonical languages)",
    )
    parser.add_argument(
        "--ref-type",
        choices=REF_TYPE_CHOICES + ["all"],
        default="all",
        help="Which reference type to translate (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview counts only; never call Anthropic or write to the database",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap number of source items enumerated per ref_type, for sampling",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Translation model/version string (default: {DEFAULT_MODEL})",
    )
    return parser.parse_args(argv)


def _get_translation_client() -> Anthropic:
    """Construct the raw Anthropic SDK client from the DEDICATED translation key.

    Never reads ANTHROPIC_API_KEY (the app's key) -- this isolation is a LOCKED
    requirement (see CONTEXT.md / PLAN.md T-pxt-03).
    """
    api_key = os.getenv("TRANSLATION_ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "TRANSLATION_ANTHROPIC_API_KEY is not set. This batch job requires a dedicated "
            "personal Claude API key, separate from the app's ANTHROPIC_API_KEY, so translation "
            "cost/usage never touches the running app's key. Set TRANSLATION_ANTHROPIC_API_KEY "
            "before running."
        )
    return Anthropic(api_key=api_key)


# ------------------------------------------------------------------ #
# Translation + upsert
# ------------------------------------------------------------------ #

def translate_text(client, *, model: str, text: str, language: str) -> str:
    """Translate a single piece of reference text into `language` via the raw Anthropic SDK."""
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=TRANSLATION_SYSTEM_PROMPT.format(language=language),
        messages=[{"role": "user", "content": text}],
    )
    return response.content[0].text.strip()


def upsert_translation(
    session_factory,
    *,
    ref_type: str,
    ref_key: str,
    language: str,
    translated_text: str,
    model_name: str,
) -> None:
    """Idempotent upsert of a single translated row, keyed by the composite PK."""
    with session_factory() as db:
        row = ReferenceTranslation(
            ref_type=ref_type,
            ref_key=str(ref_key),
            language=language,
            translated_text=translated_text,
            source="mt",
            translated_at=datetime.now(timezone.utc),
            model=model_name,
        )
        db.merge(row)
        db.commit()


# ------------------------------------------------------------------ #
# Corpus enumeration
# ------------------------------------------------------------------ #

def _iter_source_items(
    pc_index, *, namespace: str = "ns1", limit: Optional[int] = None
) -> Iterator[tuple[str, dict]]:
    """Yield (item_id, metadata_dict) tuples by paging through a Pinecone index's
    `.list()` (id pages) and `.fetch()` (id -> vector w/ metadata), stopping once
    `limit` items have been yielded (if `limit` is not None)."""
    yielded = 0
    for page_ids in pc_index.list(namespace=namespace):
        if not page_ids:
            continue
        fetched = pc_index.fetch(ids=page_ids, namespace=namespace)
        for vector_id, vector in fetched.vectors.items():
            yield vector_id, (vector.metadata or {})
            yielded += 1
            if limit is not None and yielded >= limit:
                return


def _extract_text_for_ref_type(ref_type: str, metadata: dict) -> Optional[str]:
    """Extract and decompress the source-language text for a given ref_type from
    raw Pinecone metadata."""
    if ref_type == "hadith":
        raw = metadata.get("text_en", "") or ""
    elif ref_type == "quran_translation":
        raw = metadata.get("english_quran_translation", "") or ""
    elif ref_type == "tafsir_text":
        raw = metadata.get("text_chunk", "") or ""
    else:
        return None
    return decompress_text(raw) or None


def _index_name_for_ref_type(ref_type: str) -> str:
    if ref_type == "hadith":
        return DEEN_DENSE_INDEX_NAME
    return QURAN_DENSE_INDEX_NAME


# ------------------------------------------------------------------ #
# Batch runner
# ------------------------------------------------------------------ #

def run_batch(
    *,
    languages: list[str],
    ref_types: list[str],
    limit: Optional[int],
    dry_run: bool,
    model_name: str,
    translation_client,
    pc_client,
    session_factory,
) -> dict:
    """Run the batch translation job. Returns a nested summary dict
    {ref_type: {language: count}} of items that were (or, on --dry-run, would be)
    translated. One bad item/language never aborts the whole run."""
    summary: dict[str, dict[str, int]] = {rt: {lang: 0 for lang in languages} for rt in ref_types}

    for ref_type in ref_types:
        pc_index = pc_client.Index(_index_name_for_ref_type(ref_type))
        for item_id, metadata in _iter_source_items(pc_index, limit=limit):
            text = _extract_text_for_ref_type(ref_type, metadata)
            if not text:
                continue

            for language in languages:
                try:
                    summary[ref_type][language] += 1
                    if dry_run:
                        continue
                    translated = translate_text(
                        translation_client, model=model_name, text=text, language=language
                    )
                    upsert_translation(
                        session_factory,
                        ref_type=ref_type,
                        ref_key=item_id,
                        language=language,
                        translated_text=translated,
                        model_name=model_name,
                    )
                except Exception:
                    logger.error(
                        "Failed to translate/upsert item_id=%s ref_type=%s language=%s",
                        item_id,
                        ref_type,
                        language,
                        exc_info=True,
                    )

    return summary


def main() -> None:
    args = parse_args()
    languages = [lang.strip().lower() for lang in args.languages.split(",") if lang.strip()]
    ref_types = REF_TYPE_CHOICES if args.ref_type == "all" else [args.ref_type]

    translation_client = None if args.dry_run else _get_translation_client()
    pc_client = Pinecone(api_key=PINECONE_API_KEY)

    summary = run_batch(
        languages=languages,
        ref_types=ref_types,
        limit=args.limit,
        dry_run=args.dry_run,
        model_name=args.model,
        translation_client=translation_client,
        pc_client=pc_client,
        session_factory=SessionLocal,
    )
    logger.info("Batch complete: %s", summary)


if __name__ == "__main__":
    main()
