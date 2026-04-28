"""
LangGraph-based agentic chat agent for Islamic education.

This agent plans retrieval iteratively so it can choose between
Shia hadith, Sunni hadith, and Quran/Tafsir evidence per query.
"""

import json
from typing import Any, Dict, List, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from agents.config.agent_config import AgentConfig, DEFAULT_AGENT_CONFIG
from agents.prompts.agent_prompts import (
    AGENT_SYSTEM_PROMPT,
)
from agents.state.chat_state import ChatState
from agents.tools import (
    check_if_non_islamic_tool,
    enhance_query_tool,
    retrieve_quran_tafsir_tool,
    retrieve_shia_documents_tool,
    retrieve_sunni_documents_tool,
    translate_to_english_tool,
)
from core import utils
from core.config import ANTHROPIC_API_KEY
import logging
from core.context import correlation_id as correlation_id_ctx

logger = logging.getLogger(__name__)


class ChatAgent:
    """
    LangGraph-based agentic chat system for Islamic education.
    """

    def __init__(self, config: AgentConfig = None):
        self.config = config or DEFAULT_AGENT_CONFIG
        self.tools = [
            check_if_non_islamic_tool,
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
        )
        return llm.bind_tools(self.tools)

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

    def _fiqh_classification_node(self, state: ChatState) -> dict:
        logger.debug("Fiqh classification started", extra={"correlation_id": correlation_id_ctx.get()})
        try:
            from modules.fiqh.classifier import classify_fiqh_query

            # Note: new classifier takes only query (not session_id) — Pitfall 3
            category = classify_fiqh_query(state["user_query"])
            is_fiqh = category.startswith("VALID_")
            logger.debug("Fiqh classification complete", extra={"correlation_id": correlation_id_ctx.get(), "fiqh_category": category, "is_fiqh": is_fiqh})
            return {
                "fiqh_category": category,
                "is_fiqh": is_fiqh,
                "classification_checked": True,
            }
        except Exception as exc:
            logger.error("Fiqh classification error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
            return {
                "fiqh_category": "",
                "is_fiqh": False,
                "classification_checked": True,
                "errors": state.get("errors", []) + [f"Fiqh classification error: {str(exc)}"],
            }

    def _route_after_fiqh_check(self, state: ChatState) -> Literal["fiqh", "exit", "continue"]:
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

    def _agent_node(self, state: ChatState) -> ChatState:
        logger.debug("Agent node iteration", extra={"correlation_id": correlation_id_ctx.get(), "iteration": state["iterations"]})

        state["iterations"] += 1
        if state["iterations"] > self.config.max_iterations:
            logger.debug("Max iterations reached", extra={"correlation_id": correlation_id_ctx.get(), "max_iterations": self.config.max_iterations})
            state["should_end"] = True
            state["errors"].append(f"Max iterations ({self.config.max_iterations}) reached")
            return state

        messages = list(state["messages"])

        # D-08: filter spurious empty AIMessages emitted by Claude in tool-calling sequences.
        # AIMessage(content="", tool_calls=[...]) is valid (Claude tool-call request) — preserved.
        # AIMessage(content="", tool_calls=None/[]) with no tool_calls is spurious — filtered out.
        messages = [
            msg for msg in messages
            if not (
                isinstance(msg, AIMessage)
                and msg.content == ""
                and not getattr(msg, "tool_calls", None)
            )
        ]

        if state["iterations"] == 1:
            messages.insert(0, SystemMessage(content=AGENT_SYSTEM_PROMPT))
            messages.append(HumanMessage(content=self._build_initial_user_message(state)))
        else:
            messages.append(HumanMessage(content=self._build_iteration_summary(state)))

        try:
            response = self.llm.invoke(messages)
            state["messages"].append(response)
            if not getattr(response, "tool_calls", None) and self._has_any_documents(state):
                state["ready_to_answer"] = True
        except Exception as exc:
            logger.error("Agent node error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
            state["errors"].append(f"Agent error: {str(exc)}")
            state["should_end"] = True

        return state

    def _tool_node(self, state: ChatState) -> ChatState:
        logger.debug("Tool node executing", extra={"correlation_id": correlation_id_ctx.get()})
        last_message = state["messages"][-1] if state["messages"] else None

        if last_message is None or not getattr(last_message, "tool_calls", None):
            logger.debug("Tool node: no tool calls found", extra={"correlation_id": correlation_id_ctx.get()})
            return state

        self._apply_tool_call_defaults(state, last_message.tool_calls)
        tool_node = ToolNode(self.tools)
        result = tool_node.invoke(state)
        result_messages = result.get("messages", [])

        for message in result_messages:
            if not hasattr(message, "name"):
                continue

            tool_name = message.name
            result_data = self._parse_tool_payload(message.content)
            logger.debug("Tool executed", extra={"correlation_id": correlation_id_ctx.get(), "tool_name": tool_name})

            if tool_name == "check_if_non_islamic_tool":
                state["is_non_islamic"] = result_data.get("is_non_islamic", False)
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

        if result_messages:
            state["messages"].extend(result_messages)
        return state

    def _generate_response_node(self, state: ChatState) -> ChatState:
        logger.debug("Generating final response", extra={"correlation_id": correlation_id_ctx.get()})

        all_docs = state["retrieved_docs"] + state.get("quran_docs", [])
        references = utils.compact_format_references(all_docs)
        generation_messages = [
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            HumanMessage(
                content=f"""User query: {state['user_query']}

Retrieved references:
{references}

Generate a comprehensive, accurate response that directly addresses the user's question using the retrieved sources. Cite specific books, hadith numbers, and scholars when referencing the sources."""
            ),
        ]

        try:
            from core.chat_models import get_generator_model

            llm = get_generator_model()
            response = llm.invoke(generation_messages)
            state["final_response"] = response.content
            state["response_generated"] = True
            logger.debug("Response generated", extra={"correlation_id": correlation_id_ctx.get(), "response_chars": len(response.content)})
        except Exception as exc:
            logger.error("Response generation error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
            state["errors"].append(f"Response generation error: {str(exc)}")
            state["final_response"] = "I apologize, but I encountered an error generating the response."

        return state

    def _check_early_exit_node(self, state: ChatState) -> dict:
        logger.debug("Check early exit node", extra={"correlation_id": correlation_id_ctx.get()})
        from agents.prompts.agent_prompts import EARLY_EXIT_NON_ISLAMIC

        if state.get("is_non_islamic"):
            return {
                "final_response": EARLY_EXIT_NON_ISLAMIC,
                "early_exit_message": EARLY_EXIT_NON_ISLAMIC,
            }

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
                    "Do not provide any ruling."
                )
                from langchain_core.messages import HumanMessage
                response = model.invoke([HumanMessage(content=prompt_text)])
                msg = response.content.strip()
            except Exception as exc:
                logger.error("LLM rejection error", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
                msg = (
                    "I'm unable to answer this question as it involves something harmful or unethical."
                )
            return {"final_response": msg, "early_exit_message": msg}

        return {"final_response": "Unable to process the query."}

    def _call_fiqh_subgraph_node(self, state: ChatState) -> dict:
        """
        Wrapper node that invokes the FiqhAgent sub-graph.
        Projects ChatState -> FiqhState input, invokes sub-graph, maps output -> ChatState delta.
        Uses Pattern 1 (node wrapper) because ChatState and FiqhState share no keys.
        """
        logger.debug("Invoking FAIR-RAG sub-graph", extra={"correlation_id": correlation_id_ctx.get()})
        from agents.fiqh.fiqh_graph import fiqh_subgraph

        try:
            result = fiqh_subgraph.invoke({
                "query": state["user_query"],
                "iteration": 0,
                "accumulated_docs": [],
                "prior_queries": [],
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

    def _generate_fiqh_response_node(self, state: ChatState) -> dict:
        """
        Non-streaming generation node for the fiqh path.
        Uses fiqh-specific system prompt and formats filtered docs as numbered evidence.
        The streaming path in pipeline_langgraph.py bypasses this node and streams
        tokens directly — this node serves the non-streaming (invoke) path only.
        """
        logger.debug("Generating fiqh answer (non-streaming)", extra={"correlation_id": correlation_id_ctx.get()})
        from modules.fiqh.generator import (
            _prompt,
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
            response = model.invoke(_prompt.format_messages(
                query=state["user_query"],
                evidence=_format_evidence(docs),
            ))
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
        if state.get("is_non_islamic") or state.get("is_fiqh"):
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
            if tool_name == "check_if_non_islamic_tool":
                args.setdefault("query", state["working_query"])
                args.setdefault("session_id", state["runtime_session_id"])
            elif tool_name == "translate_to_english_tool":
                args.setdefault("text", state["working_query"])
            elif tool_name == "enhance_query_tool":
                args.setdefault("query", state["working_query"])
                args.setdefault("session_id", state["runtime_session_id"])
            elif tool_name == "retrieve_shia_documents_tool":
                args.setdefault("query", state["working_query"])
                args.setdefault("num_documents", retrieval_config.get("shia_doc_count", self.config.retrieval.shia_doc_count))
            elif tool_name == "retrieve_sunni_documents_tool":
                args.setdefault("query", state["working_query"])
                args.setdefault("num_documents", retrieval_config.get("sunni_doc_count", self.config.retrieval.sunni_doc_count))
            elif tool_name == "retrieve_quran_tafsir_tool":
                args.setdefault("query", state["working_query"])
                args.setdefault("num_documents", retrieval_config.get("quran_doc_count", self.config.retrieval.quran_doc_count))

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
        try:
            from core.memory import make_history

            history = make_history(session_id)
            return history.messages
        except Exception as exc:
            logger.error("Failed to load runtime history", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "error": str(exc)})
            return []

    def invoke(
        self,
        user_query: str,
        session_id: str,
        target_language: str = "english",
        config: dict = None,
    ):
        from agents.state.chat_state import create_initial_state

        initial_state = create_initial_state(
            user_query=user_query,
            session_id=session_id,
            target_language=target_language,
            config=config or self.config.to_dict(),
            initial_messages=self._load_runtime_messages(session_id),
        )

        final_state = self.compiled_graph.invoke(
            initial_state,
            config={"configurable": {"thread_id": session_id}},
        )
        return final_state

    async def astream(
        self,
        user_query: str,
        session_id: str,
        target_language: str = "english",
        config: dict = None,
        streaming_mode: bool = False,
    ):
        from agents.state.chat_state import create_initial_state

        initial_state = create_initial_state(
            user_query=user_query,
            session_id=session_id,
            target_language=target_language,
            config=config or self.config.to_dict(),
            initial_messages=self._load_runtime_messages(session_id),
            streaming_mode=streaming_mode,
        )

        async for event in self.compiled_graph.astream(
            initial_state,
            config={"configurable": {"thread_id": session_id}},
        ):
            yield event
