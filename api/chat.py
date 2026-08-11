from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from db.async_session import get_db_async
from db.schemas.chat_history import SavedChatDetailResponse, SavedChatListResponse
from models.JWTBearer import JWTAuthorizationCredentials
from models.schemas import ChatRequest
from core import pipeline
from core import pipeline_langgraph
from core.auth import auth
from core.memory import make_history
from core.rate_limit import enforce_chat_rate_limit
from agents.config.agent_config import AgentConfig
from services import chat_persistence_service
import logging
from core.context import correlation_id as correlation_id_ctx
from core.sentry import bind_sentry_scope

logger = logging.getLogger(__name__)

chat_router = APIRouter(
    prefix="/chat",
    tags=["chat"]
)
def _extract_user_id(credentials: Optional[JWTAuthorizationCredentials]) -> Optional[str]:
    if not credentials:
        return None
    return credentials.claims.get("sub")


def _require_user_id(credentials: JWTAuthorizationCredentials) -> str:
    user_id = _extract_user_id(credentials)
    if not user_id:
        raise HTTPException(status_code=403, detail="Invalid token: missing user identifier")
    return user_id

# Abuse guard on the chat POST routes. Route-level dependencies resolve before
# the endpoint's own parameters and in list order, so `auth` must be listed
# first — it populates `request.state.user_id`, which the limiter keys on.
# FastAPI caches it, so the JWT is still verified only once per request.
@chat_router.post("/", dependencies=[Depends(auth), Depends(enforce_chat_rate_limit)])
async def chat_pipeline_ep(
    request: ChatRequest,
    credentials: JWTAuthorizationCredentials = Depends(auth),
):
    """
    Non-streaming chat endpoint with Redis-backed memory.
    Expects:
      {
        "user_query": "What does Islam say about justice?",
        "session_id": "user42:thread-7"
      }
    """
    user_query = (request.user_query or "").strip()
    session_id = (getattr(request, "session_id", "") or "").strip()

    if not user_query:
        return {"response": "Please provide an appropriate query."}
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")

    try:
        ai_response = pipeline.chat_pipeline(user_query, session_id)
        return {"response": ai_response}
    except Exception:
        # Log the exception elsewhere; don't leak details to client
        raise HTTPException(status_code=500, detail="Internal Server Error")


@chat_router.post("/stream", dependencies=[Depends(auth), Depends(enforce_chat_rate_limit)])
async def chat_pipeline_stream_ep(
    request: ChatRequest,
    credentials: JWTAuthorizationCredentials = Depends(auth),
    db: AsyncSession = Depends(get_db_async),
):
    """
    Streaming chat endpoint with Redis-backed memory.
    Expects:
      {
        "user_query": "What does Islam say about justice?",
        "session_id": "user42:thread-7",
        "language": "english"
      }
    """
    user_query = (request.user_query or "").strip()
    session_id = (getattr(request, "session_id", "") or "").strip()
    target_language = (getattr(request, "language", "") or "english").strip()

    if not user_query:
        raise HTTPException(status_code=400, detail="Please provide an appropriate query.")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")

    try:
        user_id = _extract_user_id(credentials)
        runtime_session_id = session_id

        if user_id:
            runtime_session_id = await chat_persistence_service.hydrate_runtime_history_if_empty(
                db,
                user_id=user_id,
                session_id=session_id,
            )
            await chat_persistence_service.persist_user_message(
                db,
                user_id=user_id,
                session_id=session_id,
                user_query=user_query,
            )

        response = pipeline.chat_pipeline_streaming(user_query, runtime_session_id, target_language)

        if not user_id:
            return response

        return chat_persistence_service.wrap_streaming_response_for_persistence(
            response=response,
            db=db,
            user_id=user_id,
            session_id=session_id,
        )
    except Exception as e:
        logger.error(
            "Unhandled error in /chat/stream",
            exc_info=True,
            extra={"correlation_id": correlation_id_ctx.get(), "endpoint": "/chat/stream"},
        )
        raise HTTPException(status_code=500, detail="Internal Server Error")


