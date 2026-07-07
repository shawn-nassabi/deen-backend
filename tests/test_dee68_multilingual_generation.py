"""
DEE-68 multilingual generation tests.

Deterministic unit tests (mocked, no network) proving both the streaming
generation template and the non-streaming `_generate_response_node` inject
the user's `target_language` directive into the generation system message.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

LANGUAGES = ["arabic", "farsi", "urdu", "german", "bahasa melayu", "french"]


class TestNonStreamingLanguageInjection:
    """_generate_response_node must inject state['target_language'] into the
    generation system message via core.prompt_templates.generator_messages,
    matching the streaming path's behavior."""

    def _make_agent(self):
        from agents.core.chat_agent import ChatAgent
        from agents.config.agent_config import DEFAULT_AGENT_CONFIG
        return ChatAgent(DEFAULT_AGENT_CONFIG)

    def _make_state(self, user_query="test", **overrides):
        from agents.state.chat_state import create_initial_state
        state = create_initial_state(user_query, "test-session-dee68", **overrides)
        state["retrieved_docs"] = []
        state["quran_docs"] = []
        return state

    @pytest.mark.asyncio
    @pytest.mark.parametrize("lang", LANGUAGES)
    async def test_generate_response_node_injects_target_language(self, lang):
        agent = self._make_agent()
        state = self._make_state(user_query="What is Imamate?", target_language=lang)

        mock_response = MagicMock(content="stub answer", response_metadata={})
        with patch(
            "agents.core.chat_agent._retry_ainvoke",
            new=AsyncMock(return_value=mock_response),
        ) as mocked_retry_ainvoke:
            result = await agent._generate_response_node(state)

        assert result["final_response"] == "stub answer"

        call_messages = mocked_retry_ainvoke.call_args[0][1]
        system_content = call_messages[0].content
        system_text = system_content if isinstance(system_content, str) else str(system_content)
        assert lang.lower() in system_text.lower(), (
            f"target_language '{lang}' not injected into system message: {system_text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_generate_response_node_english_control_case(self):
        """Default target_language='english' must still complete without error
        and set final_response."""
        agent = self._make_agent()
        state = self._make_state(user_query="What is Imamate?")
        assert state["target_language"] == "english"

        mock_response = MagicMock(content="stub answer", response_metadata={})
        with patch(
            "agents.core.chat_agent._retry_ainvoke",
            new=AsyncMock(return_value=mock_response),
        ):
            result = await agent._generate_response_node(state)

        assert result["final_response"] == "stub answer"
        assert not result["errors"]


class TestGeneratorMessagesTemplateInjectsLanguage:
    """Pure regression guard on the shared template mechanism used by both
    the streaming and (post-fix) non-streaming generation paths."""

    @pytest.mark.parametrize("lang", LANGUAGES)
    def test_generator_messages_injects_target_language(self, lang):
        from core import prompt_templates

        messages = prompt_templates.generator_messages(
            query="test query",
            references="",
            target_language=lang,
        )

        system_message = messages[0]
        assert lang.lower() in system_message.content.lower(), (
            f"target_language '{lang}' not found in generator_messages system content"
        )
