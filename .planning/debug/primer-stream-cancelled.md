---
slug: primer-stream-cancelled
status: root_cause_found
trigger: Sentry-reported CancelledError on POST /primers/personalized/stream during the streaming Anthropic request
created: 2026-05-10
updated: 2026-05-10
---

# Debug Session: primer-stream-cancelled

## Symptoms

**Expected behavior:** `/primers/personalized/stream` completes the streaming personalized-primer generation and returns SSE chunks until done.

**Actual behavior:** Request fails mid-flight with `asyncio.CancelledError` raised from inside the Anthropic SDK streaming HTTP read. Sentry captures the exception. Error message: `Cancelled by cancel scope 73b84aa6f910`.

**Error stack trace (Sentry):**
```
File "langchain_core/language_models/chat_models.py", line 615, in astream
  async for chunk in self._astream(
File "langchain_anthropic/chat_models.py", line 1680, in _astream
  stream = await self._acreate(payload)
File "langchain_anthropic/chat_models.py", line 1628, in _acreate
  return await self._async_client.messages.create(**payload)
File "anthropic/resources/messages/messages.py", line 2443, in create
  return await self._post(...)
File "anthropic/_base_client.py", line 1996, in post
  return await self.request(cast_to, opts, stream=stream, stream_cls=stream_cls)
File "anthropic/_base_client.py", line 1716, in request
  response = await self._client.send(...)
File "httpx/_client.py", ... _send_single_request
File "httpx/_transports/default.py", ... handle_async_request
File "httpcore/_async/connection_pool.py", line 256, in handle_async_request
  raise exc from None
File "httpcore/_async/http11.py", line 217, in _receive_event
  data = await self._network_stream.read(...)
File "anyio/streams/tls.py", line 204, in receive
  data = await self._call_sslobject_method(self._ssl_object.read, max_bytes)
File "anyio/_backends/_asyncio.py", line 1246, in receive
  await self._protocol.read_event.wait()
File "asyncio/locks.py", line 213, in wait
  await fut
CancelledError: Cancelled by cancel scope 73b84aa6f910
```

**Endpoint:** `POST /primers/personalized/stream`
**Correlation ID:** `90fcaa79-6272-4968-b366-560c35102e1f`
**User:** `2ea57e39-dd19-44ed-9496-bcfd42d39d95`
**Lesson:** `5`

**Breadcrumb timeline (UTC):**
- 23:47:14.676 — Starting streaming primer generation (`/primers/personalized/stream`, force_refresh=false)
- 23:47:14.718 → 23:47:14.840 — Sequence of Postgres SELECT queries (cached primer lookup, user memory profile, note_embeddings count, lesson_chunk_embeddings count + body, pgvector cosine similarity search, lesson_content fetch)
- 23:47:14.838 — `[EMBEDDINGS] 0.059s` (services.primer_service)
- 23:47:14.838 — `[DB] 0.091s` (services.primer_service)
- 23:47:14.850 — First `POST https://api.anthropic.com/v1/messages`
- 23:47:14.850 — `Retrying request to /v1/messages in 0.453226 seconds` (anthropic._base_client) — first attempt failed almost instantly
- 23:47:16.018 — Second `POST https://api.anthropic.com/v1/messages` (retry, ~1.17s after first)
- 23:47:16.046 — `CancelledError: Cancelled by cancel scope 73b84aa6f910` (~28 ms after retry POST initiated)

**Timeline:** Single occurrence reported; not yet known whether transient or recurring. Was working before unless similar incidents existed earlier.

**Reproduction:** Not yet attempted. Probably reproducible by initiating a streaming primer fetch from a client and then aborting/disconnecting before the LLM stream completes.

## Initial Observations

- The cancellation surfaces *inside* the Anthropic SDK's HTTP receive path — the failure point is `httpcore._async.http11._receive_event` → `anyio._asyncio.SocketStream.receive` → `asyncio.locks.wait`. The future being awaited is cancelled externally; httpx/anthropic SDK don't raise `CancelledError` of their own accord here.
- The first POST at 23:47:14.850 was retried by the Anthropic SDK after 0.453s. That retry itself was cancelled 28 ms after it started — much faster than any normal Anthropic stream would complete, strongly indicating the cancellation source is *upstream of the SDK*, not Anthropic returning early.
- `Cancelled by cancel scope <id>` is the diagnostic format anyio/Sentry produces when an outer cancel scope (likely a Starlette `BackgroundTask`, FastAPI request lifecycle, or `asyncio.wait_for` timeout) cancels the inflight task.
- Endpoint is the SSE streaming primer — `services/primer_service.py` and `api/primers.py` are the obvious source files. Sentry currently treats client-disconnect-mid-stream cancellations as exceptions because the `CancelledError` propagates uncaught into Sentry's middleware.

