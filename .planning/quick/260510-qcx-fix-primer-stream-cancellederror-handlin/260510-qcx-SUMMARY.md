---
phase: 260510-qcx
plan: 01
subsystem: streaming-observability
tags: [sentry, sse, cancellation, async, streaming, primer, agentic]
requires: []
provides:
  - QCX-01  # /primers/personalized/stream: CancelledError handler logs INFO + re-raises
  - QCX-02  # /chat/stream/agentic response_generator: same pattern
  - QCX-03  # Sentry before_send drops CancelledError events
affects:
  - api/primers.py
  - core/pipeline_langgraph.py
  - core/sentry.py
tech_stack_added: []
patterns:
  - "except asyncio.CancelledError: logger.info(...); raise — at SSE generator boundaries"
  - "Composed Sentry before_send hook (filter → scrub) preserves PII-scrubbing while adding pre-filters"
key_files_created: []
key_files_modified:
  - api/primers.py
  - core/pipeline_langgraph.py
  - core/sentry.py
decisions:
  - "Three atomic single-file commits, one per file — matches plan's <output> contract and isolates blame radius"
  - "Composed `_before_send` instead of replacing `_scrub_pii` — keeps existing PII-scrubbing behavior byte-identical and re-runnable in isolation"
  - "No new pytest suite — plan explicitly defers test coverage; inline AST/ordering/filter-smoke checks are the gates"
metrics:
  duration: "~6 minutes (single-pass, no deviations)"
  completed: "2026-05-10"
  tasks_completed: 3
  files_modified: 3
  lines_added: 63
  lines_removed: 1
---

# Phase 260510-qcx Plan 01: Fix primer stream CancelledError handling Summary

Three single-file commits stop benign SSE client disconnects from surfacing as Sentry incidents — per-handler INFO logging on `/primers/personalized/stream` and `/chat/stream/agentic`, plus a defense-in-depth Sentry `before_send` filter that drops any `asyncio.CancelledError` event from any other code path.

## Edits Made

| # | File | Lines added | Commit |
|---|------|-------------|--------|
| 1 | `api/primers.py` | +19 / -0 | `9740ecd` |
| 2 | `core/pipeline_langgraph.py` | +16 / -0 | `ecf374f` |
| 3 | `core/sentry.py` | +28 / -1 | `8f03c25` |

### Task 1 — `api/primers.py` (commit `9740ecd`)

- Added `import asyncio` at top (was missing; line 1 of import block).
- Inserted `except asyncio.CancelledError:` in `stream_personalized_primer.event_generator()`, immediately before `except HTTPException as http_exc:`.
- Handler logs at `logger.info(...)` with `extra={"correlation_id": corr_id, "user_id": request.user_id, "lesson_id": request.lesson_id, "endpoint": "/primers/personalized/stream"}` and re-raises with a bare `raise`.
- No SSE bytes emitted inside the handler.
- Existing `except HTTPException` and `except Exception` blocks untouched.

### Task 2 — `core/pipeline_langgraph.py` (commit `ecf374f`)

- `import asyncio` already present at line 8 — no new import added.
- Inserted `except asyncio.CancelledError:` in `chat_pipeline_streaming_agentic.response_generator()`, immediately before `except Exception as e:` (line ~494) and before the `finally:` block (line ~516).
- Handler logs at `logger.info(...)` with `extra={"correlation_id": correlation_id_ctx.get(), "session_id": session_id, "endpoint": "/chat/stream/agentic"}` and re-raises.
- No `user_id` invented — not in scope at that call site (confirmed by planner and re-verified by executor).
- Existing `except Exception` history-persistence path and `finally:` contextvar release are byte-identical.

### Task 3 — `core/sentry.py` (commit `8f03c25`)

- Added `import asyncio` at top (was missing).
- Added `_drop_cancelled_error(event, hint)` returning `None` when `hint["exc_info"][0] is asyncio.CancelledError`, else the event unchanged.
- Added `_before_send(event, hint)` composing `_drop_cancelled_error` → `_scrub_pii`.
- Switched `sentry_sdk.init(..., before_send=_before_send, ...)` (was `before_send=_scrub_pii`).
- `_scrub_pii` body preserved verbatim; `bind_sentry_scope` and `record_cache_metrics_breadcrumb` untouched.

