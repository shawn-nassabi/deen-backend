"""
State schema for the LangGraph chat agent.
Defines all the information tracked throughout the conversation flow.
"""

from typing import TypedDict, Optional, List, Dict, Any, Annotated
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage


class ChatState(TypedDict):
    """
    State for the agentic chat pipeline.

    This state is passed between nodes in the LangGraph and tracks
    all relevant information throughout the conversation flow.
    """

    # Core conversation data
    messages: Annotated[List[BaseMessage], add_messages]
    """Message history for the agent (uses add_messages reducer)"""

    user_query: str
    """Original user query"""

    working_query: str
    """Current query used for retrieval after translation/enhancement"""

    session_id: str
    """Session identifier for conversation persistence"""

    runtime_session_id: str
    """Runtime history key used for transcript memory"""

    target_language: str
    """User's preferred language (default: "english")"""

    # Translation tracking
    is_translated: bool
    """Whether the query has been translated to English"""

    original_language: Optional[str]
    """Original language of the query if translated"""

    # Classification results
    is_non_islamic: Optional[bool]
    """True if query is not about Islamic education"""

    is_fiqh: Optional[bool]
    """True if query asks for a fiqh ruling"""

    fiqh_category: str
    """6-category fiqh classification result. One of: VALID_OBVIOUS, VALID_SMALL,
    VALID_LARGE, VALID_REASONER, OUT_OF_SCOPE_FIQH, UNETHICAL, or '' (not yet classified)"""

    classification_checked: bool
    """Whether classification has been performed"""

    # Query enhancement
    enhanced_query: Optional[str]
    """Enhanced version of the query for better retrieval"""

    query_enhanced: bool
    """Whether query enhancement has been performed"""

    # Document retrieval
    retrieved_docs: List[Dict[str, Any]]
    """Retrieved documents from knowledge base"""

    shia_docs_count: int
    """Number of Shia documents retrieved"""

    sunni_docs_count: int
    """Number of Sunni documents retrieved"""

    quran_docs_count: int
    """Number of Quran/Tafsir documents retrieved"""

    quran_docs: List[Dict[str, Any]]
    """Retrieved Quran/Tafsir documents (stored separately from hadith docs)"""

    streaming_mode: bool
    """When True, the graph skips generate_response so the pipeline can stream tokens"""

    retrieval_completed: bool
    """Whether document retrieval has been performed"""

    retrieval_attempts: List[Dict[str, Any]]
    """Ordered list of retrieval attempts with source/query metadata"""

    source_coverage: Dict[str, bool]
    """Whether Shia, Sunni, and Quran/Tafsir sources have been searched successfully"""

    ready_to_answer: bool
    """Whether the agent has decided it has enough evidence to answer"""

    # Response generation
    final_response: Optional[str]
    """Final generated response to the user"""

    response_generated: bool
    """Whether final response has been generated"""

    # Configuration
    config: Dict[str, Any]
    """Configuration parameters (retrieval settings, model params, etc.)"""

    # Flow control
    should_end: bool
    """Whether the agent should stop (e.g., after classification rejection)"""

    early_exit_message: Optional[str]
    """Message to send if exiting early (e.g., non-Islamic or fiqh query)"""

    # Error tracking
    errors: List[str]
    """List of errors encountered during processing"""

    # Metadata
    iterations: int
    """Number of agent iterations (for debugging and limits)"""

    # Cache metrics (Phase 19, D-07 option b — accumulated by _agent_node, read at SSE done)
    cache_creation_tokens_total: int
    """Sum of cache_creation_input_tokens across all _agent_node LLM calls this turn (D-05)"""

    cache_read_tokens_total: int
    """Sum of cache_read_input_tokens across all _agent_node LLM calls this turn (D-05)"""

    # Fiqh FAIR-RAG pipeline results
    fiqh_filtered_docs: List[Dict[str, Any]]
    """Final filtered fiqh documents from sub-graph exit. Empty list if fiqh path not taken."""

    fiqh_sea_result: Optional[Any]
    """SEAResult from final sub-graph iteration. None if fiqh path not taken.
    Typed as Any to avoid circular import; actual type is modules.fiqh.sea.SEAResult."""

    fiqh_status_events: List[Dict[str, str]]
    """Status events accumulated inside the fiqh sub-graph, surfaced up so the
    pipeline can yield them as SSE status events in the order they occurred.
    Each event: {"step": str, "message": str}. Empty list if fiqh path not taken."""


def create_initial_state(
    user_query: str,
    session_id: str,
    target_language: str = "english",
    config: Optional[Dict[str, Any]] = None,
    initial_messages: Optional[List[BaseMessage]] = None,
    streaming_mode: bool = False,
) -> ChatState:
    """
    Create initial state for a new chat interaction.

    Args:
        user_query: The user's question
        session_id: Session identifier
        target_language: User's preferred language
        config: Optional configuration overrides
        initial_messages: Optional existing conversation history
        streaming_mode: Whether the graph should stop before response generation

    Returns:
        ChatState with initial values
    """
    return ChatState(
        messages=initial_messages or [],
        user_query=user_query,
        working_query=user_query,
        session_id=session_id,
        runtime_session_id=session_id,
        target_language=target_language,
        is_translated=False,
        original_language=None,
        is_non_islamic=None,
        is_fiqh=None,
        fiqh_category="",
        classification_checked=False,
        enhanced_query=None,
        query_enhanced=False,
        retrieved_docs=[],
        shia_docs_count=0,
        sunni_docs_count=0,
        quran_docs_count=0,
        quran_docs=[],
        streaming_mode=streaming_mode,
        retrieval_completed=False,
        retrieval_attempts=[],
        source_coverage={
            "shia": False,
            "sunni": False,
            "quran_tafsir": False,
        },
        ready_to_answer=False,
        final_response=None,
        response_generated=False,
        config=config or {},
        should_end=False,
        early_exit_message=None,
        errors=[],
        iterations=0,
        cache_creation_tokens_total=0,
        cache_read_tokens_total=0,
        fiqh_filtered_docs=[],
        fiqh_sea_result=None,
        fiqh_status_events=[],
    )
