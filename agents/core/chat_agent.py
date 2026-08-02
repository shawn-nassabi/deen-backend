"""
LangGraph-based agentic chat agent for Islamic education.

This agent plans retrieval iteratively so it can choose between
Shia hadith, Sunni hadith, and Quran/Tafsir evidence per query.
"""

import asyncio
import json
import os
from typing import Any, Dict, List, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from core.resilience import anthropic_retry
from agents.config.agent_config import AgentConfig, DEFAULT_AGENT_CONFIG
from agents.prompts.agent_prompts import (
    AGENT_SYSTEM_PROMPT,
    EARLY_EXIT_FIQH,
)
from agents.state.chat_state import ChatState
from agents.tools import (
    enhance_query_tool,
    retrieve_quran_tafsir_tool,
    retrieve_shia_documents_tool,
    retrieve_sunni_documents_tool,
    translate_to_english_tool,
)
from agents.tools.retrieval_tools import retrieve_quran_tafsir_tool_cached
from core import prompt_templates
from core import utils
from core.config import ANTHROPIC_API_KEY
import logging
from core.context import correlation_id as correlation_id_ctx
from core.chat_models import make_cached_system_message
from core.token_telemetry import record_llm_usage

logger = logging.getLogger(__name__)


@anthropic_retry
async def _retry_ainvoke(llm, messages):
    """Module-level helper so @anthropic_retry can absorb transient errors
    around LangGraph node LLM calls without each node redefining its own
    retry-decorated wrapper. Each invocation is a fresh retry context."""
    return await llm.ainvoke(messages)


def _clamp_doc_count(value, lo: int, hi: int) -> int:
    """Bound an agent-supplied num_documents to [lo, hi] (token-cost Phase 1).

    The tool signatures accept bare ints and the LLM controls the value, so
    without this an over-eager plan could request arbitrarily many documents.
    Falls back to `lo` on non-numeric input.
    """
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return lo


