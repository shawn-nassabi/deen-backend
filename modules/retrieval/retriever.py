import asyncio
import logging

from core.config import (
    DEEN_DENSE_INDEX_NAME,
    DEEN_SPARSE_BM25_INDEX_NAME,
    DEEN_SPARSE_INDEX_NAME,
    HADITH_SPARSE_BACKEND,
    QURAN_DENSE_INDEX_NAME,
)
import core.vectorstore as vectorstore_module
from core.utils import decompress_text
from core.resilience import pinecone_retry
from modules.embedding import embedder
from modules.reranking import reranker

logger = logging.getLogger(__name__)


def _require_index_name(index_name, env_var_name):
    if not index_name or not str(index_name).strip():
        raise ValueError(
            f"{env_var_name} is not configured. Quran/Tafsir retrieval is unavailable until this Pinecone index name is set."
        )
    return index_name


def _hadith_sparse_index_name() -> str | None:
    """Resolve the Pinecone sparse index for hadith retrieval (DEE-21).

    Returns None when ``HADITH_SPARSE_BACKEND=bm25`` but
    ``DEEN_SPARSE_BM25_INDEX_NAME`` is unset — caller should skip sparse search.
    """
    if HADITH_SPARSE_BACKEND == "bm25":
        if not DEEN_SPARSE_BM25_INDEX_NAME or not str(DEEN_SPARSE_BM25_INDEX_NAME).strip():
            logger.error(
                "HADITH_SPARSE_BACKEND=bm25 but DEEN_SPARSE_BM25_INDEX_NAME is not set — "
                "sparse retrieval disabled for this request; using dense-only."
            )
            return None
        return DEEN_SPARSE_BM25_INDEX_NAME
    return DEEN_SPARSE_INDEX_NAME


def _empty_sparse_results() -> dict:
    """Sparse result shape consumed by ``reranker.rerank_documents``."""
    return {"matches": []}


def _sync_sparse_search(query: str, *, k: int, sect_filter: dict | None = None) -> dict:
    """Run hadith sparse Pinecone query, or return empty matches when sparse is skipped."""
    sparse_embedding = embedder.generate_hadith_sparse_embedding(query)
    sparse_index_name = _hadith_sparse_index_name()
    if sparse_embedding is None or sparse_index_name is None:
        return _empty_sparse_results()

    sparse_vectorstore = vectorstore_module._get_sparse_vectorstore(sparse_index_name)
    query_kwargs: dict = {
        "top_k": k,
        "include_metadata": True,
        "sparse_vector": sparse_embedding,
        "namespace": "ns1",
    }
    if sect_filter is not None:
        query_kwargs["filter"] = sect_filter
    return sparse_vectorstore.query(**query_kwargs)


# --- Sync retrieval (kept for legacy callers) ------------------------------


def retrieve_documents(query, no_of_docs=10):
    try:
        dense_vectorstore = vectorstore_module._get_vectorstore(DEEN_DENSE_INDEX_NAME)
        dense_docs_and_score = dense_vectorstore.similarity_search_with_score(query, k=20)

        sparse_docs = _sync_sparse_search(query, k=20)

        result = reranker.rerank_documents(dense_docs_and_score, sparse_docs, no_of_docs)
        return result
    except Exception:
        logger.error("retrieve_documents error", exc_info=True)
        return []


def retrieve_shia_documents(query, no_of_docs=10):
    try:
        dense_vectorstore = vectorstore_module._get_vectorstore(DEEN_DENSE_INDEX_NAME)
        dense_docs_and_score = dense_vectorstore.similarity_search_with_score(
            query, filter={'sect': 'shia'}, k=no_of_docs
        )

        sparse_docs = _sync_sparse_search(query, k=no_of_docs, sect_filter={'sect': 'shia'})

        result = reranker.rerank_documents(dense_docs_and_score, sparse_docs, no_of_docs)
        return result
    except Exception:
        logger.error("retrieve_shia_documents error", exc_info=True)
        return []


def retrieve_sunni_documents(query, no_of_docs=10):
    try:
        dense_vectorstore = vectorstore_module._get_vectorstore(DEEN_DENSE_INDEX_NAME)
        dense_docs_and_score = dense_vectorstore.similarity_search_with_score(
            query, filter={'sect': 'sunni'}, k=no_of_docs
        )

        sparse_docs = _sync_sparse_search(query, k=no_of_docs, sect_filter={'sect': 'sunni'})

        result = reranker.rerank_documents(dense_docs_and_score, sparse_docs, no_of_docs)
        return result
    except Exception:
        logger.error("retrieve_sunni_documents error", exc_info=True)
        return []


# Token-cost DEE-60 Phase 2: whitelist of Quran/Tafsir metadata fields — the
# union of everything read by core/utils.py formatters, the frontend
# quran_references JSON, and the _is_quran_doc grouping check ("Type").
# Drops the gzip+base64 duplicates (text_chunk, english_quran_translation)
# that already exist decompressed as top-level doc fields.
QURAN_METADATA_WHITELIST = (
    "surah_name",
    "title",
    "chapter_number",
    "verses_covered",
    "starting_verse",
    "ending_verse",
    "author",
    "collection",
    "volume",
    "sect",
    "Type",
)


def _whitelist_quran_metadata(md: dict) -> dict:
    if not isinstance(md, dict):
        return {}
    return {k: md[k] for k in QURAN_METADATA_WHITELIST if k in md}


