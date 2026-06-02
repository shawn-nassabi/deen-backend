"""
Regression tests for the async translation path.

Pin two contracts:

1. `atranslate_to_english` must not raise (it has a broad try/except that
   swallows + logs), but it must also not silently fall through to the
   original text because of a deterministic `AttributeError` in
   `_atranslate_to_english_call` — a bug that previously slipped past CI
   because no test exercised the async path.

2. The async helper must build messages via
   `prompt_templates.translation_messages(...)` — mirroring the sync
   `translate_to_english` — and pass them to `chat_model.ainvoke`.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.translation import translator


@pytest.mark.asyncio
async def test_atranslate_to_english_returns_translated_content(monkeypatch):
    """Happy path: mocked translator model returns AIMessage-like response,
    the function returns the stripped content (not the original text)."""
    fake_model = SimpleNamespace(
        ainvoke=AsyncMock(return_value=SimpleNamespace(content="Hello")),
    )
    monkeypatch.setattr(translator.chat_models, "get_translator_model", lambda: fake_model)

    out = await translator.atranslate_to_english("Bonjour", "french")

    assert out == "Hello"
    fake_model.ainvoke.assert_awaited_once()
    # Ensure messages (list), not a ChatPromptValue, are passed through.
    (call_args,), _ = fake_model.ainvoke.call_args_list[0].args, fake_model.ainvoke.call_args_list[0].kwargs
    assert isinstance(call_args, list) and call_args, "expected non-empty messages list"


@pytest.mark.asyncio
async def test_atranslate_to_english_does_not_raise_attribute_error(monkeypatch):
    """Regression: the previous implementation referenced
    `prompt_templates.translation_prompt_template`, which does not exist,
    so every call raised AttributeError. After the fix, the function must
    complete normally for a non-English query.
    """
    fake_model = SimpleNamespace(
        ainvoke=AsyncMock(return_value=SimpleNamespace(content="Peace")),
    )
    monkeypatch.setattr(translator.chat_models, "get_translator_model", lambda: fake_model)

    # If `_atranslate_to_english_call` raised AttributeError, the outer
    # function would catch it, log, and return the original text. We
    # assert the mocked content is returned — proving the inner call
    # succeeded.
    out = await translator.atranslate_to_english("Salam", "arabic")
    assert out == "Peace"


@pytest.mark.asyncio
async def test_atranslate_to_english_english_short_circuits(monkeypatch):
    """`source_language == 'english'` skips the LLM call entirely."""
    fake_model = SimpleNamespace(ainvoke=AsyncMock())
    monkeypatch.setattr(translator.chat_models, "get_translator_model", lambda: fake_model)

    out = await translator.atranslate_to_english("Hello", "english")
    assert out == "Hello"
    fake_model.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_atranslate_to_english_empty_string_short_circuits():
    """Empty input must return empty string without invoking any model."""
    out = await translator.atranslate_to_english("", "french")
    assert out == ""


def test_prompt_templates_has_translation_messages_helper():
    """Pin the public surface: `translation_messages` is the correct helper.
    The previously-referenced `translation_prompt_template` attribute does
    not exist on the module and must not be reintroduced without also
    updating callers."""
    from core import prompt_templates

    assert hasattr(prompt_templates, "translation_messages")
    assert not hasattr(prompt_templates, "translation_prompt_template")
