"""
Retrieval tools for the LangGraph agent.
These tools fetch relevant documents from the knowledge base.
"""

import asyncio

from langchain_core.tools import tool
from modules.retrieval import retriever
from typing import Dict, List
import logging
from core.context import correlation_id as correlation_id_ctx

logger = logging.getLogger(__name__)


@tool
async def retrieve_shia_documents_tool(query: str, num_documents: int = 5) -> Dict[str, any]:
    """
    Retrieve relevant documents from the Shia Islamic knowledge base.
    
    Use this tool to find hadith, narrations, and texts specifically from Shia sources.
    The retrieval uses hybrid search (dense + sparse) with reranking for best results.
    
    Args:
        query: The search query (should be enhanced if possible)
        num_documents: Number of documents to retrieve (default: 5, recommended: 3-10)
        
    Returns:
        Dictionary with:
        - documents (List[Dict]): Retrieved documents with metadata
        - count (int): Number of documents retrieved
        - source (str): "shia"
        
    Each document contains:
        - hadith_id: Unique identifier
        - metadata: Book, chapter, hadith number, author, volume, source
        - page_content_en: English text
        - page_content_ar: Arabic text (if available)
        
    When to use:
    - For questions specifically about Shia beliefs, practices, or sources
    - When the user asks about Twelver Shia Islam
    - As the primary source for most queries (Shia is the default perspective)
    
    Recommended num_documents:
    - 3-5: For specific, focused queries
    - 5-7: For broader topics requiring more context
    - 7-10: For complex questions needing comprehensive coverage
    """
    try:
        # Phase 3 (DEE-42) introduces native `aretrieve_shia_documents` backed by
        # PineconeVectorStore.asimilarity_search_with_score; until then run the
        # sync retriever off the event loop so concurrent agents don't queue.
        docs = await asyncio.to_thread(retriever.retrieve_shia_documents, query, num_documents)

        return {
            "documents": docs,
            "count": len(docs),
            "source": "shia",
            "query_used": query
        }
    except Exception as e:
        logger.error("Retrieval error", exc_info=True, extra={
            "correlation_id": correlation_id_ctx.get(),
            "error": str(e),
        })
        return {
            "documents": [],
            "count": 0,
            "source": "shia",
            "query_used": query,
            "error": str(e)
        }


@tool
async def retrieve_sunni_documents_tool(query: str, num_documents: int = 2) -> Dict[str, any]:
    """
    Retrieve relevant documents from the Sunni Islamic knowledge base.
    
    Use this tool to find hadith, narrations, and texts from Sunni sources.
    Useful for comparative analysis or providing multiple perspectives.
    
    Args:
        query: The search query (should be enhanced if possible)
        num_documents: Number of documents to retrieve (default: 2, recommended: 1-5)
        
    Returns:
        Dictionary with:
        - documents (List[Dict]): Retrieved documents with metadata
        - count (int): Number of documents retrieved
        - source (str): "sunni"
        
    Each document contains:
        - hadith_id: Unique identifier
        - metadata: Book, chapter, hadith number, author, volume, source
        - page_content_en: English text
        - page_content_ar: Arabic text (if available)
        
    When to use:
    - For comparative perspectives on shared topics
    - When user explicitly asks about Sunni viewpoints
    - For hadith that appear in both traditions
    - To provide a more comprehensive view on certain topics
    
    When NOT to use:
    - For purely Shia-specific topics (Imamate, specific Shia practices)
    - When user specifically requests only Shia sources
    
    Recommended num_documents:
    - 1-2: For supplementary context (default)
    - 2-4: For comparative analysis
    - 4-5: When user specifically asks for Sunni perspective
    """
    try:
        docs = await asyncio.to_thread(retriever.retrieve_sunni_documents, query, num_documents)

        return {
            "documents": docs,
            "count": len(docs),
            "source": "sunni",
            "query_used": query
        }
    except Exception as e:
        logger.error("Retrieval error", exc_info=True, extra={
            "correlation_id": correlation_id_ctx.get(),
            "error": str(e),
        })
        return {
            "documents": [],
            "count": 0,
            "source": "sunni",
            "query_used": query,
            "error": str(e)
        }


