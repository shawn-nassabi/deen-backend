import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from core import pipeline
from core.auth import auth
from core.context import correlation_id as correlation_id_ctx
from core.logging_config import setup_logging
from core.sentry import bind_sentry_scope
from models.JWTBearer import JWTAuthorizationCredentials
from db.session import get_db
from models.schemas import (
    ElaborationRequest,
    LessonPageQuizQuestionsAdminResponse,
    LessonPageQuizQuestionsResponse,
    QuizQuestionAdminResponse,
    QuizQuestionCreateRequest,
    QuizQuestionPatchRequest,
    QuizQuestionPutRequest,
    QuizSubmissionAckResponse,
    SubmitLessonPageQuizAnswerRequest,
)
from services.hikmah_quiz_service import (
    HikmahQuizService,
    process_quiz_submission_background,
)

setup_logging()
logger = logging.getLogger("api.hikmah")

hikmah_router = APIRouter(
    prefix="/hikmah",
    tags=["hikmah"]
)


@hikmah_router.post("/elaborate/stream")
async def chat_pipeline_stream_ep(
    request: ElaborationRequest,
    credentials: JWTAuthorizationCredentials = Depends(auth),
):
    """
    Streaming endpoint to get explanation on selected text in a hikam tree lesson.
    Expects:
      {
        "selected_text": "What does Islam say about justice?",
        "context_text": "The full lesson text...",
        "hikmah_tree_name": "Hikam of Imam Ali",
        "lesson_name": "Justice and Fairness",
        "lesson_summary": "A brief summary of the lesson",
        "user_id": "user123"  // Optional: For memory agent to take notes
      }
    """

    corr_id = correlation_id_ctx.get()
    bind_sentry_scope(corr_id, "/hikmah/elaborate/stream", user_id=request.user_id)
    try:
        logger.info(
            "Hikmah elaboration request received",
            extra={
                "correlation_id": corr_id,
                "user_id": request.user_id,
                "selected_text_len": len(request.selected_text or ""),
                "selected_text_preview": (request.selected_text or "")[:120],
                "context_text_len": len(request.context_text or ""),
                "context_text_preview": (request.context_text or "")[:120],
                "lesson_summary_len": len(request.lesson_summary or ""),
                "lesson_summary_preview": (request.lesson_summary or "")[:120],
                "hikmah_tree_name": request.hikmah_tree_name,
                "lesson_name": request.lesson_name,
            },
        )
        # Returns a StreamingResponse from the now-async pipeline (DEE-44)
        return await pipeline.hikmah_elaboration_pipeline_streaming(
            selected_text=request.selected_text,
            context_text=request.context_text,
            hikmah_tree_name=request.hikmah_tree_name,
            lesson_name=request.lesson_name,
            lesson_summary=request.lesson_summary,
            user_id=request.user_id  # Pass user_id to pipeline for memory integration
        )
    except Exception as e:
        logger.error(
            "Unhandled error in /hikmah/elaborate/stream",
            exc_info=True,
            extra={"correlation_id": corr_id, "user_id": request.user_id},
        )
        raise HTTPException(status_code=500, detail="Internal Server Error")