## Suspected Causes (pre-investigation)

1. **Client disconnect mid-stream** — frontend (or curl/browser) closed the SSE connection before the upstream Anthropic stream produced a token. Starlette cancels the request task, which propagates the `CancelledError` into the awaited HTTP read. This is the canonical pattern in async FastAPI SSE.
2. **Request-side timeout** — an `asyncio.wait_for(...)` or a Caddy/uvicorn idle timeout fired before the second Anthropic retry returned.
3. **Caller cancellation** — primer service wrapped in a TaskGroup or `asyncio.shield`-less section that gets cancelled when an outer guard hits.

`(1)` is the prior probability winner given that the cancellation hit only 28 ms into the retry — far too short for the Anthropic server itself to be the source, but matching well with a TCP RST/FIN from a client close.

## Current Focus

- **hypothesis:** SSE client disconnect during the streaming Anthropic call cancels the request task; the `CancelledError` bubbles up through httpx into Sentry because the primer streaming code path doesn't shield, swallow, or distinguish cancellations from real errors.
- **test:** Reproduce by initiating a `POST /primers/personalized/stream`, then closing the client connection mid-stream. Verify Sentry captures the same `Cancelled by cancel scope ...` trace. Also: inspect `api/primers.py` + `services/primer_service.py` for the SSE generator's cancellation handling.
- **expecting:** A clean exit path on client disconnect — either silent (debug-log only) or a sentinel breadcrumb — rather than a Sentry-captured exception.
- **next_action:** Read `api/primers.py` (streaming route) and `services/primer_service.py` (LLM invocation) to confirm there's no client-disconnect handling around the `chain.astream()` / Anthropic call.
- **reasoning_checkpoint:** Confirm via `/primers/personalized/stream` route handler that the streaming generator does not catch `CancelledError` separately from generic exceptions before reporting to Sentry.

## Evidence

- timestamp: 2026-05-10 — **Python 3.11 hierarchy verified**: `asyncio.CancelledError` directly subclasses `BaseException` (MRO: `[CancelledError, BaseException, object]`). It is NOT a subclass of `Exception`. So `except Exception` blocks do NOT catch it (verified by repro in `/tmp/test_cancel.py`).
- timestamp: 2026-05-10 — **No `CancelledError` handling anywhere in app code**: `grep -rn "CancelledError" api/ services/ core/` returns zero matches. Neither the primer stream nor `/chat/stream/agentic` distinguishes cancellation from real errors.
- timestamp: 2026-05-10 — **api/primers.py:267–290** — `event_generator()` has only `except HTTPException` and `except Exception as e:` handlers. Both perform `logger.error("...", exc_info=True, ...)` and then `yield` SSE error events. Neither catches `CancelledError`, so on client disconnect the generator simply raises out of the `async for chunk in primers_model.astream(messages)` call inside the chain, and the `CancelledError` propagates upward unhandled by the application.
- timestamp: 2026-05-10 — **services/primer_service.py:108–116** — `stream_personalized_primer` has the same broad `except Exception as e:` pattern (no `CancelledError` handling). `_stream_bullets_with_llm` at line 868 contains the `async for chunk in primers_model.astream(messages):` loop where the cancellation is raised. Same shape as the chat pipeline.
- timestamp: 2026-05-10 — **core/pipeline_langgraph.py:494** — the analogous `/chat/stream/agentic` generator has the exact same `except Exception as e:` pattern with `logger.error("Pipeline error", exc_info=True, ...)`. So that endpoint suffers from the identical bug; it just has not surfaced in Sentry as visibly, likely because chat streams are user-driven (the user is watching) while primer streams are pre-fetched (the user often navigates away mid-stream).
- timestamp: 2026-05-10 — **Starlette source — venv/.../starlette/responses.py:261–268** — `StreamingResponse.__call__` (on the `spec_version < (2,4)` path) wires up an `anyio.create_task_group()` with two concurrent tasks: `stream_response(send)` and `listen_for_disconnect(receive)`. When `listen_for_disconnect` returns (because the client sent `http.disconnect`), it calls `task_group.cancel_scope.cancel()` (line 265). That is **the literal `cancel scope <id>` cited in the Sentry trace** — confirming the cancellation source is upstream of the application, originating in Starlette's disconnect-listener mechanism.
- timestamp: 2026-05-10 — **uvicorn source — venv/.../uvicorn/protocols/http/h11_impl.py:406–408** — `run_asgi` wraps the entire ASGI call in `except BaseException as exc: self.logger.error("Exception in ASGI application\n", exc_info=exc)`. This is the path that surfaces the `CancelledError` to Sentry: since `CancelledError` is `BaseException`, it bypasses Starlette's `except OSError` (responses.py:258) and our `except Exception` blocks, lands here, and `logger.error(..., exc_info=...)` then triggers `LoggingIntegration` (configured in `core/sentry.py` with `event_level=logging.ERROR`) which calls `sentry_sdk.capture_event(...)` with the original exception's traceback. That traceback shows the frame where the future was awaited (the Anthropic SDK read), which is exactly what we see in the Sentry incident.
- timestamp: 2026-05-10 — **core/sentry.py:38–42** — `LoggingIntegration(level=logging.INFO, event_level=logging.ERROR, sentry_logs_level=logging.INFO)`. The `event_level=logging.ERROR` is precisely what turns uvicorn's `logger.error` into a Sentry event. (The Sentry ASGI integration's own `except Exception` at `venv/.../sentry_sdk/integrations/asgi.py:266` does NOT catch `CancelledError` either — so the LoggingIntegration → uvicorn `logger.error` path is the *sole* mechanism by which this incident surfaced.)
- timestamp: 2026-05-10 — **Why a 28 ms retry cancellation is consistent with client-disconnect, not Anthropic 5xx**: 28 ms after the retry POST is too fast for Anthropic to have produced a response and far too fast for an upstream HTTP error; it is exactly the latency of a TCP FIN/RST being delivered to the local socket. The 453 ms gap before the first retry is a routine Anthropic-SDK retry on a transient connection issue and is a red herring — the cancellation source is the client closing the SSE connection.

