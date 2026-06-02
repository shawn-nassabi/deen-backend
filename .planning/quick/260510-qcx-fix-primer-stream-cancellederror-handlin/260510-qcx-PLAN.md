---
phase: 260510-qcx
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - api/primers.py
  - core/pipeline_langgraph.py
  - core/sentry.py
autonomous: true
requirements:
  - QCX-01  # /primers/personalized/stream: catch CancelledError, log INFO, re-raise
  - QCX-02  # /chat/stream/agentic response_generator: same CancelledError pattern
  - QCX-03  # Sentry before_send: drop events whose exc_info[0] is asyncio.CancelledError
must_haves:
  truths:
    - "A benign SSE client disconnect on /primers/personalized/stream no longer produces a Sentry event."
    - "A benign SSE client disconnect on /chat/stream/agentic no longer produces a Sentry event."
    - "The CancelledError still propagates after being logged, so Starlette/anyio cancel scopes complete cleanly."
    - "Existing real-error handling (HTTPException, generic Exception) is unchanged in shape and behavior."
  artifacts:
    - path: "api/primers.py"
      provides: "CancelledError handler in event_generator() that logs INFO + re-raises (before except Exception)."
      contains: "except asyncio.CancelledError"
    - path: "core/pipeline_langgraph.py"
      provides: "CancelledError handler in response_generator() that logs INFO + re-raises (before except Exception)."
      contains: "except asyncio.CancelledError"
    - path: "core/sentry.py"
      provides: "before_send filter that drops events whose top-level exception is asyncio.CancelledError."
      contains: "asyncio.CancelledError"
  key_links:
    - from: "api/primers.py event_generator"
      to: "logger.info (correlation_id, user_id, lesson_id)"
      via: "except asyncio.CancelledError before except Exception"
      pattern: "except asyncio\\.CancelledError"
    - from: "core/pipeline_langgraph.py response_generator"
      to: "logger.info (correlation_id, session_id)"
      via: "except asyncio.CancelledError before except Exception"
      pattern: "except asyncio\\.CancelledError"
    - from: "core/sentry.py sentry_sdk.init"
      to: "_scrub_pii (existing before_send)"
      via: "composed before_send that first filters CancelledError, then delegates to _scrub_pii"
      pattern: "before_send"
---

<objective>
Stop Sentry from capturing benign SSE client-disconnect `asyncio.CancelledError`s on the two streaming endpoints, and add a defense-in-depth Sentry filter that drops any remaining `CancelledError` events from other code paths.

