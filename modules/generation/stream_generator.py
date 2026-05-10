import logging
from core import utils
from core import chat_models
from core import prompt_templates
from core.memory import trim_history, make_history
from core.logging_config import setup_logging, get_memory_logger
import asyncio
from typing import Optional
import threading

setup_logging()
logger = logging.getLogger("hikmah.stream")
memory_logger = get_memory_logger(level=logging.DEBUG)

def generate_response_stream(query: str, retrieved_docs: list, session_id: str, target_language: str = "english"):
    """
    Generates a streaming response using the chat model.
    Yields chunks of text as they are generated.
    """
    print("INSIDE generate_response_stream")
    # Format retrieved references
    references = utils.compact_format_references(retrieved_docs=retrieved_docs)

    chat_model = chat_models.get_generator_model()

    history_messages = make_history(session_id).messages
    messages = prompt_templates.generator_messages(
        query=query,
        references=references,
        target_language=target_language,
        chat_history=history_messages,
    )

    # Stream chunks to caller
    for chunk in chat_model.stream(messages):
        # `chunk` is typically an AIMessageChunk or string
        yield getattr(chunk, "content", str(chunk) if chunk is not None else "")

    # After stream completes, cap history length
    hist = make_history(session_id)
    trim_history(hist)

def _build_elaboration_messages(
    selected_text: str,
    context_text: str,
    hikmah_tree_name: str,
    lesson_name: str,
    lesson_summary: str,
    retrieved_docs: list,
) -> list:
    references = utils.compact_format_references(retrieved_docs=retrieved_docs)
    return prompt_templates.hikmah_elaboration_messages(
        selected_text=selected_text,
        context_text=context_text,
        hikmah_tree_name=hikmah_tree_name,
        lesson_name=lesson_name,
        lesson_summary=lesson_summary,
        references=references,
    )


def _schedule_hikmah_memory_update(user_id: str, selected_text: str, hikmah_tree_name: str, lesson_name: str):
    """Fire-and-forget memory update. Runs in a daemon thread with its own
    event loop so it never blocks the response stream and is independent of
    whether the caller is sync or async."""
    memory_logger.info(
        "Scheduling hikmah memory update",
        extra={
            "user_id": user_id,
            "selected_text_len": len(selected_text or ""),
            "selected_text_preview": (selected_text or "")[:120],
            "hikmah_tree_name": hikmah_tree_name,
            "lesson_name": lesson_name,
            "context_text_passed": False,
            "lesson_summary_passed": False,
        },
    )
    thread = threading.Thread(
        target=_run_memory_update_sync,
        args=(user_id, selected_text, hikmah_tree_name, lesson_name),
        daemon=True,
    )
    thread.start()
    print(f"🧠 Memory agent thread started for user {user_id}")


def generate_elaboration_response_stream(selected_text: str, context_text: str, hikmah_tree_name: str, lesson_name: str, lesson_summary: str, retrieved_docs: list, user_id: Optional[str] = None):
    """
    Sync streaming generator kept for legacy callers. Prefer
    `agenerate_elaboration_response_stream` from inside an event loop (DEE-44).
    """
    print("INSIDE generate_elaboration_response_stream")
    logger.info(
        "Starting hikmah elaboration stream",
        extra={
            "user_id": user_id,
            "selected_text_len": len(selected_text or ""),
            "selected_text_preview": (selected_text or "")[:120],
            "context_text_len": len(context_text or ""),
            "lesson_summary_len": len(lesson_summary or ""),
            "hikmah_tree_name": hikmah_tree_name,
            "lesson_name": lesson_name,
        },
    )
    chat_model = chat_models.get_generator_model()
    messages = _build_elaboration_messages(
        selected_text, context_text, hikmah_tree_name, lesson_name, lesson_summary, retrieved_docs
    )

    for chunk in chat_model.stream(messages):
        yield getattr(chunk, "content", str(chunk) if chunk is not None else "")

    if user_id:
        _schedule_hikmah_memory_update(user_id, selected_text, hikmah_tree_name, lesson_name)