## Eliminated

- **Anthropic-side 5xx / timeout** — eliminated. The retry was cancelled 28 ms after the second POST started, which is inconsistent with any server-side return. The cancellation came from the client/Starlette task group, not from the upstream HTTP service.
- **`asyncio.wait_for` outer timeout** — eliminated. No `wait_for(...)` wraps the primer streaming path; the only timeouts in play are uvicorn/Caddy idle timeouts which would not trigger within 1.4 s of request start.
- **`primers_model` mis-configuration** — eliminated. The same `primers_model.astream(...)` was successfully invoked (`POST https://api.anthropic.com/v1/messages` returned without error at 23:47:14.850); the cancellation is unrelated to model setup.
- **Generic 500 from `catch_exceptions_mw` (main.py:122)** — eliminated. That middleware also only catches `Exception`, not `BaseException`/`CancelledError`. It is bypassed entirely by this cancellation.
- **Sentry's own ASGI integration catching the exception** — eliminated. `sentry_sdk/integrations/asgi.py:266` is `except Exception as exc:` (not `BaseException`). It does not catch `CancelledError`. The only mechanism that surfaces this to Sentry is the `LoggingIntegration` event-handler triggered by uvicorn's `logger.error` at `h11_impl.py:408`.

## Resolution

### Root cause

When the SSE client disconnects mid-stream (frontend navigation, tab close, network drop) on `/primers/personalized/stream`, Starlette's `StreamingResponse.__call__` cancels its internal `anyio` cancel scope (`responses.py:265`). That cancellation propagates *into* the body iterator's currently-suspended `await` — which is the `httpcore` SSL receive future inside `primers_model.astream(messages)` (langchain → anthropic → httpx → httpcore → anyio). Python raises `asyncio.CancelledError` at that `await fut` line.

`CancelledError` is a `BaseException`, not an `Exception`, in Python 3.11. The application's exception handlers in `event_generator()` (`api/primers.py:267`/`:276`), `stream_personalized_primer()` (`services/primer_service.py:108`), and the global `catch_exceptions_mw` (`main.py:126`) all use `except Exception` and so do not catch it. The cancellation therefore propagates out of the ASGI app into uvicorn's protocol layer, where `h11_impl.py:406` catches **`BaseException`** and calls `logger.error("Exception in ASGI application", exc_info=exc)`. Our `LoggingIntegration` (`core/sentry.py:38`, `event_level=logging.ERROR`) converts that ERROR log record into a Sentry event with the original traceback — which is the report we are seeing.

So this is **not a bug in the LLM call, the retry logic, or the Anthropic SDK**. It is a missing-handler problem in the SSE streaming generator: a benign client disconnect (which should be a 0-noise occurrence in any production SSE service) is being reported as an application exception because we never special-case `CancelledError`. The same flaw exists on `/chat/stream/agentic` (`core/pipeline_langgraph.py:494`); it has just not surfaced as loudly because chat streams are interactive and rarely abandoned mid-flight, whereas primer streams are background prefetches.

### Suggested fix (do not apply yet — for user review)

Two minimal, surgical changes — both are diagnose-only proposals; nothing is being changed in the repo as part of this report.