def retrieve_quran_documents(query, no_of_docs=5):
    """
    Retrieve Quran Tafsir documents from the dedicated dense-only Pinecone index.
    Uses direct Pinecone query (no sparse search, no reranking).
    """
    try:
        index_name = _require_index_name(QURAN_DENSE_INDEX_NAME, "QURAN_DENSE_INDEX_NAME")
        query_vector = embedder.getDenseEmbedder().embed_query(query)

        index = vectorstore_module._get_sparse_vectorstore(index_name)
        results = index.query(
            vector=query_vector,
            top_k=no_of_docs,
            include_metadata=True,
            namespace="ns1",
        )

        docs = []
        for match in results.matches:
            md = match.metadata or {}
            text_chunk = decompress_text(md.get("text_chunk", ""))
            quran_translation = decompress_text(md.get("english_quran_translation", ""))
            docs.append({
                "chunk_id": match.id,
                "metadata": _whitelist_quran_metadata(md),
                "page_content_en": text_chunk,
                "quran_translation": quran_translation,
            })
        return docs
    except ValueError:
        logger.error("retrieve_quran_documents misconfigured (missing index)", exc_info=True)
        raise
    except Exception:
        logger.error("retrieve_quran_documents error", exc_info=True)
        raise


# --- Async retrieval (DEE-42) ----------------------------------------------
#
# Dense vectorstore search uses langchain-pinecone's native
# asimilarity_search_with_score (HTTP I/O bound). Sparse Pinecone queries use
# the v1 sync SDK; offloaded to a thread until a follow-up adopts
# PineconeAsyncio. Reranking and sparse encoding (TF-IDF / BM25) are CPU-bound —
# they stay in run_in_executor so they don't pin the event loop. Dense + sparse
# branches run concurrently via asyncio.gather.


@pinecone_retry
async def _dense_search(index_name, query, *, k, sect_filter=None):
    vectorstore = vectorstore_module._get_vectorstore(index_name)
    kwargs = {"k": k}
    if sect_filter is not None:
        kwargs["filter"] = sect_filter
    return await vectorstore.asimilarity_search_with_score(query, **kwargs)


@pinecone_retry
async def _sparse_search(query, *, k, sect_filter=None, namespace="ns1"):
    sparse_embedding = await asyncio.to_thread(embedder.generate_hadith_sparse_embedding, query)
    sparse_index_name = _hadith_sparse_index_name()
    if sparse_embedding is None or sparse_index_name is None:
        return _empty_sparse_results()

    sparse_index = vectorstore_module._get_sparse_vectorstore(sparse_index_name)
    return await asyncio.to_thread(
        sparse_index.query,
        top_k=k,
        include_metadata=True,
        sparse_vector=sparse_embedding,
        namespace=namespace,
        **({"filter": sect_filter} if sect_filter is not None else {}),
    )


async def _aretrieve_with_filter(query, no_of_docs, sect):
    try:
        dense_docs_and_score, sparse_docs = await asyncio.gather(
            _dense_search(DEEN_DENSE_INDEX_NAME, query, k=no_of_docs, sect_filter={"sect": sect}),
            _sparse_search(query, k=no_of_docs, sect_filter={"sect": sect}),
        )
        return await asyncio.to_thread(
            reranker.rerank_documents, dense_docs_and_score, sparse_docs, no_of_docs
        )
    except Exception:
        logger.error(
            "Pinecone retrieval failed after retries (sect=%s)", sect, exc_info=True
        )
        return []


async def aretrieve_shia_documents(query, no_of_docs=10):
    return await _aretrieve_with_filter(query, no_of_docs, "shia")


async def aretrieve_sunni_documents(query, no_of_docs=10):
    return await _aretrieve_with_filter(query, no_of_docs, "sunni")


@pinecone_retry
async def _aretrieve_quran_call(index, query_vector, no_of_docs):
    return await asyncio.to_thread(
        index.query,
        vector=query_vector,
        top_k=no_of_docs,
        include_metadata=True,
        namespace="ns1",
    )


async def aretrieve_quran_documents(query, no_of_docs=5):
    """Async variant of `retrieve_quran_documents`. The dense embedder hits
    sentence-transformers (CPU on torch) — `aembed_query` runs that in
    LangChain's executor so it doesn't block the event loop. The Pinecone
    query stays in `to_thread` until PineconeAsyncio adoption."""
    try:
        index_name = _require_index_name(QURAN_DENSE_INDEX_NAME, "QURAN_DENSE_INDEX_NAME")
        query_vector = await embedder.getDenseEmbedder().aembed_query(query)

        index = vectorstore_module._get_sparse_vectorstore(index_name)
        results = await _aretrieve_quran_call(index, query_vector, no_of_docs)

        docs = []
        for match in results.matches:
            md = match.metadata or {}
            text_chunk = decompress_text(md.get("text_chunk", ""))
            quran_translation = decompress_text(md.get("english_quran_translation", ""))
            docs.append({
                "chunk_id": match.id,
                "metadata": _whitelist_quran_metadata(md),
                "page_content_en": text_chunk,
                "quran_translation": quran_translation,
            })
        return docs
    except ValueError:
        logger.error(
            "aretrieve_quran_documents misconfigured (missing index)", exc_info=True
        )
        raise
    except Exception:
        logger.error("aretrieve_quran_documents failed after retries", exc_info=True)
        raise


"""
Returns a list of the following:
'metadata': {'book': '4 | The Book about people with Divine Authority',
              'chapter': 'Chapter 93 | The Birth of the Imams',
              'hadith_number': '5',
              'text': 'Al-Husayn ibn Muhammad has narrated from Mu‘alla ibn Muhammad from Ahmad ibn Muhammad ibn ‘Abd...',
              'author': 'Shaykh Muḥammad b. Yaʿqūb al-Kulaynī',
              'volume': 'NA',
              'source': 'Volume 1'
              }
"""