async def agenerate_elaboration_response_stream(
    selected_text: str,
    context_text: str,
    hikmah_tree_name: str,
    lesson_name: str,
    lesson_summary: str,
    retrieved_docs: list,
    user_id: Optional[str] = None,
):
    """Native async generator. Uses `chain.astream` so the worker can serve
    other concurrent SSE streams while this one waits on Anthropic tokens.
    The fire-and-forget memory thread is unchanged — it doesn't share a loop
    with the caller anyway."""
    logger.info(
        "Starting hikmah elaboration stream (async)",
        extra={
            "user_id": user_id,
            "selected_text_len": len(selected_text or ""),
            "selected_text_preview": (selected_text or "")[:120],
            "context_text_len": len(context_text or ""),
            "lesson_summary_len": len(lesson_summary or ""),
            "hikmah_tree_name": hikmah_tree_name,
            "lesson_name": lesson_name,
        },
    )
    chat_model = chat_models.get_generator_model()
    messages = _build_elaboration_messages(
        selected_text, context_text, hikmah_tree_name, lesson_name, lesson_summary, retrieved_docs
    )

    async for chunk in chat_model.astream(messages):
        yield getattr(chunk, "content", str(chunk) if chunk is not None else "")

    if user_id:
        _schedule_hikmah_memory_update(user_id, selected_text, hikmah_tree_name, lesson_name)


def _run_memory_update_sync(user_id: str, selected_text: str,
                            hikmah_tree_name: str, lesson_name: str):
    """
    Synchronous wrapper to run async memory update in a separate thread.
    This is a true "fire and forget" background task that runs independently
    of the API response thread.
    
    Note: We only pass essential context (selected_text, lesson, tree) to avoid
    overwhelming the memory agent with verbose data.
    """
    try:
        memory_logger.debug(
            "Hikmah memory update thread starting",
            extra={
                "user_id": user_id,
                "selected_text_len": len(selected_text or ""),
                "selected_text_preview": (selected_text or "")[:120],
                "hikmah_tree_name": hikmah_tree_name,
                "lesson_name": lesson_name,
            },
        )
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run the async memory update
        loop.run_until_complete(_update_hikmah_memory(
            user_id=user_id,
            selected_text=selected_text,
            hikmah_tree_name=hikmah_tree_name,
            lesson_name=lesson_name
        ))
        
        loop.close()
        
    except Exception as e:
        print(f"❌ Error in hikmah memory update background thread: {e}")
        import traceback
        traceback.print_exc()


async def _update_hikmah_memory(user_id: str, selected_text: str,
                                hikmah_tree_name: str, lesson_name: str):
    """
    Background task to update user memory after hikmah elaboration.
    Runs in a separate thread with its own event loop.
    Thread-safe and handles multiple concurrent users.
    
    Only receives essential context:
    - selected_text: What the user asked about (the key signal)
    - lesson_name: Which lesson they're in
    - hikmah_tree_name: Which educational tree they're studying
    
    This focused approach helps the agent make precise, non-redundant notes.
    """
    db = None
    try:
        from agents.models.db_config import SessionLocal
        from agents.core.universal_memory_agent import UniversalMemoryAgent

        # Create a fresh database session for this background thread
        # Important: Create session inside try block to ensure proper cleanup
        db = SessionLocal()
        
        # Initialize memory agent with the fresh session
        memory_agent = UniversalMemoryAgent(db)
        
        memory_logger.debug(
            "Updating hikmah memory",
            extra={
                "user_id": user_id,
                "selected_text_len": len(selected_text or ""),
                "selected_text_preview": (selected_text or "")[:120],
                "hikmah_tree_name": hikmah_tree_name,
                "lesson_name": lesson_name,
                "context_text_passed": False,
                "lesson_summary_passed": False,
            },
        )
        # Analyze hikmah elaboration interaction with optimized context
        result = await memory_agent.analyze_hikmah_elaboration(
            user_id=user_id,
            selected_text=selected_text,
            hikmah_tree_name=hikmah_tree_name,
            lesson_name=lesson_name
            # Note: context_text removed - it's too verbose and not needed
        )
        
        # Log success with details
        print(f"✅ Hikmah memory updated for user {user_id}")
        if result.get('notes_added'):
            print(f"   📝 Added {len(result['notes_added'])} note(s)")
        
    except Exception as e:
        print(f"❌ Error updating hikmah memory for user {user_id}: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Always close the database session, even if there's an error
        if db is not None:
            try:
                db.close()
            except Exception as close_error:
                print(f"⚠️ Error closing DB session: {close_error}")
