from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from langchain_huggingface import HuggingFaceEmbeddings
from pinecone_text.sparse import BM25Encoder
from sklearn.feature_extraction.text import TfidfVectorizer

from core.config import HADITH_SPARSE_BACKEND
from modules.embedding import proprecessor

logger = logging.getLogger(__name__)

tfif_vectorizer = TfidfVectorizer(
    preprocessor=None,
    stop_words="english",
    analyzer="word",
    lowercase=False,
    use_idf=True,
    smooth_idf=True,
    sublinear_tf=True,
    norm=None,
)

sentence_transformer = HuggingFaceEmbeddings(model_name="sentence-transformers/all-mpnet-base-v2")

# Resolve path relative to this file — works regardless of process cwd.
HADITH_BM25_ENCODER_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "hadith_bm25_encoder.json"
)

_hadith_bm25_encoder: BM25Encoder | None = None


def getSparseEmbedder():
    return tfif_vectorizer


def getDenseEmbedder():
    return sentence_transformer


def generate_sparse_embedding(query: str) -> dict[str, list]:
    """Generates a sparse embedding for the given query using TF-IDF."""
    print("INSIDE generate_sparse_embedding")
    normalized_query = proprecessor.normalize_text(query)
    vec = getSparseEmbedder().fit_transform([normalized_query])
    vec_array = vec[0].toarray().squeeze()
    indices = np.atleast_1d(vec_array).nonzero()[0].tolist()
    values = vec_array[indices].tolist()
    return {"indices": indices, "values": values}


def _get_hadith_bm25_encoder() -> BM25Encoder | None:
    """Load the corpus-fit hadith BM25 encoder from disk, then cache.

    Returns None when the encoder file is absent (caller must skip sparse retrieval).
    """
    global _hadith_bm25_encoder
    if _hadith_bm25_encoder is not None:
        return _hadith_bm25_encoder

    if not HADITH_BM25_ENCODER_PATH.is_file():
        logger.error(
            "Hadith BM25 encoder missing at %s — sparse retrieval disabled for this "
            "request. Run `python scripts/reindex_hadith_sparse.py --encoder-only` "
            "after approving the reindex script (DEE-21).",
            HADITH_BM25_ENCODER_PATH,
        )
        return None

    enc = BM25Encoder()
    enc.load(str(HADITH_BM25_ENCODER_PATH))
    _hadith_bm25_encoder = enc
    return _hadith_bm25_encoder


def generate_bm25_sparse_embedding(query: str) -> dict[str, list] | None:
    """Encode a query with the corpus-fit hadith BM25 encoder.

    Returns None when the encoder file is missing (never falls back to TF-IDF).
    """
    encoder = _get_hadith_bm25_encoder()
    if encoder is None:
        return None

    sparse_vec: dict[str, Any] = encoder.encode_queries(query)
    return {
        "indices": list(sparse_vec["indices"]),
        "values": list(sparse_vec["values"]),
    }


def generate_hadith_sparse_embedding(query: str) -> dict[str, list] | None:
    """Dispatch hadith sparse encoding by ``HADITH_SPARSE_BACKEND``.

    - ``tfidf`` (default): legacy TF-IDF query encoding.
    - ``bm25``: corpus-fit BM25 via ``generate_bm25_sparse_embedding``; returns
      None when the encoder file is missing (caller should skip sparse / use dense only).
    """
    if HADITH_SPARSE_BACKEND == "bm25":
        return generate_bm25_sparse_embedding(query)
    return generate_sparse_embedding(query)
