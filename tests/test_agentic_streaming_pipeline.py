import asyncio

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from agents.config.agent_config import AgentConfig, RetrievalConfig
from agents.core.chat_agent import ChatAgent
from agents.state.chat_state import create_initial_state
from agents.tools.retrieval_tools import retrieve_quran_tafsir_tool
from core import pipeline_langgraph


class _FakeLLM:
    def invoke(self, messages):
        return AIMessage(content="done")


def _make_agent(monkeypatch, config=None):
    monkeypatch.setattr(ChatAgent, "_create_llm_with_tools", lambda self: _FakeLLM())
    return ChatAgent(config or AgentConfig())


def test_tool_defaults_use_runtime_session_and_config(monkeypatch):
    agent = _make_agent(
        monkeypatch,
        AgentConfig(
            retrieval=RetrievalConfig(
                shia_doc_count=6,
                sunni_doc_count=3,
                quran_doc_count=4,
            )
        ),
    )
    state = create_initial_state(
        user_query="Tell me about patience",
        session_id="runtime-session",
        config=agent.config.to_dict(),
    )
    tool_calls = [
        {"name": "enhance_query_tool", "args": {}},
        {"name": "retrieve_shia_documents_tool", "args": {}},
        {"name": "retrieve_sunni_documents_tool", "args": {}},
        {"name": "retrieve_quran_tafsir_tool", "args": {}},
    ]

    agent._apply_tool_call_defaults(state, tool_calls)

    assert tool_calls[0]["args"]["session_id"] == "runtime-session"
    assert tool_calls[1]["args"]["num_documents"] == 6
    assert tool_calls[2]["args"]["num_documents"] == 3
    assert tool_calls[3]["args"]["num_documents"] == 4


def test_record_retrieval_result_tracks_sources_and_dedupes_docs(monkeypatch):
    agent = _make_agent(monkeypatch)
    state = create_initial_state(
        user_query="What does the Quran say about patience?",
        session_id="runtime-session",
        config=agent.config.to_dict(),
    )

    shia_doc = {
        "metadata": {
            "hadith_id": "h-1",
            "sect": "shia",
            "reference": "Al-Kafi",
        },
        "page_content_en": "Patience is a virtue.",
    }
    quran_doc = {
        "chunk_id": "q-1",
        "metadata": {
            "surah_name": "Al-Baqarah",
            "title": "Patience",
        },
        "page_content_en": "Tafsir text",
        "quran_translation": "Seek help through patience and prayer.",
    }

    agent._record_retrieval_result(
        state,
        {
            "source": "shia",
            "query_used": "patience in shia hadith",
            "count": 1,
            "documents": [shia_doc, shia_doc],
        },
        "retrieve_shia_documents_tool",
    )
    agent._record_retrieval_result(
        state,
        {
            "source": "quran_tafsir",
            "query_used": "quran verses about patience",
            "count": 1,
            "documents": [quran_doc],
        },
        "retrieve_quran_tafsir_tool",
    )

    assert len(state["retrieval_attempts"]) == 2
    assert len(state["retrieved_docs"]) == 1
    assert len(state["quran_docs"]) == 1
    assert state["source_coverage"]["shia"] is True
    assert state["source_coverage"]["quran_tafsir"] is True
    assert state["shia_docs_count"] == 1
    assert state["quran_docs_count"] == 1


def test_should_continue_prefers_tool_execution_over_existing_docs(monkeypatch):
    agent = _make_agent(monkeypatch)
    state = create_initial_state(
        user_query="Tell me about Imam Ali",
        session_id="runtime-session",
        config=agent.config.to_dict(),
        streaming_mode=True,
    )
    state["retrieved_docs"] = [
        {
            "metadata": {"hadith_id": "h-1", "sect": "shia"},
            "page_content_en": "Example",
        }
    ]
    state["retrieval_completed"] = True
    state["messages"] = [
        AIMessage(
            content="Need more evidence",
            tool_calls=[
                {
                    "name": "retrieve_sunni_documents_tool",
                    "args": {"query": "imam ali shared virtues"},
                    "id": "call-1",
                    "type": "tool_call",
                }
            ],
        )
    ]

    assert agent._should_continue(state) == "continue"