class ChatAgent:
    """
    LangGraph-based agentic chat system for Islamic education.
    """

    def __init__(self, config: AgentConfig = None):
        self.config = config or DEFAULT_AGENT_CONFIG
        # check_if_non_islamic_tool is deliberately NOT bound (token-cost
        # Phase 1, DEE-60): intent classification already runs
        # deterministically on every request in _fiqh_classification_node,
        # so the agent-side tool was pure duplication — its schema cost
        # ~1.3k chars on every agent call and each use re-ran the intent
        # classifier a second time.
        self.tools = [
            translate_to_english_tool,
            enhance_query_tool,
            retrieve_shia_documents_tool,
            retrieve_sunni_documents_tool,
            retrieve_quran_tafsir_tool,
        ]
        self.llm = self._create_llm_with_tools()
        self.graph = self._build_graph()
        self.checkpointer = MemorySaver()
        self.compiled_graph = self.graph.compile(checkpointer=self.checkpointer)

    def _create_llm_with_tools(self):
        llm = ChatAnthropic(
            model=self.config.model.agent_model,
            api_key=ANTHROPIC_API_KEY,
            temperature=self.config.model.temperature,
            max_tokens=self.config.model.max_tokens,
            # Token-cost DEE-60 Phase 4: SDK retries 5 -> 2 (calls are also
            # wrapped in @anthropic_retry x2 => worst case 6 attempts, not 18).
            max_retries=2,
            timeout=60,
        )
        # Build a bind_tools list with the last tool replaced by the cached Anthropic dict.
        # self.tools keeps callable objects for ToolNode; this list is only for bind_tools.
        bind_tools_list = [
            translate_to_english_tool,
            enhance_query_tool,
            retrieve_shia_documents_tool,
            retrieve_sunni_documents_tool,
            retrieve_quran_tafsir_tool_cached,
        ]
        return llm.bind_tools(bind_tools_list)

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(ChatState)
        workflow.add_node("fiqh_classification", self._fiqh_classification_node)
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("tools", self._tool_node)
        workflow.add_node("generate_response", self._generate_response_node)
        workflow.add_node("check_early_exit", self._check_early_exit_node)
        workflow.add_node("fiqh_subgraph", self._call_fiqh_subgraph_node)
        workflow.add_node("generate_fiqh_response", self._generate_fiqh_response_node)

        workflow.set_entry_point("fiqh_classification")
        workflow.add_conditional_edges(
            "fiqh_classification",
            self._route_after_fiqh_check,
            {
                "fiqh": "fiqh_subgraph",
                "exit": "check_early_exit",
                "continue": "agent",
            },
        )
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "continue": "tools",
                "generate": "generate_response",
                "exit": "check_early_exit",
                "end": END,
            },
        )
        workflow.add_edge("tools", "agent")
        workflow.add_edge("generate_response", END)
        workflow.add_edge("check_early_exit", END)
        workflow.add_edge("fiqh_subgraph", "generate_fiqh_response")
        workflow.add_edge("generate_fiqh_response", END)
        return workflow

    async def _fiqh_classification_node(self, state: ChatState) -> dict:
        # DEE-12: deterministic intent classification runs first so casual / non-Islamic
        # messages route to the early-exit node reliably — not left to the agent's
        # discretionary tool calls. Fiqh classification only runs for islamic intent.
        logger.debug("Classification started", extra={"correlation_id": correlation_id_ctx.get()})
        result: dict = {"classification_checked": True}

        try:
            from modules.classification.classifier import aclassify_intent

            intent = await aclassify_intent(state["user_query"], state.get("session_id"))
            result["is_non_islamic"] = intent == "non_islamic"
            result["is_casual"] = intent == "casual"
            logger.debug("Intent classification complete", extra={"correlation_id": correlation_id_ctx.get(), "intent": intent})
        except Exception as exc:
            logger.error("Intent classification error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
            result["is_non_islamic"] = False
            result["is_casual"] = False

        # Casual / non-Islamic messages exit before retrieval — skip fiqh classification.
        if result["is_non_islamic"] or result["is_casual"]:
            result["fiqh_category"] = ""
            result["is_fiqh"] = False
            return result

        try:
            from modules.fiqh.classifier import aclassify_fiqh_query

            category = await aclassify_fiqh_query(state["user_query"])
            result["fiqh_category"] = category
            result["is_fiqh"] = category.startswith("VALID_")
            logger.debug("Fiqh classification complete", extra={"correlation_id": correlation_id_ctx.get(), "fiqh_category": category, "is_fiqh": result["is_fiqh"]})
        except Exception as exc:
            logger.error("Fiqh classification error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
            result["fiqh_category"] = ""
            result["is_fiqh"] = False
            result["errors"] = state.get("errors", []) + [f"Fiqh classification error: {str(exc)}"]

        return result

    def _route_after_fiqh_check(self, state: ChatState) -> Literal["fiqh", "exit", "continue"]:
        # DEE-12: casual / non-Islamic intent exits deterministically before retrieval.
        if state.get("is_casual") or state.get("is_non_islamic"):
            logger.debug("Routing to early exit: casual/non-Islamic intent", extra={"correlation_id": correlation_id_ctx.get()})
            return "exit"
        category = state.get("fiqh_category", "")
        if category in {"VALID_OBVIOUS", "VALID_SMALL", "VALID_LARGE", "VALID_REASONER"}:
            logger.debug("Routing to fiqh sub-graph", extra={"correlation_id": correlation_id_ctx.get(), "fiqh_category": category})
            return "fiqh"
        if category == "UNETHICAL":
            logger.debug("Routing to early exit: unethical query", extra={"correlation_id": correlation_id_ctx.get()})
            return "exit"
        # OUT_OF_SCOPE_FIQH = general Islamic question (history, theology, etc.)
        # — let the regular hadith/Quran agent handle it
        logger.debug("Routing to agent: not a fiqh query", extra={"correlation_id": correlation_id_ctx.get()})
        return "continue"

    async def _agent_node(self, state: ChatState) -> ChatState:
        logger.debug("Agent node iteration", extra={"correlation_id": correlation_id_ctx.get(), "iteration": state["iterations"]})

        state["iterations"] += 1
        if state["iterations"] > self.config.max_iterations:
            logger.debug("Max iterations reached", extra={"correlation_id": correlation_id_ctx.get(), "max_iterations": self.config.max_iterations})
            state["should_end"] = True
            state["errors"].append(f"Max iterations ({self.config.max_iterations}) reached")
            return state

        def _filter_spurious(msgs):
            # D-08: filter spurious empty AIMessages emitted by Claude in tool-calling
            # sequences. AIMessage(content="", tool_calls=[...]) is valid (Claude
            # tool-call request) — preserved. Empty content with no tool_calls is
            # spurious — filtered out.
            return [
                msg for msg in msgs
                if not (
                    isinstance(msg, AIMessage)
                    and msg.content == ""
                    and not getattr(msg, "tool_calls", None)
                )
            ]

        if os.getenv("AGENT_CACHE_V2", "1") != "0":
            # Token-cost DEE-60 Phase 3: append-only prompt construction.
            # The human turn (initial message on iteration 1, iteration
            # summary afterwards) is PERSISTED into state so iteration N+1's
            # rendered request is an exact byte-prefix extension of iteration
            # N's; the system prompt is sent on EVERY iteration
            # (byte-identical — previously iteration >= 2 sent no system at
            # all, forfeiting the tools+system cache prefix). A rolling
            # cache_control breakpoint rides the newest human message; older
            # markers are swept to respect Anthropic's 4-breakpoint budget
            # (tools + system + newest message = 3 used).
            self._sweep_cache_markers(state["messages"])
            human_text = (
                self._build_initial_user_message(state)
                if state["iterations"] == 1
                else self._build_iteration_summary(state)
            )
            state["messages"].append(HumanMessage(content=[
                {"type": "text", "text": human_text, "cache_control": {"type": "ephemeral"}}
            ]))
            messages = _filter_spurious(list(state["messages"]))
            messages.insert(0, make_cached_system_message(AGENT_SYSTEM_PROMPT))
        else:
            # Legacy (AGENT_CACHE_V2=0): human turns stay local to this call;
            # system prompt only on iteration 1.
            messages = _filter_spurious(list(state["messages"]))
            if state["iterations"] == 1:
                messages.insert(0, make_cached_system_message(AGENT_SYSTEM_PROMPT))
                messages.append(HumanMessage(content=self._build_initial_user_message(state)))
            else:
                messages.append(HumanMessage(content=self._build_iteration_summary(state)))

        try:
            response = await _retry_ainvoke(self.llm, messages)
            # Cache metrics: use response_metadata["usage"] (raw Anthropic dict).
            # Do NOT use the LangChain usage wrapper — it double-counts cached tokens
            # in streaming paths (GitHub #32818).
            _usage = (response.response_metadata or {}).get("usage", {})
            _cache_creation = _usage.get("cache_creation_input_tokens", 0) or 0
            _cache_read = _usage.get("cache_read_input_tokens", 0) or 0
            record_llm_usage("agent", response)
            logger.debug(
                "Agent LLM cache metrics",
                extra={
                    "correlation_id": correlation_id_ctx.get(),
                    "cache_hit": _cache_read > 0,
                    "cache_creation_tokens": _cache_creation,
                    "cache_read_tokens": _cache_read,
                },
            )
            state["messages"].append(response)
            # Phase 19 (D-05, D-07 option b): accumulate per-turn cache tokens.
            # Sum across all iterations; ratio computed once at SSE done in pipeline_langgraph.
            state["cache_creation_tokens_total"] = state.get("cache_creation_tokens_total", 0) + _cache_creation
            state["cache_read_tokens_total"] = state.get("cache_read_tokens_total", 0) + _cache_read
            if not getattr(response, "tool_calls", None) and self._has_any_documents(state):
                state["ready_to_answer"] = True
        except Exception as exc:
            logger.error("Agent node error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
            state["errors"].append(f"Agent error: {str(exc)}")
            state["should_end"] = True

        return state

    async def _tool_node(self, state: ChatState) -> ChatState:
        logger.debug("Tool node executing", extra={"correlation_id": correlation_id_ctx.get()})
        last_message = state["messages"][-1] if state["messages"] else None

        if last_message is None or not getattr(last_message, "tool_calls", None):
            logger.debug("Tool node: no tool calls found", extra={"correlation_id": correlation_id_ctx.get()})
            return state

        self._apply_tool_call_defaults(state, last_message.tool_calls)
        tool_node = ToolNode(self.tools)
        # Every bound tool is now `@tool async def` (DEE-41), so ToolNode runs
        # them via .ainvoke and they cooperatively yield while waiting on
        # retrieval / classification / enhancement / translation.
        result = await tool_node.ainvoke(state)
        result_messages = result.get("messages", [])

        for message in result_messages:
            if not hasattr(message, "name"):
                continue

            tool_name = message.name
            result_data = self._parse_tool_payload(message.content)
            logger.debug("Tool executed", extra={"correlation_id": correlation_id_ctx.get(), "tool_name": tool_name})

            if tool_name == "check_if_non_islamic_tool":
                state["is_non_islamic"] = result_data.get("is_non_islamic", False)
                state["is_casual"] = result_data.get("is_casual", False)
                state["classification_checked"] = True
                continue

            if tool_name == "translate_to_english_tool":
                translated_text = result_data.get("translated_text") or state["working_query"]
                original_text = result_data.get("original_text") or state["working_query"]
                source_language = (result_data.get("source_language") or "").strip().lower()
                state["working_query"] = translated_text
                state["is_translated"] = bool(source_language and source_language != "english")
                state["original_language"] = source_language or None
                if translated_text != original_text:
                    state["enhanced_query"] = translated_text
                continue

            if tool_name == "enhance_query_tool":
                enhanced_query = result_data.get("enhanced_query") or state["working_query"]
                state["enhanced_query"] = enhanced_query
                state["query_enhanced"] = True
                state["working_query"] = enhanced_query
                continue

            if tool_name in {
                "retrieve_shia_documents_tool",
                "retrieve_sunni_documents_tool",
                "retrieve_quran_tafsir_tool",
            }:
                self._record_retrieval_result(state, result_data, tool_name)
                # Token-cost DEE-60 Phase 2: full docs are now in state
                # (retrieved_docs / quran_docs — the generation step's only
                # source); rewrite the ToolMessage the PLANNER sees to a
                # compact view before it enters state["messages"] and gets
                # re-sent on every subsequent agent iteration.
                self._compact_tool_message(message, result_data)

        if result_messages:
            state["messages"].extend(result_messages)
        return state

    @staticmethod
    def _sweep_cache_markers(messages) -> None:
        """Strip cache_control from previously persisted message blocks so at
        most one messages-tier breakpoint (the newest human message) exists
        per request (token-cost DEE-60 Phase 3). Only touches block-form
        content we created; plain-string history and ToolMessages pass by."""
        for msg in messages:
            content = getattr(msg, "content", None)
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict):
                    block.pop("cache_control", None)

    @staticmethod
    def _compact_tool_message(message, result_data: Dict[str, Any]) -> None:
        """Replace a retrieval ToolMessage's content with a compact planner
        view: source, count, query, and per-doc id/title/snippet.

        The planner only needs coverage + enough signal to judge evidence
        sufficiency; the full texts (plus Arabic) were costing thousands of
        re-sent tokens per iteration while generation never reads messages.
        `ensure_ascii=False` avoids 6x \\uXXXX inflation on Arabic snippets.
        Kill-switch: TOOLMSG_COMPACT=0 restores the raw payload.
        """
        if os.getenv("TOOLMSG_COMPACT", "1") == "0":
            return
        docs = result_data.get("documents", []) or []
        compact_docs = []
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            md = doc.get("metadata", {}) or {}
            compact_docs.append({
                "id": doc.get("hadith_id") or doc.get("chunk_id"),
                "title": md.get("book_title") or md.get("surah_name"),
                "chapter": md.get("chapter_title") or md.get("verses_covered"),
                "number": md.get("hadith_no"),
                "sect": md.get("sect"),
                "snippet": (doc.get("page_content_en") or "")[:300],
            })
        payload = {
            "source": result_data.get("source"),
            "count": result_data.get("count", len(docs)),
            "query_used": result_data.get("query_used"),
            "documents": compact_docs,
        }
        if result_data.get("error"):
            payload["error"] = result_data["error"]
        message.content = json.dumps(payload, ensure_ascii=False)

    async def _generate_response_node(self, state: ChatState) -> ChatState:
        logger.debug("Generating final response", extra={"correlation_id": correlation_id_ctx.get()})

        all_docs = state["retrieved_docs"] + state.get("quran_docs", [])
        references = utils.compact_format_references(all_docs)
        generation_messages = prompt_templates.generator_messages(
            query=state["user_query"],
            references=references,
            target_language=state["target_language"],
        )

        try:
            from core.chat_models import get_generator_model

            llm = get_generator_model()
            response = await _retry_ainvoke(llm, generation_messages)
            record_llm_usage("generation_nonstream", response)
            state["final_response"] = response.content
            state["response_generated"] = True
            logger.debug("Response generated", extra={"correlation_id": correlation_id_ctx.get(), "response_chars": len(response.content)})
        except Exception as exc:
            logger.error("Response generation error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
            state["errors"].append(f"Response generation error: {str(exc)}")
            state["final_response"] = "I apologize, but I encountered an error generating the response."

        return state

    async def _check_early_exit_node(self, state: ChatState) -> dict:
        logger.debug("Check early exit node", extra={"correlation_id": correlation_id_ctx.get()})
        from agents.prompts.agent_prompts import EARLY_EXIT_NON_ISLAMIC, EARLY_EXIT_CASUAL

        # --- Casual branch (greetings, thanks, small talk) ---
        if state.get("is_casual"):
            try:
                from core.chat_models import get_classifier_model
                model = get_classifier_model()
                prompt_text = (
                    f"The user sent a casual or social message: '{state['user_query']}'\n\n"
                    "Reply warmly and briefly (1 sentence). Invite them to ask about "
                    "Twelver Shia Islam — theology, history, the Imams, the Quran, or practice. "
                    "Do not fabricate any religious content. Do not use emojis."
                )
                from langchain_core.messages import HumanMessage
                response = await _retry_ainvoke(model, [HumanMessage(content=prompt_text)])
                record_llm_usage("early_exit_casual", response)
                msg = response.content.strip()
            except Exception as exc:
                logger.error("LLM casual reply error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
                msg = EARLY_EXIT_CASUAL
            return {"final_response": msg, "early_exit_message": msg}

        # --- Non-Islamic branch ---
        if state.get("is_non_islamic"):
            try:
                from core.chat_models import get_classifier_model
                model = get_classifier_model()
                prompt_text = (
                    f"A user asked: '{state['user_query']}'\n\n"
                    "This question is outside your scope — you specialize in Twelver Shia Islamic "
                    "education. Warmly and briefly (1-2 sentences) let them know you focus on "
                    "Islamic topics and invite an on-topic question. "
                    "Do NOT answer the off-topic question. Do not use emojis."
                )
                from langchain_core.messages import HumanMessage
                response = await _retry_ainvoke(model, [HumanMessage(content=prompt_text)])
                record_llm_usage("early_exit_non_islamic", response)
                msg = response.content.strip()
            except Exception as exc:
                logger.error("LLM non-Islamic rejection error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
                msg = EARLY_EXIT_NON_ISLAMIC
            return {"final_response": msg, "early_exit_message": msg}

        # --- Fiqh UNETHICAL branch (unchanged) ---
        category = state.get("fiqh_category", "")
        if category == "UNETHICAL":
            # LLM-generated personalized rejection message (D-12)
            try:
                from core.chat_models import get_classifier_model

                model = get_classifier_model()
                prompt_text = (
                    f"A user asked: '{state['user_query']}'\n\n"
                    "This question asks for a ruling on something harmful or unethical. "
                    "Politely decline to answer in 1-2 sentences, without judging the user. "
                    "Do not provide any ruling. Do not use emojis."
                )
                from langchain_core.messages import HumanMessage
                response = await _retry_ainvoke(model, [HumanMessage(content=prompt_text)])
                record_llm_usage("early_exit_unethical", response)
                msg = response.content.strip()
            except Exception as exc:
                logger.error("LLM rejection error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
                msg = (
                    "I'm unable to answer this question as it involves something harmful or unethical."
                )
            return {"final_response": msg, "early_exit_message": msg}

        return {"final_response": "Unable to process the query."}

    async def _call_fiqh_subgraph_node(self, state: ChatState) -> dict:
        """
        Wrapper node that invokes the FiqhAgent sub-graph.
        Projects ChatState -> FiqhState input, invokes sub-graph, maps output -> ChatState delta.
        Uses Pattern 1 (node wrapper) because ChatState and FiqhState share no keys.

        DEE-44 made every fiqh sub-graph node `async def`, so the whole 10-15s
        subgraph run now drives via `.ainvoke` and yields between LLM calls
        instead of blocking the executor.
        """
        logger.debug("Invoking FAIR-RAG sub-graph", extra={"correlation_id": correlation_id_ctx.get()})
        from agents.fiqh.fiqh_graph import fiqh_subgraph
        from core.context import _push_fiqh_status

        # Real-time SSE: emit the latency-expectation intro the moment we
        # enter the wrapper node, before the ~10-15s sub-graph invoke. Without
        # this, the parent astream loop only sees fiqh_subgraph activity AFTER
        # the sub-graph completes, leaving the user staring at "Fiqh query
        # detected..." for the whole window.
        _push_fiqh_status(
            "fiqh_subgraph",
            "Processing fiqh query (this may take 10-15 seconds)...",
        )

        try:
            result = await fiqh_subgraph.ainvoke({
                "query": state["user_query"],
                "iteration": 0,
                "accumulated_docs": [],
                "prior_queries": [],
                "pending_queries": [],
                "sea_result": None,
                "verdict": "INSUFFICIENT",
                "status_events": [],
            })
            fiqh_filtered_docs = result.get("accumulated_docs", [])
            fiqh_sea_result = result.get("sea_result")
            status_events = result.get("status_events", [])

            logger.debug("Fiqh sub-graph complete", extra={"correlation_id": correlation_id_ctx.get(), "doc_count": len(fiqh_filtered_docs), "status_event_count": len(status_events)})
            return {
                "fiqh_filtered_docs": fiqh_filtered_docs,
                "fiqh_sea_result": fiqh_sea_result,
                # Surface status_events via the node delta so
                # core.pipeline_langgraph.py can yield them as in-order SSE status
                # events after the blocking sub-graph invoke returns.
                "fiqh_status_events": list(status_events),
            }
        except Exception as exc:
            logger.error("Fiqh sub-graph error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
            return {
                "fiqh_filtered_docs": [],
                "fiqh_sea_result": None,
                "fiqh_status_events": [],
                "errors": state.get("errors", []) + [f"Fiqh sub-graph error: {str(exc)}"],
            }

    async def _generate_fiqh_response_node(self, state: ChatState) -> dict:
        """
        Non-streaming generation node for the fiqh path — serves the
        `ainvoke` (/chat/agentic) path only.

        On the SSE path (`streaming_mode=True`) this node is a no-op:
        core/pipeline_langgraph.py streams the fiqh generation itself from
        the merged final state (fiqh_category + fiqh_filtered_docs). Before
        the token-cost Phase 1 fix (DEE-60), this guard was missing AND the
        pipeline kept only the last node delta, so this node's non-streamed
        answer was what users received (as a single blob, with no
        fiqh_references event ever emitted).
        """
        if state.get("streaming_mode"):
            logger.debug("Skipping fiqh generation node (streaming mode)", extra={"correlation_id": correlation_id_ctx.get()})
            return {}
        logger.debug("Generating fiqh answer (non-streaming)", extra={"correlation_id": correlation_id_ctx.get()})
        from modules.fiqh.generator import (
            _build_messages,
            _format_evidence,
            _build_references_section,
            INSUFFICIENT_WARNING,
            FATWA_DISCLAIMER,
        )
        from core.chat_models import get_generator_model

        docs = state.get("fiqh_filtered_docs", [])
        sea_result = state.get("fiqh_sea_result")
        is_sufficient = getattr(sea_result, "verdict", "INSUFFICIENT") == "SUFFICIENT"

        if not docs:
            fallback = (
                "I was unable to retrieve relevant rulings for this question. "
                "Please consult Sistani's official resources at sistani.org "
                "or contact his office directly." + FATWA_DISCLAIMER
            )
            return {"final_response": fallback, "response_generated": True}

        try:
            model = get_generator_model()
            response = await _retry_ainvoke(model, _build_messages(
                query=state["user_query"],
                evidence=_format_evidence(docs),
            ))
            record_llm_usage("fiqh_generation_nonstream", response)
            answer = response.content.strip()
            answer += _build_references_section(answer, docs)
            if not is_sufficient:
                answer += INSUFFICIENT_WARNING
            answer += FATWA_DISCLAIMER
            return {"final_response": answer, "response_generated": True}
        except Exception as exc:
            logger.error("Fiqh response generation error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
            return {
                "errors": state.get("errors", []) + [f"Fiqh generation error: {str(exc)}"],
                "final_response": "Unable to generate fiqh answer." + FATWA_DISCLAIMER,
                "response_generated": True,
            }

    def _should_continue(self, state: ChatState) -> Literal["continue", "generate", "exit", "end"]:
        if state.get("is_non_islamic") or state.get("is_fiqh") or state.get("is_casual"):
            logger.debug("Routing: early exit", extra={"correlation_id": correlation_id_ctx.get()})
            return "exit"

        if state.get("should_end"):
            logger.debug("Routing: should_end flag set", extra={"correlation_id": correlation_id_ctx.get()})
            return "end"

        last_message = state["messages"][-1] if state["messages"] else None
        if last_message is None:
            logger.debug("Routing: no messages, ending", extra={"correlation_id": correlation_id_ctx.get()})
            return "end"

        if getattr(last_message, "tool_calls", None):
            logger.debug("Routing: continue to tools", extra={"correlation_id": correlation_id_ctx.get(), "tool_call_count": len(last_message.tool_calls)})
            return "continue"

        if state.get("ready_to_answer") and self._has_any_documents(state):
            if state.get("streaming_mode"):
                logger.debug("Routing: evidence sufficient, ending for streaming", extra={"correlation_id": correlation_id_ctx.get()})
                return "end"
            logger.debug("Routing: evidence sufficient, generating response", extra={"correlation_id": correlation_id_ctx.get()})
            return "generate"

        if self._has_any_documents(state):
            if state.get("streaming_mode"):
                logger.debug("Routing: stopped after retrieval, ending for streaming", extra={"correlation_id": correlation_id_ctx.get()})
                return "end"
            logger.debug("Routing: stopped after retrieval, generating response", extra={"correlation_id": correlation_id_ctx.get()})
            return "generate"

        logger.debug("Routing: no evidence, ending", extra={"correlation_id": correlation_id_ctx.get()})
        return "end"

    def _build_initial_user_message(self, state: ChatState) -> str:
        retrieval_config = self._get_retrieval_config(state)
        parts = [
            f"User query: {state['user_query']}",
            f"Working query: {state['working_query']}",
            f"Runtime session key: {state['runtime_session_id']}",
            (
                "Default retrieval counts: "
                f"Shia={retrieval_config.get('shia_doc_count', self.config.retrieval.shia_doc_count)}, "
                f"Sunni={retrieval_config.get('sunni_doc_count', self.config.retrieval.sunni_doc_count)}, "
                f"Quran/Tafsir={retrieval_config.get('quran_doc_count', self.config.retrieval.quran_doc_count)}"
            ),
        ]
        if state["target_language"] != "english":
            parts.append(f"User's preferred language: {state['target_language']}")
        return "\n".join(parts)

    def _build_iteration_summary(self, state: ChatState) -> str:
        attempts = state.get("retrieval_attempts", [])
        attempt_lines = []
        for attempt in attempts[-5:]:
            status = "ok" if attempt.get("success") else "failed"
            attempt_lines.append(
                f"- source={attempt.get('source')} status={status} count={attempt.get('count', 0)} query={attempt.get('query_used')}"
            )

        coverage = state.get("source_coverage", {})
        lines = [
            "Current evidence summary:",
            f"- working_query={state.get('working_query')}",
            f"- translated={state.get('is_translated')}",
            f"- query_enhanced={state.get('query_enhanced')}",
            f"- shia_docs={state.get('shia_docs_count', 0)}",
            f"- sunni_docs={state.get('sunni_docs_count', 0)}",
            f"- quran_docs={state.get('quran_docs_count', 0)}",
            (
                "- source_coverage="
                f"shia:{coverage.get('shia', False)}, "
                f"sunni:{coverage.get('sunni', False)}, "
                f"quran_tafsir:{coverage.get('quran_tafsir', False)}"
            ),
        ]
        if attempt_lines:
            lines.append("Recent retrieval attempts:")
            lines.extend(attempt_lines)
        lines.append(
            "If evidence is sufficient, stop calling tools. If it is incomplete, call another tool or revise the retrieval query."
        )
        return "\n".join(lines)

    def _apply_tool_call_defaults(self, state: ChatState, tool_calls: List[Dict[str, Any]]) -> None:
        retrieval_config = self._get_retrieval_config(state)
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue

            tool_name = tool_call.get("name")
            args = tool_call.setdefault("args", {})
            if tool_name == "translate_to_english_tool":
                args.setdefault("text", state["working_query"])
            elif tool_name == "enhance_query_tool":
                args.setdefault("query", state["working_query"])
                args.setdefault("session_id", state["runtime_session_id"])
            elif tool_name == "retrieve_shia_documents_tool":
                args.setdefault("query", state["working_query"])
                args.setdefault("num_documents", retrieval_config.get("shia_doc_count", self.config.retrieval.shia_doc_count))
                args["num_documents"] = _clamp_doc_count(args.get("num_documents"), 1, 10)
            elif tool_name == "retrieve_sunni_documents_tool":
                args.setdefault("query", state["working_query"])
                args.setdefault("num_documents", retrieval_config.get("sunni_doc_count", self.config.retrieval.sunni_doc_count))
                args["num_documents"] = _clamp_doc_count(args.get("num_documents"), 0, 5)
            elif tool_name == "retrieve_quran_tafsir_tool":
                args.setdefault("query", state["working_query"])
                args.setdefault("num_documents", retrieval_config.get("quran_doc_count", self.config.retrieval.quran_doc_count))
                args["num_documents"] = _clamp_doc_count(args.get("num_documents"), 0, 5)

    def _record_retrieval_result(self, state: ChatState, result_data: Dict[str, Any], tool_name: str) -> None:
        source = result_data.get("source") or tool_name.replace("retrieve_", "").replace("_tool", "")
        docs = result_data.get("documents", []) or []
        query_used = result_data.get("query_used") or state["working_query"]
        error = result_data.get("error")
        count = result_data.get("count", len(docs))

        state["retrieval_attempts"].append(
            {
                "source": source,
                "query_used": query_used,
                "count": count,
                "success": bool(docs) and not error,
                "error": error,
            }
        )
        state["retrieval_completed"] = True
        state["ready_to_answer"] = False

        if error:
            state["errors"].append(f"{source} retrieval error: {error}")

        if source == "quran_tafsir":
            state["quran_docs"] = self._merge_documents(state["quran_docs"], docs, "chunk_id")
        else:
            state["retrieved_docs"] = self._merge_documents(state["retrieved_docs"], docs, "hadith_id")

        coverage = state.get("source_coverage", {})
        coverage[source] = coverage.get(source, False) or bool(docs)
        state["source_coverage"] = coverage
        self._refresh_source_counts(state)

    def _refresh_source_counts(self, state: ChatState) -> None:
        shia_count = 0
        sunni_count = 0
        for doc in state.get("retrieved_docs", []):
            metadata = doc.get("metadata", {}) or {}
            sect = str(metadata.get("sect", "")).strip().lower()
            if sect == "shia":
                shia_count += 1
            elif sect == "sunni":
                sunni_count += 1

        state["shia_docs_count"] = shia_count
        state["sunni_docs_count"] = sunni_count
        state["quran_docs_count"] = len(state.get("quran_docs", []))

    def _merge_documents(
        self,
        existing_docs: List[Dict[str, Any]],
        new_docs: List[Dict[str, Any]],
        primary_id_key: str,
    ) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen_ids = set()

        def stable_id(doc: Dict[str, Any]) -> str:
            metadata = doc.get("metadata", {}) or {}
            value = doc.get(primary_id_key) or metadata.get(primary_id_key)
            if value:
                return str(value)
            fallback = metadata.get("reference") or metadata.get("title") or doc.get("page_content_en", "")
            return str(fallback)[:250]

        for doc in existing_docs + list(new_docs or []):
            if not isinstance(doc, dict):
                continue
            identifier = stable_id(doc)
            if identifier in seen_ids:
                continue
            seen_ids.add(identifier)
            merged.append(doc)

        return merged

    def _get_retrieval_config(self, state: ChatState) -> Dict[str, Any]:
        return (state.get("config") or {}).get("retrieval", {})

    def _parse_tool_payload(self, content: Any) -> Dict[str, Any]:
        if isinstance(content, dict):
            return content
        if isinstance(content, str):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {"raw": content}
        return {}

    def _has_any_documents(self, state: ChatState) -> bool:
        return bool(state.get("retrieved_docs") or state.get("quran_docs"))

    @staticmethod
    def _load_runtime_messages(session_id: str):
        """Sync history load used by `astream()` (kept sync because callers
        like `core.pipeline_langgraph` already invoke this from a non-async
        context inside the streaming wrapper)."""
        try:
            from core.memory import make_history

            history = make_history(session_id)
            return history.messages
        except Exception as exc:
            logger.error("Failed to load runtime history", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
            return []

    @staticmethod
    async def _aload_runtime_messages(session_id: str):
        """Async-native runtime history load (DEE-43). Uses
        `core.memory.amake_history` so Redis I/O doesn't block the event loop.

        Token-cost DEE-60 Phase 2: the loaded window is budgeted (read-side
        only — Redis still stores the full history) because these messages
        seed state["messages"] and are re-sent on every agent iteration."""
        try:
            from core.history_budget import AGENT_BUDGET, budget_messages
            from core.memory import amake_history

            history = amake_history(session_id)
            messages = await history.aget_messages()
            return budget_messages(messages, *AGENT_BUDGET)
        except Exception as exc:
            logger.error("Failed to load runtime history", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
            return []

    async def ainvoke(
        self,
        user_query: str,
        session_id: str,
        target_language: str = "english",
        config: dict = None,
    ):
        """Native async entry point. Every node is `async def` so this is the
        only correct way to drive the graph from inside an event loop."""
        from agents.state.chat_state import create_initial_state

        initial_messages = await self._aload_runtime_messages(session_id)
        initial_state = create_initial_state(
            user_query=user_query,
            session_id=session_id,
            target_language=target_language,
            config=config or self.config.to_dict(),
            initial_messages=initial_messages,
        )

        return await self.compiled_graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": session_id}},
        )

    def invoke(
        self,
        user_query: str,
        session_id: str,
        target_language: str = "english",
        config: dict = None,
    ):
        """Sync wrapper for callers outside an event loop. Inside FastAPI
        routes use `await ainvoke(...)` directly — `asyncio.run()` cannot be
        called from a running loop."""
        return asyncio.run(
            self.ainvoke(
                user_query=user_query,
                session_id=session_id,
                target_language=target_language,
                config=config,
            )
        )

    async def astream(
        self,
        user_query: str,
        session_id: str,
        target_language: str = "english",
        config: dict = None,
        streaming_mode: bool = False,
    ):
        from agents.state.chat_state import create_initial_state

        initial_messages = await self._aload_runtime_messages(session_id)
        initial_state = create_initial_state(
            user_query=user_query,
            session_id=session_id,
            target_language=target_language,
            config=config or self.config.to_dict(),
            initial_messages=initial_messages,
            streaming_mode=streaming_mode,
        )

        async for event in self.compiled_graph.astream(
            initial_state,
            config={"configurable": {"thread_id": session_id}},
        ):
            yield event
