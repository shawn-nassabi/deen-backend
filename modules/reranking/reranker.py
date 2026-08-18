# modules/reranking/reranker.py
from collections import defaultdict
from core.config import DENSE_RESULT_WEIGHT, SPARSE_RESULT_WEIGHT
from core import utils
import logging
import traceback
from pprint import pformat

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)  # or DEBUG while debugging

# Token-cost DEE-60 Phase 2: the raw Pinecone metadata carries gzip+base64
# duplicates of the text (text_en on sparse hits, text_ar always) that no
# downstream consumer reads after decompression — but they were serialized
# into ToolMessages and re-sent to the LLM on every agent iteration. The
# whitelist is the union of every field read by core/utils.py formatters
# and the frontend reference JSON.
HADITH_METADATA_WHITELIST = (
    "author",
    "volume",
    "book_number",
    "book_title",
    "chapter_number",
    "chapter_title",
    "collection",
    "grade_ar",
    "grade_en",
    "hadith_id",
    "hadith_no",
    "hadith_url",
    "lang",
    "sect",
    "reference",
)


def _whitelist_metadata(md: dict) -> dict:
    if not isinstance(md, dict):
        return {}
    return {k: md[k] for k in HADITH_METADATA_WHITELIST if k in md}


def _extract_sparse_matches(sparse_results):
    """Normalize a Pinecone sparse query result to a list of mutable match dicts."""
    if sparse_results is None:
        return []
    if isinstance(sparse_results, dict):
        return sparse_results.get("matches", []) or []
    # Pinecone SDK QueryResponse is NOT a dict — the previous isinstance(dict)
    # guard silently dropped every real sparse hit (DEE-21).
    to_dict = getattr(sparse_results, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict().get("matches", []) or []
        except Exception:
            logger.exception("[RERANK] sparse to_dict() failed; falling back to .matches")
    return list(getattr(sparse_results, "matches", None) or [])


def rerank_documents(dense_results, sparse_results, no_of_docs):
    """
    Merges and reranks documents based on their dense and sparse scores.
    """
    logger.info("INSIDE rerank_documents")
    try:
        dense_count = len(dense_results) if dense_results is not None else 0
        sparse_matches = _extract_sparse_matches(sparse_results)
        logger.info("[RERANK] dense_count=%s sparse_count=%s", dense_count, len(sparse_matches))

        # Normalize dense and sparse scores in-place (defensive)
        try:
            normalize_inplace(dense_results, 1)
        except Exception:
            logger.exception("[RERANK] normalize_inplace(dense_results) failed.\nDense sample: %s",
                             safe_sample_dense(dense_results))
        try:
            normalize_inplace(sparse_matches, "score")
        except Exception:
            logger.exception("[RERANK] normalize_inplace(sparse_matches) failed.\nSparse sample: %s",
                             safe_sample_sparse(sparse_matches))

        combined_with_weighted_scores = defaultdict(lambda: {
            "dense_score": 0.0,
            "sparse_score": 0.0,
            "metadata": {},
            "page_content_en": "",
            "page_content_ar": ""
        })

        # Add dense docs
        for idx, pair in enumerate(dense_results or []):
            try:
                doc, score = pair
                md = getattr(doc, "metadata", {}) or {}
                hadith_id = md.get("hadith_id")
                if not hadith_id:
                    logger.debug("[RERANK][DENSE][%d] Missing hadith_id; skipping. Metadata keys=%s", idx, list(md.keys()))
                    continue

                # Decompress safely; fall back to original if already plain
                try:
                    page_content_english_decompressed = utils.decompress_text(getattr(doc, "page_content", "") or "")
                except Exception:
                    logger.debug("[RERANK][DENSE][%d] decompress page_content failed; using raw.", idx)
                    page_content_english_decompressed = getattr(doc, "page_content", "") or ""

                try:
                    page_content_arabic_decompressed = utils.decompress_text(md.get("text_ar", "") or "")
                except Exception:
                    page_content_arabic_decompressed = md.get("text_ar", "") or ""

                combined_with_weighted_scores[hadith_id]["dense_score"] += float(score) * float(DENSE_RESULT_WEIGHT)
                combined_with_weighted_scores[hadith_id]["metadata"] = md or combined_with_weighted_scores[hadith_id]["metadata"]
                if not combined_with_weighted_scores[hadith_id]["page_content_en"]:
                    combined_with_weighted_scores[hadith_id]["page_content_en"] = page_content_english_decompressed
                if not combined_with_weighted_scores[hadith_id]["page_content_ar"]:
                    combined_with_weighted_scores[hadith_id]["page_content_ar"] = page_content_arabic_decompressed
            except Exception:
                logger.exception("[RERANK][DENSE][%d] Failed to merge dense doc.", idx)

        # Add sparse docs
        for idx, match in enumerate(sparse_matches):
            try:
                # Pinecone REST (dict) or SDK object (duck-typed)
                if isinstance(match, dict):
                    md = match.get("metadata", {}) or {}
                    score = match.get("score", 0.0)
                else:
                    md = getattr(match, "metadata", {}) or {}
                    score = getattr(match, "score", 0.0)

                hadith_id = md.get("hadith_id")
                if not hadith_id:
                    logger.debug("[RERANK][SPARSE][%d] Missing hadith_id; skipping. Metadata keys=%s", idx, list(md.keys()))
                    continue

                # Safe decompression
                try:
                    page_en = utils.decompress_text(md.get("text_en", "") or "")
                except Exception:
                    page_en = md.get("text_en", "") or ""
                try:
                    page_ar = utils.decompress_text(md.get("text_ar", "") or "")
                except Exception:
                    page_ar = md.get("text_ar", "") or ""

                combined_with_weighted_scores[hadith_id]["sparse_score"] += float(score) * float(SPARSE_RESULT_WEIGHT)
                if not combined_with_weighted_scores[hadith_id]["metadata"]:
                    combined_with_weighted_scores[hadith_id]["metadata"] = md
                if not combined_with_weighted_scores[hadith_id]["page_content_en"]:
                    combined_with_weighted_scores[hadith_id]["page_content_en"] = page_en
                if not combined_with_weighted_scores[hadith_id]["page_content_ar"]:
                    combined_with_weighted_scores[hadith_id]["page_content_ar"] = page_ar
            except Exception:
                logger.exception("[RERANK][SPARSE][%d] Failed to merge sparse match.", idx)

        # Sort by combined score (dense + sparse)
        try:
            sorted_combined_docs = sorted(
                combined_with_weighted_scores.items(),
                key=lambda item: item[1]["dense_score"] + item[1]["sparse_score"],
                reverse=True
            )
        except Exception:
            logger.exception("[RERANK] Sorting failed. Combined keys snapshot: %s",
                             list(combined_with_weighted_scores.keys())[:10])
            sorted_combined_docs = list(combined_with_weighted_scores.items())

        top = sorted_combined_docs[:no_of_docs]
        logger.info("[RERANK] returning top=%d (requested %d). Top IDs=%s",
                    len(top), no_of_docs, [k for k, _ in top])

        # return top no_of_docs from the sorted results (metadata whitelisted —
        # compressed text blobs never leave this module)
        return [
            {
                "hadith_id": hadith_id,
                "metadata": _whitelist_metadata(data["metadata"]),
                "page_content_en": data["page_content_en"],
                "page_content_ar": data["page_content_ar"]
            }
            for hadith_id, data in top
        ]
    except Exception:
        logger.error("[RERANK] Unhandled error:\n%s", traceback.format_exc())
        return []


def normalize_inplace(items, score_key):
    """Normalize the scores in-place for a list of items (dicts or tuples)."""
    try:
        n = len(items) if hasattr(items, "__len__") else None
        logger.debug("normalize_inplace: n=%s score_key=%s", n, score_key)
        if not items:
            return

        # Build score list defensively
        scores = []
        for i, item in enumerate(items):
            try:
                if isinstance(item, tuple):
                    s = item[1]
                else:
                    # If dict-like
                    s = item.get(score_key) if isinstance(item, dict) else getattr(item, score_key, None)
                if s is None:
                    logger.debug("normalize_inplace: missing score at idx=%d item=%r", i, item)
                    continue
                scores.append(float(s))
            except Exception:
                logger.exception("normalize_inplace: error extracting score at idx=%d", i)

        if not scores:
            logger.debug("normalize_inplace: no valid scores found; nothing to normalize.")
            return

        min_score = min(scores)
        max_score = max(scores)
        if max_score == min_score:
            norm = lambda _: 1.0
        else:
            denom = (max_score - min_score)
            norm = lambda s: (s - min_score) / denom

        for i, item in enumerate(items):
            try:
                if isinstance(item, tuple):
                    # Replace (doc, score) with (doc, normalized_score)
                    items[i] = (item[0], norm(float(item[1])))
                else:
                    if isinstance(item, dict) and score_key in item and item[score_key] is not None:
                        item[score_key] = norm(float(item[score_key]))
                    elif hasattr(item, score_key):
                        setattr(item, score_key, norm(float(getattr(item, score_key))))
                    else:
                        # nothing to set; continue
                        pass
            except Exception:
                logger.exception("normalize_inplace: error normalizing idx=%d", i)

    except Exception:
        logger.error("normalize_inplace: unhandled error.\n%s", traceback.format_exc())


def safe_sample_dense(dense):
    try:
        if not dense:
            return "[]"
        sample = dense[:2]
        return pformat([(type(x[0]).__name__ if isinstance(x, tuple) else type(x).__name__, x[1] if isinstance(x, tuple) else None) for x in sample])
    except Exception:
        return "<dense sample unavailable>"

def safe_sample_sparse(matches):
    try:
        if not matches:
            return "[]"
        m = matches[0]
        if isinstance(m, dict):
            return pformat({"type": "dict", "keys": list(m.keys()), "md_keys": list((m.get('metadata') or {}).keys())})
        return pformat({"type": type(m).__name__, "has_score": hasattr(m, 'score'), "has_metadata": hasattr(m, 'metadata')})
    except Exception:
        return "<sparse sample unavailable>"