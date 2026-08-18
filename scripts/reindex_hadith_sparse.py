"""
Rebuild the hadith sparse Pinecone index using a corpus-fit BM25 encoder (DEE-21).

Why this exists
---------------
The hadith sparse path historically encoded queries with a TF-IDF vectorizer that
was ``fit_transform``-ed on the *single incoming query*. That produces a vocabulary
anchored to that one query, so its term indices are not comparable to whatever
vectors live in the sparse index. This script fixes the document side: it fits one
BM25 encoder on the whole hadith corpus, persists it, and re-upserts the sparse
index using ``encode_documents``. Query time then uses ``encode_queries`` from the
same persisted encoder, so both sides share a vocabulary.

The hadith corpus is not in this repo (unlike fiqh's PDF) — it lives in the dense
Pinecone index. So we enumerate the dense index, decompress ``text_en`` from each
vector's metadata, and use that as the corpus.

Design notes
------------
* Three phases, with an on-disk JSONL cache between them, so peak memory holds
  only the plain texts rather than every vector's full metadata.
* Metadata is copied verbatim from the dense vector. This is deliberate: the
  reranker keys on ``hadith_id`` and retrieval filters on ``sect``, so dropping
  or reshaping metadata would silently break sect filtering and the merge step.
* Writes only to the sparse index (default: DEEN_SPARSE_BM25_INDEX_NAME, a
  staging index). The dense index is read-only here.

Usage
-----
    python scripts/reindex_hadith_sparse.py --dry-run            # inspect, no writes
    python scripts/reindex_hadith_sparse.py --limit 200          # small dev pass
    python scripts/reindex_hadith_sparse.py --encoder-only       # fit + dump encoder
    python scripts/reindex_hadith_sparse.py                      # full reindex
"""
from __future__ import annotations

import argparse
import json
import logging
import ssl
import sys
import time
from pathlib import Path
from typing import Any, Iterator

# Add project root to sys.path (required for local imports)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import nltk
from pinecone import Pinecone, ServerlessSpec
from pinecone_text.sparse import BM25Encoder

from core.config import (
    DEEN_DENSE_INDEX_NAME,
    DEEN_SPARSE_BM25_INDEX_NAME,
    DEEN_SPARSE_BM25_NAMESPACE,
    DEEN_SPARSE_INDEX_NAME,
    PINECONE_API_KEY,
)
from core.logging_config import setup_logging
from core.utils import decompress_text

# Imported for single-source-of-truth on the encoder path. Note this pulls in the
# sentence-transformer at import time (~20s); harmless for a one-off script.
from modules.embedding.embedder import HADITH_BM25_ENCODER_PATH

setup_logging()
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #

# Source namespace on the dense index. The BM25 vectors are written to a
# *separate* namespace (default "bm25") so they can live in the existing sparse
# index without disturbing the current data — Pinecone projects cap the number
# of serverless indexes, and namespaces are fully isolated from each other.
NAMESPACE = "ns1"
CORPUS_CACHE_PATH = project_root / "data" / "hadith_corpus_cache.jsonl"
FETCH_BATCH_SIZE = 100
UPSERT_BATCH_SIZE = 100
TEXT_METADATA_KEY = "text_en"


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _md_of(vector: Any) -> dict:
    """Read metadata off a Pinecone vector, tolerating dict or SDK-object shape.

    The SDK returns model objects, not dicts — assuming one shape is exactly the
    bug that made sparse retrieval a no-op in the reranker.
    """
    if isinstance(vector, dict):
        return vector.get("metadata") or {}
    return getattr(vector, "metadata", None) or {}


def _vectors_of(fetch_response: Any) -> dict:
    """Read the id -> vector mapping off a Pinecone fetch response."""
    if isinstance(fetch_response, dict):
        return fetch_response.get("vectors") or {}
    return getattr(fetch_response, "vectors", None) or {}


def _extract_text(metadata: dict) -> str:
    """Return decompressed English text for a hadith vector, or '' if unusable."""
    raw = metadata.get(TEXT_METADATA_KEY) or ""
    if not raw:
        return ""
    try:
        return (decompress_text(raw) or "").strip()
    except Exception:
        # Some records may be stored uncompressed; fall back to the raw value.
        return str(raw).strip()


# ------------------------------------------------------------------ #
# Phase A — enumerate the dense index into a JSONL cache
# ------------------------------------------------------------------ #

