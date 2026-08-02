"""
Token-cost DEE-60 Phase 5 tests (long-chat conversation summaries).

Covers: trigger threshold + every-second-turn refresh cadence, Haiku
summarization + Redis storage (faked), summary injection only when the
history budget dropped messages, kill-switch, and the fire-and-forget
persistence hook.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

import services.summary_service as summary_service
from core import memory


def _run(coro):
    return asyncio.run(coro)


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


class _FakeHistory:
    def __init__(self, messages):
        self._messages = messages

    async def aget_messages(self):
        return list(self._messages)


def _turns(n_pairs):
    msgs = []
    for i in range(n_pairs):
        msgs.append(HumanMessage(content=f"question {i}"))
        msgs.append(AIMessage(content=f"answer {i}"))
    return msgs


def _patch_env(monkeypatch, messages, fake_redis=None, summary_calls=None):
    fake_redis = fake_redis if fake_redis is not None else _FakeRedis()
    monkeypatch.setattr(memory, "USE_REDIS", True)
    monkeypatch.setattr(memory, "_get_async_redis", lambda: fake_redis)
    monkeypatch.setattr(memory, "amake_history", lambda sid: _FakeHistory(messages))

    calls = summary_calls if summary_calls is not None else []

    class _FakeModel:
        async def ainvoke(self, msgs):
            calls.append(msgs)
            return SimpleNamespace(content="Earlier the user asked about patience and Imamate.", response_metadata={})

    from core import chat_models

    monkeypatch.setattr(chat_models, "get_enhancer_model", lambda: _FakeModel())
    return fake_redis, calls


def test_no_refresh_below_trigger(monkeypatch):
    monkeypatch.delenv("HISTORY_SUMMARY", raising=False)
    fake_redis, calls = _patch_env(monkeypatch, _turns(5))  # 10 msgs == trigger
    _run(summary_service.refresh_session_summary("s1"))
    assert calls == [] and fake_redis.store == {}


def test_refresh_summarizes_older_turns_and_stores(monkeypatch):
    monkeypatch.delenv("HISTORY_SUMMARY", raising=False)
    # 14 messages: (14 - 10) % 4 == 0 -> refresh runs
    fake_redis, calls = _patch_env(monkeypatch, _turns(7))
    _run(summary_service.refresh_session_summary("s1"))

    assert len(calls) == 1
    prompt = calls[0][0].content
    assert "question 0" in prompt
    assert "question 6" not in prompt, "the freshest turns must NOT be summarized"
    stored = fake_redis.store[summary_service._summary_key("s1")]
    assert b"patience" in stored


def test_refresh_cadence_every_second_turn(monkeypatch):
    monkeypatch.delenv("HISTORY_SUMMARY", raising=False)
    # 12 messages: (12 - 10) % 4 == 2 -> skip this turn
    fake_redis, calls = _patch_env(monkeypatch, _turns(6))
    _run(summary_service.refresh_session_summary("s1"))
    assert calls == [] and fake_redis.store == {}


def test_kill_switch_disables_everything(monkeypatch):
    monkeypatch.setenv("HISTORY_SUMMARY", "0")
    fake_redis, calls = _patch_env(monkeypatch, _turns(8))
    _run(summary_service.refresh_session_summary("s1"))
    assert calls == []
    assert _run(summary_service.get_session_summary("s1")) is None


def test_prepend_only_when_budget_dropped_messages(monkeypatch):
    monkeypatch.delenv("HISTORY_SUMMARY", raising=False)
    fake_redis = _FakeRedis()
    fake_redis.store[summary_service._summary_key("s1")] = b"Earlier: patience discussion."
    monkeypatch.setattr(memory, "USE_REDIS", True)
    monkeypatch.setattr(memory, "_get_async_redis", lambda: fake_redis)

    full = _turns(10)
    budgeted = full[-8:]
    result = _run(summary_service.prepend_summary_if_truncated("s1", full, budgeted))
    assert isinstance(result[0], HumanMessage)
    assert "Summary of the earlier conversation" in result[0].content
    assert result[1:] == budgeted

    # Nothing dropped -> no injection even though a summary exists.
    untouched = _run(summary_service.prepend_summary_if_truncated("s1", budgeted, budgeted))
    assert untouched == budgeted


def test_persistence_hook_schedules_background_refresh(monkeypatch):
    monkeypatch.delenv("HISTORY_SUMMARY", raising=False)
    monkeypatch.setattr(memory, "USE_REDIS", True)
    scheduled = []

    async def _fake_refresh(session_id):
        scheduled.append(session_id)

    monkeypatch.setattr(summary_service, "refresh_session_summary", _fake_refresh)

    async def _drive():
        summary_service.maybe_schedule_summary_refresh("s-hook")
        await asyncio.sleep(0)  # let the task run

    _run(_drive())
    assert scheduled == ["s-hook"]


def test_schedule_is_noop_without_running_loop(monkeypatch):
    monkeypatch.delenv("HISTORY_SUMMARY", raising=False)
    monkeypatch.setattr(memory, "USE_REDIS", True)
    summary_service.maybe_schedule_summary_refresh("s-sync")  # must not raise