## Import Status Confirmation

| File | `import asyncio` status before | Action |
|------|-------------------------------|--------|
| `api/primers.py` | NOT present | Added (alphabetical stdlib position, right above `import logging`) |
| `core/pipeline_langgraph.py` | Already present (line 8) | No change |
| `core/sentry.py` | NOT present | Added (alphabetical stdlib position, top of file) |

## Verification Output

All five overall-verification steps from the plan's `<verification>` section passed:

### 1. Static parse — all three files compile

```
$ python3 -c "import ast; [ast.parse(open(p).read()) for p in ['api/primers.py', 'core/pipeline_langgraph.py', 'core/sentry.py']]; print('OK')"
OK
```

### 2. Handler ordering — `CancelledError` precedes `Exception` in both stream files

```
api/primers.py                  OK (cancel=9264,  except=10567)
core/pipeline_langgraph.py      OK (cancel=24925, except=25699)
```

### 3. Sentry filter unit smoke

```
$ python3 -c "<asserts from Task 3 verify block>"
OK
```

Asserts covered:
- CancelledError-bearing `exc_info` → `_drop_cancelled_error` returns `None`
- ValueError-bearing `exc_info` → returns event unchanged
- Empty hint → returns event unchanged
- `_before_send` drops CancelledError BEFORE attempting to scrub
- `_before_send` on non-cancel event still scrubs `request.data` (PII preservation: `{'request': {}, 'x': 1}`)

### 4. Imports load

```
core.sentry            OK
core.pipeline_langgraph OK
api.primers            (env failure — missing DB_NAME, unrelated to this change)
```

Per the plan's step 4 note ("if it fails for env reasons, the static-parse check in step 1 is the authoritative gate"), the `api.primers` import failure is environmental (Pydantic Settings requires DB_NAME) and not caused by this change. Static parse + behavior of the new handler are gated by steps 1, 2, and 5.

### 5. No `yield` inside `CancelledError` handler — both files

```
$ python3 - <<'PY'  # regex scan from plan
... PY
OK
```

Confirms each new block contains only `logger.info(...)` + bare `raise`; no `yield` statements that would attempt to write to a closed socket.

## Deviations from Plan

None. Plan executed exactly as written.

The plan's `<context>` references `.planning/debug/primer-stream-cancelled.md` for root-cause background; that file is not present in the worktree. This did not block execution because the plan's `<action>` blocks are fully self-contained (concrete code snippets, line numbers, and variable scopes were validated by Read before each Edit). Tracked here for traceability only.

## Success Criteria Confirmation

- [x] A client closing the SSE connection mid-stream on `/primers/personalized/stream` produces an INFO log (with `correlation_id`, `user_id`, `lesson_id`, `endpoint`) and is suppressed before reaching Sentry. (Task 1 commit `9740ecd` + Task 3 safety net commit `8f03c25`.)
- [x] Same for `/chat/stream/agentic` — INFO log with `correlation_id`, `session_id`, `endpoint`. (Task 2 commit `ecf374f` + Task 3 safety net.)
- [x] `_drop_cancelled_error` drops any other path's CancelledError before it reaches the wire. (Verified in step 3 of overall verification.)
- [x] Real application errors (HTTPException, generic Exception) continue to be captured by Sentry exactly as before; `_scrub_pii` PII-stripping behavior preserved through the composed `_before_send`. (Verified in step 3.)
- [x] Three atomic commits, one per file. (`9740ecd`, `ecf374f`, `8f03c25`.)

## Self-Check: PASSED

**Files created/modified — exist on disk:**

| File | Status |
|------|--------|
| `api/primers.py` | FOUND |
| `core/pipeline_langgraph.py` | FOUND |
| `core/sentry.py` | FOUND |

**Commits — present in git log:**

| Hash | Subject | Status |
|------|---------|--------|
| `9740ecd` | `260510-qcx: catch CancelledError in primer stream event_generator` | FOUND |
| `ecf374f` | `260510-qcx: catch CancelledError in agentic stream response_generator` | FOUND |
| `8f03c25` | `260510-qcx: drop CancelledError events in Sentry before_send` | FOUND |
