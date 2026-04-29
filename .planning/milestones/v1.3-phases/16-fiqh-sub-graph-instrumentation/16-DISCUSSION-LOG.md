# Phase 16: Fiqh Sub-graph Instrumentation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-28
**Phase:** 16-fiqh-sub-graph-instrumentation
**Areas discussed:** extra={} field composition, FIQH-03 fail-open scope, Query content in retrieve_node

---

## extra={} Field Composition

### Question 1: Missing fields when a node doesn't have them yet

| Option | Description | Selected |
|--------|-------------|----------|
| Omit absent fields | Only include fields that are meaningfully available | ✓ |
| Use None for absent fields | Always include all three keys; set to None when not yet known | |
| Use 0 for absent fields | Always include all three keys; set to 0 when not yet known | |

**User's choice:** Omit absent fields  
**Notes:** Avoids misleading Sentry search results (e.g., `doc_count:0` in decompose_node where no retrieval has happened)

### Question 2: doc_count in retrieve_node

| Option | Description | Selected |
|--------|-------------|----------|
| New docs this iteration | `doc_count=len(new_docs)` — docs returned by this retrieval pull | ✓ |
| Total accumulated after dedup | `doc_count=len(existing)` after dedup — running total | |
| Both — separate keys | `new_doc_count` and `accumulated_doc_count` as separate keys | |

**User's choice:** New docs this iteration  
**Notes:** Makes FIQH-02 detection direct — `doc_count:0` in Sentry = zero new docs this pull

### Question 3: doc_count in filter_node

| Option | Description | Selected |
|--------|-------------|----------|
| Post-filter count only | `doc_count=len(filtered)` — what matters for FIQH-03 | ✓ |
| Both pre and post counts | `pre_doc_count` and `post_doc_count` as separate keys | |

**User's choice:** Post-filter count only  
**Notes:** Makes FIQH-03 detection direct — `doc_count:0` = filter dropped everything

---

## FIQH-03 Fail-open Scope

| Option | Description | Selected |
|--------|-------------|----------|
| WARNING only — no behavior change | Log WARNING when filtered is empty, propagate empty list | ✓ |
| Add fail-open + WARNING on empty result | When filter returns [], log WARNING then fall back to accumulated_docs | |

**User's choice:** WARNING only — no behavior change  
**Notes:** User asked for clarification on what was happening and what was being proposed. After explanation, confirmed: just add the warning, don't change the graph behavior. The current behavior (empty filter result → assess → INSUFFICIENT → refine or exit) is correct and intentional.

---

## Query Content in retrieve_node

| Option | Description | Selected |
|--------|-------------|----------|
| Drop it — log doc_count only | Remove current_query[:60] per Phase 15 D-05 | ✓ |
| Keep the sub-query snippet | Sub-queries are keyword rewrites, arguably lower PII risk | |

**User's choice:** Drop it — log doc_count only  
**Notes:** Consistent with Phase 15 D-05 blanket stance — no query content at any level

---

## Claude's Discretion

- Exact log message strings (e.g., "Fiqh retrieval returned zero documents") — user deferred to Claude
- Whether the existing INFO log in `_route_after_assess` stays alongside the new FIQH-04 WARNING — Claude determined it should stay (fires on all exits; WARNING fires only on exhaustion path)

## Deferred Ideas

None.
