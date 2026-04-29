---
phase: 13
slug: sentry-infrastructure
status: verified
threats_open: 0
asvs_level: 1
created: 2026-04-26
---

# Phase 13 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| client → CorrelationIdMiddleware | Client may send arbitrary X-Correlation-ID header | UUID string (low sensitivity) |
| Sentry SDK → Sentry remote | Error event payload sent to external Sentry service | May contain request body, stack traces, PII |
| env vars → core/sentry.py | SENTRY_ENABLED and SENTRY_DSN loaded at module import time | Credentials (SENTRY_DSN) |
| catch_exceptions_mw → caller | Unhandled exception response may expose internal error detail | Exception message string |
| logger.error → LoggingIntegration → Sentry | ERROR-level log records forwarded to Sentry automatically | Stack traces, request path |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-13-01 | Tampering | CorrelationIdMiddleware | mitigate | Always generates server-side UUID via `str(uuid.uuid4())`. Incoming `X-Correlation-ID` from clients is never read (`grep "request.headers" core/middleware.py` = 0). | closed |
| T-13-02 | Information Disclosure | _scrub_pii / before_send | mitigate | `event["request"].pop("data", None)` removes entire request body (including `user_query`) before Sentry transport. GDPR Article 9 compliance for Islamic religious content. Verified: `.pop("data")` present in core/sentry.py. | closed |
| T-13-03 | Information Disclosure | SENTRY_DSN in env | accept | SENTRY_DSN loaded from `.env` via `core/config.py`; never hardcoded or logged. `.env` is gitignored. Risk: DSN exposure in process listing — low risk, standard practice for all SaaS SDKs. | closed |
| T-13-04 | Information Disclosure | Sentry Logs PII path | accept | `before_send` does NOT cover Sentry Logs (requires `before_send_log` at sentry-sdk ≥ 2.35.0). No log calls added in Phase 13. Phases 14–16 must not put `user_query` content into `extra={}` fields. Risk accepted at Phase 13 level. | closed |
| T-13-05 | Denial of Service | sentry_sdk.init() | mitigate | Python module caching (`sys.modules`) guarantees the `if SENTRY_ENABLED and SENTRY_DSN:` block in core/sentry.py executes exactly once per process. No additional guard needed. | closed |
| T-13-06 | Information Disclosure | SENTRY_ENABLED in dev | mitigate | `SENTRY_ENABLED` defaults to `False` (requires explicit `SENTRY_ENABLED=true` in env). Local dev with no `.env` setting never triggers Sentry connections. | closed |
| T-13-07 | Information Disclosure | catch_exceptions_mw response body | mitigate | Response body branching on `ENV == "development"`: production always returns `{"detail": "internal_error"}` (no error string); dev includes `"error": str(e)` for debugging. Two branches verified in main.py. | closed |
| T-13-08 | Information Disclosure | Duplicate Sentry events | accept | Original mitigation (logger.error-only) was invalidated by CR-01: LoggingIntegration cannot capture exceptions swallowed by catch_exceptions_mw. Code review fix intentionally added `sentry_sdk.capture_exception(e)` alongside `logger.error(exc_info=True)`. Potential duplicate Sentry events when both fire — accepted as a known trade-off. Risk: minor (duplicate dashboard entries, no data loss). See CR-01 in 13-REVIEW-FIX.md. | closed |
| T-13-09 | Information Disclosure | sentry_sdk import in main.py | accept | Original mitigation (remove import sentry_sdk from main.py) was reversed by the CR-01 fix. `import sentry_sdk` re-added at main.py:87, used only in `catch_exceptions_mw` under `if SENTRY_ENABLED` guard. Risk: low — usage is single-purpose and guarded. All SDK init still goes through core/sentry.py. See CR-01 in 13-REVIEW-FIX.md. | closed |
| T-13-10 | Tampering | Middleware registration order | mitigate | CorrelationIdMiddleware registered after CORSMiddleware in main.py source. Starlette `add_middleware` uses `list.insert(0)`, so last-registered runs first — correlation_id ContextVar is set before all downstream code. Position verified: `CorrelationIdMiddleware` index > `CORSMiddleware` index in main.py. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-13-01 | T-13-03 | SENTRY_DSN loaded from .env (gitignored); DSN exposure in process listing is low-risk, standard SaaS SDK practice. | Shawn Nassabi | 2026-04-26 |
| AR-13-02 | T-13-04 | before_send PII scrubbing does not cover Sentry Logs path at sentry-sdk 2.27.0. No log calls added in Phase 13; Phases 14–16 must avoid putting user_query in extra= fields. | Shawn Nassabi | 2026-04-26 |
| AR-13-03 | T-13-08 | Duplicate Sentry events (logger.error + capture_exception both fire) introduced by CR-01 code review fix. LoggingIntegration cannot capture exceptions consumed by catch_exceptions_mw; explicit capture_exception required for functional Sentry error reporting. Duplicate events are a minor dashboard quality issue with no security impact. | Shawn Nassabi | 2026-04-26 |
| AR-13-04 | T-13-09 | import sentry_sdk re-added to main.py by CR-01 fix. Usage is single-purpose (capture_exception under SENTRY_ENABLED guard) and documented. All SDK initialization still goes through core/sentry.py. | Shawn Nassabi | 2026-04-26 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-26 | 10 | 10 | 0 | gsd-security-auditor (Claude) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log (AR-13-01 through AR-13-04)
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-04-26
