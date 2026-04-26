---
status: partial
phase: 13-sentry-infrastructure
source: [13-VERIFICATION.md]
started: 2026-04-26T22:15:00Z
updated: 2026-04-26T22:15:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. sentry_sdk.init() fires exactly once with real DSN
expected: Start server with `SENTRY_ENABLED=true SENTRY_DSN=<dsn>`, verify Sentry dashboard shows one initialization event and no duplicate on subsequent requests.
result: [pending]

### 2. X-Correlation-ID header delivered on all response types
expected: `curl -v http://localhost:8000/health` (standard) and the SSE streaming route both return `X-Correlation-ID` header. BaseHTTPMiddleware can behave differently for streaming responses; requires a running server to confirm.
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
