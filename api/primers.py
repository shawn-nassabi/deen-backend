from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import logging
import json

from db.session import get_db
from db.crud.lessons import lesson_crud
from services.primer_service import PrimerService
from core.auth import auth
from core.context import correlation_id as correlation_id_ctx
from core.sentry import bind_sentry_scope
from models.JWTBearer import JWTAuthorizationCredentials
from models.schemas import (
    PersonalizedPrimerRequest,
    PersonalizedPrimerResponse,
    BaselinePrimerResponse
)

logger = logging.getLogger(__name__)

primers_router = APIRouter(
    prefix="/primers",
    tags=["primers"]
)


@primers_router.get("/{lesson_id}/baseline", response_model=BaselinePrimerResponse)
async def get_baseline_primer(
    lesson_id: int,
    credentials: JWTAuthorizationCredentials = Depends(auth),
    db: Session = Depends(get_db),
):
    """
    Get baseline primer for a lesson.
    Returns preset bullets and glossary that are shown to all users.
    """
    corr_id = correlation_id_ctx.get()
    bind_sentry_scope(corr_id, "/primers/{lesson_id}/baseline", user_id=None)

    try:
        logger.info(
            "Fetching baseline primer",
            extra={"correlation_id": corr_id, "lesson_id": lesson_id, "endpoint": "/primers/{lesson_id}/baseline"},
        )

        lesson = lesson_crud.get(db, lesson_id)
        if not lesson:
            logger.warning(
                "Lesson not found",
                extra={"correlation_id": corr_id, "lesson_id": lesson_id},
            )
            raise HTTPException(status_code=404, detail="Lesson not found")

        logger.info(
            "Baseline primer fetched successfully",
            extra={"correlation_id": corr_id, "lesson_id": lesson_id},
        )

        return BaselinePrimerResponse(
            lesson_id=lesson.id,
            baseline_bullets=lesson.baseline_primer_bullets or [],
            glossary=lesson.baseline_primer_glossary or {},
            updated_at=lesson.baseline_primer_updated_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error fetching baseline primer",
            exc_info=True,
            extra={"correlation_id": corr_id, "lesson_id": lesson_id},
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@primers_router.post("/personalized", response_model=PersonalizedPrimerResponse)
async def get_personalized_primer(
    request: PersonalizedPrimerRequest,
    credentials: JWTAuthorizationCredentials = Depends(auth),
    db: Session = Depends(get_db),
):
    """
    Get personalized "For You" primer section.

    Request body:
    - user_id: User identifier
    - lesson_id: Lesson to generate primer for
    - force_refresh: Optional, bypass cache and regenerate
    - filter: Optional, if True use embeddings-based filtering, if False use all notes (default: False)

    Returns:
    - personalized_bullets: List of 2-3 personalized prerequisite explanations
    - generated_at: Timestamp when primer was generated
    - from_cache: Whether result came from cache
    - stale: Whether cache was stale (returned anyway)
    - personalized_available: Whether personalization was possible
    """
    corr_id = correlation_id_ctx.get()
    bind_sentry_scope(corr_id, "/primers/personalized", user_id=request.user_id)

    try:
        logger.info(
            "Generating personalized primer",
            extra={
                "correlation_id": corr_id,
                "user_id": request.user_id,
                "lesson_id": request.lesson_id,
                "force_refresh": request.force_refresh,
                "filter": request.filter,
                "endpoint": "/primers/personalized",
            },
        )

        # Validate lesson exists
        lesson = lesson_crud.get(db, request.lesson_id)
        if not lesson:
            logger.warning(
                "Lesson not found",
                extra={"correlation_id": corr_id, "lesson_id": request.lesson_id},
            )
            raise HTTPException(status_code=404, detail="Lesson not found")

        service = PrimerService(db)
        result = await service.generate_personalized_primer(
            user_id=request.user_id,
            lesson_id=request.lesson_id,
            force_refresh=request.force_refresh,
            filter=request.filter
        )

        logger.info(
            "Personalized primer generated",
            extra={
                "correlation_id": corr_id,
                "user_id": request.user_id,
                "lesson_id": request.lesson_id,
                "filter": request.filter,
                "from_cache": result.get("from_cache"),
                "personalized_available": result.get("personalized_available"),
            },
        )

        return PersonalizedPrimerResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error generating personalized primer",
            exc_info=True,
            extra={
                "correlation_id": corr_id,
                "user_id": request.user_id,
                "lesson_id": request.lesson_id,
                "filter": request.filter,
            },
        )

        # Return fallback response instead of 500 error
        return PersonalizedPrimerResponse(
            personalized_bullets=[],
            generated_at=None,
            from_cache=False,
            stale=False,
            personalized_available=False
        )


@primers_router.post("/personalized/stream")
async def stream_personalized_primer(
    request: PersonalizedPrimerRequest,
    credentials: JWTAuthorizationCredentials = Depends(auth),
    db: Session = Depends(get_db),
):
    """
    Stream personalized primer generation in real-time.

    Request body:
    - user_id: User identifier
    - lesson_id: Lesson to generate primer for
    - force_refresh: Optional, bypass cache and regenerate
    - filter: Optional, if True use embeddings-based filtering, if False use all notes (default: False)

    This endpoint returns Server-Sent Events (SSE) with the following event types:
    - status: Status updates (checking cache, generating, etc.)
    - llm_chunk: Raw LLM tokens as they're generated (real-time streaming)
    - bullet: Individual parsed bullet after LLM completes
    - metadata: Final metadata (from_cache, personalized_available, etc.)
    - error: Error information
    - done: Completion signal

    Example SSE format:
    event: status
    data: {"message": "Checking cache..."}

    event: llm_chunk
    data: {"content": "{\n  \"person"}

    event: bullet
    data: {"index": 0, "content": "First personalized bullet..."}

    event: done
    data: {"success": true}
    """
    corr_id = correlation_id_ctx.get()
    bind_sentry_scope(corr_id, "/primers/personalized/stream", user_id=request.user_id)

    async def event_generator():
        """Generate SSE events for streaming primer generation"""
        try:
            logger.info(
                "Starting streaming primer generation",
                extra={
                    "correlation_id": corr_id,
                    "user_id": request.user_id,
                    "lesson_id": request.lesson_id,
                    "force_refresh": request.force_refresh,
                    "filter": request.filter,
                    "endpoint": "/primers/personalized/stream",
                },
            )

            # Send initial status
            yield f"event: status\ndata: {json.dumps({'message': 'Starting primer generation...'})}\n\n"

            # Validate lesson exists
            lesson = lesson_crud.get(db, request.lesson_id)
            if not lesson:
                logger.warning(
                    "Lesson not found",
                    extra={"correlation_id": corr_id, "lesson_id": request.lesson_id},
                )
                yield f"event: error\ndata: {json.dumps({'error': 'Lesson not found'})}\n\n"
                yield f"event: done\ndata: {json.dumps({'success': False})}\n\n"
                return

            service = PrimerService(db)

            # Stream the generation process
            async for event in service.stream_personalized_primer(
                user_id=request.user_id,
                lesson_id=request.lesson_id,
                force_refresh=request.force_refresh,
                filter=request.filter
            ):
                event_type = event.get("type", "status")
                event_data = {k: v for k, v in event.items() if k != "type"}

                # Format as SSE
                yield f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"

            # Send completion event
            yield f"event: done\ndata: {json.dumps({'success': True})}\n\n"

            logger.info(
                "Streaming primer generation completed",
                extra={
                    "correlation_id": corr_id,
                    "user_id": request.user_id,
                    "lesson_id": request.lesson_id,
                    "filter": request.filter,
                },
            )

        except HTTPException as http_exc:
            logger.error(
                "HTTP error in streaming primer generation",
                exc_info=True,
                extra={"correlation_id": corr_id, "endpoint": "/primers/personalized/stream"},
            )
            yield f"event: error\ndata: {json.dumps({'error': str(http_exc.detail)})}\n\n"
            yield f"event: done\ndata: {json.dumps({'success': False})}\n\n"

        except Exception as e:
            logger.error(
                "Error in streaming primer generation",
                exc_info=True,
                extra={
                    "correlation_id": corr_id,
                    "user_id": request.user_id,
                    "lesson_id": request.lesson_id,
                    "filter": request.filter,
                },
            )

            # Send error event
            yield f"event: error\ndata: {json.dumps({'error': 'Internal server error', 'personalized_available': False})}\n\n"
            yield f"event: done\ndata: {json.dumps({'success': False})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable buffering in nginx
        }
    )
