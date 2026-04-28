"""
LangGraph-based agentic pipeline for chat.

This replaces the hardcoded pipeline with an intelligent agent
that decides which tools to use and when.
"""

import json
import logging
from typing import AsyncGenerator, Optional

from fastapi.responses import StreamingResponse

from agents.config.agent_config import AgentConfig, DEFAULT_AGENT_CONFIG
from agents.core.chat_agent import ChatAgent
from core import utils
from core.context import correlation_id as correlation_id_ctx

logger = logging.getLogger(__name__)


# Human-readable status messages for each agent node.
#
# NOTE on `"tools": None`:
#   Per-tool status events are emitted on the `agent` node event (where the
#   AIMessage.tool_calls are first visible, BEFORE the `tools` node runs).
#   We intentionally skip a redundant generic emission on the `tools` node
#   event via `if node_msg:` in the streaming loop.
NODE_STATUS_MESSAGES = {
    "fiqh_classification": "Fiqh query detected...",
    "agent": "Agent thinking...",
    "tools": None,  # intentional: per-tool messages on 'agent' event cover this window
    "generate_response": "Preparing answer...",
    "check_early_exit": "Finalizing...",
    # Fiqh FAIR-RAG pipeline nodes
    "fiqh_subgraph": "Processing fiqh query (this may take 10-15 seconds)...",
    "generate_fiqh_response": "Preparing fiqh answer...",
    # Fiqh sub-graph stage status (fallback-only if fiqh_status_events is empty,
    # e.g. error path). Normal runs surface real per-iteration messages from
    # node_state["fiqh_status_events"] (populated by the sub-graph).
    "fiqh_decompose": "Decomposing fiqh query...",
    "fiqh_retrieve": "Retrieving fiqh documents...",
    "fiqh_filter": "Filtering evidence...",
    "fiqh_assess": "Assessing evidence sufficiency...",
    "fiqh_refine": "Refining query...",
}

# Human-readable status messages for each tool call
TOOL_STATUS_MESSAGES = {
    "check_if_non_islamic_tool": "Checking if query is within scope...",
    "translate_to_english_tool": "Translating your question...",
    "enhance_query_tool": "Enhancing your question...",
    "retrieve_shia_documents_tool": "Searching Shia sources...",
    "retrieve_sunni_documents_tool": "Searching Sunni sources...",
    "retrieve_quran_tafsir_tool": "Searching Quran and Tafsir...",
}


# Categories that trigger the FAIR-RAG fiqh path
VALID_FIQH_CATEGORIES = {"VALID_OBVIOUS", "VALID_SMALL", "VALID_LARGE", "VALID_REASONER"}


def sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event string.

    Note on extensibility: `status` events are advisory and new `step` values
    may be added over time (e.g., `starting`, `fiqh_decompose`, etc.). Clients
    SHOULD ignore unknown `step` values rather than treat them as errors.
    The non-status event contract (response_chunk, response_end,
    hadith_references, quran_references, fiqh_references, error, done) is
    stable and its payload shapes are preserved.
    """
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def chat_pipeline_streaming_agentic(
    user_query: str,
    session_id: str,
    target_language: str = "english",
    config: Optional[AgentConfig] = None
) -> StreamingResponse:
    """
    Agentic chat pipeline using LangGraph with proper SSE protocol.

    SSE Event types emitted:
      - status:            {"step": str, "message": str}   -- per node / tool call
      - response_chunk:    {"token": str}                  -- per LLM token
      - response_end:      {}                              -- after last token
      - hadith_references: [...]                           -- hadith docs JSON
      - quran_references:  [...]                           -- quran/tafsir docs JSON
      - error:             {"message": str}                -- on any error
      - done:              {}                              -- final event
    """
    logger.info("Pipeline started", extra={
        "correlation_id": correlation_id_ctx.get(),
        "session_id": session_id,
        "target_language": target_language,
    })

    agent_config = config or DEFAULT_AGENT_CONFIG
    agent = ChatAgent(agent_config)

    async def response_generator() -> AsyncGenerator[str, None]:
        assistant_text = ""
        history_written = False

        try:
            final_state = None
            emitted_tool_call_ids = set()
            fiqh_trail_emitted = False

            # Pre-flight: emit an immediate status event so the frontend shows
            # feedback during the synchronous classify_fiqh_query() LLM call
            # inside _fiqh_classification_node (which otherwise produces a
            # multi-second silent gap between request start and the first
            # node-arrival event).
            yield sse_event(
                "status",
                {"step": "starting", "message": "Checking query classification..."},
            )

            async for event in agent.astream(
                user_query=user_query,
                session_id=session_id,
                target_language=target_language,
                config=agent_config.to_dict(),
                streaming_mode=True
            ):
                for node_name, node_state in event.items():
                    logger.debug("Node traversal", extra={"correlation_id": correlation_id_ctx.get(), "node": node_name})
                    final_state = node_state

                    # Emit the node-arrival status event (may be None for 'tools'
                    # — per-tool messages on the 'agent' event cover that window).
                    node_msg = NODE_STATUS_MESSAGES.get(node_name)
                    # `fiqh_classification` runs on every query; only announce
                    # "Fiqh query detected..." when the classifier actually
                    # routed to the fiqh path. Non-fiqh outcomes fall through
                    # to the next node's status (e.g. "Agent thinking...").
                    if node_name == "fiqh_classification":
                        is_fiqh = (
                            node_state.get("is_fiqh")
                            if isinstance(node_state, dict)
                            else False
                        )
                        if not is_fiqh:
                            node_msg = None
                    if node_msg:
                        yield sse_event("status", {"step": node_name, "message": node_msg})

                    # Per-tool status events: emit only on the 'agent' node event,
                    # where the AIMessage with tool_calls is first surfaced (BEFORE
                    # the 'tools' node runs). Scanning on the 'tools' event is
                    # redundant and causes whiplash in the status stream.
                    if node_name == "agent":
                        messages = node_state.get("messages", []) if isinstance(node_state, dict) else []
                        for msg in messages:
                            if hasattr(msg, "tool_calls") and msg.tool_calls:
                                for index, tc in enumerate(msg.tool_calls):
                                    tool_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                                    tool_call_id = None
                                    if isinstance(tc, dict):
                                        tool_call_id = tc.get("id")
                                    else:
                                        tool_call_id = getattr(tc, "id", None)
                                    if not tool_call_id:
                                        tool_call_id = f"{node_name}:{index}:{tool_name}"

                                    if tool_name and tool_call_id not in emitted_tool_call_ids:
                                        emitted_tool_call_ids.add(tool_call_id)
                                        tool_msg = TOOL_STATUS_MESSAGES.get(
                                            tool_name, f"Running {tool_name}..."
                                        )
                                        yield sse_event(
                                            "status",
                                            {"step": tool_name, "message": tool_msg},
                                        )

                    # Fiqh sub-graph: the node-arrival status (keep-alive message
                    # "Processing fiqh query (this may take 10-15 seconds)...") was
                    # already emitted above via NODE_STATUS_MESSAGES. Now replay
                    # the batch of per-iteration status events the sub-graph
                    # accumulated while it ran (surfaced via Task 1).
                    if node_name == "fiqh_subgraph" and isinstance(node_state, dict):
                        fiqh_status_events = node_state.get("fiqh_status_events") or []
                        if fiqh_status_events:
                            fiqh_trail_emitted = True
                            for ev in fiqh_status_events:
                                if not isinstance(ev, dict):
                                    continue
                                step = ev.get("step")
                                message = ev.get("message")
                                if step and message:
                                    yield sse_event(
                                        "status",
                                        {"step": step, "message": message},
                                    )

            if final_state is None:
                yield sse_event("error", {"message": "No response generated."})
                yield sse_event("done", {})
                return

            runtime_session_id = final_state.get("runtime_session_id", session_id)

            # --- Early exit (fiqh / non-Islamic) ---
            if final_state.get("early_exit_message"):
                assistant_text = final_state["early_exit_message"]
                yield sse_event("response_chunk", {"token": assistant_text})
                yield sse_event("response_end", {})
                from services import chat_persistence_service

                chat_persistence_service.append_turn_to_runtime_history(
                    runtime_session_id=runtime_session_id,
                    user_query=user_query,
                    assistant_text=assistant_text,
                )
                history_written = True
                yield sse_event("done", {})
                return

            # --- Fiqh FAIR-RAG streaming path ---
            if final_state.get("fiqh_category") in VALID_FIQH_CATEGORIES:
                from modules.fiqh.generator import (
                    _prompt as fiqh_prompt,
                    _format_evidence,
                    _build_references_section,
                    INSUFFICIENT_WARNING,
                    FATWA_DISCLAIMER,
                )
                from core import chat_models
                from core.utils import format_fiqh_references_as_json

                # Fallback-only: if the retrospective fiqh trail was NOT emitted
                # (e.g. sub-graph raised before any node ran and returned an
                # empty fiqh_status_events list), emit the pre-canned stage
                # messages as a best-effort progress breadcrumb. Normal runs
                # emit the real per-iteration events during the node loop.
                if not fiqh_trail_emitted:
                    fiqh_stages = [
                        ("fiqh_decompose", "Decomposing fiqh query..."),
                        ("fiqh_retrieve", "Retrieving fiqh documents..."),
                        ("fiqh_filter", "Filtering evidence..."),
                        ("fiqh_assess", "Assessing evidence sufficiency..."),
                    ]
                    for stage_step, stage_msg in fiqh_stages:
                        yield sse_event("status", {"step": stage_step, "message": stage_msg})

                yield sse_event("status", {"step": "generate_fiqh_response", "message": "Preparing fiqh answer..."})

                fiqh_docs = final_state.get("fiqh_filtered_docs", [])
                sea_result = final_state.get("fiqh_sea_result")
                is_sufficient = getattr(sea_result, "verdict", "INSUFFICIENT") == "SUFFICIENT"

                if not fiqh_docs:
                    # No evidence retrieved — emit fallback message
                    fallback = (
                        "I was unable to retrieve relevant rulings for this question. "
                        "Please consult Sistani's official resources at sistani.org "
                        "or contact his office directly." + FATWA_DISCLAIMER
                    )
                    assistant_text = fallback
                    yield sse_event("response_chunk", {"token": fallback})
                    yield sse_event("response_end", {})
                else:
                    # Stream fiqh answer token-by-token using fiqh-specific prompt (D-06)
                    model = chat_models.get_generator_model()
                    chain = fiqh_prompt | model
                    response_tokens = []
                    for chunk in chain.stream({
                        "query": user_query,
                        "evidence": _format_evidence(fiqh_docs),
                    }):
                        token = getattr(chunk, "content", str(chunk) if chunk is not None else "")
                        if token:
                            response_tokens.append(token)
                            yield sse_event("response_chunk", {"token": token})

                    answer_text = "".join(response_tokens).strip()

                    # Post-process: append ## Sources, optional insufficient warning, fatwa disclaimer
                    references_section = _build_references_section(answer_text, fiqh_docs)
                    if references_section:
                        yield sse_event("response_chunk", {"token": references_section})

                    if not is_sufficient:
                        yield sse_event("response_chunk", {"token": INSUFFICIENT_WARNING})
                        answer_text += INSUFFICIENT_WARNING

                    yield sse_event("response_chunk", {"token": FATWA_DISCLAIMER})
                    answer_text += FATWA_DISCLAIMER
                    if references_section:
                        answer_text += references_section

                    assistant_text = answer_text
                    yield sse_event("response_end", {})

                # Persist fiqh answer to conversation history
                if assistant_text and not history_written:
                    from services import chat_persistence_service
                    chat_persistence_service.append_turn_to_runtime_history(
                        runtime_session_id=runtime_session_id,
                        user_query=user_query,
                        assistant_text=assistant_text,
                    )
                    history_written = True

                # Emit fiqh_references SSE event (D-14, INTG-05)
                if fiqh_docs:
                    fiqh_json = format_fiqh_references_as_json(fiqh_docs)
                    yield sse_event("fiqh_references", {"references": fiqh_json})

            # --- Existing hadith/non-fiqh streaming path ---
            else:
                hadith_docs = final_state.get("retrieved_docs", [])
                quran_docs = final_state.get("quran_docs", [])
                all_docs = hadith_docs + quran_docs

                if all_docs or final_state.get("final_response"):
                    if final_state.get("final_response"):
                        assistant_text = final_state["final_response"]
                        yield sse_event("response_chunk", {"token": assistant_text})
                        yield sse_event("response_end", {})
                    else:
                        from core import chat_models, prompt_templates
                        from core.memory import make_history

                        yield sse_event("status", {"step": "generate_response", "message": "Preparing answer..."})

                        references = utils.compact_format_references(all_docs)
                        chat_model = chat_models.get_generator_model()
                        prompt = prompt_templates.generator_prompt_template
                        chain = prompt | chat_model
                        history_messages = make_history(runtime_session_id).messages

                        response_tokens = []
                        for chunk in chain.stream(
                            {
                                "target_language": target_language,
                                "query": user_query,
                                "references": references,
                                "chat_history": history_messages,
                            },
                        ):
                            token = getattr(chunk, "content", str(chunk) if chunk is not None else "")
                            if token:
                                response_tokens.append(token)
                                yield sse_event("response_chunk", {"token": token})

                        assistant_text = "".join(response_tokens).strip()
                        yield sse_event("response_end", {})
                else:
                    errors = final_state.get("errors", []) if isinstance(final_state, dict) else []
                    if any("quran_tafsir retrieval error" in error for error in errors):
                        assistant_text = "I couldn't access the Quran and Tafsir sources I needed just now, so I can't answer this reliably."
                    elif any("retrieval error" in error for error in errors):
                        assistant_text = "I couldn't access enough source material to answer this reliably right now."
                    else:
                        assistant_text = "I apologize, but I couldn't retrieve enough information to answer your question."
                    yield sse_event("response_chunk", {"token": assistant_text})
                    yield sse_event("response_end", {})

                if assistant_text and not history_written:
                    from services import chat_persistence_service

                    chat_persistence_service.append_turn_to_runtime_history(
                        runtime_session_id=runtime_session_id,
                        user_query=user_query,
                        assistant_text=assistant_text,
                    )
                    history_written = True

                if hadith_docs:
                    hadith_json = utils.format_references_as_json(hadith_docs)
                    yield sse_event("hadith_references", {"references": hadith_json})

                if quran_docs:
                    quran_json = utils.format_quran_references_as_json(quran_docs)
                    yield sse_event("quran_references", {"references": quran_json})

            yield sse_event("done", {})

        except Exception as e:
            logger.error("Pipeline error", exc_info=True, extra={
                "correlation_id": correlation_id_ctx.get(),
                "session_id": session_id,
            })
            if assistant_text and not history_written:
                try:
                    from services import chat_persistence_service

                    chat_persistence_service.append_turn_to_runtime_history(
                        runtime_session_id=final_state.get("runtime_session_id", session_id) if final_state else session_id,
                        user_query=user_query,
                        assistant_text=assistant_text,
                    )
                except Exception as memory_exc:
                    logger.warning("Failed to append runtime history after error", exc_info=True, extra={
                        "correlation_id": correlation_id_ctx.get(),
                        "session_id": session_id,
                    })
            yield sse_event("error", {"message": str(e)})
            yield sse_event("done", {})

    return StreamingResponse(response_generator(), media_type="text/event-stream")


def chat_pipeline_agentic(
    user_query: str,
    session_id: str,
    target_language: str = "english",
    config: Optional[AgentConfig] = None
) -> dict:
    """
    Non-streaming agentic chat pipeline.

    Args:
        user_query: The user's question
        session_id: Session identifier
        target_language: User's preferred language
        config: Optional AgentConfig for customization

    Returns:
        Dictionary with response and metadata
    """
    logger.info("Pipeline started", extra={
        "correlation_id": correlation_id_ctx.get(),
        "session_id": session_id,
        "target_language": target_language,
    })

    agent_config = config or DEFAULT_AGENT_CONFIG
    agent = ChatAgent(agent_config)

    try:
        final_state = agent.invoke(
            user_query=user_query,
            session_id=session_id,
            target_language=target_language,
            config=agent_config.to_dict()
        )
    except Exception:
        logger.error("Pipeline error", exc_info=True, extra={
            "correlation_id": correlation_id_ctx.get(),
            "session_id": session_id,
        })
        raise

    response_data = {
        "response": final_state.get("final_response", "Unable to generate response"),
        "retrieved_docs": final_state.get("retrieved_docs", []),
        "quran_docs": final_state.get("quran_docs", []),
        "metadata": {
            "iterations": final_state.get("iterations", 0),
            "classification_checked": final_state.get("classification_checked", False),
            "query_enhanced": final_state.get("query_enhanced", False),
            "retrieval_completed": final_state.get("retrieval_completed", False),
            "shia_docs_count": final_state.get("shia_docs_count", 0),
            "sunni_docs_count": final_state.get("sunni_docs_count", 0),
            "quran_docs_count": final_state.get("quran_docs_count", 0),
            "errors": final_state.get("errors", [])
        }
    }

    return response_data
