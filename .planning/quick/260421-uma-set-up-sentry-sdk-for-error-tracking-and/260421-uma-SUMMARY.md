---
phase: quick
plan: 260421-uma
subsystem: observability
tags: [sentry, error-tracking, fastapi, monitoring]
dependency_graph:
  requires: []
  provides: [sentry-error-capture, sentry-fastapi-integration]
  affects: [main.py, core/config.py]
tech_stack:
  added: [sentry-sdk[fastapi]==2.27.0]
  patterns: [conditional-sdk-init, dev-only-debug-endpoint, env-gated-config]
key_files:
  created: []
  modified:
    - requirements.txt
    - core/config.py
    - main.py
    - .env.example
decisions:
  - "SENTRY_DSN absence silently disables Sentry rather than crashing server — consistent with optional integration pattern"
  - "FastAPI integration automatic via sentry-sdk[fastapi] extras — no manual middleware needed"
  - "sentry_sdk.init placed before app = FastAPI() to ensure exception capture during app startup"
metrics:
  duration: "~5 minutes"
  completed: "2026-04-22"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 4
---

# Quick Task 260421-uma: Set Up Sentry SDK for Error Tracking Summary

**One-liner:** Sentry SDK integrated with FastAPI via sentry-sdk[fastapi]==2.27.0, initialized from SENTRY_DSN env var before app creation, with dev-only /sentry-debug verification endpoint.

## What Was Done

Integrated the Sentry SDK into the FastAPI backend for automatic unhandled exception capture and structured logging. Sentry is opt-in: when `SENTRY_DSN` is absent the server boots normally with no Sentry overhead.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add sentry-sdk to requirements and SENTRY_DSN to config | eeb8f6b | requirements.txt, core/config.py, .env.example |
| 2 | Initialize Sentry in main.py and add /sentry-debug endpoint | fe61762 | main.py |

## Changes Made

### requirements.txt
- Appended `sentry-sdk[fastapi]==2.27.0` — the `[fastapi]` extras variant activates the automatic FastAPI integration (no manual middleware required).

### core/config.py
- Added `SENTRY_DSN = os.getenv("SENTRY_DSN")` immediately after the `ENV` variable. No ValueError guard — a missing DSN disables Sentry silently, consistent with the fiqh index pattern already in this file.

### main.py
- Extended `from core.config import validate_supabase_config, SENTRY_DSN`.
- Added `import sentry_sdk` and a conditional init block before `app = FastAPI(lifespan=lifespan)`:
  - `send_default_pii=True` — captures user-identifying context on errors
  - `enable_logs=True` — routes Python logging into Sentry
  - `environment` — set from `os.getenv("ENV", "development")`
- Added `/sentry-debug` endpoint at the bottom of the file, wrapped in `if os.getenv("ENV", "development") == "development":` — raises `ZeroDivisionError` to verify Sentry capture is live.

### .env.example
- Added `# === Sentry ===` section at the bottom with the real DSN in a comment and `SENTRY_DSN=` as an empty placeholder. Real DSN never appears in application code.

## Verification

1. Syntax check: PASSED — `ast.parse(open('main.py').read())` clean
2. Init order: `sentry_sdk.init` on line 18, `app = FastAPI` on line 42
3. No hardcoded DSN: `grep -r "099509c03ea362587f0984" . --include="*.py"` returns exit 1 (not found)
4. Dev-only guard confirmed: `/sentry-debug` is wrapped in `if os.getenv("ENV", "development") == "development":`
5. .env.example: real DSN appears only in a comment, `SENTRY_DSN=` placeholder is empty

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. Sentry integration is fully wired: SDK installed, init gated on env var, FastAPI integration automatic via extras.

## Self-Check: PASSED

- `requirements.txt` contains `sentry-sdk[fastapi]==2.27.0`: confirmed
- `core/config.py` exports `SENTRY_DSN`: confirmed
- `main.py` has `sentry_sdk.init` before `app = FastAPI`: confirmed (lines 18 vs 42)
- `/sentry-debug` endpoint present and dev-gated: confirmed
- Commits eeb8f6b and fe61762 exist in git log: confirmed
