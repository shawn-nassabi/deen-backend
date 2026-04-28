---
phase: 15
slug: pipeline-and-tools-instrumentation
status: verified
threats_open: 0
asvs_level: 1
created: 2026-04-27
---

# Phase 15 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

Phase 15 ("Pipeline and Tools Instrumentation") replaced ad-hoc `print()` statements in three files with structured `logger.*` calls integrated with Sentry's `LoggingIntegration`. The threat surface is therefore narrow: information disclosure via log payloads, denial of service via log volume against Sentry's quota, and repudiation via duplicate Sentry events from belt-and-suspenders capture paths.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| user input → log `extra={}` | User-supplied query text and LLM-derived working_query must never flow into log extra fields (which Sentry's LoggingIntegration ships to the Sentry Logs stream). | user_query, working_query (high sensitivity) |
| LLM response content → log stream | Generated assistant content can paraphrase user input and must never be printed or logged. | LLM response text (high sensitivity) |
| tool result payload → log stream | Retrieved document snippets and tool return payloads must not enter the log stream. | retrieved doc text (medium sensitivity) |
| `logger.error` → Sentry | Sentry's `LoggingIntegration` auto-captures `logger.error` as a Sentry event. A second `capture_exception()` call alongside would double-count the same exception. | exception type + traceback |
| `logger.debug` → Sentry | Sentry's `LoggingIntegration` threshold is INFO; DEBUG records do not reach Sentry — used here for high-volume node-traversal records. | node-name strings (low sensitivity) |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-15-01 | Information Disclosure | `core/pipeline_langgraph.py` log `extra={}` dicts | mitigate | Every `extra={}` (lines 94-98, 130, 384-387, 398-401, 426-430) contains only `correlation_id`, `session_id`, `target_language`, `node`, `error`. No `user_query` / `working_query`. | closed |
| T-15-02 | Denial of Service | Streaming-loop node-traversal logs (`core/pipeline_langgraph.py:130`) | mitigate | Emitted via `logger.debug(...)`, below Sentry `LoggingIntegration` INFO threshold — never consumes Sentry log quota. | closed |
| T-15-03 | Repudiation | Duplicate Sentry events on SSE generator exception (`core/pipeline_langgraph.py`) | mitigate | `logger.error("Pipeline error", exc_info=True, ...)` at line 384 is the sole capture path. `grep -c "capture_exception" core/pipeline_langgraph.py` → 0. | closed |
| T-15-04 | Information Disclosure | `agents/tools/retrieval_tools.py` `logger.error` extras (4 sites) | mitigate | Lines 59-62, 121-124, 182-185, 245-248 — extras contain only `correlation_id` and `error`. The `query` parameter appears only in docstrings and `query_used` return-payload keys, never in a log extra. | closed |
| T-15-05 | Information Disclosure | `_call_fiqh_subgraph_node` formerly printed `state["user_query"][:80]` (`agents/core/chat_agent.py:311`) | mitigate | Replaced by `logger.debug("Invoking FAIR-RAG sub-graph", extra={"correlation_id": ...})`. Subsequent debug at line 328 logs only `doc_count` and `status_event_count`. | closed |
| T-15-06 | Information Disclosure | `_agent_node` formerly printed agent response content (`agents/core/chat_agent.py` lines 172-175) | mitigate | Block deleted entirely (D-04). The `try` body now contains only `llm.invoke`, state mutation, and the structured `except` branch. LLM response content does not enter the log stream. | closed |
| T-15-07 | Repudiation | Duplicate Sentry events on any node exception (`agents/core/chat_agent.py`) | mitigate | All 7 error sites (lines 120, 177, 264, 297, 338, 388, 605) use `logger.error(..., exc_info=True, ...)`. `grep -c "capture_exception" agents/core/chat_agent.py` → 0. | closed |
| T-15-08 | Information Disclosure | `_tool_node` tool-result payload (`agents/core/chat_agent.py:202`) | mitigate | Replaced with `logger.debug("Tool executed", extra={"correlation_id": ..., "tool_name": tool_name})`. Former `str(result_data)[:200]` payload is gone. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|

No accepted risks.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-27 | 8 | 8 | 0 | gsd-security-auditor (Claude) |

### Security Audit 2026-04-27

| Metric | Count |
|--------|-------|
| Threats found | 8 |
| Closed | 8 |
| Open | 0 |

**Cross-file sweep:**

| Sweep | Result |
|-------|--------|
| `print(` across `core/pipeline_langgraph.py`, `agents/tools/retrieval_tools.py`, `agents/core/chat_agent.py` | 0 / 0 / 0 |
| `capture_exception` across the same three files | 0 / 0 / 0 |
| Logger declarations | `core/pipeline_langgraph.py:16-19`, `agents/tools/retrieval_tools.py:9-12`, `agents/core/chat_agent.py:33-36` |
| `logger.error(...)` sites with `exc_info=True` | 12 / 12 |

**Observations (informational, non-blocking):**

- The non-streaming `chat_pipeline_agentic` invoke around `core/pipeline_langgraph.py:435-440` is a bare `agent.invoke(...)` without an enclosing `try/except`. This was flagged as code-review item WR-03 and addressed by commit `089caeb`; if the wrapper is later regressed, T-15-03 / T-15-07 would not be re-opened (their concern is duplicate-event prevention, not coverage), but a future audit may wish to track exception-handling coverage as a separate threat.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log (none)
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-04-27