@hikmah_router.get(
    "/pages/{lesson_content_id}/quiz-questions",
    response_model=LessonPageQuizQuestionsResponse,
)
async def get_page_quiz_questions(
    lesson_content_id: int,
    credentials: JWTAuthorizationCredentials = Depends(auth),
    db: Session = Depends(get_db),
):
    """Get all active multiple-choice quiz questions associated with a lesson page."""
    corr_id = correlation_id_ctx.get()
    try:
        service = HikmahQuizService(db)
        return service.get_questions_for_page(lesson_content_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Lesson content page not found")
    except Exception as e:
        logger.error(
            "Error fetching quiz questions",
            extra={"correlation_id": corr_id, "lesson_content_id": lesson_content_id, "error": str(e)},
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@hikmah_router.post(
    "/pages/{lesson_content_id}/quiz-submit",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=QuizSubmissionAckResponse,
)
async def submit_page_quiz_answer(
    lesson_content_id: int,
    request: SubmitLessonPageQuizAnswerRequest,
    background_tasks: BackgroundTasks,
    credentials: JWTAuthorizationCredentials = Depends(auth),
):
    """
    Fire-and-forget quiz answer submission endpoint.
    Returns immediately; processing is done asynchronously in the background.
    """
    background_tasks.add_task(
        process_quiz_submission_background,
        lesson_content_id,
        request.user_id,
        request.question_id,
        request.selected_choice_id,
        request.answered_at,
    )

    return QuizSubmissionAckResponse(status="received")


@hikmah_router.post(
    "/pages/{lesson_content_id}/quiz-questions",
    status_code=status.HTTP_201_CREATED,
    response_model=QuizQuestionAdminResponse,
)
async def create_page_quiz_question(
    lesson_content_id: int,
    request: QuizQuestionCreateRequest,
    credentials: JWTAuthorizationCredentials = Depends(auth),
    db: Session = Depends(get_db),
):
    """Create one quiz question (with choices) for a lesson page."""
    corr_id = correlation_id_ctx.get()
    try:
        service = HikmahQuizService(db)
        return service.create_question(lesson_content_id, request.model_dump())
    except LookupError:
        raise HTTPException(status_code=404, detail="Lesson content page not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            "Error creating quiz question",
            extra={"correlation_id": corr_id, "lesson_content_id": lesson_content_id, "error": str(e)},
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@hikmah_router.get(
    "/pages/{lesson_content_id}/quiz-questions/admin",
    response_model=LessonPageQuizQuestionsAdminResponse,
)
async def list_page_quiz_questions_admin(
    lesson_content_id: int,
    include_inactive: bool = Query(False),
    credentials: JWTAuthorizationCredentials = Depends(auth),
    db: Session = Depends(get_db),
):
    """List quiz questions for authoring (optionally including inactive questions)."""
    corr_id = correlation_id_ctx.get()
    try:
        service = HikmahQuizService(db)
        return service.list_questions_for_page_admin(lesson_content_id, include_inactive=include_inactive)
    except LookupError:
        raise HTTPException(status_code=404, detail="Lesson content page not found")
    except Exception as e:
        logger.error(
            "Error listing quiz questions for admin",
            extra={
                "correlation_id": corr_id,
                "lesson_content_id": lesson_content_id,
                "include_inactive": include_inactive,
                "error": str(e),
            },
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@hikmah_router.get(
    "/pages/{lesson_content_id}/quiz-questions/{question_id}",
    response_model=QuizQuestionAdminResponse,
)
async def get_page_quiz_question(
    lesson_content_id: int,
    question_id: int,
    credentials: JWTAuthorizationCredentials = Depends(auth),
    db: Session = Depends(get_db),
):
    """Get one quiz question for authoring."""
    corr_id = correlation_id_ctx.get()
    try:
        service = HikmahQuizService(db)
        return service.get_question_for_page(lesson_content_id, question_id)
    except LookupError as e:
        message = str(e)
        if "lesson content page" in message.lower():
            raise HTTPException(status_code=404, detail="Lesson content page not found")
        raise HTTPException(status_code=404, detail="Quiz question not found for lesson page")
    except Exception as e:
        logger.error(
            "Error fetching quiz question",
            extra={
                "correlation_id": corr_id,
                "lesson_content_id": lesson_content_id,
                "question_id": question_id,
                "error": str(e),
            },
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@hikmah_router.put(
    "/pages/{lesson_content_id}/quiz-questions/{question_id}",
    response_model=QuizQuestionAdminResponse,
)
async def replace_page_quiz_question(
    lesson_content_id: int,
    question_id: int,
    request: QuizQuestionPutRequest,
    credentials: JWTAuthorizationCredentials = Depends(auth),
    db: Session = Depends(get_db),
):
    """Replace question metadata and choices."""
    corr_id = correlation_id_ctx.get()
    try:
        service = HikmahQuizService(db)
        return service.replace_question(lesson_content_id, question_id, request.model_dump())
    except LookupError as e:
        message = str(e)
        if "lesson content page" in message.lower():
            raise HTTPException(status_code=404, detail="Lesson content page not found")
        raise HTTPException(status_code=404, detail="Quiz question not found for lesson page")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            "Error replacing quiz question",
            extra={
                "correlation_id": corr_id,
                "lesson_content_id": lesson_content_id,
                "question_id": question_id,
                "error": str(e),
            },
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@hikmah_router.patch(
    "/pages/{lesson_content_id}/quiz-questions/{question_id}",
    response_model=QuizQuestionAdminResponse,
)
async def patch_page_quiz_question(
    lesson_content_id: int,
    question_id: int,
    request: QuizQuestionPatchRequest,
    credentials: JWTAuthorizationCredentials = Depends(auth),
    db: Session = Depends(get_db),
):
    """Patch question metadata only."""
    corr_id = correlation_id_ctx.get()
    payload = request.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    try:
        service = HikmahQuizService(db)
        return service.patch_question(lesson_content_id, question_id, payload)
    except LookupError as e:
        message = str(e)
        if "lesson content page" in message.lower():
            raise HTTPException(status_code=404, detail="Lesson content page not found")
        raise HTTPException(status_code=404, detail="Quiz question not found for lesson page")
    except Exception as e:
        logger.error(
            "Error patching quiz question",
            extra={
                "correlation_id": corr_id,
                "lesson_content_id": lesson_content_id,
                "question_id": question_id,
                "error": str(e),
            },
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@hikmah_router.delete(
    "/pages/{lesson_content_id}/quiz-questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_page_quiz_question(
    lesson_content_id: int,
    question_id: int,
    credentials: JWTAuthorizationCredentials = Depends(auth),
    db: Session = Depends(get_db),
):
    """Hard delete a quiz question and cascaded children."""
    corr_id = correlation_id_ctx.get()
    try:
        service = HikmahQuizService(db)
        service.delete_question(lesson_content_id, question_id)
    except LookupError as e:
        message = str(e)
        if "lesson content page" in message.lower():
            raise HTTPException(status_code=404, detail="Lesson content page not found")
        raise HTTPException(status_code=404, detail="Quiz question not found for lesson page")
    except Exception as e:
        logger.error(
            "Error deleting quiz question",
            extra={
                "correlation_id": corr_id,
                "lesson_content_id": lesson_content_id,
                "question_id": question_id,
                "error": str(e),
            },
        )
        raise HTTPException(status_code=500, detail="Internal server error")
