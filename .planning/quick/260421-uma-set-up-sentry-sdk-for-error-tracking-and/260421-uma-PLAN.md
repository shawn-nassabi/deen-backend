---
phase: quick
plan: 260421-uma
type: execute
wave: 1
depends_on: []
files_modified:
  - requirements.txt
  - core/config.py
  - main.py
  - .env.example
autonomous: true
requirements: []

must_haves:
  truths:
    - "Sentry SDK is installed and importable"
    - "Sentry is initialized before the FastAPI app is created, using SENTRY_DSN from env"
    - "SENTRY_DSN is not hardcoded anywhere in application code"
    - "GET /sentry-debug raises a ZeroDivisionError only when ENV=development"
    - "Unhandled exceptions are captured by Sentry automatically via FastAPI integration"
  artifacts:
    - path: "requirements.txt"
      provides: "sentry-sdk[fastapi] pinned dependency"
    - path: "core/config.py"
      provides: "SENTRY_DSN variable loaded from env"
    - path: "main.py"
      provides: "sentry_sdk.init() call before app = FastAPI(...), /sentry-debug endpoint"
    - path: ".env.example"
      provides: "SENTRY_DSN placeholder with the real DSN in a comment"
  key_links:
    - from: "main.py"
      to: "core/config.py"
      via: "import SENTRY_DSN"
      pattern: "from core.config import.*SENTRY_DSN"
    - from: "sentry_sdk.init"
      to: "FastAPI app"
      via: "called before app = FastAPI()"
      pattern: "sentry_sdk.init"
---

<objective>
Integrate the Sentry SDK into the FastAPI backend for error tracking and structured logging.

Purpose: Capture unhandled exceptions and server errors automatically in Sentry so they are
visible in the Sentry dashboard without relying solely on local logs or user reports.

Output: sentry-sdk added to requirements.txt; SENTRY_DSN in core/config.py; Sentry initialized
in main.py with FastAPI integration; a dev-only /sentry-debug verification endpoint.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md

<!-- Key interfaces the executor needs -->
<interfaces>
From core/config.py (module-level pattern — add SENTRY_DSN alongside other os.getenv vars):
```python
SENTRY_DSN = os.getenv("SENTRY_DSN")   # Optional — absence disables Sentry silently
```

From main.py (Sentry init must go BEFORE app = FastAPI(lifespan=lifespan)):
```python
# Current structure:
import os
from core.config import validate_supabase_config  # existing import
app = FastAPI(lifespan=lifespan)                   # line 33
```

Sentry FastAPI integration pattern:
```python
import sentry_sdk
from core.config import SENTRY_DSN, ENV

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=True,
        enable_logs=True,
        environment=ENV,
    )
# sentry_sdk.init MUST be called BEFORE app = FastAPI(...)
# FastAPI integration is automatic when sentry-sdk[fastapi] is installed
```

