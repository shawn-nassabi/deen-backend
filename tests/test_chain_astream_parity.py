"""
Token-equivalence parity test for the Phase 1 (DEE-40) chain.stream → chain.astream
swap in core/pipeline_langgraph.py.

This test does NOT exercise the real pipeline; it isolates the contract we care
about — that for the same input, `chain.stream` and `chain.astream` yield the
same sequence of token strings against an identically-seeded model. If a future
LangChain upgrade changes streaming semantics or chunk types, this test catches
it without us having to run the whole agentic flow.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Iterator, List

import pytest
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.prompts import ChatPromptTemplate


_TOKENS = ["The ", "patience ", "is ", "rewarded ", "in ", "abundance."]


class _ParityModel(BaseChatModel):
    """Sync `_stream` and async `_astream` yield the exact same token sequence."""

    @property
    def _llm_type(self) -> str:
        return "parity-fake"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop=None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="".join(_TOKENS)))]
        )

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop=None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="".join(_TOKENS)))]
        )

    def _stream(
        self,
        messages: List[BaseMessage],
        stop=None,
        run_manager=None,
        **kwargs,
    ) -> Iterator[ChatGenerationChunk]:
        for tok in _TOKENS:
            yield ChatGenerationChunk(message=AIMessageChunk(content=tok))

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop=None,
        run_manager=None,
        **kwargs,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for tok in _TOKENS:
            yield ChatGenerationChunk(message=AIMessageChunk(content=tok))


def _build_chain():
    prompt = ChatPromptTemplate.from_messages([("human", "{query}")])
    return prompt | _ParityModel()


def _collect_sync_tokens() -> List[str]:
    chain = _build_chain()
    out: List[str] = []
    for chunk in chain.stream({"query": "patience"}):
        token = getattr(chunk, "content", str(chunk) if chunk is not None else "")
        if token:
            out.append(token)
    return out


async def _collect_async_tokens() -> List[str]:
    chain = _build_chain()
    out: List[str] = []
    async for chunk in chain.astream({"query": "patience"}):
        token = getattr(chunk, "content", str(chunk) if chunk is not None else "")
        if token:
            out.append(token)
    return out


@pytest.mark.asyncio
async def test_stream_and_astream_yield_identical_tokens():
    sync_tokens = _collect_sync_tokens()
    async_tokens = await _collect_async_tokens()

    # The order, count, and content must be byte-for-byte identical so the
    # SSE response_chunk events emitted to the client don't change shape
    # after the Phase 1 swap.
    assert sync_tokens == async_tokens
    assert "".join(sync_tokens) == "".join(_TOKENS)
