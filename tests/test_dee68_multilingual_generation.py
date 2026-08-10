"""
DEE-68 multilingual generation tests.

Deterministic unit tests (mocked, no network) proving both the streaming
generation template and the non-streaming `_generate_response_node` inject
the user's `target_language` directive into the rendered generation request.

Token-cost DEE-60 Phase 3 note: with the cache-aware layout (AGENT_CACHE_V2,
default on) the language directive lives in the final human message instead
of the system message, so the model still receives it while the system block
stays byte-identical for prompt caching. These tests therefore assert the
directive appears anywhere in the rendered request, not in a specific slot.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

LANGUAGES = ["arabic", "farsi", "urdu", "german", "bahasa melayu", "french"]


def _rendered_text(messages) -> str:
    """Flatten every message's content (string or block-list) to one string."""
    parts = []
    for message in messages:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    parts.append(str(block.get("text", "")))
                else:
                    parts.append(str(block))
    return "\n".join(parts)


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
        rendered = _rendered_text(call_messages)
        assert lang.lower() in rendered.lower(), (
            f"target_language '{lang}' not injected into the rendered request: {rendered[:200]}"
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

        rendered = _rendered_text(messages)
        assert lang.lower() in rendered.lower(), (
            f"target_language '{lang}' not found in the rendered generator messages"
        )
