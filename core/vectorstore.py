import logging

from core.config import PINECONE_API_KEY
from langchain_pinecone import PineconeVectorStore
from modules.embedding import embedder
from pinecone import Pinecone, ServerlessSpec

logger = logging.getLogger(__name__)

pc = Pinecone(
        api_key=PINECONE_API_KEY
    )


def _require_index_name(index_name):
    if not index_name or not str(index_name).strip():
        raise ValueError("Pinecone index name is missing or empty.")
    return index_name


def _get_sparse_vectorstore(index_name):
    index = pc.Index(_require_index_name(index_name))
    return index


def _get_vectorstore(index_name):
    embeddings = embedder.getDenseEmbedder()
    try:
        return PineconeVectorStore(
            index_name=_require_index_name(index_name),
            embedding=embeddings,
            pinecone_api_key=PINECONE_API_KEY,
            namespace="ns1",
            text_key="text_en"
        )
    except Exception:
        logger.error("Error initializing PineconeVectorStore", exc_info=True)
        raise
