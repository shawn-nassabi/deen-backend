---
phase: 14
slug: route-layer-instrumentation
status: verified
threats_open: 0
asvs_level: 1
created: 2026-04-27
---

# Phase 14 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| client→/references | User-controlled query string into pipeline; exception messages previously leaked back | Query params (user text) |
| client→/chat/stream/agentic | user_query, session_id, config JSON into agentic pipeline | Query content, config |
| client→/chat/agentic | Same as above for non-streaming variant | Query content, config |
| client→/primers/* | user_id and lesson_id into service layer; included in extra={} as searchable fields | Opaque identifiers |
| log sink→Sentry | extra={} fields from all route handlers flow to Sentry Logs via LoggingIntegration | Structured log fields |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-14-01 | Information Disclosure | api/reference.py except block | mitigate | `detail="internal_error"` hardcoded; `logger.error(exc_info=True)` routes exception to Sentry only | closed |
| T-14-02 | Information Disclosure | api/hikmah.py + api/reference.py extra={} | accept | extra={} fields are non-sensitive: correlation_id (UUID), lesson_content_id (int), lesson_name (opaque string). No user_query text. | closed |
| T-14-03 | Tampering | correlation_id in extra={} | accept | correlation_id is generated server-side by CorrelationIdMiddleware — client cannot inject | closed |
| T-14-04 | Information Disclosure | api/primers.py logger.error in except blocks | mitigate | traceback.print_exc() removed; logger.error(exc_info=True) in all four except blocks | closed |
| T-14-05 | Information Disclosure | api/primers.py extra={} log fields | accept | Fields: correlation_id, lesson_id (int), user_id (opaque sub), from_cache (bool). No user_query or content text. | closed |
| T-14-06 | Tampering | correlation_id in primers extra={} | accept | correlation_id sourced from server-side ContextVar — client cannot inject | closed |
| T-14-07 | Information Disclosure | api/chat.py logger.info start log | mitigate | Start logs use `query_length: len(user_query)` (int); user_query string absent from all logger.info extras | closed |
| T-14-08 | Information Disclosure | api/chat.py except blocks | mitigate | logger.error(exc_info=True) in all three agentic handlers; all HTTPException details are hardcoded strings with no str(e) interpolation | closed |
| T-14-09 | Tampering | correlation_id in chat extra={} | accept | correlation_id is server-generated UUID from ContextVar — client cannot spoof | closed |
| T-14-10 | Denial of Service | Config parse in agentic handler | accept | Malformed config falls back to default AgentConfig; parse failure caught with logger.warning, execution continues | closed |
| T-14-11 | Elevation of Privilege | user_id in Sentry tags via bind_sentry_scope | accept | user_id is Cognito sub claim — opaque UUID, not PII; internal observability only | closed |

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-14-01 | T-14-02 | extra={} log fields in hikmah/reference are non-sensitive structural identifiers (int IDs, UUIDs, opaque strings) — no user query text | gsd-security-auditor | 2026-04-27 |
| AR-14-02 | T-14-03 | correlation_id generated server-side by CorrelationIdMiddleware ContextVar; no client injection path | gsd-security-auditor | 2026-04-27 |
| AR-14-03 | T-14-05 | user_id is opaque Cognito sub (UUID); lesson_id is int; no content text logged | gsd-security-auditor | 2026-04-27 |
| AR-14-04 | T-14-06 | Same as AR-14-02 — ContextVar is server-populated only | gsd-security-auditor | 2026-04-27 |
| AR-14-05 | T-14-09 | Same as AR-14-02 for chat routes | gsd-security-auditor | 2026-04-27 |
| AR-14-06 | T-14-10 | Parse errors caught and execution falls back to default AgentConfig; no DoS vector | gsd-security-auditor | 2026-04-27 |
| AR-14-07 | T-14-11 | Cognito sub is opaque UUID with no PII value; acceptable for internal observability | gsd-security-auditor | 2026-04-27 |

---

## Auditor Notes

- `api/chat.py` `POST /chat/` bare `except Exception:` has no handler-level `logger.error`. Exception logging falls back to global `catch_exceptions_mw` middleware. No `str(e)` leaked to client. Not in T-14-08 scope (which targets agentic endpoints only).
- `api/hikmah.py` except blocks include `"error": str(e)` in `extra={}` passed to `logger.error`. Exception text routes to Sentry structured fields, not to client. Consistent with T-14-02 accepted disposition. Advisory: if exception messages ever embed user-supplied content, that text would appear in Sentry log fields.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-27 | 11 | 11 | 0 | gsd-security-auditor (claude-sonnet-4-6) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter
