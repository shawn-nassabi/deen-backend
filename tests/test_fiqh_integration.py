"""
Integration tests for Phase 4: fiqh SSE path in pipeline_langgraph.py
and routing logic in chat_agent.py.

All tests are mock-based — no real LLM, Pinecone, or Redis calls.
Run: pytest tests/test_fiqh_integration.py -v
"""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.state.chat_state import create_initial_state


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_fiqh_doc(ruling_number: str = "100") -> dict:
    return {
        "chunk_id": f"ruling_{ruling_number}_chunk0",
        "metadata": {
            "source_book": "Islamic Laws",
            "chapter": "Chapter of Purity",
            "section": "Wudu",
            "ruling_number": ruling_number,
            "text_en": f"Ruling {ruling_number} text",
        },
        "page_content": f"Ruling {ruling_number} text",
    }


def _make_sufficient_sea_result():
    from modules.fiqh.sea import SEAResult, Finding
    return SEAResult(
        findings=[Finding(description="test", confirmed=True, citation="quote", gap_summary="")],
        verdict="SUFFICIENT",
        confirmed_facts=["fact"],
        gaps=[],
    )


def _parse_sse_chunks(chunks: list[str]) -> list[dict]:
    """Parse raw SSE chunks into list of {event, data} dicts."""
    import re
    events = []
    buffer = "".join(chunks)
    for raw in re.split(r"\n\n+", buffer.strip()):
        if not raw.strip():
            continue
        event_type = data_str = None
        for line in raw.split("\n"):
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_str = line[5:].strip()
        if event_type:
            data = {}
            if data_str:
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    data = {"raw": data_str}
            events.append({"event": event_type, "data": data})
    return events


async def _collect_sse(gen) -> list[dict]:
    """Collect all SSE events from an async generator (StreamingResponse body)."""
    from fastapi.responses import StreamingResponse
    if isinstance(gen, StreamingResponse):
        chunks = []
        async for chunk in gen.body_iterator:
            if isinstance(chunk, bytes):
                chunks.append(chunk.decode())
            else:
                chunks.append(chunk)
        return _parse_sse_chunks(chunks)
    return []


# --------------------------------------------------------------------------- #
# Tests: pipeline_langgraph.py fiqh SSE path
# --------------------------------------------------------------------------- #

