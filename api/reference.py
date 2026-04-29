import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from models.schemas import ReferenceRequest
from core import pipeline
from core.auth import auth
from core.context import correlation_id as correlation_id_ctx
from core.sentry import bind_sentry_scope
from models.JWTBearer import JWTAuthorizationCredentials

logger = logging.getLogger(__name__)

ref_router = APIRouter(
    prefix='/references',
    tags=['references']
)

# Takes query parameter called 'sect', which can equal to sunni, shia, or both.
# Also accepts 'limit' parameter to control number of references (1-50, default: 10)
# Example usage: http://localhost:8000/references?sect=both&limit=20
# Example json body input:: {"user_query": "What does Islam say about justice?"}
@ref_router.post("/")
async def references_pipeline(
    request: ReferenceRequest,
    credentials: JWTAuthorizationCredentials = Depends(auth),
    sect: str = Query("both", enum=["sunni", "shia", "both"]),
    limit: int = Query(10, ge=1, le=50, description="Number of references to fetch (1-50)"),
):
    user_query = request.user_query.strip()
    corr_id = correlation_id_ctx.get()
    bind_sentry_scope(corr_id, "/references")
    logger.info(
        "References request received",
        extra={"correlation_id": corr_id, "endpoint": "/references"},
    )

    if not user_query:
        raise HTTPException(status_code=400, detail="Please provide an appropriate query.")

    try:
        results = pipeline.references_pipeline(user_query, sect, limit)
        logger.info(
            "References request completed",
            extra={"correlation_id": corr_id, "endpoint": "/references"},
        )
        return {"response": results}

    except Exception as e:
        logger.error(
            "References pipeline error",
            exc_info=True,
            extra={"correlation_id": corr_id, "endpoint": "/references"},
        )
        raise HTTPException(status_code=500, detail="internal_error")