Purpose: A client closing an SSE connection mid-stream is a normal end-of-stream condition, not an application error. Today these surface as Sentry incidents (via uvicorn's `BaseException` catch + our `LoggingIntegration(event_level=ERROR)`) and create false-positive noise. Three surgical changes (one per file) eliminate that noise without altering real error handling.

Output: Three single-file commits — `api/primers.py`, `core/pipeline_langgraph.py`, `core/sentry.py` — each adding `CancelledError` awareness in the locally idiomatic style of the file.

Background (debug investigation, full root-cause analysis):
`.planning/debug/primer-stream-cancelled.md`
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md
@.planning/debug/primer-stream-cancelled.md

<interfaces>
<!-- Local scope and existing patterns the executor needs to match. -->
<!-- Extracted from the actual files; executor should match these conventions, not reinvent them. -->

# api/primers.py — event_generator() (inside POST /primers/personalized/stream handler, ~line 210)
# In-scope variables at the except-chain at lines 267 / 276:
#   corr_id      — from `correlation_id_ctx.get()` at line 207
#   request      — PersonalizedPrimerRequest (request.user_id, request.lesson_id, request.filter)
#   db, lesson, service — irrelevant for the cancellation handler
# Existing logger calls in this file use:
#   logger.info("...", extra={"correlation_id": corr_id, "user_id": request.user_id, "lesson_id": request.lesson_id, ...})
# `asyncio` is NOT yet imported at the top of this file — must be added.
# `import logging` and `logger = logging.getLogger(__name__)` are already present.

# core/pipeline_langgraph.py — response_generator() (inside chat_pipeline_streaming_agentic, ~line 141)
# In-scope variables at the except-chain at line 494:
#   session_id        — function parameter
#   user_query        — function parameter
#   final_state       — may be None
#   assistant_text, history_written — local accumulators
# Existing logger calls in this file use:
#   logger.error("...", exc_info=True, extra={"correlation_id": correlation_id_ctx.get(), "session_id": session_id})
# `import asyncio` is ALREADY present at line 8. `logger = logging.getLogger(__name__)` is present.
# There is NO `user_id` in scope at this call site — do not invent one.

# core/sentry.py — sentry_sdk.init(...) call (lines 30–46)
# Existing before_send hook:
#   def _scrub_pii(event: dict, hint: dict) -> dict:
#       if "request" in event:
#           event["request"].pop("data", None)
#       return event
# `sentry_sdk.init(..., before_send=_scrub_pii, ...)` is wired at line 44.
# `asyncio` is NOT imported. Must be added (top-of-file).
# Pattern requirement: keep _scrub_pii's PII behavior intact. The new filter
# must run FIRST (drop the event if CancelledError) and then chain to _scrub_pii
# for whatever survives.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: api/primers.py — catch CancelledError in event_generator()</name>
  <files>api/primers.py</files>
  <action>
Add an `asyncio.CancelledError` handler to `event_generator()` in `stream_personalized_primer`, placed BEFORE the existing `except HTTPException as http_exc:` block (around line 267) so it gets first dibs on cancellations.

Concrete steps:

1. Re-open `api/primers.py` and confirm the current shape of the except-chain at the end of `event_generator()` (currently `except HTTPException` then `except Exception`). Confirm line numbers — they are approximately 267 (HTTPException) and 276 (Exception); use the Read tool to verify before editing.

2. Verify `import asyncio` is present at the top of the file. As of this plan it is NOT — there is only `import logging` and `import json` plus the framework imports. Add `import asyncio` in alphabetical position among the stdlib imports (right after `import json`).

3. Insert the new handler IMMEDIATELY BEFORE `except HTTPException as http_exc:`:

```python
except asyncio.CancelledError:
    # Client closed the SSE connection mid-stream (frontend nav, tab close,
    # network drop). This is a normal end-of-stream condition, not an
    # application error. Logged at INFO so LoggingIntegration does not
    # capture it as a Sentry event. Re-raise so anyio's cancel scope can
    # unwind cleanly — swallowing CancelledError in an async generator
    # corrupts the surrounding cancel scope.
    logger.info(
        "Client disconnected during primer stream",
        extra={
            "correlation_id": corr_id,
            "user_id": request.user_id,
            "lesson_id": request.lesson_id,
            "endpoint": "/primers/personalized/stream",
        },
    )
    raise
```

4. DO NOT yield any further SSE bytes inside this handler — the socket is gone; another yield would surface a secondary error. DO NOT alter the existing `except HTTPException` or `except Exception` blocks in any way.

5. The handler MUST be `except asyncio.CancelledError:` (not `except (asyncio.CancelledError, ...):`) — keep it a single-exception clause. The `raise` MUST be a bare `raise` (re-raise the active exception), not `raise CancelledError()`.

Do not refactor anything else in this file. Do not reformat unrelated lines.
  </action>
  <verify>
    <automated>python -c "import ast, sys; src = open('api/primers.py').read(); tree = ast.parse(src); assert 'import asyncio' in src, 'missing asyncio import'; assert 'except asyncio.CancelledError' in src, 'missing CancelledError handler'; assert src.count('except asyncio.CancelledError') == 1, 'expected exactly one handler in this file'; print('OK')"</automated>
    <manual>Read api/primers.py and confirm: (a) `import asyncio` is at file top; (b) the new `except asyncio.CancelledError:` block sits immediately before `except HTTPException as http_exc:`; (c) the block logs at `logger.info(...)` with `extra={"correlation_id": corr_id, "user_id": request.user_id, "lesson_id": request.lesson_id, "endpoint": "/primers/personalized/stream"}`; (d) the block ends with a bare `raise`; (e) no SSE `yield` statements appear inside the new handler; (f) the existing `except HTTPException` and `except Exception` blocks are byte-identical to before.</manual>
  </verify>
  <done>
    - `api/primers.py` imports `asyncio`.
    - `event_generator()` catches `asyncio.CancelledError` BEFORE `except HTTPException`, logs at INFO with the correct `extra` keys, and re-raises with a bare `raise`.
    - File imports and parses cleanly (`python -c "import ast; ast.parse(open('api/primers.py').read())"`).
    - The CancelledError handler emits no SSE bytes.
    - Single-file commit, message prefix `DEE-` not required for quick tasks — use `fix(primer-stream): treat SSE client disconnect as benign in event_generator` or similar.
  </done>
</task>

<task type="auto">
  <name>Task 2: core/pipeline_langgraph.py — catch CancelledError in response_generator()</name>
  <files>core/pipeline_langgraph.py</files>
  <action>
Apply the same pattern to `response_generator()` inside `chat_pipeline_streaming_agentic` (function defined at line 114, generator defined at line 141). The current `except Exception as e:` at approximately line 494 is the target.

Concrete steps:

1. Re-open `core/pipeline_langgraph.py` and confirm the line numbers for the `except Exception as e:` at the bottom of `response_generator()` (currently ~494). Use Read/grep to verify before editing.

2. Confirm `import asyncio` is present at the top of the file — it IS, at line 8. No new import needed.

3. Insert the new handler IMMEDIATELY BEFORE the existing `except Exception as e:` at line ~494, and BEFORE the `finally:` block that follows the Exception handler:

```python
except asyncio.CancelledError:
    # SSE client disconnect: Starlette cancels the StreamingResponse task
    # group, which propagates CancelledError into whatever await we are
    # suspended on (LLM stream, tool call, retrieval). Treat as normal
    # end-of-stream. Log at INFO so LoggingIntegration does not capture
    # to Sentry, and re-raise so anyio's cancel scope completes cleanly.
    logger.info(
        "Client disconnected during agentic chat stream",
        extra={
            "correlation_id": correlation_id_ctx.get(),
            "session_id": session_id,
            "endpoint": "/chat/stream/agentic",
        },
    )
    raise
```

4. DO NOT add any `yield sse_event(...)` calls inside this handler — same reasoning as Task 1.

5. DO NOT touch the existing `except Exception as e:` block — its history-persistence-on-error behavior must remain identical. DO NOT touch the `finally:` block that releases the `fiqh_status_queue` contextvar.

6. Use ONLY the variables actually in scope: `correlation_id_ctx.get()` and `session_id`. Do NOT add `user_id` — there is no `user_id` in scope at this call site (verified). Do NOT use `final_state` inside the handler (it may be `None`).

7. The handler MUST be `except asyncio.CancelledError:` placed BEFORE `except Exception as e:`. Order matters because `CancelledError` is BaseException — `except Exception` does not catch it, but a clean explicit handler is required for the INFO-log behavior.

Do not refactor anything else. Do not reformat surrounding lines.
  </action>
  <verify>
    <automated>python -c "import ast, sys; src = open('core/pipeline_langgraph.py').read(); ast.parse(src); assert 'except asyncio.CancelledError' in src, 'missing CancelledError handler'; assert src.count('except asyncio.CancelledError') >= 1, 'no handler found'; idx_cancel = src.find('except asyncio.CancelledError'); idx_exc = src.find('except Exception as e:', idx_cancel); assert idx_cancel < idx_exc, 'CancelledError handler must precede except Exception'; print('OK')"</automated>
    <manual>Read `core/pipeline_langgraph.py` and confirm: (a) the new `except asyncio.CancelledError:` block sits inside `response_generator()` immediately before `except Exception as e:` near line ~494; (b) it logs at `logger.info(...)` with `extra={"correlation_id": correlation_id_ctx.get(), "session_id": session_id, "endpoint": "/chat/stream/agentic"}`; (c) it ends with bare `raise`; (d) no `yield sse_event(...)` calls appear inside the new handler; (e) the existing `except Exception as e:` body (the history-persistence + error-event + done-event sequence) is byte-identical; (f) the `finally:` block is byte-identical.</manual>
  </verify>
  <done>
    - `response_generator()` catches `asyncio.CancelledError` BEFORE `except Exception`, logs at INFO with the correct `extra` keys, and re-raises.
    - File parses cleanly.
    - The CancelledError handler emits no SSE bytes.
    - Existing error/finally paths unchanged.
    - Single-file commit, e.g. `fix(agentic-stream): treat SSE client disconnect as benign in response_generator`.
  </done>
</task>

<task type="auto">
  <name>Task 3: core/sentry.py — before_send filter drops CancelledError events</name>
  <files>core/sentry.py</files>
  <action>
Add a defense-in-depth `before_send` filter that drops any Sentry event whose top-level exception is `asyncio.CancelledError`. This catches future code paths that miss the per-handler fix in Tasks 1 and 2.

Concrete steps:

1. Re-open `core/sentry.py` and review the current shape. Today `before_send=_scrub_pii` is wired into `sentry_sdk.init(...)` at line 44. We need to preserve `_scrub_pii`'s PII-stripping behavior while running CancelledError filtering FIRST.

2. Add `import asyncio` at the top of the file. Current stdlib imports are `import logging` and `import os` — add `import asyncio` so the final order is `import asyncio` then `import logging` then `import os` (alphabetical).

3. Add a new module-level function `_drop_cancelled_error` ABOVE `_scrub_pii` (so the dependency reads top-down). Spec:

```python
def _drop_cancelled_error(event: dict, hint: dict) -> dict | None:
    """Drop Sentry events whose top-level exception is asyncio.CancelledError.

    A benign SSE client disconnect on a streaming endpoint surfaces as
    CancelledError in uvicorn's `BaseException` ASGI catch (h11_impl.py),
    which then becomes a Sentry event via LoggingIntegration (event_level=ERROR).
    Per-handler fixes in api/primers.py and core/pipeline_langgraph.py turn
    these into INFO logs, but this filter is the safety net for any code
    path that adds the same vulnerability later.

    Returning None tells the Sentry SDK to discard the event entirely.
    """
    exc_info = hint.get("exc_info") if hint else None
    if exc_info and exc_info[0] is asyncio.CancelledError:
        return None
    return event
```

4. Compose the two `before_send` functions into a single hook. Add a new function ABOVE the `sentry_sdk.init(...)` call:

```python
def _before_send(event: dict, hint: dict) -> dict | None:
    """Composed before_send: filter CancelledError first, then scrub PII."""
    event = _drop_cancelled_error(event, hint)
    if event is None:
        return None
    return _scrub_pii(event, hint)
```

5. Change `before_send=_scrub_pii` (line 44) to `before_send=_before_send`. Do not change anything else inside `sentry_sdk.init(...)` — keep `dsn`, `send_default_pii`, `environment`, `integrations`, `enable_logs` byte-identical.

6. Keep `_scrub_pii` unchanged in body — the existing PII scrubbing logic stays intact and is now invoked through `_before_send`.

7. Do NOT remove or rename `_scrub_pii`. Existing tests / callers may reference it.

8. Use `dict | None` return-type syntax (consistent with `session_id: str | None` already used in `bind_sentry_scope` at line 52 — confirms PEP 604 syntax is in style for this file).

Do not refactor `bind_sentry_scope` or `record_cache_metrics_breadcrumb`. Do not touch the `SENTRY_ENABLED` gate.
  </action>
  <verify>
    <automated>python -c "import ast, sys; src = open('core/sentry.py').read(); tree = ast.parse(src); assert 'import asyncio' in src, 'missing asyncio import'; assert 'def _drop_cancelled_error' in src, 'missing _drop_cancelled_error'; assert 'def _before_send' in src, 'missing _before_send composer'; assert 'def _scrub_pii' in src, '_scrub_pii must remain'; assert 'before_send=_before_send' in src, 'init must use composed hook'; assert 'asyncio.CancelledError' in src, 'filter must reference CancelledError'; print('OK')"</automated>
    <automated>python -c "import sys; sys.path.insert(0, '.'); import asyncio; from core.sentry import _drop_cancelled_error, _before_send, _scrub_pii; assert _drop_cancelled_error({'x':1}, {'exc_info': (asyncio.CancelledError, asyncio.CancelledError(), None)}) is None, 'CancelledError event should be dropped'; assert _drop_cancelled_error({'x':1}, {'exc_info': (ValueError, ValueError(), None)}) == {'x':1}, 'non-CancelledError should pass through'; assert _drop_cancelled_error({'x':1}, {}) == {'x':1}, 'no exc_info should pass through'; assert _before_send({'request': {'data': 'secret'}, 'x':1}, {'exc_info': (asyncio.CancelledError, asyncio.CancelledError(), None)}) is None, 'CancelledError must be dropped before scrubbing'; out = _before_send({'request': {'data': 'secret'}, 'x':1}, {}); assert out == {'request': {}, 'x':1}, 'non-cancel events must be scrubbed: got ' + repr(out); print('OK')"</automated>
    <manual>Read `core/sentry.py` and confirm: (a) `import asyncio` is present at file top; (b) `_drop_cancelled_error` is defined and returns `None` when `hint["exc_info"][0] is asyncio.CancelledError`; (c) `_before_send` chains `_drop_cancelled_error` then `_scrub_pii`; (d) `sentry_sdk.init(...)` uses `before_send=_before_send`; (e) `_scrub_pii` body is unchanged; (f) `bind_sentry_scope` and `record_cache_metrics_breadcrumb` are byte-identical.</manual>
  </verify>
  <done>
    - `core/sentry.py` imports `asyncio`.
    - `_drop_cancelled_error(event, hint)` is defined and returns `None` for `asyncio.CancelledError` events.
    - `_before_send(event, hint)` composes `_drop_cancelled_error` then `_scrub_pii`.
    - `sentry_sdk.init(...)` uses `before_send=_before_send`.
    - Both inline verify scripts pass.
    - Single-file commit, e.g. `fix(sentry): drop CancelledError events in before_send (defense-in-depth)`.
  </done>
</task>

</tasks>

<verification>
After all three tasks land:

1. **Static parse** — all three files parse cleanly:
   ```bash
   python -c "import ast; [ast.parse(open(p).read()) for p in ['api/primers.py', 'core/pipeline_langgraph.py', 'core/sentry.py']]; print('OK')"
   ```

2. **Handler ordering** — `except asyncio.CancelledError` precedes `except Exception` in both stream files:
   ```bash
   for f in api/primers.py core/pipeline_langgraph.py; do
     python -c "src=open('$f').read(); ic=src.find('except asyncio.CancelledError'); ie=src.find('except Exception', ic); print('$f', 'OK' if 0 <= ic < ie else 'FAIL'); "
   done
   ```

3. **Sentry filter unit smoke** — re-run the inline assertions from Task 3's automated verify command; expected `OK`.

4. **Imports load** — verify the modules import without error in the project's Python interpreter:
   ```bash
   python -c "import core.sentry, core.pipeline_langgraph; from api import primers; print('OK')"
   ```
   (This depends on existing env vars / venv being active — if it fails for env reasons, the static-parse check in step 1 is the authoritative gate.)

5. **No yield inside CancelledError handler** — manually confirm via grep that the new handlers in `api/primers.py` and `core/pipeline_langgraph.py` contain only `logger.info(...)` + `raise`, no `yield`:
   ```bash
   python - <<'PY'
   import re
   for path in ['api/primers.py', 'core/pipeline_langgraph.py']:
       src = open(path).read()
       m = re.search(r'except asyncio\.CancelledError:(.*?)(?=\n    except |\n        except )', src, re.DOTALL)
       assert m, f'no CancelledError block found in {path}'
       block = m.group(1)
       assert 'yield' not in block, f'YIELD inside CancelledError handler in {path}'
       assert 'logger.info' in block, f'expected logger.info in {path}'
       assert re.search(r'\n\s+raise\s*(\n|$)', block), f'expected bare `raise` in {path}'
   print('OK')
   PY
   ```

No new pytest tests are added (per <constraints>). Real verification of the Sentry behavior requires a live disconnect repro, which is out of scope for this quick fix.
</verification>

<success_criteria>
- A client closing the SSE connection mid-stream on `/primers/personalized/stream` produces an INFO log (with `correlation_id`, `user_id`, `lesson_id`, `endpoint`) and NO Sentry event.
- A client closing the SSE connection mid-stream on `/chat/stream/agentic` produces an INFO log (with `correlation_id`, `session_id`, `endpoint`) and NO Sentry event.
- Any other code path that raises `asyncio.CancelledError` and reaches Sentry is dropped by the `_drop_cancelled_error` filter before reaching the wire.
- Real application errors (HTTPException, other Exceptions) continue to be captured by Sentry exactly as before — the PII-scrubbing behavior of `_scrub_pii` is preserved through the composed `_before_send`.
- Three atomic commits, one per file.
</success_criteria>

<output>
After completion, create `.planning/quick/260510-qcx-fix-primer-stream-cancellederror-handlin/260510-qcx-01-SUMMARY.md` summarizing:
- The three edits made (file, lines added, commit hash).
- Confirmation that `import asyncio` was added where missing (`api/primers.py`, `core/sentry.py`) and was already present in `core/pipeline_langgraph.py`.
- Output of the static-parse and handler-ordering checks from the `<verification>` section.
- Any deviations from the plan (expected: none).
</output>
