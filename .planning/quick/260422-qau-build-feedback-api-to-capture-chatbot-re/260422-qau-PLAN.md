---
phase: 260422-qau
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - api/feedback.py
  - models/schemas.py
  - main.py
autonomous: true
requirements: [QAU-01]

must_haves:
  truths:
    - "POST /feedback returns 200 with {ok: true} when given valid rating, user_query, and chatbot_response"
    - "Each successful submission appends exactly one row to feedback.csv with datetime, rating, comment, user_query, chatbot_response columns"
    - "feedback.csv is created with a header row if it does not yet exist"
    - "Missing or invalid rating value returns 422 (Pydantic validation error)"
    - "No user IDs, session IDs, or IP addresses appear anywhere in the CSV"
  artifacts:
    - path: "api/feedback.py"
      provides: "POST /feedback route handler and CSV append logic"
      exports: ["router"]
    - path: "models/schemas.py"
      provides: "FeedbackRequest and FeedbackResponse Pydantic models"
      contains: "class FeedbackRequest"
    - path: "main.py"
      provides: "Router registration"
      contains: "feedback.router"
  key_links:
    - from: "main.py"
      to: "api/feedback.py"
      via: "app.include_router(feedback.router)"
      pattern: "include_router.*feedback"
    - from: "api/feedback.py"
      to: "feedback.csv"
      via: "csv.writer append in POST handler"
      pattern: "csv\\.writer|DictWriter"
---

<objective>
Add a POST /feedback endpoint that records like/dislike ratings on chatbot responses to a local CSV file.

Purpose: Capture qualitative signal on chatbot quality without any PII and without requiring a database.
Output: api/feedback.py (route + CSV logic), two Pydantic models in models/schemas.py, router wired in main.py, feedback.csv created on first use.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@main.py
@models/schemas.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add FeedbackRequest and FeedbackResponse schemas to models/schemas.py</name>
  <files>models/schemas.py</files>
  <action>
    Append two Pydantic models to the bottom of models/schemas.py:

    ```python
    from typing import Literal  # add to existing imports if not already present

    class FeedbackRequest(BaseModel):
        rating: Literal["like", "dislike"]
        comment: Optional[str] = None
        user_query: str
        chatbot_response: str

    class FeedbackResponse(BaseModel):
        ok: bool
        message: str
    ```

    - `rating` uses `Literal["like", "dislike"]` so Pydantic rejects any other value with 422.
    - `comment` is optional (None if omitted).
    - `user_query` and `chatbot_response` are required strings.
    - `Literal` is already available from `typing` in Python 3.8+; check the existing import line and add it if absent.
    - Do NOT add user_id, session_id, or any identifier field.
  </action>
  <verify>
    python3 -c "from models.schemas import FeedbackRequest, FeedbackResponse; r = FeedbackRequest(rating='like', user_query='q', chatbot_response='a'); print(r)"
  </verify>
  <done>FeedbackRequest and FeedbackResponse import cleanly; FeedbackRequest with rating='bad' raises ValidationError.</done>
</task>

<task type="auto">
  <name>Task 2: Create api/feedback.py with POST /feedback route and CSV logic</name>
  <files>api/feedback.py</files>
  <action>
    Create api/feedback.py from scratch:

    ```python
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
    ```

    Key decisions:
    - `prefix="/feedback"` + `@router.post("")` → endpoint is `POST /feedback`.
    - `datetime.now(timezone.utc).isoformat()` produces ISO 8601 with UTC offset.
    - Opens file in append mode (`"a"`) so existing rows are never overwritten.
    - `_ensure_csv_header()` is called before every write; the `Path.exists()` check is cheap and race-condition-safe for single-process use.
    - `FEEDBACK_CSV_PATH` is configurable via `FEEDBACK_CSV_PATH` env var; defaults to `feedback.csv` at the CWD (project root when running `uvicorn main:app`).
    - No user ID, session ID, or request IP is captured anywhere in this file.
  </action>
  <verify>
    python3 -c "
import asyncio, os
os.environ.setdefault('FEEDBACK_CSV_PATH', '/tmp/test_feedback.csv')
from api.feedback import submit_feedback
from models.schemas import FeedbackRequest
req = FeedbackRequest(rating='like', user_query='What is wudu?', chatbot_response='Wudu is ritual purification.')
result = asyncio.run(submit_feedback(req))
print(result)
import csv
with open('/tmp/test_feedback.csv') as f: print(f.read())
"
  </verify>
  <done>Script prints FeedbackResponse(ok=True, message='Feedback recorded.') and the CSV file contains a header row followed by one data row with datetime, rating, comment, user_query, chatbot_response. No user identifiers present.</done>
</task>

<task type="auto">
  <name>Task 3: Register feedback router in main.py</name>
  <files>main.py</files>
  <action>
    In main.py, add two changes:

    1. Add the import alongside the other api imports near the top of the file:
       ```python
       from api import feedback
       ```

    2. Register the router after the existing `app.include_router(primers.primers_router)` line:
       ```python
       app.include_router(feedback.router)             # /feedback
       ```

    Follow the exact style of the surrounding router registrations (trailing comment with path).
    Do not touch any other lines.
  </action>
  <verify>
    python3 -c "
import os; os.environ['FEEDBACK_CSV_PATH'] = '/tmp/fb_main_test.csv'
from main import app
routes = [r.path for r in app.routes]
assert '/feedback' in routes, f'Route not found. Routes: {routes}'
print('OK — /feedback registered')
"
  </verify>
  <done>`/feedback` appears in app.routes; the server starts without import errors.</done>
</task>

</tasks>

<verification>
After all tasks complete, run a full end-to-end smoke test:

```bash
# Start server in background
uvicorn main:app --port 8099 &
sleep 2

# Submit a like
curl -s -X POST http://127.0.0.1:8099/feedback \
  -H "Content-Type: application/json" \
  -d '{"rating":"like","comment":"Very helpful","user_query":"What is zakat?","chatbot_response":"Zakat is one of the five pillars..."}' | python3 -m json.tool

# Submit a dislike with no comment
curl -s -X POST http://127.0.0.1:8099/feedback \
  -H "Content-Type: application/json" \
  -d '{"rating":"dislike","user_query":"Is music haram?","chatbot_response":"..."}' | python3 -m json.tool

# Confirm bad rating returns 422
curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:8099/feedback \
  -H "Content-Type: application/json" \
  -d '{"rating":"meh","user_query":"q","chatbot_response":"a"}'

# Inspect CSV — should have 3 rows (1 header + 2 data)
cat feedback.csv

kill %1
```

Expected: two 200 responses with `{"ok": true}`, one 422, CSV has header + 2 data rows with no user identifiers.
</verification>

<success_criteria>
- POST /feedback with valid payload returns HTTP 200 and `{"ok": true, "message": "Feedback recorded."}`
- POST /feedback with rating not in ["like", "dislike"] returns HTTP 422
- feedback.csv is auto-created on first request with correct header row
- Every row in feedback.csv contains: datetime (ISO 8601), rating, comment, user_query, chatbot_response — and nothing else
- pytest tests -q passes (no regressions)
</success_criteria>

<output>
After completion, create `.planning/quick/260422-qau-build-feedback-api-to-capture-chatbot-re/260422-qau-SUMMARY.md`
</output>