class TestFiqhSSEPath:
    """Tests for the fiqh streaming path in chat_pipeline_streaming_agentic."""

    def _make_fiqh_final_state(self, category: str = "VALID_SMALL", docs=None) -> dict:
        """Build a final_state dict that looks like a completed fiqh run."""
        s = create_initial_state("Is wudu required before salah?", "test-session")
        s["fiqh_category"] = category
        s["is_fiqh"] = category.startswith("VALID_")
        s["fiqh_filtered_docs"] = docs if docs is not None else [_make_fiqh_doc("100"), _make_fiqh_doc("101")]
        s["fiqh_sea_result"] = _make_sufficient_sea_result()
        s["early_exit_message"] = None  # valid fiqh — no early exit
        s["runtime_session_id"] = "test-session"
        return s

    @pytest.mark.asyncio
    async def test_fiqh_path_emits_stage_status_events(self):
        """Valid fiqh final_state produces status events for each fiqh pipeline stage."""
        final_state = self._make_fiqh_final_state("VALID_SMALL")

        with patch("agents.core.chat_agent.ChatAgent") as MockAgent:
            mock_agent = MagicMock()
            MockAgent.return_value = mock_agent

            # Simulate astream yielding one event with the fiqh node output
            async def fake_astream(*args, **kwargs):
                yield {"generate_fiqh_response": final_state}

            mock_agent.astream = fake_astream

            with patch("core.pipeline_langgraph.ChatAgent", MockAgent):
                    mock_model_instance = MagicMock()
                    mock_model_instance.stream.return_value = [
                        MagicMock(content="Based on Sistani's ruling [1], "),
                        MagicMock(content="wudu is required."),
                    ]

                    with patch("core.chat_models.get_generator_model", return_value=mock_model_instance):
                        from core.pipeline_langgraph import chat_pipeline_streaming_agentic
                        response = await chat_pipeline_streaming_agentic(
                            user_query="Is wudu required before salah?",
                            session_id="test-session",
                        )
                        events = await _collect_sse(response)

        step_names = [e["data"].get("step") for e in events if e["event"] == "status"]
        assert "fiqh_decompose" in step_names, f"Expected fiqh_decompose in status steps, got: {step_names}"
        assert "fiqh_retrieve" in step_names
        assert "fiqh_filter" in step_names
        assert "fiqh_assess" in step_names
        assert "generate_fiqh_response" in step_names

    @pytest.mark.asyncio
    async def test_fiqh_path_emits_response_chunks(self):
        """Valid fiqh final_state with docs produces response_chunk events."""
        final_state = self._make_fiqh_final_state("VALID_SMALL")

        with patch("agents.core.chat_agent.ChatAgent") as MockAgent:
            mock_agent = MagicMock()
            MockAgent.return_value = mock_agent

            async def fake_astream(*args, **kwargs):
                yield {"generate_fiqh_response": final_state}

            mock_agent.astream = fake_astream

            with patch("core.pipeline_langgraph.ChatAgent", MockAgent):
                    mock_model_instance = MagicMock()
                    mock_model_instance.stream.return_value = [MagicMock(content="wudu is required [1].")]

                    with patch("core.chat_models.get_generator_model", return_value=mock_model_instance):
                        with patch("services.chat_persistence_service.append_turn_to_runtime_history"):
                            from core.pipeline_langgraph import chat_pipeline_streaming_agentic
                            response = await chat_pipeline_streaming_agentic(
                                user_query="Is wudu required?",
                                session_id="test-session",
                            )
                            events = await _collect_sse(response)

        chunk_events = [e for e in events if e["event"] == "response_chunk"]
        assert len(chunk_events) > 0, "Expected at least one response_chunk event"
        end_events = [e for e in events if e["event"] == "response_end"]
        assert len(end_events) == 1, "Expected exactly one response_end event"

    @pytest.mark.asyncio
    async def test_fiqh_path_emits_fiqh_references_event(self):
        """Valid fiqh final_state produces a fiqh_references SSE event with correct metadata."""
        final_state = self._make_fiqh_final_state("VALID_SMALL", docs=[_make_fiqh_doc("712")])

        with patch("agents.core.chat_agent.ChatAgent") as MockAgent:
            mock_agent = MagicMock()
            MockAgent.return_value = mock_agent

            async def fake_astream(*args, **kwargs):
                yield {"generate_fiqh_response": final_state}

            mock_agent.astream = fake_astream

            with patch("core.pipeline_langgraph.ChatAgent", MockAgent):
                    mock_model_instance = MagicMock()
                    mock_model_instance.stream.return_value = [MagicMock(content="answer [1].")]

                    with patch("core.chat_models.get_generator_model", return_value=mock_model_instance):
                        with patch("services.chat_persistence_service.append_turn_to_runtime_history"):
                            from core.pipeline_langgraph import chat_pipeline_streaming_agentic
                            response = await chat_pipeline_streaming_agentic(
                                user_query="Fiqh question",
                                session_id="test-session",
                            )
                            events = await _collect_sse(response)

        ref_events = [e for e in events if e["event"] == "fiqh_references"]
        assert len(ref_events) == 1, f"Expected 1 fiqh_references event, got {len(ref_events)}"
        refs = ref_events[0]["data"]["references"]
        assert len(refs) == 1
        assert refs[0]["book"] == "Islamic Laws"
        assert refs[0]["ruling_number"] == "712"
        assert "chapter" in refs[0]
        assert "section" in refs[0]

    @pytest.mark.asyncio
    async def test_non_fiqh_path_no_fiqh_references_event(self):
        """Non-fiqh final_state does NOT emit fiqh_references event."""
        s = create_initial_state("Who was Imam Ali?", "test-session")
        s["fiqh_category"] = ""   # not fiqh
        s["retrieved_docs"] = []
        s["quran_docs"] = []
        s["early_exit_message"] = None
        s["runtime_session_id"] = "test-session"

        with patch("agents.core.chat_agent.ChatAgent") as MockAgent:
            mock_agent = MagicMock()
            MockAgent.return_value = mock_agent

            async def fake_astream(*args, **kwargs):
                yield {"agent": s}

            mock_agent.astream = fake_astream

            with patch("core.pipeline_langgraph.ChatAgent", MockAgent):
                from core.pipeline_langgraph import chat_pipeline_streaming_agentic
                response = await chat_pipeline_streaming_agentic(
                    user_query="Who was Imam Ali?",
                    session_id="test-session",
                )
                events = await _collect_sse(response)

        ref_events = [e for e in events if e["event"] == "fiqh_references"]
        assert len(ref_events) == 0, "Non-fiqh query must not emit fiqh_references event"

    @pytest.mark.asyncio
    async def test_fiqh_path_empty_docs_returns_fallback(self):
        """Fiqh path with empty fiqh_filtered_docs returns a fallback message without LLM call."""
        final_state = self._make_fiqh_final_state("VALID_SMALL", docs=[])

        with patch("agents.core.chat_agent.ChatAgent") as MockAgent:
            mock_agent = MagicMock()
            MockAgent.return_value = mock_agent

            async def fake_astream(*args, **kwargs):
                yield {"generate_fiqh_response": final_state}

            mock_agent.astream = fake_astream

            with patch("core.pipeline_langgraph.ChatAgent", MockAgent):
                with patch("services.chat_persistence_service.append_turn_to_runtime_history"):
                    from core.pipeline_langgraph import chat_pipeline_streaming_agentic
                    response = await chat_pipeline_streaming_agentic(
                        user_query="Fiqh question",
                        session_id="test-session",
                    )
                    events = await _collect_sse(response)

        chunk_events = [e for e in events if e["event"] == "response_chunk"]
        assert len(chunk_events) >= 1
        # Fallback text must reference sistani.org
        all_tokens = "".join(e["data"].get("token", "") for e in chunk_events)
        assert "sistani.org" in all_tokens.lower() or "sistani" in all_tokens.lower(), \
            f"Fallback must reference Sistani, got: {all_tokens[:200]}"
        # No fiqh_references event when no docs
        ref_events = [e for e in events if e["event"] == "fiqh_references"]
        assert len(ref_events) == 0


