---
phase: 260422-qau
plan: "01"
subsystem: feedback-api
tags: [feedback, csv, api, pydantic]
dependency_graph:
  requires: []
  provides: [POST /feedback endpoint, feedback.csv capture]
  affects: [main.py, models/schemas.py]
tech_stack:
  added: []
  patterns: [csv.DictWriter append, Literal validation, APIRouter prefix]
key_files:
  created:
    - api/feedback.py
  modified:
    - models/schemas.py
    - main.py
decisions:
  - Use Literal["like","dislike"] on rating field so Pydantic returns 422 for any other value — no custom validator needed
  - CSV path configurable via FEEDBACK_CSV_PATH env var, defaults to feedback.csv at CWD
  - _ensure_csv_header() called on every write (cheap Path.exists() check) rather than at startup, so the file is created lazily on first use
metrics:
  duration: "~2 minutes"
  completed: "2026-04-22"
  tasks_completed: 3
  files_changed: 3
---

# Phase 260422-qau Plan 01: Build Feedback API to Capture Chatbot Responses — Summary

**One-liner:** PII-free like/dislike feedback endpoint backed by a local CSV file using Pydantic Literal validation for rating enforcement.

## What Was Built

A `POST /feedback` endpoint that lets the frontend capture user ratings (like/dislike) on chatbot responses. Each submission appends one row to `feedback.csv` — no database required, no user identifiers stored.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Add FeedbackRequest and FeedbackResponse schemas | ac4a448 | models/schemas.py |
| 2 | Create api/feedback.py with POST /feedback route and CSV logic | 4c57b3d | api/feedback.py |
| 3 | Register feedback router in main.py | 14025b8 | main.py |

## Key Decisions

1. **Literal["like", "dislike"] for rating** — Pydantic rejects any other value with a 422 at the framework layer; no custom validator needed.
2. **Lazy CSV creation** — `_ensure_csv_header()` checks `Path.exists()` before each write. The file is only created when the first request arrives; no startup side effects.
3. **Env-configurable CSV path** — `FEEDBACK_CSV_PATH` env var lets deployments and tests redirect output without code changes.
4. **No auth requirement** — Feedback endpoint is public (no JWT required), consistent with the rest of the app's current opt-in auth pattern.

## Verification Results

- `POST /feedback` with `rating="like"` returns `{"ok": true, "message": "Feedback recorded."}`
- `POST /feedback` with `rating="bad"` raises Pydantic `ValidationError` (422 in HTTP context)
- CSV auto-created with correct header row on first request
- Data row contains: `datetime`, `rating`, `comment`, `user_query`, `chatbot_response` — no user identifiers
- `/feedback` appears in `app.routes`
- pytest tests -q: 100 passed, 0 regressions (1 pre-existing failure in `test_fiqh_integration.py::test_out_of_scope_routes_to_exit` — unrelated to this task, confirmed failing before changes)

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED
