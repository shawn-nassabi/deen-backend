from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple

from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import iterate_in_threadpool

from core.memory import amake_history, atrim_history, make_history, trim_history
from db.models.chat_messages import ChatMessage
from db.models.chat_sessions import ChatSession

REFERENCES_MARKER = "\n\n\n[REFERENCES]\n\n\n"


def build_runtime_session_id(user_id: str, session_id: str) -> str:
    return f"{user_id}:{session_id}"


def derive_chat_title(first_query: str) -> str:
    title = (first_query or "").strip()
    if not title:
        return "New Chat"
    return title[:50]


def extract_answer_text(stream_text: str) -> str:
    text = stream_text or ""

    marker_index = text.find(REFERENCES_MARKER)
    if marker_index != -1:
        text = text[:marker_index]

    agentic_text = _extract_agentic_sse_answer_text(text)
    if agentic_text or _looks_like_sse_stream(text):
        return agentic_text

    return text.strip()


def _looks_like_sse_stream(stream_text: str) -> bool:
    normalized = (stream_text or "").replace("\r\n", "\n").replace("\r", "\n")
    return "event:" in normalized and "data:" in normalized


def _extract_agentic_sse_answer_text(stream_text: str) -> str:
    normalized = (stream_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""

    tokens: List[str] = []
    for raw_event in re.split(r"\n\n+", normalized):
        if not raw_event.strip():
            continue

        event_type = None
        data_lines: List[str] = []
        for line in raw_event.split("\n"):
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())

        if event_type != "response_chunk" or not data_lines:
            continue

        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            continue

        token = payload.get("token")
        if isinstance(token, str) and token:
            tokens.append(token)

    return "".join(tokens).strip()


def _to_text(chunk: Any) -> str:
    if isinstance(chunk, bytes):
        return chunk.decode("utf-8", errors="ignore")
    return str(chunk)


async def _iterate_chunks(body_iterator: Any) -> AsyncIterator[Any]:
    if hasattr(body_iterator, "__aiter__"):
        async for chunk in body_iterator:
            yield chunk
        return

    async for chunk in iterate_in_threadpool(body_iterator):
        yield chunk


def _touch_session(session_row: ChatSession) -> None:
    now = datetime.utcnow()
    session_row.updated_at = now
    session_row.last_message_at = now


async def _get_session(db: AsyncSession, user_id: str, session_id: str) -> Optional[ChatSession]:
    stmt = (
        select(ChatSession)
        .where(ChatSession.user_id == user_id, ChatSession.session_id == session_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_or_create_session(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    first_query: str,
) -> ChatSession:
    session_row = await _get_session(db, user_id, session_id)
    if session_row:
        return session_row

    session_row = ChatSession(
        user_id=user_id,
        session_id=session_id,
        title=derive_chat_title(first_query),
    )
    db.add(session_row)
    await db.flush()
    return session_row


async def append_message(
    db: AsyncSession,
    *,
    session_row: ChatSession,
    role: str,
    content: str,
) -> ChatMessage:
    message = ChatMessage(
        chat_session_id=session_row.id,
        role=role,
        content=content,
    )
    db.add(message)
    _touch_session(session_row)
    return message


async def persist_user_message(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    user_query: str,
) -> ChatSession:
    session_row = await get_or_create_session(
        db,
        user_id=user_id,
        session_id=session_id,
        first_query=user_query,
    )
    await append_message(
        db,
        session_row=session_row,
        role="user",
        content=user_query,
    )
    await db.commit()
    await db.refresh(session_row)
    return session_row


async def persist_assistant_message(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    assistant_text: str,
) -> Optional[ChatMessage]:
    cleaned_text = (assistant_text or "").strip()
    if not cleaned_text:
        return None

    session_row = await _get_session(db, user_id, session_id)
    if not session_row:
        return None

    message = await append_message(
        db,
        session_row=session_row,
        role="assistant",
        content=cleaned_text,
    )
    await db.commit()
    return message


async def hydrate_runtime_history_if_empty(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
) -> str:
    """Async-native hydration: Redis check + Postgres backfill both run on the
    event loop without `asyncio.to_thread` (DEE-45)."""
    runtime_session_id = build_runtime_session_id(user_id, session_id)
    history = amake_history(runtime_session_id)

    if await history.aget_messages():
        return runtime_session_id

    session_row = await _get_session(db, user_id, session_id)
    if not session_row:
        return runtime_session_id

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.chat_session_id == session_row.id)
        .order_by(ChatMessage.id.asc())
    )
    result = await db.execute(stmt)
    db_messages = list(result.scalars().all())
    if not db_messages:
        return runtime_session_id

    langchain_messages = []
    for message in db_messages:
        if message.role == "user":
            langchain_messages.append(HumanMessage(content=message.content))
        elif message.role == "assistant":
            langchain_messages.append(AIMessage(content=message.content))

    if langchain_messages:
        await history.aadd_messages(langchain_messages)
        await atrim_history(history)

    return runtime_session_id