def test_streaming_pipeline_uses_runtime_history_and_appends_once(monkeypatch):
    captured = {"history": None, "append_calls": []}

    class FakeHistory:
        def __init__(self):
            self.messages = [HumanMessage(content="Earlier context")]

    class FakeAgent:
        def __init__(self, config):
            self.config = config

        async def astream(self, **kwargs):
            yield {
                "agent": {
                    "messages": [],
                    "runtime_session_id": "runtime-key",
                    "retrieved_docs": [
                        {
                            "metadata": {
                                "hadith_id": "h-1",
                                "sect": "shia",
                                "reference": "Al-Kafi",
                            },
                            "page_content_en": "Patience is from faith.",
                        }
                    ],
                    "quran_docs": [],
                }
            }

    def fake_make_history(session_id):
        assert session_id == "runtime-key"
        return FakeHistory()

    def fake_model_fn(payload):
        captured["history"] = payload  # payload is now the chat_history list directly
        return "Generated answer"

    def fake_append_turn_to_runtime_history(**kwargs):
        captured["append_calls"].append(kwargs)

    monkeypatch.setattr(pipeline_langgraph, "ChatAgent", FakeAgent)
    monkeypatch.setattr("core.memory.make_history", fake_make_history)
    monkeypatch.setattr(
        "core.prompt_templates.generator_messages",
        lambda query, references, target_language, chat_history: chat_history,
    )
    monkeypatch.setattr("core.chat_models.get_generator_model", lambda: RunnableLambda(fake_model_fn))
    monkeypatch.setattr(
        "services.chat_persistence_service.append_turn_to_runtime_history",
        fake_append_turn_to_runtime_history,
    )

    async def _run():
        response = await pipeline_langgraph.chat_pipeline_streaming_agentic(
            user_query="Tell me about patience",
            session_id="runtime-key",
            target_language="english",
        )
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    output = asyncio.run(_run())

    assert 'event: response_chunk' in output
    assert captured["history"] and captured["history"][0].content == "Earlier context"
    assert captured["append_calls"] == [
        {
            "runtime_session_id": "runtime-key",
            "user_query": "Tell me about patience",
            "assistant_text": "Generated answer",
        }
    ]


def test_streaming_pipeline_early_exit_appends_once(monkeypatch):
    append_calls = []

    class FakeAgent:
        def __init__(self, config):
            self.config = config

        async def astream(self, **kwargs):
            yield {
                "check_early_exit": {
                    "messages": [],
                    "runtime_session_id": "runtime-key",
                    "early_exit_message": "Please consult a qualified scholar.",
                }
            }

    monkeypatch.setattr(pipeline_langgraph, "ChatAgent", FakeAgent)
    monkeypatch.setattr(
        "services.chat_persistence_service.append_turn_to_runtime_history",
        lambda **kwargs: append_calls.append(kwargs),
    )

    async def _run():
        response = await pipeline_langgraph.chat_pipeline_streaming_agentic(
            user_query="Is shrimp halal?",
            session_id="runtime-key",
            target_language="english",
        )
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    output = asyncio.run(_run())

    assert "Please consult a qualified scholar." in output
    assert append_calls == [
        {
            "runtime_session_id": "runtime-key",
            "user_query": "Is shrimp halal?",
            "assistant_text": "Please consult a qualified scholar.",
        }
    ]


def test_retrieve_quran_tafsir_tool_returns_error_payload(monkeypatch):
    monkeypatch.setattr(
        "modules.retrieval.retriever.retrieve_quran_documents",
        lambda query, no_of_docs: (_ for _ in ()).throw(
            ValueError("QURAN_DENSE_INDEX_NAME is not configured.")
        ),
    )

    result = retrieve_quran_tafsir_tool.invoke(
        {"query": "Quranic evidence for Imamate", "num_documents": 3}
    )

    assert result["documents"] == []
    assert result["source"] == "quran_tafsir"
    assert result["query_used"] == "Quranic evidence for Imamate"
    assert "QURAN_DENSE_INDEX_NAME" in result["error"]


def test_streaming_pipeline_surfaces_quran_retrieval_unavailable_message(monkeypatch):
    append_calls = []

    class FakeAgent:
        def __init__(self, config):
            self.config = config

        async def astream(self, **kwargs):
            yield {
                "agent": {
                    "messages": [],
                    "runtime_session_id": "runtime-key",
                    "retrieved_docs": [],
                    "quran_docs": [],
                    "errors": [
                        "quran_tafsir retrieval error: QURAN_DENSE_INDEX_NAME is not configured."
                    ],
                }
            }

    monkeypatch.setattr(pipeline_langgraph, "ChatAgent", FakeAgent)
    monkeypatch.setattr(
        "services.chat_persistence_service.append_turn_to_runtime_history",
        lambda **kwargs: append_calls.append(kwargs),
    )

    async def _run():
        response = await pipeline_langgraph.chat_pipeline_streaming_agentic(
            user_query="Give me more Quran based evidence for Imamate",
            session_id="runtime-key",
            target_language="english",
        )
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    output = asyncio.run(_run())

    assert "I couldn't access the Quran and Tafsir sources I needed just now" in output
    assert append_calls == [
        {
            "runtime_session_id": "runtime-key",
            "user_query": "Give me more Quran based evidence for Imamate",
            "assistant_text": "I couldn't access the Quran and Tafsir sources I needed just now, so I can't answer this reliably.",
        }
    ]
