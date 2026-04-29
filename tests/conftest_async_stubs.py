"""
Shared deterministic stubs for the async-migration test suite (DEE-36).

Every later phase reuses these fixtures so the loadtest, concurrency baseline,
SSE-order snapshot, and Sentry propagation tests all run against an in-process
FastAPI app with no external API keys, no live Pinecone, no real Redis.

What gets stubbed
-----------------
- The agent's planner LLM (ChatAnthropic bound with tools) — replaced by
  FakePlannerLLM, which scripts a tool-call AIMessage on iteration 1 and a
  no-tool-calls AIMessage on iteration 2. Sleeps `llm_sleep_s` per .invoke().
- The generator LLM (core.chat_models.get_generator_model) used by the
  streaming `prompt | model` chain — replaced by FakeGeneratorLLM. Sleeps
  `llm_sleep_s` per generate() call and `per_token_sleep_s` per stream chunk.
- modules.retrieval.retriever.retrieve_shia_documents — sleeps
  `retrieval_sleep_s` then returns canned docs.
- modules.fiqh.classifier.classify_fiqh_query — returns "OUT_OF_SCOPE_FIQH"
  immediately so the fiqh sub-graph is never invoked from these tests.

Sleep tunables in StubConfig let tests dial blocking durations up or down so
the per-phase concurrency gates stay deterministic regardless of CI host.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

import pytest
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


# --- Configuration ---------------------------------------------------------


@dataclass
class StubConfig:
    """Latency knobs for the deterministic pipeline stubs."""

    llm_sleep_s: float = 0.2
    retrieval_sleep_s: float = 0.1
    per_token_sleep_s: float = 0.05
    tokens: List[str] = field(default_factory=lambda: ["Hello", " ", "world", ", ", "patience."])
    canned_docs: List[Dict[str, Any]] = field(default_factory=lambda: [
        {
            "hadith_id": "fake-shia-1",
            "page_content_en": "Indeed, patience is half of faith.",
            "page_content_ar": "",
            "metadata": {
                "book": "Al-Kafi",
                "volume": "2",
                "chapter": "Patience",
                "hadith_number": "1",
                "author": "al-Kulayni",
                "source": "shia",
            },
        }
    ])


# --- Fake LLMs -------------------------------------------------------------


class _BaseFakeChat(BaseChatModel):
    """Common scaffolding for the planner and generator fakes.

    Both subclasses sleep `invoke_sleep_s` per non-streaming call. The
    generator subclass also sleeps `per_token_sleep_s` per yielded chunk.

    All tunable fields are declared as Pydantic fields with defaults so
    construction stays `FakePlannerLLM(invoke_sleep_s=...)` style — no
    post-init attribute mutation, which Pydantic v2 BaseChatModel discourages.
    """

    invoke_sleep_s: float = 0.2

    @property
    def _llm_type(self) -> str:
        return "fake-deen-chat"

    def bind_tools(self, tools, **kwargs):
        # ChatAgent only invokes `.invoke()` on the bound model and reads
        # `tool_calls` off the response — it never introspects the bound
        # tools list itself, so returning self preserves identity without
        # storing extra state on a Pydantic model.
        return self


class FakePlannerLLM(_BaseFakeChat):
    """Scripts the agent's iteration: tool call → final empty-tool-calls msg.

    Decision is stateless: if the message history contains any ToolMessage,
    the agent has already received retrieval results, so emit the final
    no-tool-calls AIMessage. Otherwise emit a single retrieve_shia_documents
    tool_call. Stateless + monotonic message history = robust to LangGraph
    re-entries and concurrent FakePlannerLLM instances across requests.
    """

    @staticmethod
    def _make_tool_call_message() -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "retrieve_shia_documents_tool",
                    "args": {"query": "patience", "num_documents": 3},
                    "id": "fake-tc-1",
                    "type": "tool_call",
                }
            ],
        )

    @staticmethod
    def _make_final_message() -> AIMessage:
        return AIMessage(content="ready_to_answer", tool_calls=[])

    def _next_response(self, messages: List[BaseMessage]) -> AIMessage:
        if any(isinstance(m, ToolMessage) for m in messages):
            return self._make_final_message()
        return self._make_tool_call_message()

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        time.sleep(self.invoke_sleep_s)
        msg = self._next_response(messages)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        await asyncio.sleep(self.invoke_sleep_s)
        msg = self._next_response(messages)
        return ChatResult(generations=[ChatGeneration(message=msg)])


class FakeGeneratorLLM(_BaseFakeChat):
    """Streaming-capable fake. Used by the prompt | model chain that runs
    after the agent finishes (core/pipeline_langgraph.py:337)."""

    tokens: List[str] = ["Hello", " ", "world"]
    per_token_sleep_s: float = 0.05

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        time.sleep(self.invoke_sleep_s)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="".join(self.tokens)))]
        )

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        await asyncio.sleep(self.invoke_sleep_s)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="".join(self.tokens)))]
        )

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        for tok in self.tokens:
            time.sleep(self.per_token_sleep_s)
            yield ChatGenerationChunk(message=AIMessageChunk(content=tok))

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for tok in self.tokens:
            await asyncio.sleep(self.per_token_sleep_s)
            yield ChatGenerationChunk(message=AIMessageChunk(content=tok))


# --- Patch installer -------------------------------------------------------


@contextmanager
def install_pipeline_stubs(cfg: Optional[StubConfig] = None):
    """Monkeypatch the agentic pipeline so a real chat_pipeline_streaming_agentic
    invocation runs end-to-end without any external dependencies.

    Yields the StubConfig actually applied so callers can read the latencies
    used (e.g. the loadtest computes expected sequential time from these).
    """
    cfg = cfg or StubConfig()

    import agents.core.chat_agent as chat_agent_mod
    from core import chat_models
    from modules.fiqh import classifier as fiqh_classifier_mod
    from modules.retrieval import retriever as retriever_mod

    # --- Planner LLM stub ---------------------------------------------------
    def _planner_factory(*args, **kwargs):
        return FakePlannerLLM(invoke_sleep_s=cfg.llm_sleep_s)

    original_chat_anthropic = chat_agent_mod.ChatAnthropic
    chat_agent_mod.ChatAnthropic = _planner_factory  # type: ignore[assignment]

    # --- Generator LLM stub -------------------------------------------------
    def _generator_factory():
        return FakeGeneratorLLM(
            invoke_sleep_s=cfg.llm_sleep_s,
            per_token_sleep_s=cfg.per_token_sleep_s,
            tokens=list(cfg.tokens),
        )

    original_get_generator_model = chat_models.get_generator_model
    chat_models.get_generator_model = _generator_factory

    # --- Retrieval stub -----------------------------------------------------
    # Both sync and async variants must be stubbed: tools call the async
    # variants (DEE-42); legacy /references and /hikmah pipeline calls plus
    # any cached imports still resolve to the sync ones.
    def _stub_retrieve_shia(query, num_documents=5):
        time.sleep(cfg.retrieval_sleep_s)
        return list(cfg.canned_docs[:num_documents] or cfg.canned_docs)

    def _stub_retrieve_sunni(query, num_documents=2):
        time.sleep(cfg.retrieval_sleep_s)
        return []

    def _stub_retrieve_quran(query, num_documents=3):
        time.sleep(cfg.retrieval_sleep_s)
        return []

    async def _astub_retrieve_shia(query, num_documents=5):
        await asyncio.sleep(cfg.retrieval_sleep_s)
        return list(cfg.canned_docs[:num_documents] or cfg.canned_docs)

    async def _astub_retrieve_sunni(query, num_documents=2):
        await asyncio.sleep(cfg.retrieval_sleep_s)
        return []

    async def _astub_retrieve_quran(query, num_documents=3):
        await asyncio.sleep(cfg.retrieval_sleep_s)
        return []

    originals = {
        "shia": retriever_mod.retrieve_shia_documents,
        "sunni": retriever_mod.retrieve_sunni_documents,
        "quran": retriever_mod.retrieve_quran_documents,
        "ashia": getattr(retriever_mod, "aretrieve_shia_documents", None),
        "asunni": getattr(retriever_mod, "aretrieve_sunni_documents", None),
        "aquran": getattr(retriever_mod, "aretrieve_quran_documents", None),
    }
    retriever_mod.retrieve_shia_documents = _stub_retrieve_shia
    retriever_mod.retrieve_sunni_documents = _stub_retrieve_sunni
    retriever_mod.retrieve_quran_documents = _stub_retrieve_quran
    if originals["ashia"] is not None:
        retriever_mod.aretrieve_shia_documents = _astub_retrieve_shia
        retriever_mod.aretrieve_sunni_documents = _astub_retrieve_sunni
        retriever_mod.aretrieve_quran_documents = _astub_retrieve_quran

    # --- Fiqh classifier stub (skip the fiqh sub-graph entirely) ------------
    # ChatAgent._fiqh_classification_node now awaits `aclassify_fiqh_query`
    # directly (DEE-44); patch both for forward/backward compat.
    original_classify_fiqh = fiqh_classifier_mod.classify_fiqh_query
    original_aclassify_fiqh = getattr(fiqh_classifier_mod, "aclassify_fiqh_query", None)
    fiqh_classifier_mod.classify_fiqh_query = lambda query: "OUT_OF_SCOPE_FIQH"

    async def _astub_classify_fiqh(query):
        return "OUT_OF_SCOPE_FIQH"

    if original_aclassify_fiqh is not None:
        fiqh_classifier_mod.aclassify_fiqh_query = _astub_classify_fiqh

    try:
        yield cfg
    finally:
        chat_agent_mod.ChatAnthropic = original_chat_anthropic  # type: ignore[assignment]
        chat_models.get_generator_model = original_get_generator_model
        retriever_mod.retrieve_shia_documents = originals["shia"]
        retriever_mod.retrieve_sunni_documents = originals["sunni"]
        retriever_mod.retrieve_quran_documents = originals["quran"]
        if originals["ashia"] is not None:
            retriever_mod.aretrieve_shia_documents = originals["ashia"]
            retriever_mod.aretrieve_sunni_documents = originals["asunni"]
            retriever_mod.aretrieve_quran_documents = originals["aquran"]
        fiqh_classifier_mod.classify_fiqh_query = original_classify_fiqh
        if original_aclassify_fiqh is not None:
            fiqh_classifier_mod.aclassify_fiqh_query = original_aclassify_fiqh


# --- Concurrency harness ---------------------------------------------------


async def _drain_pipeline_response(response) -> List[str]:
    chunks: List[str] = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8")
        chunks.append(chunk)
    return chunks


async def run_pipeline_once(
    *,
    user_query: str = "What does Islam say about patience?",
    session_id: str = "stub-session",
) -> tuple[float, List[str]]:
    """Run a single agentic streaming call against the in-process pipeline and
    return (elapsed_seconds, raw_sse_chunks). Stubs MUST be installed first."""
    from core import pipeline_langgraph

    started = time.perf_counter()
    response = await pipeline_langgraph.chat_pipeline_streaming_agentic(
        user_query=user_query,
        session_id=session_id,
    )
    chunks = await _drain_pipeline_response(response)
    elapsed = time.perf_counter() - started
    return elapsed, chunks


async def run_pipeline_concurrent(
    *,
    n: int,
    user_query: str = "What does Islam say about patience?",
    session_prefix: str = "stub-session",
) -> Dict[str, Any]:
    """Fire N concurrent pipeline calls and return wall-clock + per-request stats."""

    async def _one(i: int):
        return await run_pipeline_once(
            user_query=user_query,
            session_id=f"{session_prefix}-{i}",
        )

    overall_started = time.perf_counter()
    results = await asyncio.gather(*[_one(i) for i in range(n)])
    overall_elapsed = time.perf_counter() - overall_started

    durations = sorted(r[0] for r in results)
    p50 = durations[len(durations) // 2]
    p95 = durations[max(0, int(round(len(durations) * 0.95)) - 1)]

    return {
        "n": n,
        "wall_clock_s": overall_elapsed,
        "per_request_s": durations,
        "p50_s": p50,
        "p95_s": p95,
        "throughput_rps": n / overall_elapsed if overall_elapsed > 0 else 0.0,
        "all_chunks": [r[1] for r in results],
    }


# --- Pytest fixtures -------------------------------------------------------


@pytest.fixture
def stub_config() -> StubConfig:
    """Default stub latencies. Override per-test by constructing your own
    StubConfig and passing it to install_pipeline_stubs()."""
    return StubConfig()


@pytest.fixture
def installed_stubs(stub_config):
    """Patch every blocking pipeline call for the duration of one test."""
    with install_pipeline_stubs(stub_config) as applied:
        yield applied