# Backwards-compatible alias retained for any caller still using the legacy name.
ahydrate_runtime_history_if_empty = hydrate_runtime_history_if_empty


def append_turn_to_runtime_history(
    *,
    runtime_session_id: str,
    user_query: str,
    assistant_text: str,
) -> None:
    """Sync variant kept for legacy callers and existing test patches. Prefer
    `aappend_turn_to_runtime_history` from inside an event loop (DEE-43)."""
    history = make_history(runtime_session_id)
    history.add_messages(
        [
            HumanMessage(content=user_query),
            AIMessage(content=assistant_text),
        ]
    )
    trim_history(history)


async def aappend_turn_to_runtime_history(
    *,
    runtime_session_id: str,
    user_query: str,
    assistant_text: str,
) -> None:
    """Async-native variant. Uses redis.asyncio so Redis I/O doesn't block
    the event loop on every concurrent agentic stream's persistence step."""
    history = amake_history(runtime_session_id)
    await history.aadd_messages(
        [
            HumanMessage(content=user_query),
            AIMessage(content=assistant_text),
        ]
    )
    await atrim_history(history)


async def list_sessions(
    db: AsyncSession,
    *,
    user_id: str,
    limit: int,
    offset: int,
) -> Tuple[List[Dict[str, Any]], int]:
    total_stmt = (
        select(func.count(ChatSession.id))
        .where(ChatSession.user_id == user_id)
    )
    total_result = await db.execute(total_stmt)
    total = total_result.scalar() or 0

    message_count_subq = (
        select(
            ChatMessage.chat_session_id.label("chat_session_id"),
            func.count(ChatMessage.id).label("message_count"),
        )
        .group_by(ChatMessage.chat_session_id)
        .subquery()
    )

    rows_stmt = (
        select(ChatSession, message_count_subq.c.message_count)
        .outerjoin(message_count_subq, ChatSession.id == message_count_subq.c.chat_session_id)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.last_message_at.desc(), ChatSession.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows_result = await db.execute(rows_stmt)
    rows = rows_result.all()

    items: List[Dict[str, Any]] = []
    for session_row, message_count in rows:
        items.append(
            {
                "session_id": session_row.session_id,
                "title": session_row.title,
                "created_at": session_row.created_at,
                "updated_at": session_row.updated_at,
                "last_message_at": session_row.last_message_at,
                "message_count": int(message_count or 0),
            }
        )

    return items, int(total)


async def get_session_with_messages(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    limit: int,
    offset: int,
) -> Optional[Dict[str, Any]]:
    session_row = await _get_session(db, user_id, session_id)
    if not session_row:
        return None

    total_stmt = (
        select(func.count(ChatMessage.id))
        .where(ChatMessage.chat_session_id == session_row.id)
    )
    total_result = await db.execute(total_stmt)
    total_messages = total_result.scalar() or 0

    messages_stmt = (
        select(ChatMessage)
        .where(ChatMessage.chat_session_id == session_row.id)
        .order_by(ChatMessage.id.asc())
        .offset(offset)
        .limit(limit)
    )
    messages_result = await db.execute(messages_stmt)
    messages = list(messages_result.scalars().all())

    return {
        "session_id": session_row.session_id,
        "title": session_row.title,
        "created_at": session_row.created_at,
        "updated_at": session_row.updated_at,
        "last_message_at": session_row.last_message_at,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
            }
            for message in messages
        ],
        "total_messages": int(total_messages),
    }


def wrap_streaming_response_for_persistence(
    *,
    response: StreamingResponse,
    db: AsyncSession,
    user_id: str,
    session_id: str,
    on_assistant_message_saved: Optional[Callable[[str], Awaitable[None] | None]] = None,
) -> StreamingResponse:
    original_iterator = response.body_iterator
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}

    async def _save_callback(text: str) -> None:
        if not on_assistant_message_saved:
            return
        result = on_assistant_message_saved(text)
        if hasattr(result, "__await__"):
            await result

    async def wrapped_iterator() -> AsyncIterator[Any]:
        collected_chunks: List[str] = []
        try:
            async for chunk in _iterate_chunks(original_iterator):
                collected_chunks.append(_to_text(chunk))
                yield chunk
        except Exception:
            partial_answer = extract_answer_text("".join(collected_chunks))
            if partial_answer:
                await persist_assistant_message(
                    db,
                    user_id=user_id,
                    session_id=session_id,
                    assistant_text=partial_answer,
                )
                await _save_callback(partial_answer)
            raise
        else:
            full_answer = extract_answer_text("".join(collected_chunks))
            if full_answer:
                await persist_assistant_message(
                    db,
                    user_id=user_id,
                    session_id=session_id,
                    assistant_text=full_answer,
                )
                await _save_callback(full_answer)

    return StreamingResponse(
        wrapped_iterator(),
        status_code=response.status_code,
        media_type=response.media_type,
        headers=headers,
        background=response.background,
    )
