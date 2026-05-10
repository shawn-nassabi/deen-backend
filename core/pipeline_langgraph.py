"""
LangGraph-based agentic pipeline for chat.

This replaces the hardcoded pipeline with an intelligent agent
that decides which tools to use and when.
"""

import asyncio
import json
from typing import AsyncGenerator, Optional

from fastapi.responses import StreamingResponse

from agents.config.agent_config import AgentConfig, DEFAULT_AGENT_CONFIG
from agents.core.chat_agent import ChatAgent
from core import utils
import logging
from core.context import correlation_id as correlation_id_ctx, fiqh_status_queue
from core.sentry import record_cache_metrics_breadcrumb

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


def _emit_cache_metrics_breadcrumb(final_state) -> None:
    """Compute per-turn cache efficiency ratio and emit Sentry breadcrumb.

    Phase 19 (D-05, D-06, D-08, D-09):
      - Sum across all _agent_node iterations is read from ChatState fields
        (cache_creation_tokens_total, cache_read_tokens_total). D-07 option b.
      - Cold-cache (denominator 0) -> 0.0, NOT ZeroDivisionError. Required
        explicitly by ROADMAP.md Phase 19 success criterion 2.
      - Helper at core.sentry is a no-op when SENTRY_ENABLED is false (D-09),
        so this caller can fire unconditionally on every done boundary.
      - final_state may be None (line 201 path) or a dict missing the new
        fields (defensive against legacy/test ChatState construction).

    NOTE: Only _agent_node LLM calls are counted. Generator nodes
    (_generate_response_node, _generate_fiqh_response_node) are excluded by
    design because they run outside the iterative tool-calling loop where
    prompt cache warm-up occurs.
    """
    if final_state is None or not isinstance(final_state, dict):
        sum_creation = 0
        sum_read = 0
        n_iter = 0
    else:
        sum_creation = final_state.get("cache_creation_tokens_total", 0) or 0
        sum_read = final_state.get("cache_read_tokens_total", 0) or 0
        n_iter = final_state.get("iterations", 0) or 0
    total = sum_creation + sum_read
    ratio = (sum_read / total) if total > 0 else 0.0  # D-06 cold-cache guard
    record_cache_metrics_breadcrumb(
        cache_efficiency_ratio=ratio,
        cache_read_tokens=sum_read,
        cache_creation_tokens=sum_creation,
        iterations=n_iter,
    )


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

        # Producer/consumer multiplex: agent.astream events AND fiqh sub-graph
        # real-time status events (pushed via the fiqh_status_queue contextvar
        # from inside sub-graph nodes) flow through a single output queue. The
        # consumer loop below yields items as they arrive, so status events
        # emitted DURING the ~10-15s fiqh sub-graph window reach the SSE
        # stream in real time instead of being batched at sub-graph
        # completion. See .planning/quick/260509-3cd-realtime-fiqh-sse-status-events/.
        output_queue: asyncio.Queue = asyncio.Queue()
        queue_token = fiqh_status_queue.set(output_queue)

        # Mutable boxes for closure-shared state (producer task writes;
        # consumer + post-loop body read).
        state_box: dict = {"final_state": None, "exception": None}
        fiqh_realtime_count: dict = {"v": 0}
        fiqh_trail_emitted_box: dict = {"v": False}

        # Sentinel marking producer completion (or failure).
        _AGENT_DONE = object()

        async def _agent_producer() -> None:
            """Drive agent.astream and translate node events into SSE strings.

            SSE strings are pushed into output_queue. fiqh sub-graph nodes
            push status dicts into the same queue via the contextvar; the
            consumer loop below dispatches based on item type.
            """
            try:
                # Pre-flight: emit an immediate status event so the frontend
                # shows feedback during the synchronous classify_fiqh_query()
                # LLM call inside _fiqh_classification_node (otherwise the
                # first ~2-4s would be silent).
                await output_queue.put(sse_event(
                    "status",
                    {"step": "starting", "message": "Checking query classification..."},
                ))

                emitted_tool_call_ids: set = set()

                async for event in agent.astream(
                    user_query=user_query,
                    session_id=session_id,
                    target_language=target_language,
                    config=agent_config.to_dict(),
                    streaming_mode=True
                ):
                    for node_name, node_state in event.items():
                        logger.debug("Node traversal", extra={"correlation_id": correlation_id_ctx.get(), "node": node_name})
                        state_box["final_state"] = node_state

                        # Node-arrival status. Skip 'fiqh_subgraph' here: the
                        # keep-alive message is now pushed via the contextvar
                        # queue from _call_fiqh_subgraph_node entry (real-time
                        # at sub-graph start, not after the 10-15s wait).
                        if node_name != "fiqh_subgraph":
                            node_msg = NODE_STATUS_MESSAGES.get(node_name)
                            # `fiqh_classification` runs on every query; only
                            # announce "Fiqh query detected..." when the
                            # classifier actually routed to the fiqh path.
                            if node_name == "fiqh_classification":
                                is_fiqh = (
                                    node_state.get("is_fiqh")
                                    if isinstance(node_state, dict)
                                    else False
                                )
                                if not is_fiqh:
                                    node_msg = None
                            if node_msg:
                                await output_queue.put(sse_event(
                                    "status",
                                    {"step": node_name, "message": node_msg},
                                ))

                        # Per-tool status events: emit only on the 'agent'
                        # node event, where the AIMessage with tool_calls is
                        # first surfaced (BEFORE the 'tools' node runs).
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
                                            await output_queue.put(sse_event(
                                                "status",
                                                {"step": tool_name, "message": tool_msg},
                                            ))

                        # Fiqh sub-graph: real-time status events should have
                        # already been pushed by sub-graph nodes via the
                        # contextvar queue while the sub-graph ran. If the
                        # real-time path emitted something, suppress the
                        # retrospective replay (it would only duplicate). If
                        # not (e.g. sub-graph raised before any node ran, so
                        # status_events is empty AND fiqh_realtime_count == 0),
                        # the canned-stages fallback below the consumer loop
                        # still fires — same safety net as before.
                        if node_name == "fiqh_subgraph" and isinstance(node_state, dict):
                            if fiqh_realtime_count["v"] > 0:
                                # Real-time path covered the trail.
                                fiqh_trail_emitted_box["v"] = True
                            else:
                                fiqh_status_events = node_state.get("fiqh_status_events") or []
                                if fiqh_status_events:
                                    fiqh_trail_emitted_box["v"] = True
                                    for ev in fiqh_status_events:
                                        if not isinstance(ev, dict):
                                            continue
                                        step = ev.get("step")
                                        message = ev.get("message")
                                        if step and message:
                                            await output_queue.put(sse_event(
                                                "status",
                                                {"step": step, "message": message},
                                            ))
            except Exception as exc:
                state_box["exception"] = exc
            finally:
                await output_queue.put(_AGENT_DONE)

        producer_task = asyncio.create_task(_agent_producer())

        try:
            # Consumer loop: yield items as they arrive. Items are either
            # SSE-encoded strings (from the producer) or raw status dicts
            # (from fiqh sub-graph nodes via the contextvar). The dict path
            # tracks fiqh_realtime_count so the producer can suppress the
            # retrospective replay.
            while True:
                item = await output_queue.get()
                if item is _AGENT_DONE:
                    break
                if isinstance(item, dict) and "step" in item and "message" in item:
                    fiqh_realtime_count["v"] += 1
                    yield sse_event(
                        "status",
                        {"step": item["step"], "message": item["message"]},
                    )
                elif isinstance(item, str):
                    yield item
                else:
                    logger.debug("Unexpected output_queue item type", extra={
                        "correlation_id": correlation_id_ctx.get(),
                        "type": type(item).__name__,
                    })

            # Surface any exception raised inside the producer.
            await producer_task
            if state_box["exception"] is not None:
                raise state_box["exception"]

            final_state = state_box["final_state"]
            fiqh_trail_emitted = fiqh_trail_emitted_box["v"]

            if final_state is None:
                yield sse_event("error", {"message": "No response generated."})
                _emit_cache_metrics_breadcrumb(final_state)
                yield sse_event("done", {})
                return

            runtime_session_id = final_state.get("runtime_session_id", session_id)

            # --- Early exit (fiqh / non-Islamic) ---
            if final_state.get("early_exit_message"):
                assistant_text = final_state["early_exit_message"]
                yield sse_event("response_chunk", {"token": assistant_text})
                yield sse_event("response_end", {})
                from services import chat_persistence_service

                await chat_persistence_service.aappend_turn_to_runtime_history(
                    runtime_session_id=runtime_session_id,
                    user_query=user_query,
                    assistant_text=assistant_text,
                )
                history_written = True
                _emit_cache_metrics_breadcrumb(final_state)
                yield sse_event("done", {})
                return

            # --- Fiqh FAIR-RAG streaming path ---
            if final_state.get("fiqh_category") in VALID_FIQH_CATEGORIES:
                from modules.fiqh.generator import (
                    _build_messages as fiqh_build_messages,
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
                    fiqh_messages = fiqh_build_messages(
                        query=user_query,
                        evidence=_format_evidence(fiqh_docs),
                    )
                    response_tokens = []
                    async for chunk in model.astream(fiqh_messages):
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
                    await chat_persistence_service.aappend_turn_to_runtime_history(
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
                        from core.memory import amake_history

                        yield sse_event("status", {"step": "generate_response", "message": "Preparing answer..."})

                        references = utils.compact_format_references(all_docs)
                        chat_model = chat_models.get_generator_model()
                        history_messages = await amake_history(runtime_session_id).aget_messages()
                        messages = prompt_templates.generator_messages(
                            query=user_query,
                            references=references,
                            target_language=target_language,
                            chat_history=history_messages,
                        )

                        response_tokens = []
                        async for chunk in chat_model.astream(messages):
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

                    await chat_persistence_service.aappend_turn_to_runtime_history(
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

            _emit_cache_metrics_breadcrumb(final_state)
            yield sse_event("done", {})

        except Exception as e:
            logger.error("Pipeline error", exc_info=True, extra={
                "correlation_id": correlation_id_ctx.get(),
                "session_id": session_id,
            })
            if assistant_text and not history_written:
                try:
                    from services import chat_persistence_service

                    await chat_persistence_service.aappend_turn_to_runtime_history(
                        runtime_session_id=final_state.get("runtime_session_id", session_id) if final_state else session_id,
                        user_query=user_query,
                        assistant_text=assistant_text,
                    )
                except Exception as memory_exc:
                    logger.warning("Failed to append runtime history after error", exc_info=True, extra={
                        "correlation_id": correlation_id_ctx.get(),
                        "session_id": session_id,
                    })
            yield sse_event("error", {"message": "An error occurred. Please try again."})
            _emit_cache_metrics_breadcrumb(final_state)
            yield sse_event("done", {})
        finally:
            # Always release the contextvar so a later request on this asyncio
            # task chain can't accidentally inherit a closed queue. The
            # producer task has already drained itself by the time we get
            # here (consumer loop only exits on _AGENT_DONE, which the
            # producer's own finally guarantees) so cancellation is unneeded.
            try:
                fiqh_status_queue.reset(queue_token)
            except Exception:
                pass

    return StreamingResponse(response_generator(), media_type="text/event-stream")


async def chat_pipeline_agentic(
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

    final_state = await agent.ainvoke(
        user_query=user_query,
        session_id=session_id,
        target_language=target_language,
        config=agent_config.to_dict()
    )

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