@tool
async def retrieve_combined_documents_tool(
    query: str, 
    shia_num_documents: int = 5, 
    sunni_num_documents: int = 2
) -> Dict[str, any]:
    """
    Retrieve relevant documents from both Shia and Sunni knowledge bases in one call.
    
    This is a convenience tool that retrieves from both sources and combines them.
    Use this when you want a comprehensive view with both perspectives.
    
    Args:
        query: The search query (should be enhanced if possible)
        shia_num_documents: Number of Shia documents to retrieve (default: 5)
        sunni_num_documents: Number of Sunni documents to retrieve (default: 2)
        
    Returns:
        Dictionary with:
        - documents (List[Dict]): Combined documents from both sources
        - shia_count (int): Number of Shia documents retrieved
        - sunni_count (int): Number of Sunni documents retrieved
        - total_count (int): Total documents retrieved
        
    When to use:
    - For general Islamic topics that benefit from multiple perspectives
    - When you want to provide comprehensive coverage
    - For historical events, shared practices, or common teachings
    
    When to use separate tools instead:
    - When you need control over the retrieval process
    - When you want to retrieve Shia first, then conditionally retrieve Sunni
    - When query complexity requires different query formulations for each source
    """
    try:
        # Fire both retrievals concurrently so the combined call doesn't pay
        # 2x the latency of a single source.
        shia_docs, sunni_docs = await asyncio.gather(
            asyncio.to_thread(retriever.retrieve_shia_documents, query, shia_num_documents),
            asyncio.to_thread(retriever.retrieve_sunni_documents, query, sunni_num_documents),
        )

        combined_docs = shia_docs + sunni_docs

        return {
            "documents": combined_docs,
            "shia_count": len(shia_docs),
            "sunni_count": len(sunni_docs),
            "total_count": len(combined_docs),
            "query_used": query
        }
    except Exception as e:
        logger.error("Retrieval error", exc_info=True, extra={
            "correlation_id": correlation_id_ctx.get(),
            "error": str(e),
        })
        return {
            "documents": [],
            "shia_count": 0,
            "sunni_count": 0,
            "total_count": 0,
            "query_used": query,
            "error": str(e)
        }


@tool
async def retrieve_quran_tafsir_tool(query: str, num_documents: int = 3) -> Dict[str, any]:
    """
    Retrieve Quran verses and Tafsir (exegesis/explanation) from the Quran knowledge base.
    
    Use this tool to find Quranic content and scholarly Tafsir commentary.
    The retrieval searches a dedicated Quran and Tafsir vector database.
    
    Args:
        query: The search query (should be enhanced if possible)
        num_documents: Number of documents to retrieve (default: 3, recommended: 2-5)
        
    Returns:
        Dictionary with:
        - documents (List[Dict]): Retrieved documents with metadata
        - count (int): Number of documents retrieved
        - source (str): "quran_tafsir"
        
    Each document contains:
        - chunk_id: Unique identifier
        - metadata: Surah name, chapter number, verses covered, author, collection, volume
        - page_content_en: Tafsir text (English)
        - quran_translation: English translation of the Quran verses
        
    When to use:
    - When the query asks about Quranic verses, Surahs, or their meanings
    - When Tafsir (exegesis/commentary) on specific Quran passages is needed
    - When Quranic evidence would strengthen or complement a response
    - For questions about Quranic themes, stories, or teachings
    - Can be used ALONGSIDE hadith retrieval tools for comprehensive answers
    
    When NOT to use:
    - For purely hadith-related questions with no Quranic dimension
    - When the user only asks about historical events unrelated to the Quran
    
    Recommended num_documents:
    - 2-3: For specific verse or Surah queries
    - 3-5: For broader Quranic themes or comparative topics
    """
    try:
        docs = await asyncio.to_thread(retriever.retrieve_quran_documents, query, num_documents)

        return {
            "documents": docs,
            "count": len(docs),
            "source": "quran_tafsir",
            "query_used": query
        }
    except Exception as e:
        logger.error("Retrieval error", exc_info=True, extra={
            "correlation_id": correlation_id_ctx.get(),
            "error": str(e),
        })
        return {
            "documents": [],
            "count": 0,
            "source": "quran_tafsir",
            "query_used": query,
            "error": str(e)
        }
