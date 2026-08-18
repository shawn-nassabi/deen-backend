# DEE-21: Fix dropped sparse results & add corpus-fit BM25 sparse retrieval

*Team summary · PR [#117](https://github.com/shawn-nassabi/deen-backend/pull/117) · Linear DEE-21*

---

## What this does

Hadith retrieval is advertised as hybrid (dense + sparse), but sparse has been contributing **nothing** in production. This PR fixes two independent defects that both silently disabled it, then adds a corpus-fit BM25 sparse backend behind a config flag.

Prod behaviour is unchanged by default: `HADITH_SPARSE_BACKEND` defaults to `tfidf`, and BM25 vectors live in a separate Pinecone namespace (`bm25`) inside the existing sparse index.

**Scope:** hadith Shia/Sunni hybrid retrieval only. Dense retrieval, Quran/Tafsir, and fiqh FAIR-RAG are untouched.

---

## Which endpoints are affected

Any route that reaches `modules/retrieval/retriever.py` for Shia/Sunni hadith (verified in `api/chat.py`, `api/reference.py`, `api/hikmah.py` — these use named routers such as `@chat_router.post`, not `@router.post`, so a bare `grep '@router.post'` in `api/` will miss them):

| Endpoint | Path | Retrieval call site |
|---|---|---|
| Agentic chat (streaming) | `POST /chat/stream/agentic` | `retrieve_shia_documents_tool` / `retrieve_sunni_documents_tool` via LangGraph |
| Agentic chat (non-streaming) | `POST /chat/agentic` | same agentic pipeline |
| Reference lookup | `POST /references` | `aretrieve_shia_documents` / `aretrieve_sunni_documents` |
| Legacy streaming chat | `POST /chat/stream` | `retrieve_shia_documents` / `retrieve_sunni_documents` |
| Hikmah elaboration (streaming) | `POST /hikmah/elaborate/stream` | `aretrieve_shia_documents` (Shia only) |

Legacy `POST /chat/` (non-streaming, `retrieve_documents`) also hits the sparse path but is low-traffic compared to the routes above.

Deliberately **not** changed: Quran/Tafsir retrieval (`retrieve_quran_*`), fiqh subgraph, dense-only paths.

---

## Problem

### 1. Sparse results were discarded before reranking

`modules/reranking/reranker.py` read sparse hits like this:

```python
sparse_matches = []
if isinstance(sparse_results, dict):
    sparse_matches = sparse_results.get("matches", []) or []
```

Pinecone's `.query()` returns a `QueryResponse` object, **not** a `dict`. Verified against the live index:

```
type       : QueryResponse
is dict    : False
has matches: True
n matches  : 1
```

So `sparse_matches` was always `[]`. Every sparse hit was dropped, `SPARSE_RESULT_WEIGHT` never applied, and "hybrid" retrieval was effectively dense-only — while still paying the latency cost of the sparse query.

### 2. Query-side TF-IDF was fit per request

`generate_sparse_embedding()` called `fit_transform()` on the **single incoming query**:

```python
vec = getSparseEmbedder().fit_transform([normalized_query])
```

That builds a vocabulary from that one query, so the resulting term indices are not comparable to the corpus-fit vectors stored in the sparse index. Even with defect #1 fixed, sparse scores would be meaningless on the existing index.

The fiqh path already does this correctly (corpus-fit `BM25Encoder`, `encode_documents` at ingest / `encode_queries` at query time). This PR brings hadith in line with it.

---

## How it works

### Reranker fix (always on)

New `_extract_sparse_matches()` normalises `None` / `dict` / Pinecone `QueryResponse` into a list of match dicts before the weighted merge. **This alone restores sparse contribution on the default `tfidf` backend** — though TF-IDF scores remain weak for reason #2 above.

### BM25 backend (opt-in)

When `HADITH_SPARSE_BACKEND=bm25`:

1. Query encoding uses a corpus-fit `BM25Encoder` loaded from `data/hadith_bm25_encoder.json`.
2. Sparse queries target namespace `bm25` (configurable via `DEEN_SPARSE_BM25_NAMESPACE`) in the existing sparse index.
3. If the encoder file is missing, we log **ERROR** and skip sparse for that request (dense-only). We **never** silently fall back to TF-IDF against the BM25 namespace.

All sparse encoding is CPU-bound and runs in `asyncio.to_thread` on the async path.

---

## Why a namespace instead of a new index

The original plan used a separate staging index. Pinecone refused:

```
FORBIDDEN: You've reached the max serverless indexes allowed in project (5).
Use namespaces to partition your data into logical groups...
```

BM25 vectors now live in `deen-index-v2-sparse` under namespace `bm25`, alongside the existing `ns1` data. Namespaces are fully isolated, so this needs no new infrastructure, no plan upgrade, and touches nothing in prod until the flag is flipped.

---

## Reindex script

The hadith corpus is not in the repo (unlike fiqh's PDF) — it lives in the dense index. `scripts/reindex_hadith_sparse.py` enumerates it, decompresses `text_en`, fits BM25, and upserts sparse vectors under the same vector IDs.

Three phases with an on-disk JSONL cache between them, so peak memory holds only the plain texts rather than every vector's full metadata. Metadata is copied verbatim from dense vectors — the reranker keys on `hadith_id` and retrieval filters on `sect`.

```bash
python scripts/reindex_hadith_sparse.py --dry-run --limit 200   # inspect, no writes
python scripts/reindex_hadith_sparse.py --encoder-only          # fit + persist encoder
python scripts/reindex_hadith_sparse.py                         # full reindex
python scripts/reindex_hadith_sparse.py --skip-enumerate --skip-fit   # re-upsert only
```

**Guard:** the script refuses to write to the live `ns1` namespace of the existing sparse index.

The encoder file (`data/hadith_bm25_encoder.json`) and corpus cache (`data/hadith_corpus_cache.jsonl`) are gitignored and must be generated per environment. Unlike fiqh, there is no Dockerfile `--encoder-only` step — the corpus exists only in Pinecone.

---

## Environment variables

| Variable | Default | Required | Notes |
|---|---|---|---|
| `HADITH_SPARSE_BACKEND` | `tfidf` | yes (validated) | Set to `bm25` to enable staging backend |
| `DEEN_SPARSE_BM25_NAMESPACE` | `bm25` | no | Namespace for BM25 vectors in existing sparse index |
| `DEEN_SPARSE_BM25_INDEX_NAME` | *(unset)* | no | Optional override; falls back to `DEEN_SPARSE_INDEX_NAME` |

Existing vars unchanged: `DEEN_SPARSE_INDEX_NAME`, `DENSE_RESULT_WEIGHT` (0.8), `SPARSE_RESULT_WEIGHT` (0.2).

---

## Deployment

1. Deploy with `HADITH_SPARSE_BACKEND=tfidf` (default) — zero risk; the reranker fix alone restores sparse hits on the existing index.
2. Run the reindex once per environment to populate the `bm25` namespace and produce the encoder file.
3. Flip `HADITH_SPARSE_BACKEND=bm25` in dev/staging and compare.

**Rollback:** set `HADITH_SPARSE_BACKEND=tfidf`. Instant, no reindex, no redeploy of code.

---

## Changes

| File | What changed |
|---|---|
| `modules/reranking/reranker.py` | `_extract_sparse_matches()` — fixes QueryResponse handling so sparse hits reach the merge |
| `core/config.py` | `HADITH_SPARSE_BACKEND`, `DEEN_SPARSE_BM25_INDEX_NAME`, `DEEN_SPARSE_BM25_NAMESPACE` |
| `modules/embedding/embedder.py` | Lazy BM25 encoder, `generate_bm25_sparse_embedding()`, `generate_hadith_sparse_embedding()` dispatcher; TF-IDF code untouched |
| `modules/retrieval/retriever.py` | Backend-aware sparse index + namespace resolution; shared `_sync_sparse_search()`; dense-only fallback when encoder/index unavailable |
| `scripts/reindex_hadith_sparse.py` | **New.** Corpus enumeration, BM25 fit, namespace upsert |
| `.gitignore` | Ignore `data/hadith_bm25_encoder.json`, `data/*.jsonl` |

- **No new `requirements.txt` entries** — `pinecone-text==0.11.0` was already present (used by fiqh ingestion); this PR only adds a new import site in `embedder.py`.
- **No database migrations.**

---

## Verification

Reindex completed against the live dense index:

```
Cached 59082 records (seen=59082, skipped_no_text=0)
Fitting BM25 encoder on 59082 documents... 100%|██████| [01:18<00:00, 751it/s]
Upsert complete: 59077 vectors in deen-index-v2-sparse namespace=bm25
```

5 of 59,082 documents were skipped because BM25 produced an empty vector (all terms out-of-vocabulary); Pinecone rejects empty sparse vectors, so they are dropped rather than failing the batch.

**Before the reranker fix**, `sparse_count` was structurally guaranteed to be 0. After:

```
[RERANK] dense_count=5 sparse_count=5     # tfidf backend
[RERANK] dense_count=5 sparse_count=5     # bm25 backend
```

Same query (`"What does Islam say about patience?"`, Shia), top-5 IDs:

| # | tfidf | bm25 |
|---|---|---|
| 1 | `al-kafi_2_47_3` | `al-kafi_2_47_3` |
| 2 | `faqih_3-1_86_4043` | `faqih_2_23_1776` |
| 3 | `al-kafi_2_47_23` | `al-kafi_2_47_23` |
| 4 | `al-kafi_2_47_4` | `al-kafi_2_47_19` |
| 5 | `al-kafi_8_69_1` | `al-kafi_2_47_4` |

BM25 returns 4/5 results from al-Kafi book 2 ch. 47 vs 3/5, dropping an unrelated book-8 result — tighter topical concentration. This is a single query and demonstrates correctness, not a quality claim; see follow-ups.

**Manual check:** grep server logs for `[RERANK] dense_count=… sparse_count=…` — `sparse_count` should be > 0 on hadith queries after deploy.

---

## Follow-ups (not in this PR)

- **Eval harness** with a golden query set for recall@k across both backends — the actual quality evidence.
- **Retune `DENSE_RESULT_WEIGHT` / `SPARSE_RESULT_WEIGHT`.** Currently 0.8 / 0.2, but those were tuned when sparse contributed nothing. Now that sparse actually counts, they need revisiting.
- **`.env.example`** — document the three new env var names (no values).
- **`main.py` startup warning** when `HADITH_SPARSE_BACKEND=bm25` and encoder file is missing (mirror fiqh's `_warn_if_fiqh_encoder_missing()` in `main.py`, already called at startup today).
- **Unit tests** for encoder dispatch and `_extract_sparse_matches`.
- **Docs refresh** — `documentation/AI_PIPELINE.md` and `PRODUCT_OVERVIEW.md` still describe TF-IDF-only sparse retrieval.
- **Quran/tafsir path is still dense-only** — no sparse retrieval at all. Same treatment would likely help exact ayah references.