def build_corpus_cache(
    pc: Pinecone,
    *,
    limit: int | None = None,
    cache_path: Path = CORPUS_CACHE_PATH,
) -> int:
    """Enumerate the dense hadith index and write {id, text, metadata} to JSONL.

    Returns the number of usable records written.
    """
    if not DEEN_DENSE_INDEX_NAME:
        raise ValueError("DEEN_DENSE_INDEX_NAME is not set in .env")

    dense_idx = pc.Index(DEEN_DENSE_INDEX_NAME)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped_no_text = 0
    seen = 0

    logger.info("Enumerating dense index %s (namespace=%s)...", DEEN_DENSE_INDEX_NAME, NAMESPACE)
    with cache_path.open("w", encoding="utf-8") as fh:
        for id_batch in dense_idx.list(namespace=NAMESPACE):
            # `list()` yields a list of ids per page; guard against a bare string.
            ids = [id_batch] if isinstance(id_batch, str) else list(id_batch)
            if not ids:
                continue

            for chunk_start in range(0, len(ids), FETCH_BATCH_SIZE):
                chunk_ids = ids[chunk_start : chunk_start + FETCH_BATCH_SIZE]
                response = dense_idx.fetch(ids=chunk_ids, namespace=NAMESPACE)

                for vector_id, vector in _vectors_of(response).items():
                    seen += 1
                    metadata = dict(_md_of(vector))
                    text = _extract_text(metadata)
                    if not text:
                        skipped_no_text += 1
                        continue

                    fh.write(
                        json.dumps(
                            {"id": vector_id, "text": text, "metadata": metadata},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    written += 1

                    if limit is not None and written >= limit:
                        logger.info("Reached --limit %d; stopping enumeration.", limit)
                        logger.info(
                            "Cached %d records (seen=%d, skipped_no_text=%d) -> %s",
                            written, seen, skipped_no_text, cache_path,
                        )
                        return written

            logger.info("  cached %d records so far...", written)

    logger.info(
        "Cached %d records (seen=%d, skipped_no_text=%d) -> %s",
        written, seen, skipped_no_text, cache_path,
    )
    return written


def iter_cache(cache_path: Path = CORPUS_CACHE_PATH) -> Iterator[dict]:
    """Stream records back out of the JSONL cache."""
    with cache_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


# ------------------------------------------------------------------ #
# Phase B — fit and persist the BM25 encoder
# ------------------------------------------------------------------ #

def fit_encoder(cache_path: Path = CORPUS_CACHE_PATH) -> BM25Encoder:
    """Fit BM25 on the cached corpus and persist it to HADITH_BM25_ENCODER_PATH."""
    logger.info("Downloading NLTK data (required by BM25Encoder)...")
    ssl._create_default_https_context = ssl._create_unverified_context  # macOS workaround
    nltk.download("stopwords", quiet=True)
    nltk.download("punkt_tab", quiet=True)

    texts = [record["text"] for record in iter_cache(cache_path)]
    if not texts:
        raise ValueError(f"No texts found in {cache_path}; run enumeration first.")

    logger.info("Fitting BM25 encoder on %d documents...", len(texts))
    encoder = BM25Encoder()
    encoder.fit(texts)

    encoder_path = Path(HADITH_BM25_ENCODER_PATH)
    encoder_path.parent.mkdir(parents=True, exist_ok=True)
    encoder.dump(str(encoder_path))
    logger.info("BM25 encoder persisted to %s", encoder_path)
    return encoder


# ------------------------------------------------------------------ #
# Phase C — encode documents and upsert to the sparse index
# ------------------------------------------------------------------ #

def ensure_sparse_index(pc: Pinecone, index_name: str) -> None:
    """Create the sparse index if absent, mirroring the existing indexes' region.

    Note: Pinecone projects cap serverless index count. If creation is refused,
    target the existing sparse index with a dedicated --namespace instead.
    """
    existing_names = [i.name for i in pc.list_indexes()]
    if index_name in existing_names:
        logger.info("Sparse index already exists: %s", index_name)
        return

    if DEEN_DENSE_INDEX_NAME and DEEN_DENSE_INDEX_NAME in existing_names:
        spec = pc.describe_index(DEEN_DENSE_INDEX_NAME).spec.serverless
        cloud, region = spec.cloud, spec.region
        logger.info("Using cloud=%s region=%s (from %s)", cloud, region, DEEN_DENSE_INDEX_NAME)
    else:
        cloud, region = "aws", "us-east-1"
        logger.warning("Could not read existing index spec; defaulting to %s/%s", cloud, region)

    logger.info("Creating sparse index: %s (dotproduct)", index_name)
    pc.create_index(
        name=index_name,
        metric="dotproduct",
        vector_type="sparse",  # no dimension parameter for sparse indexes
        spec=ServerlessSpec(cloud=cloud, region=region),
    )
    logger.info("Waiting for sparse index to become ready...")
    time.sleep(10)


def upsert_sparse(
    pc: Pinecone,
    encoder: BM25Encoder,
    index_name: str,
    *,
    namespace: str,
    cache_path: Path = CORPUS_CACHE_PATH,
) -> int:
    """BM25-encode cached documents and upsert them to the sparse index.

    Vector ids and metadata are preserved verbatim from the dense index so that
    sect filtering and the reranker's hadith_id lookup keep working.
    """
    sparse_idx = pc.Index(index_name)
    batch: list[dict] = []
    total = 0

    def flush(records: list[dict]) -> int:
        if not records:
            return 0
        sparse_vecs = encoder.encode_documents([r["text"] for r in records])
        vectors = [
            {
                "id": record["id"],
                "sparse_values": {
                    "indices": list(sv["indices"]),
                    "values": list(sv["values"]),
                },
                "metadata": record["metadata"],
            }
            for record, sv in zip(records, sparse_vecs)
            # A document whose terms are all out-of-vocabulary yields an empty
            # vector; Pinecone rejects those, so drop them rather than fail the batch.
            if sv.get("indices")
        ]
        if not vectors:
            return 0
        sparse_idx.upsert(vectors=vectors, namespace=namespace)
        return len(vectors)

    for record in iter_cache(cache_path):
        batch.append(record)
        if len(batch) >= UPSERT_BATCH_SIZE:
            total += flush(batch)
            batch = []
            logger.info("Upserted %d vectors to %s/%s...", total, index_name, namespace)

    total += flush(batch)
    logger.info("Upsert complete: %d vectors in %s namespace=%s", total, index_name, namespace)
    return total


# ------------------------------------------------------------------ #
# CLI entry point
# ------------------------------------------------------------------ #

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild the hadith sparse Pinecone index with a corpus-fit BM25 encoder"
    )
    parser.add_argument("--dry-run", action="store_true",
                       help="Enumerate and report only; no encoder dump, no writes")
    parser.add_argument("--encoder-only", action="store_true",
                       help="Enumerate and fit/dump the encoder; skip the sparse upsert")
    parser.add_argument("--limit", type=int, default=None,
                       help="Only process the first N usable vectors (dev shortcut)")
    parser.add_argument("--index-name", default=None,
                       help="Target sparse index (default: DEEN_SPARSE_BM25_INDEX_NAME, "
                            "falling back to the existing DEEN_SPARSE_INDEX_NAME)")
    parser.add_argument("--namespace", default=None,
                       help="Namespace to write BM25 vectors into "
                            f"(default: DEEN_SPARSE_BM25_NAMESPACE)")
    parser.add_argument("--skip-fit", action="store_true",
                       help="Reuse the already-persisted encoder instead of refitting")
    parser.add_argument("--skip-enumerate", action="store_true",
                       help="Reuse the existing JSONL cache instead of re-reading Pinecone")
    args = parser.parse_args()

    if not PINECONE_API_KEY:
        raise ValueError("PINECONE_API_KEY is not set in .env")

    pc = Pinecone(api_key=PINECONE_API_KEY)

    # --- Phase A ---
    if args.skip_enumerate:
        if not CORPUS_CACHE_PATH.is_file():
            raise ValueError(f"--skip-enumerate given but {CORPUS_CACHE_PATH} does not exist")
        count = sum(1 for _ in iter_cache())
        logger.info("Reusing cache at %s (%d records)", CORPUS_CACHE_PATH, count)
    else:
        count = build_corpus_cache(pc, limit=args.limit)

    if count == 0:
        logger.error("No usable documents found — aborting.")
        return

    if args.dry_run:
        logger.info("--- DRY RUN: first 3 cached records ---")
        for record in list(iter_cache())[:3]:
            metadata = record["metadata"]
            logger.info(
                "  id=%s sect=%r hadith_id=%r chars=%d",
                record["id"],
                metadata.get("sect"),
                metadata.get("hadith_id"),
                len(record["text"]),
            )
        logger.info("Dry run complete. %d records cached, nothing written.", count)
        return

    # --- Phase B ---
    if args.skip_fit:
        encoder_path = Path(HADITH_BM25_ENCODER_PATH)
        if not encoder_path.is_file():
            raise ValueError(f"--skip-fit given but {encoder_path} does not exist")
        logger.info("Reusing persisted encoder at %s", encoder_path)
        encoder = BM25Encoder()
        encoder.load(str(encoder_path))
    else:
        encoder = fit_encoder()

    if args.encoder_only:
        logger.info("--encoder-only: skipping sparse upsert.")
        return

    # --- Phase C ---
    # Prefer a dedicated index if one is configured; otherwise write into the
    # existing sparse index under a separate namespace.
    index_name = args.index_name or DEEN_SPARSE_BM25_INDEX_NAME or DEEN_SPARSE_INDEX_NAME
    if not index_name:
        raise ValueError(
            "No target sparse index. Set DEEN_SPARSE_INDEX_NAME (or "
            "DEEN_SPARSE_BM25_INDEX_NAME) in .env, or pass --index-name."
        )

    namespace = args.namespace or DEEN_SPARSE_BM25_NAMESPACE
    if namespace == NAMESPACE and index_name == DEEN_SPARSE_INDEX_NAME:
        raise ValueError(
            f"Refusing to overwrite the live namespace {NAMESPACE!r} in "
            f"{index_name!r}. Choose a different --namespace."
        )

    ensure_sparse_index(pc, index_name)
    upsert_sparse(pc, encoder, index_name, namespace=namespace)

    logger.info(
        "Done. Set HADITH_SPARSE_BACKEND=bm25 (index=%s namespace=%s) to use it.",
        index_name,
        namespace,
    )


if __name__ == "__main__":
    main()