**Change 1 — `api/primers.py` (`event_generator()` in `stream_personalized_primer`, ~line 210–290): add a `CancelledError` handler before `except Exception`.**

Add at the appropriate place in the handler chain (after the inner `try:`, before `except HTTPException`):

```python
except asyncio.CancelledError:
    # Client closed the SSE connection (frontend nav / tab close / network drop).
    # This is a normal, expected end-of-stream condition, not an application error.
    # Log at INFO (NOT error) so LoggingIntegration does not capture it to Sentry.
    logger.info(
        "Streaming primer client disconnect",
        extra={
            "correlation_id": corr_id,
            "user_id": request.user_id,
            "lesson_id": request.lesson_id,
            "endpoint": "/primers/personalized/stream",
        },
    )
    raise  # Re-raise so Starlette / anyio cancel scope can complete cleanly.
```

Key requirements:
1. **Catch `CancelledError` separately** — placing it `except (asyncio.CancelledError, ...)` *before* `except Exception` is mandatory because `Exception` does not catch it on 3.11 (won't actually short-circuit on its own, but separating the two intents is what makes the fix work).
2. **`raise` (do not swallow)** — re-raising is required so that anyio's cancel scope completes its bookkeeping; suppressing `CancelledError` in an async generator can cause "cancel scope corrupted" follow-on errors.
3. **Log at INFO, not ERROR** — this is what *prevents* Sentry capture. The `LoggingIntegration` `event_level` is `ERROR`, so INFO and DEBUG records do not become Sentry events.
4. **Do NOT yield SSE error events** — the client is already gone; writing further bytes will fail with another error or warning. Just re-raise.

**Change 2 — `core/pipeline_langgraph.py` (`response_generator()` ~line 494): same pattern.**

Apply the equivalent `except asyncio.CancelledError:` handler before the existing `except Exception as e:` in `response_generator()`. The chat stream has the same vulnerability; it has just not been reported yet. Use the same shape: INFO-level log, no SSE yield, `raise` to let the cancel scope unwind.

**Optional defense-in-depth — uvicorn `logger.error` filter.**

We could also reduce the noise at the *uvicorn protocol* layer by either:
- Adjusting `core/sentry.py` to install a `before_send` predicate that drops events whose `logger` is `uvicorn.error` and whose exception is `CancelledError`, OR
- Adding a `logging.Filter` to the `uvicorn.error` logger that suppresses records whose `exc_info[0] is asyncio.CancelledError`.

Either approach catches any future code path that introduces the same flaw. The two surgical handlers (Changes 1 & 2) are still the right primary fix because they keep cancellation a benign code path in our own code rather than relying on global filters.

### Specialist hint

`python` — this is an asyncio + FastAPI + Anthropic SDK issue. Idiomatic Python recommendation: catch `BaseException` (or specifically `asyncio.CancelledError`) separately from `Exception` in any async generator that wraps an outer-cancelable resource (HTTP stream, DB cursor, SSE write loop). The pattern is the same one PEP 654/3.11 emphasized when `CancelledError` was promoted out of the `Exception` hierarchy.

### Confidence

High. Every step of the chain has been verified against source:
- `CancelledError` MRO verified via live Python 3.11 import.
- Starlette `StreamingResponse` task-group cancel pattern read directly from installed package source (`venv/.../starlette/responses.py:261–268`).
- uvicorn `BaseException` → `logger.error` capture verified at `venv/.../uvicorn/protocols/http/h11_impl.py:406–408`.
- Sentry `LoggingIntegration` `event_level=logging.ERROR` confirmed in `core/sentry.py:38–42`.
- Application exception handlers (`api/primers.py:267,276`, `services/primer_service.py:108`, `core/pipeline_langgraph.py:494`, `main.py:126`) all use `except Exception` and so cannot catch `CancelledError` — verified by reading each file.

### Files involved (final list)

- `api/primers.py` (lines 267, 276) — missing `CancelledError` handler in `event_generator()`.
- `services/primer_service.py` (lines 108, 868) — `astream` site + broad `except Exception`; the latter does no harm on its own but contributes to the diffuse "no cancellation awareness" surface.
- `core/pipeline_langgraph.py` (line 494) — same defect for `/chat/stream/agentic`; should be fixed in the same PR.
- `core/sentry.py` (lines 38–42) — `LoggingIntegration` is the conduit; not the bug, but understanding it explains *why* uvicorn's ASGI-protocol logging becomes a Sentry event.
- `main.py` (line 126) — `catch_exceptions_mw` uses `except Exception` (correct, since `CancelledError` should propagate to ASGI for cancel-scope completion); no change needed here.