# --------------------------------------------------------------------------- #
# Tests: chat_agent.py routing logic
# --------------------------------------------------------------------------- #

class TestFiqhRouting:
    """Unit tests for routing logic in ChatAgent."""

    def _get_router(self):
        """Get _route_after_fiqh_check as a callable without instantiating ChatAgent."""
        from agents.core.chat_agent import ChatAgent
        # Create a minimal instance to access the method
        with patch.object(ChatAgent, "_create_llm_with_tools", return_value=MagicMock()):
            with patch.object(ChatAgent, "_build_graph", return_value=MagicMock()):
                with patch("langgraph.checkpoint.memory.MemorySaver"):
                    agent = object.__new__(ChatAgent)
                    return agent._route_after_fiqh_check

    def test_valid_fiqh_routes_to_fiqh(self):
        """VALID_SMALL fiqh_category routes to 'fiqh'."""
        router = self._get_router()
        for category in ["VALID_OBVIOUS", "VALID_SMALL", "VALID_LARGE", "VALID_REASONER"]:
            s = create_initial_state("q", "s")
            s["fiqh_category"] = category
            result = router(s)
            assert result == "fiqh", f"Expected 'fiqh' for {category}, got {result}"

    def test_out_of_scope_routes_to_exit(self):
        """OUT_OF_SCOPE_FIQH and UNETHICAL route to 'exit'."""
        router = self._get_router()
        for category in ["OUT_OF_SCOPE_FIQH", "UNETHICAL"]:
            s = create_initial_state("q", "s")
            s["fiqh_category"] = category
            result = router(s)
            assert result == "exit", f"Expected 'exit' for {category}, got {result}"

    def test_empty_category_routes_to_continue(self):
        """Empty fiqh_category (non-fiqh query) routes to 'continue'."""
        router = self._get_router()
        s = create_initial_state("Who was Imam Ali?", "s")
        s["fiqh_category"] = ""
        result = router(s)
        assert result == "continue"