Debug endpoint pattern (dev-only, matches existing ENV guard pattern in main.py):
```python
if os.getenv("ENV", "development") == "development":
    @app.get("/sentry-debug")
    def trigger_error():
        division_by_zero = 1 / 0
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add sentry-sdk to requirements and SENTRY_DSN to config</name>
  <files>requirements.txt, core/config.py, .env.example</files>
  <action>
    1. **requirements.txt** — append `sentry-sdk[fastapi]==2.27.0` after the last entry (above the closing entries near `zstandard==0.23.0`). Use the extras variant `sentry-sdk[fastapi]` so the FastAPI integration is included automatically.

    2. **core/config.py** — add `SENTRY_DSN = os.getenv("SENTRY_DSN")` near the top of the module-level variable block, after the existing `ENV` line. No ValueError guard — a missing DSN should silently disable Sentry, not crash the server.

    3. **.env.example** — append a new `=== Sentry ===` section at the bottom of the file:
    ```
    # === Sentry ===
    # Optional. When set, errors and logs are sent to Sentry.
    # Real DSN: https://099509c03ea362587f0984dd6311e609@o4511261194715136.ingest.us.sentry.io/4511261200416768
    SENTRY_DSN=
    ```
    The real DSN belongs in the developer's local .env only — never in application code.
  </action>
  <verify>
    <automated>cd /Users/shawn.n/Desktop/Deen/deen-backend && grep "sentry-sdk" requirements.txt && grep "SENTRY_DSN" core/config.py && grep "SENTRY_DSN" .env.example</automated>
  </verify>
  <done>requirements.txt contains sentry-sdk[fastapi]; core/config.py exports SENTRY_DSN; .env.example has placeholder with real DSN in comment only</done>
</task>

<task type="auto">
  <name>Task 2: Initialize Sentry in main.py and add /sentry-debug endpoint</name>
  <files>main.py</files>
  <action>
    1. Add the Sentry import and init block near the TOP of main.py, BEFORE the `app = FastAPI(lifespan=lifespan)` line. Insert after the existing `import os` line but before the lifespan context manager:

    ```python
    import sentry_sdk
    from core.config import SENTRY_DSN

    if SENTRY_DSN:
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            send_default_pii=True,
            enable_logs=True,
            environment=os.getenv("ENV", "development"),
        )
    ```

    The `from core.config import validate_supabase_config` import is already present — add `SENTRY_DSN` to that same import line OR keep it as a separate import. Either is fine; prefer extending the existing import: `from core.config import validate_supabase_config, SENTRY_DSN`.

    2. Add the /sentry-debug endpoint AFTER all the router registrations, inside the existing `if os.getenv("ENV", "development") == "development":` guard that already exists for the CORS localhost origins — but as a SEPARATE conditional block at the bottom of the file (do NOT nest it inside the CORS block). Add it after the `/_routes` endpoint:

    ```python
    if os.getenv("ENV", "development") == "development":
        @app.get("/sentry-debug", tags=["Debug"])
        def trigger_sentry_error():
            """Dev-only endpoint to verify Sentry error capture is working."""
            division_by_zero = 1 / 0
    ```

    3. Do NOT hardcode any DSN value anywhere in main.py.
  </action>
  <verify>
    <automated>cd /Users/shawn.n/Desktop/Deen/deen-backend && python -c "import ast, sys; ast.parse(open('main.py').read()); print('syntax ok')" && grep -n "sentry_sdk.init" main.py && grep -n "sentry-debug" main.py && ! grep -n "099509c03ea362587f0984" main.py</automated>
  </verify>
  <done>main.py parses without syntax errors; sentry_sdk.init is present and gated on SENTRY_DSN; /sentry-debug endpoint exists; no hardcoded DSN value in the file</done>
</task>

</tasks>

<verification>
After both tasks complete:

1. Syntax check passes: `python -c "import ast; ast.parse(open('main.py').read())"`
2. Sentry init appears before FastAPI app creation: `grep -n "sentry_sdk.init\|app = FastAPI" main.py` — init line number must be lower than app line number
3. No hardcoded DSN in codebase: `grep -r "099509c03ea362587f0984" . --include="*.py"` returns no results
4. /sentry-debug is dev-only: confirm it is wrapped in `if os.getenv("ENV", "development") == "development":`
5. .env.example has DSN in comment form only (not as a live value)
</verification>

<success_criteria>
- `sentry-sdk[fastapi]` present in requirements.txt
- `SENTRY_DSN = os.getenv("SENTRY_DSN")` in core/config.py
- `sentry_sdk.init(...)` in main.py, executed before `app = FastAPI(...)`, gated on `if SENTRY_DSN:`
- `send_default_pii=True` and `enable_logs=True` passed to init
- `/sentry-debug` endpoint present and wrapped in ENV=development guard
- Real DSN documented in .env.example comment only — zero hardcoded occurrences in .py files
</success_criteria>

<output>
After completion, create `.planning/quick/260421-uma-set-up-sentry-sdk-for-error-tracking-and/260421-uma-SUMMARY.md`
</output>