@chat_router.post(
    "/stream/agentic",
    dependencies=[Depends(auth), Depends(enforce_chat_rate_limit)],
)
async def chat_pipeline_agentic_ep(
    request: ChatRequest,
    credentials: JWTAuthorizationCredentials = Depends(auth),
    db: AsyncSession = Depends(get_db_async),
):
    """
    Agentic streaming chat endpoint using LangGraph.
    
    The agent autonomously decides which tools to use based on the query.
    
    Expects:
      {
        "user_query": "What does Islam say about justice?",
        "session_id": "user42:thread-7",
        "language": "english",
        "config": {  // Optional configuration
          "retrieval": {
            "shia_doc_count": 5,
            "sunni_doc_count": 2
          },
          "model": {
            "agent_model": "claude-sonnet-4-6",
            "temperature": 0.7
          },
          "max_iterations": 3
        }
      }
    
    Returns:
      Streaming response with AI-generated answer and references
    """
    corr_id = correlation_id_ctx.get()
    user_query = (request.user_query or "").strip()
    session_id = (getattr(request, "session_id", "") or "").strip()
    target_language = (getattr(request, "language", "") or "english").strip()
    config_dict = getattr(request, "config", None)

    if not user_query:
        raise HTTPException(status_code=400, detail="Please provide an appropriate query.")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")

    try:
        user_id = _extract_user_id(credentials)
        bind_sentry_scope(corr_id, "/chat/stream/agentic", session_id=session_id, user_id=user_id)
        logger.info(
            "Agentic stream request accepted",
            extra={
                "correlation_id": corr_id,
                "session_id": session_id,
                "endpoint": "/chat/stream/agentic",
                "user_id": user_id,
                "query_length": len(user_query),
            },
        )
        runtime_session_id = session_id
        if user_id:
            runtime_session_id = await chat_persistence_service.hydrate_runtime_history_if_empty(
                db,
                user_id=user_id,
                session_id=session_id,
            )
            await chat_persistence_service.persist_user_message(
                db,
                user_id=user_id,
                session_id=session_id,
                user_query=user_query,
            )

        # Parse config if provided
        agent_config = None
        if config_dict:
            try:
                agent_config = AgentConfig.from_dict(config_dict)
            except Exception as e:
                logger.warning(
                    "Config parse error, using default config",
                    extra={
                        "correlation_id": corr_id,
                        "session_id": session_id,
                        "endpoint": "/chat/stream/agentic",
                    },
                )

        # Returns a StreamingResponse from the agentic pipeline
        response = await pipeline_langgraph.chat_pipeline_streaming_agentic(
            user_query=user_query,
            session_id=runtime_session_id,
            target_language=target_language,
            config=agent_config
        )

        logger.info(
            "Agentic stream response assembled, returning stream",
            extra={
                "correlation_id": corr_id,
                "session_id": session_id,
                "endpoint": "/chat/stream/agentic",
                "user_id": user_id,
            },
        )

        if not user_id:
            return response

        return chat_persistence_service.wrap_streaming_response_for_persistence(
            response=response,
            db=db,
            user_id=user_id,
            session_id=session_id,
        )
    except Exception as e:
        logger.error(
            "Unhandled error in /chat/stream/agentic",
            exc_info=True,
            extra={
                "correlation_id": corr_id,
                "session_id": session_id,
                "endpoint": "/chat/stream/agentic",
                "user_id": user_id,
            },
        )
        raise HTTPException(status_code=500, detail="Internal Server Error")


@chat_router.post("/agentic", dependencies=[Depends(auth), Depends(enforce_chat_rate_limit)])
async def chat_pipeline_agentic_non_stream_ep(
    request: ChatRequest,
    credentials: JWTAuthorizationCredentials = Depends(auth),
):
    """
    Agentic non-streaming chat endpoint using LangGraph.
    
    Returns complete response after agent finishes execution.
    
    Expects same format as /stream/agentic but returns JSON instead of streaming.
    """
    corr_id = correlation_id_ctx.get()
    user_id = _extract_user_id(credentials)
    user_query = (request.user_query or "").strip()
    session_id = (getattr(request, "session_id", "") or "").strip()
    target_language = (getattr(request, "language", "") or "english").strip()
    config_dict = getattr(request, "config", None)

    if not user_query:
        raise HTTPException(status_code=400, detail="Please provide an appropriate query.")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")

    bind_sentry_scope(corr_id, "/chat/agentic", session_id=session_id, user_id=user_id)
    logger.info(
        "Agentic request accepted",
        extra={
            "correlation_id": corr_id,
            "session_id": session_id,
            "endpoint": "/chat/agentic",
            "user_id": user_id,
            "query_length": len(user_query),
        },
    )

    try:
        # Parse config if provided
        agent_config = None
        if config_dict:
            try:
                agent_config = AgentConfig.from_dict(config_dict)
            except Exception as e:
                logger.warning(
                    "Config parse error, using default config",
                    extra={
                        "correlation_id": corr_id,
                        "session_id": session_id,
                        "endpoint": "/chat/agentic",
                    },
                )

        # Get response from agentic pipeline (async since DEE-41)
        result = await pipeline_langgraph.chat_pipeline_agentic(
            user_query=user_query,
            session_id=session_id,
            target_language=target_language,
            config=agent_config
        )

        logger.info(
            "Agentic request completed",
            extra={
                "correlation_id": corr_id,
                "session_id": session_id,
                "endpoint": "/chat/agentic",
                "user_id": user_id,
            },
        )

        return result
    except Exception as e:
        logger.error(
            "Unhandled error in /chat/agentic",
            exc_info=True,
            extra={
                "correlation_id": corr_id,
                "session_id": session_id,
                "endpoint": "/chat/agentic",
                "user_id": user_id,
            },
        )
        raise HTTPException(status_code=500, detail="Internal Server Error")


# OPTIONAL: Clear a conversation's memory (useful for a "Reset chat" button)
@chat_router.delete("/session/{session_id}")
async def clear_session(
    session_id: str,
    credentials: JWTAuthorizationCredentials = Depends(auth),
):
    try:
        history = make_history(session_id)
        history.clear()

        user_id = _extract_user_id(credentials)
        if user_id:
            scoped_history = make_history(chat_persistence_service.build_runtime_session_id(user_id, session_id))
            scoped_history.clear()

        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to clear session")


@chat_router.get("/saved", response_model=SavedChatListResponse)
async def list_saved_chats(
    credentials: JWTAuthorizationCredentials = Depends(auth),
    db: AsyncSession = Depends(get_db_async),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    user_id = _require_user_id(credentials)
    items, total = await chat_persistence_service.list_sessions(
        db,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@chat_router.get("/saved/{session_id}", response_model=SavedChatDetailResponse)
async def get_saved_chat(
    session_id: str,
    credentials: JWTAuthorizationCredentials = Depends(auth),
    db: AsyncSession = Depends(get_db_async),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    user_id = _require_user_id(credentials)
    result = await chat_persistence_service.get_session_with_messages(
        db,
        user_id=user_id,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Saved chat not found")

    result["limit"] = limit
    result["offset"] = offset
    return result
