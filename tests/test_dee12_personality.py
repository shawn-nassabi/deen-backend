"""
DEE-12 personality + intent routing tests.

Deterministic unit tests mock the LLM; opt-in real_llm tests require live
Anthropic + Supabase + Pinecone (run with: pytest -m real_llm tests/test_dee12_personality.py).
"""
from __future__ import annotations

import asyncio
import sys
import os

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Deterministic unit tests — no network, no live LLM
# ---------------------------------------------------------------------------


class TestIntentClassifier:
    """aclassify_intent returns correct labels based on mocked LLM output."""

    @pytest.mark.asyncio
    async def test_aclassify_intent_casual(self):
        from modules.classification.classifier import aclassify_intent

        mock_response = MagicMock()
        mock_response.content = "casual"
        with patch(
            "modules.classification.classifier._aclassify_intent_call",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await aclassify_intent("hi", None)
        assert result == "casual"

    @pytest.mark.asyncio
    async def test_aclassify_intent_non_islamic(self):
        from modules.classification.classifier import aclassify_intent

        mock_response = MagicMock()
        mock_response.content = "non_islamic"
        with patch(
            "modules.classification.classifier._aclassify_intent_call",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await aclassify_intent("who won the World Cup?", None)
        assert result == "non_islamic"

    @pytest.mark.asyncio
    async def test_aclassify_intent_islamic(self):
        from modules.classification.classifier import aclassify_intent

        mock_response = MagicMock()
        mock_response.content = "islamic"
        with patch(
            "modules.classification.classifier._aclassify_intent_call",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await aclassify_intent("what is Imamate?", None)
        assert result == "islamic"

    @pytest.mark.asyncio
    async def test_aclassify_intent_unexpected_fallback(self):
        """Unexpected LLM output must fall back to 'islamic' (safe, avoids over-refusal)."""
        from modules.classification.classifier import aclassify_intent

        mock_response = MagicMock()
        mock_response.content = "garbage_value_not_a_valid_label"
        with patch(
            "modules.classification.classifier._aclassify_intent_call",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await aclassify_intent("something", None)
        assert result == "islamic"

    @pytest.mark.asyncio
    async def test_aclassify_intent_strips_whitespace(self):
        """LLM response with leading/trailing whitespace is normalised."""
        from modules.classification.classifier import aclassify_intent

        mock_response = MagicMock()
        mock_response.content = "  CASUAL  "  # uppercase + whitespace
        with patch(
            "modules.classification.classifier._aclassify_intent_call",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await aclassify_intent("salam", None)
        assert result == "casual"


class TestShouldContinueRouting:
    """_should_continue must route casual and non-Islamic states to 'exit'."""

    def _make_agent(self):
        from agents.core.chat_agent import ChatAgent
        from agents.config.agent_config import DEFAULT_AGENT_CONFIG
        return ChatAgent(DEFAULT_AGENT_CONFIG)

    def _make_state(self, user_query="test", **overrides):
        from agents.state.chat_state import create_initial_state
        state = create_initial_state(user_query, "test-session-routing")
        state.update(overrides)
        return state

    def test_should_continue_routes_casual_to_exit(self):
        agent = self._make_agent()
        state = self._make_state(user_query="hi", is_casual=True)
        result = agent._should_continue(state)
        assert result == "exit", f"Expected 'exit' for casual state, got '{result}'"

    def test_should_continue_routes_non_islamic_to_exit(self):
        agent = self._make_agent()
        state = self._make_state(user_query="who won the World Cup?", is_non_islamic=True)
        result = agent._should_continue(state)
        assert result == "exit", f"Expected 'exit' for non-Islamic state, got '{result}'"

    def test_should_continue_routes_fiqh_to_exit(self):
        agent = self._make_agent()
        state = self._make_state(user_query="can I fast while traveling?", is_fiqh=True)
        result = agent._should_continue(state)
        assert result == "exit", f"Expected 'exit' for fiqh state, got '{result}'"


class TestClassificationNodeIntent:
    """DEE-12: _fiqh_classification_node runs deterministic intent classification first,
    and _route_after_fiqh_check exits early for casual / non-Islamic intent — so casual
    routing no longer depends on the agent's discretionary tool calls."""

    def _make_agent(self):
        from agents.core.chat_agent import ChatAgent
        from agents.config.agent_config import DEFAULT_AGENT_CONFIG
        return ChatAgent(DEFAULT_AGENT_CONFIG)

    def _make_state(self, user_query="test", **overrides):
        from agents.state.chat_state import create_initial_state
        state = create_initial_state(user_query, "test-session-intent")
        state.update(overrides)
        return state

    @pytest.mark.asyncio
    async def test_node_casual_sets_flag_and_skips_fiqh(self):
        agent = self._make_agent()
        state = self._make_state(user_query="salam!")
        with patch("modules.classification.classifier.aclassify_intent",
                   new_callable=AsyncMock, return_value="casual"), \
             patch("modules.fiqh.classifier.aclassify_fiqh_query",
                   new_callable=AsyncMock, return_value="VALID_SMALL") as m_fiqh:
            result = await agent._fiqh_classification_node(state)
        assert result["is_casual"] is True
        assert result["is_non_islamic"] is False
        assert result["is_fiqh"] is False
        m_fiqh.assert_not_called()

    @pytest.mark.asyncio
    async def test_node_non_islamic_sets_flag_and_skips_fiqh(self):
        agent = self._make_agent()
        state = self._make_state(user_query="who won the World Cup?")
        with patch("modules.classification.classifier.aclassify_intent",
                   new_callable=AsyncMock, return_value="non_islamic"), \
             patch("modules.fiqh.classifier.aclassify_fiqh_query",
                   new_callable=AsyncMock, return_value="VALID_SMALL") as m_fiqh:
            result = await agent._fiqh_classification_node(state)
        assert result["is_non_islamic"] is True
        assert result["is_casual"] is False
        m_fiqh.assert_not_called()

    @pytest.mark.asyncio
    async def test_node_islamic_runs_fiqh(self):
        agent = self._make_agent()
        state = self._make_state(user_query="can I fast while traveling?")
        with patch("modules.classification.classifier.aclassify_intent",
                   new_callable=AsyncMock, return_value="islamic"), \
             patch("modules.fiqh.classifier.aclassify_fiqh_query",
                   new_callable=AsyncMock, return_value="VALID_SMALL") as m_fiqh:
            result = await agent._fiqh_classification_node(state)
        assert result["is_casual"] is False
        assert result["is_non_islamic"] is False
        assert result["is_fiqh"] is True
        m_fiqh.assert_called_once()

    @pytest.mark.asyncio
    async def test_node_intent_error_defaults_safe(self):
        agent = self._make_agent()
        state = self._make_state(user_query="something")
        with patch("modules.classification.classifier.aclassify_intent",
                   new_callable=AsyncMock, side_effect=Exception("boom")), \
             patch("modules.fiqh.classifier.aclassify_fiqh_query",
                   new_callable=AsyncMock, return_value="OUT_OF_SCOPE_FIQH"):
            result = await agent._fiqh_classification_node(state)
        assert result["is_casual"] is False
        assert result["is_non_islamic"] is False

    def test_route_casual_exits(self):
        agent = self._make_agent()
        assert agent._route_after_fiqh_check(self._make_state(is_casual=True, fiqh_category="")) == "exit"

    def test_route_non_islamic_exits(self):
        agent = self._make_agent()
        assert agent._route_after_fiqh_check(self._make_state(is_non_islamic=True, fiqh_category="")) == "exit"

    def test_route_islamic_continues(self):
        agent = self._make_agent()
        state = self._make_state(is_casual=False, is_non_islamic=False, fiqh_category="OUT_OF_SCOPE_FIQH")
        assert agent._route_after_fiqh_check(state) == "continue"

    def test_route_fiqh_goes_to_fiqh(self):
        agent = self._make_agent()
        state = self._make_state(is_casual=False, is_non_islamic=False, fiqh_category="VALID_SMALL")
        assert agent._route_after_fiqh_check(state) == "fiqh"


class TestCheckEarlyExitNode:
    """_check_early_exit_node branches: casual, non-Islamic, UNETHICAL."""

    def _make_agent(self):
        from agents.core.chat_agent import ChatAgent
        from agents.config.agent_config import DEFAULT_AGENT_CONFIG
        return ChatAgent(DEFAULT_AGENT_CONFIG)

    def _make_state(self, user_query="test", **overrides):
        from agents.state.chat_state import create_initial_state
        state = create_initial_state(user_query, "test-session-exit")
        state.update(overrides)
        return state

    def _mock_llm_returning(self, text: str):
        """Patch get_classifier_model to return a model whose ainvoke returns text."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = text
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        return mock_model

    @pytest.mark.asyncio
    async def test_check_early_exit_casual(self):
        agent = self._make_agent()
        state = self._make_state(user_query="hi", is_casual=True)
        mock_model = self._mock_llm_returning("Welcome!")
        with patch("core.chat_models.get_classifier_model", return_value=mock_model):
            result = await agent._check_early_exit_node(state)
        assert result["final_response"] == "Welcome!"
        assert result["early_exit_message"] == "Welcome!"

    @pytest.mark.asyncio
    async def test_check_early_exit_casual_fallback(self):
        """LLM raises → fallback to EARLY_EXIT_CASUAL constant."""
        from agents.prompts.agent_prompts import EARLY_EXIT_CASUAL

        agent = self._make_agent()
        state = self._make_state(user_query="salam", is_casual=True)
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(side_effect=Exception("timeout"))
        with patch("core.chat_models.get_classifier_model", return_value=mock_model):
            result = await agent._check_early_exit_node(state)
        assert result["final_response"] == EARLY_EXIT_CASUAL
        assert result["early_exit_message"] == EARLY_EXIT_CASUAL

    @pytest.mark.asyncio
    async def test_check_early_exit_non_islamic(self):
        agent = self._make_agent()
        state = self._make_state(user_query="who won the World Cup?", is_non_islamic=True)
        mock_model = self._mock_llm_returning("I focus on Islamic topics, feel free to ask!")
        with patch("core.chat_models.get_classifier_model", return_value=mock_model):
            result = await agent._check_early_exit_node(state)
        assert result["final_response"] == "I focus on Islamic topics, feel free to ask!"
        assert result["early_exit_message"] == "I focus on Islamic topics, feel free to ask!"

    @pytest.mark.asyncio
    async def test_check_early_exit_non_islamic_fallback(self):
        """LLM raises → fallback to EARLY_EXIT_NON_ISLAMIC constant."""
        from agents.prompts.agent_prompts import EARLY_EXIT_NON_ISLAMIC

        agent = self._make_agent()
        state = self._make_state(user_query="recipe for pizza?", is_non_islamic=True)
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(side_effect=Exception("network error"))
        with patch("core.chat_models.get_classifier_model", return_value=mock_model):
            result = await agent._check_early_exit_node(state)
        assert result["final_response"] == EARLY_EXIT_NON_ISLAMIC
        assert result["early_exit_message"] == EARLY_EXIT_NON_ISLAMIC

    @pytest.mark.asyncio
    async def test_casual_branch_precedes_non_islamic(self):
        """When both is_casual and is_non_islamic are True, casual branch fires first."""
        agent = self._make_agent()
        state = self._make_state(user_query="hi", is_casual=True, is_non_islamic=True)
        mock_model = self._mock_llm_returning("Casual reply!")
        with patch("core.chat_models.get_classifier_model", return_value=mock_model):
            result = await agent._check_early_exit_node(state)
        # The casual branch should have triggered (LLM was called once for casual)
        assert mock_model.ainvoke.call_count == 1
        # Verify the prompt contains "casual or social message" (casual branch prompt)
        call_args = mock_model.ainvoke.call_args[0][0]
        assert any("casual" in str(msg.content).lower() for msg in call_args)


class TestInitialState:
    """create_initial_state includes is_casual field."""

    def test_is_casual_in_initial_state(self):
        from agents.state.chat_state import create_initial_state
        state = create_initial_state("hi", "session-1")
        assert "is_casual" in state, "is_casual missing from initial state"
        assert state["is_casual"] is None

    def test_is_casual_default_none(self):
        from agents.state.chat_state import create_initial_state
        state = create_initial_state("what is Imamate?", "session-2")
        assert state["is_casual"] is None


class TestPromptTemplates:
    """Prompt template static checks."""

    def test_intent_classifier_system_template_has_all_labels(self):
        from core.prompt_templates import intentClassifierSystemTemplate
        assert "casual" in intentClassifierSystemTemplate.lower()
        assert "non_islamic" in intentClassifierSystemTemplate.lower()
        assert "islamic" in intentClassifierSystemTemplate.lower()

    def test_intent_classifier_system_template_has_examples(self):
        from core.prompt_templates import intentClassifierSystemTemplate
        # Must include example labels for all three classes
        assert "→ casual" in intentClassifierSystemTemplate
        assert "→ non_islamic" in intentClassifierSystemTemplate
        assert "→ islamic" in intentClassifierSystemTemplate

    def test_generator_system_template_has_voice_section(self):
        from core.prompt_templates import generatorSystemTemplate
        assert "Voice" in generatorSystemTemplate or "voice" in generatorSystemTemplate.lower()

    def test_agent_system_prompt_has_voice_section(self):
        from agents.prompts.agent_prompts import AGENT_SYSTEM_PROMPT
        assert "Voice" in AGENT_SYSTEM_PROMPT

    def test_early_exit_casual_importable(self):
        from agents.prompts.agent_prompts import EARLY_EXIT_CASUAL, EARLY_EXIT_NON_ISLAMIC
        assert EARLY_EXIT_CASUAL
        assert EARLY_EXIT_NON_ISLAMIC
        # Both must be non-empty strings
        assert len(EARLY_EXIT_CASUAL) > 10
        assert len(EARLY_EXIT_NON_ISLAMIC) > 10

    def test_bool_classifiers_still_exist(self):
        """Legacy bool classifiers must still be importable and callable."""
        from modules.classification.classifier import (
            aclassify_non_islamic_query,
            classify_non_islamic_query,
        )
        import inspect
        assert inspect.iscoroutinefunction(aclassify_non_islamic_query)
        assert callable(classify_non_islamic_query)


# ---------------------------------------------------------------------------
# Opt-in real_llm tests — require live Anthropic + Pinecone + Supabase
# ---------------------------------------------------------------------------


@pytest.mark.real_llm
class TestRealLLMPersonality:
    """Live end-to-end tests for DEE-12 personality routing.

    Run with: pytest -m real_llm tests/test_dee12_personality.py
    Requires ANTHROPIC_API_KEY and other env vars to be set.
    """

    def _make_agent(self):
        from agents.core.chat_agent import ChatAgent
        from agents.config.agent_config import DEFAULT_AGENT_CONFIG
        return ChatAgent(DEFAULT_AGENT_CONFIG)

    @pytest.mark.asyncio
    async def test_real_non_islamic_declined(self):
        """Non-Islamic query must be declined, not answered."""
        import uuid
        agent = self._make_agent()
        result = await agent.ainvoke(
            user_query="who won the World Cup in 2022?",
            session_id=f"dee12-test-{uuid.uuid4().hex}",
        )
        # Must have an early_exit_message (the decline message)
        assert result.get("early_exit_message") is not None
        # The response must NOT answer the World Cup question
        response_text = (result.get("early_exit_message") or "").lower()
        assert "won" not in response_text or "argentina" not in response_text, (
            "Response appears to have answered the off-topic question"
        )

    @pytest.mark.asyncio
    async def test_real_casual_warm_reply(self):
        """Casual greeting must receive a warm non-empty reply, not a retrieval error."""
        import uuid
        agent = self._make_agent()
        result = await agent.ainvoke(
            user_query="salam!",
            session_id=f"dee12-test-{uuid.uuid4().hex}",
        )
        early_exit = result.get("early_exit_message") or ""
        assert len(early_exit) > 10, (
            f"Casual reply too short or missing: '{early_exit}'"
        )
        # Must not be a retrieval failure / error message
        error_phrases = ["error", "failed", "unable to retrieve", "retrieval"]
        assert not any(p in early_exit.lower() for p in error_phrases), (
            f"Casual reply looks like an error: '{early_exit}'"
        )

    @pytest.mark.asyncio
    async def test_real_islamic_question_works(self):
        """Islamic question must produce a substantive answer via normal retrieval path."""
        import uuid
        agent = self._make_agent()
        result = await agent.ainvoke(
            user_query="What is the concept of Imamate in Twelver Shia Islam?",
            session_id=f"dee12-test-{uuid.uuid4().hex}",
        )
        final = result.get("final_response") or ""
        assert len(final) > 50, (
            f"Islamic question produced a too-short or empty answer: '{final}'"
        )
        # Must not be an early-exit refusal for Islamic content
        assert result.get("is_non_islamic") is not True
        assert result.get("is_casual") is not True
