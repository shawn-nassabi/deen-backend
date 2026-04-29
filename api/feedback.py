import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from models.schemas import FeedbackRequest, FeedbackResponse

logger = logging.getLogger("api.feedback")

router = APIRouter(prefix="/feedback", tags=["feedback"])

# Configurable via env var; defaults to project root
FEEDBACK_CSV_PATH = Path(os.getenv("FEEDBACK_CSV_PATH", "feedback.csv"))

_CSV_FIELDNAMES = ["datetime", "rating", "comment", "user_query", "chatbot_response"]


def _ensure_csv_header() -> None:
    """Create feedback.csv with header row if it does not exist."""
    if not FEEDBACK_CSV_PATH.exists():
        with FEEDBACK_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES)
            writer.writeheader()


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest) -> FeedbackResponse:
    """
    Record a like/dislike rating on a chatbot response.

    No PII is stored — no user IDs, session IDs, or IP addresses.
    """
    try:
        _ensure_csv_header()
        row = {
            "datetime": datetime.now(timezone.utc).isoformat(),
            "rating": request.rating,
            "comment": request.comment or "",
            "user_query": request.user_query,
            "chatbot_response": request.chatbot_response,
        }
        with FEEDBACK_CSV_PATH.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES)
            writer.writerow(row)
        logger.info("Feedback recorded: rating=%s", request.rating)
        return FeedbackResponse(ok=True, message="Feedback recorded.")
    except Exception as e:
        logger.error("Failed to write feedback: %s", e)
        raise HTTPException(status_code=500, detail="Failed to record feedback.")
