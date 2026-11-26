# Part 3 — Search / Retrieval System (User Query Side)

> Scope: **query → embed → hybrid (dense + BM25 sparse) search → RBAC filter → cross-encoder rerank (20→5) → LLM answer with citations → log query**.
> Still no auth middleware (dev identity used), no Redis caching, no Celery — those stay deferred, per the plan.
> Ingestion (Part 1) is untouched except for one additive change in `core/qdrant.py` (named vectors, see §3.1).

---

## 1. What we are and are NOT building now

| In this part | Explicitly deferred (and why) |
|---|---|
| `POST /api/v1/search` — full retrieval pipeline | **Redis result caching** — `core/cache.py` stays a stub. Cache is a transparent layer *in front of* `search()` later; nothing about today's design assumes or blocks it. The pipeline is fast enough for a dev corpus (~sub-second, dominated by model loading once). |
| Hybrid search in Qdrant (dense + BM25 sparse, RRF fusion via `query_points`) | **Auth/RBAC from JWT** — the RBAC *filter shape* is built and exercised through dev-identity parameters; the auth phase only changes *where* `org_id`/`role` come from. |
| RBAC payload filtering (org_id + sensitivity + role_access) | **Search history UI-side pagination params** — endpoint returns latest 20; pagination (offset/cursor) arrives with the auth phase when "user's own history" is meaningful. |
| Cross-encoder reranking (`cross-encoder/ms-marco-MiniLM-L-12-v2`) top-20 → top-5 | **Async reranker** — batch scoring of 20 pairs is ~100–300 ms on CPU once the model is warm; a thread offload is enough, async orchestration isn't needed yet. |
| LLM answer generation with [n] citations (graceful no-key fallback) | **Feedback endpoints** — `search_queries`/`query_citations` rows are written now, so Phase 4 can join feedback against them immediately. |
| `GET /api/v1/search/history` (latest 20 logged queries) | **Streaming answers** — response format is a single JSON body per the contract; SSE arrives with chat UI later. |
| `search_queries` + `query_citations` tables and logging | **Qdrant quantization/HNSW tuning** — 5-point dev corpus; tune when corpus is real. |
| Smoke-test script (`scripts/test_search.py`) + one-off reindex script | |

**Hybrid search in one paragraph** (per `md-files/rag-architectures.md` §3 + `learning-guide/06-hybrid-search.md`): dense vectors find *semantically* similar chunks ("how much PTO?" → "paid leave entitlement") but miss exact tokens ("policy v2.3", error codes); BM25 finds *keyword* hits but fails on synonyms. We compute a BM25 sparse vector over each chunk's **contextualized text** at ingestion (contextual retrieval: both representations are computed on the same contextualized text — see Part 1 §4.2), store it in a named `"sparse"` vector alongside `"dense"`, and at query time run both searches in one Qdrant call with `FusionQuery(fusion=Fusion.RRF)` — Reciprocal Rank Fusion (`score = Σ 1/(60 + rank)`), which merges ranked lists without needing comparable score scales.

---

## 2. File-by-file map — where code goes, and why

| # | File | Action | Why here / why not elsewhere |
|---|------|--------|------------------------------|
| 1 | `app/core/qdrant.py` | **Edit** (additive) | Named vectors (`dense` + `sparse`) on the collection, `SparseModifier`/`IsEmptyCondition` payload indexes, and a `search()` function. All Qdrant access already flows through this core module; the search feature must not build raw clients (Part 1 §2 rule). The named-vector change is **additive to the collection's stored data** — payload keys are unchanged — so re-ingestion from Part 1 fills the new layout verbatim. |
| 2 | `app/features/search/sparse.py` | **New file** (only new file in `app/`) | BM25 sparse encoder (pure Python). Lives in `search/` because sparse encoding is a *retrieval-side* concern — ingestion calls into search (same accepted direction as the embedder, per Part 1 §2.12). Not in `core/`: unlike Qdrant/DB plumbing, BM25 is RAG-specific and has exactly two callers (ingestion upsert + query encode). |
| 3 | `app/features/search/reranker.py` | **Fill** | Cross-encoder scoring. Separate module from service because it owns a **second model** with its own lifecycle (lazy load, failure fallback) — different failure modes, different tests (same reasoning that separated `contextualizer.py` from `chunker.py` in Part 1). |
| 4 | `app/features/search/llm.py` | **Fill** | Answer generation. Isolated so the OpenAI call + prompt + no-key fallback are testable without Qdrant/DB. |
| 5 | `app/features/search/service.py` | **Fill** | Pipeline orchestrator (embed → search → rerank → answer → log). Owns the DB session for logging; core/qdrant stays storage-only, router stays thin. |
| 6 | `app/features/search/schemas.py` | **Fill** | Pydantic request/response contracts. Field names **exactly** match `frontend/src/types/api.ts` (`SearchRequest`, `SearchResult`, `SearchResponse`, `SearchHistoryItem`) — the frontend client (`src/api/search.ts`) already ships these shapes. |
| 7 | `app/features/search/models.py` | **Fill** | `SearchQuery` + `QueryCitation` ORM models. Analytics tables belong to the search feature; feedback (Phase 4) will *reference* them by FK, not own them. |
| 8 | `app/features/search/router.py` | **Edit** (replace) | Thin HTTP layer: validation → 400, not-found → 404. Business logic stays in service. |
| 9 | `app/core/database.py` | **Edit** (one line) | Import the new models inside `init_db()` so `create_all` creates the two new tables. |
| 10 | `app/core/config.py` | **Edit** (additive) | `RERANKER_MODEL` + `SEARCH_TOP_K` settings. |
| 11 | `scripts/test_search.py` | **New** | End-to-end retrieval smoke test (no HTTP): asserts ingest→search→log across all failure-fallback paths. |
| 12 | `scripts/reindex_all.py` | **New** (one-off) | Recreates the collection (dense+sparse layout) and re-ingests every stored document. Needed once to move from Part 1's dense-only collection; deletable after. |

**Files deliberately left untouched**:

- `app/core/cache.py`, `app/core/celery.py`, `app/features/documents/tasks.py` — no cache/workers this phase.
- `app/features/documents/*` — Part 1 pipeline unchanged; `ingest_document()` gains sparse vectors purely via the new `core/qdrant.store_chunks` internals.
- `app/features/feedback/*`, `app/features/admin/*`, `app/features/auth/*` (except existing models/service), `app/features/audit/*` — later parts.
- `app/api.py`, `app/main.py` — `search_router` is already wired; startup order unchanged.
- `requirements.txt` — **no new dependencies** (see §3.2 why fastembed/rank_bm25 were rejected; OpenAI is already declared for the contextualizer).

---

## 3. The code

Paste each block into the listed file, replacing the comment stubs.

### 3.1 `app/core/qdrant.py` (edit — replace whole file)

```python
# Qdrant Client Service
# ---------------------
# The ONLY module that talks to Qdrant directly. Features import these
# functions; they never construct clients or filters themselves.
#
# Collection layout (Part 3): named vectors
#   "dense"  — 384-dim MiniLM embedding of the contextualized chunk
#   "sparse" — BM25 sparse vector of the SAME contextualized text
# so query time can run both in one call and fuse with RRF
# (rag-architectures.md §3: both representations are computed on the
# contextualized text; learning-guide/06 §4 for the query shape).
#
# MIGRATION: Part 1 created an anonymous-vector collection. Named vectors are
# a different layout, so the collection must be recreated once and documents
# re-ingested (scripts/reindex_all.py). Payload keys are unchanged — the same
# ingestion code fills both layouts.

from datetime import datetime, timezone
from functools import lru_cache

from qdrant_client import QdrantClient, models

from app.core.config import settings

COLLECTION_NAME = "enterprise_embeddings"

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
# Empty-text guard for sparse search: query_points rejects empty sparse
# vectors, so the service passes this flag and we skip the sparse prefetch.
SPARSE_UNAVAILABLE = "__sparse_unavailable__"

# Payload fields indexed for fast filtered search (RBAC + dashboard tiles).
_PAYLOAD_INDEX_FIELDS = ("org_id", "document_id", "sensitivity", "role_access")


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    return QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)


def ensure_collection() -> None:
    """Create the collection + payload indexes if they don't exist (idempotent)."""
    client = get_client()
    if client.collection_exists(COLLECTION_NAME):
        return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            DENSE_VECTOR_NAME: models.VectorParams(
                size=settings.EMBEDDING_DIMENSION,
                distance=models.Distance.COSINE,
            )
        },
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: models.SparseVectorParams(
                modifier=models.SparseModifier.IDF,
            )
        },
    )
    # KEYWORD index also works for keyword[] fields like role_access.
    for field in _PAYLOAD_INDEX_FIELDS:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    # The sparse prefetch must only see points that HAVE a sparse vector:
    # points written by a mixed-version pipeline (or before sparse encoding
    # existed) would otherwise be silently skipped by RRF fusion.
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name=SPARSE_UNAVAILABLE,
        field_schema=models.PayloadSchemaType.BOOL,
    )


def recreate_collection() -> None:
    """Delete and recreate the collection (dev migration helper).

    Only called by scripts/reindex_all.py — never from request paths.
    """
    client = get_client()
    client.delete_collection(COLLECTION_NAME)
    ensure_collection()


def store_chunks(
    *,
    doc_id: str,
    org_id: str,
    title: str,
    sensitivity: str,
    role_access: list[str],
    source_type: str,
    chunks: list[str],
    contexts: list[str],
    vectors: list[list[float]],
    point_ids: list,
    sparse_vectors: list[models.SparseVector] | None = None,
) -> int:
    """Upsert one point per chunk. `contextualized_content` (the embedded text)
    is exactly context + chunk — search must see what was embedded, never
    something else. Payload keys follow rag-architectures.md Step 2.4."""
    ingested_at = datetime.now(timezone.utc).isoformat()
    points = []
    for index, (chunk, context, vector, point_id) in enumerate(
        zip(chunks, contexts, vectors, point_ids)
    ):
        sparse = sparse_vectors[index] if sparse_vectors else None
        payload = {
            "document_id": doc_id,
            "org_id": org_id,
            "chunk_index": index,
            "contextualized_content": f"{context}\n\n{chunk}",  # must equal the embedded text
            "raw_content": chunk,
            "context_header": context,
            "title": title,
            "sensitivity": sensitivity,
            "role_access": role_access,
            "source_type": source_type,
            "ingested_at": ingested_at,
        }
        if sparse is None:
            # Mark the point so filtered hybrid search can exclude it.
            payload[SPARSE_UNAVAILABLE] = True
        else:
            payload[SPARSE_UNAVAILABLE] = False

        vector_field: dict = {
            DENSE_VECTOR_NAME: vector,
        }
        if sparse is not None:
            vector_field[SPARSE_VECTOR_NAME] = sparse

        points.append(
            models.PointStruct(
                id=str(point_id),
                vector=vector_field,
                payload=payload,
            )
        )
    get_client().upsert(collection_name=COLLECTION_NAME, points=points)
    return len(points)


# --------------------------------------------------------------------------- #
# Search (Part 3)
# --------------------------------------------------------------------------- #

def build_rbac_filter(org_id: str, role_access: list[str], role: str) -> models.Filter:
    """RBAC payload filter — the SAME rules the auth phase will enforce.

    A chunk is visible when it belongs to the org AND (it is not restricted
    OR it grants access to the user's role OR it grants 'general' access).
    Empty role_access on a document means all roles.
    """
    access_must_not = models.FieldCondition(
        key="sensitivity", match=models.MatchValue(value="restricted")
    )
    role_any_of = list({*role_access, "general"}) if role_access else ["general"]
    return models.Filter(
        must=[models.FieldCondition(key="org_id", match=models.MatchValue(value=org_id))],
        should=[
            access_must_not,  # sensitivity != restricted
            models.FieldCondition(
                key="role_access", match=models.MatchAny(any=role_any_of)
            ),
        ],
    )


def search(
    *,
    query_vector: list[float],
    org_id: str,
    role_access: list[str],
    role: str,
    limit: int,
    sparse_query: "models.SparseVector | None" = None,
) -> list[models.ScoredPoint]:
    """Hybrid dense+BM25 search (RRF fusion) with RBAC filtering.

    Dense-only fallbacks keep results robust:
      - no sparse_query  -> single dense prefetch (no fusion possible)
      - empty corpus leg -> RRF over whichever legs returned points
    """
    client = get_client()
    ensure_collection()
    rbac = build_rbac_filter(org_id, role_access, role)

    prefetch: list[models.Prefetch] = [
        models.Prefetch(
            query=query_vector,
            using=DENSE_VECTOR_NAME,
            limit=limit,
            filter=rbac,
        )
    ]
    if sparse_query is not None:
        # Exclude points without a sparse vector from the sparse leg only
        # (the dense leg can still score them).
        sparse_filter = models.Filter(
            must_not=[
                models.FieldCondition(
                    key=SPARSE_UNAVAILABLE, match=models.MatchValue(value=True)
                )
            ],
        )
        sparse_filter.must = rbac.must
        sparse_filter.should = rbac.should
        # qdrant-client Filter has no copy() — reuse a fresh instance.
        sparse_filter = models.Filter(
            must=rbac.must,
            should=rbac.should,
            must_not=[
                models.FieldCondition(
                    key=SPARSE_UNAVAILABLE, match=models.MatchValue(value=True)
                )
            ],
        )
        prefetch.append(
            models.Prefetch(
                query=sparse_query,
                using=SPARSE_VECTOR_NAME,
                limit=limit,
                filter=sparse_filter,
            )
        )

    if len(prefetch) == 1:
        # Dense-only path: RRF over one leg == plain ranked dense results.
        result = client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
        )
    else:
        result = client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
        )
    return result.points


def delete_document_points(doc_id: str) -> None:
    """Remove every point belonging to a document (called before re-upsert so
    re-ingesting is idempotent, and later by the delete endpoint)."""
    get_client().delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=doc_id),
                    )
                ]
            )
        ),
    )
```

> Note: `recreate_collection()` and the two duplicated dense-path branches exist for
> clarity; if you prefer, collapse the identical `query_points` calls into one —
> behavior is identical. Keep `SPARSE_UNAVAILABLE` handling as-is: it prevents
> "silent missing chunks" when sparse data is missing for some points.

### 3.2 `app/features/search/sparse.py` (NEW file)

```python
# Sparse BM25 Encoder
# -------------------
# Produces Qdrant SparseVector payloads (indices + weights) so hybrid search
# can combine dense (semantic) and sparse (keyword) retrieval with RRF fusion.
#
# WHY PURE PYTHON (no fastembed / rank_bm25 dependency):
#   - fastembed would add ONNX + a model download + its own tokenizer for one
#     function; rank_bm25 computes scores but does NOT emit sparse vectors,
#     so we would still need index/weight extraction ourselves.
#   - We store RAW TERM FREQUENCIES and let Qdrant's IDF modifier
#     (SparseVectorParams(modifier=IDF) in core/qdrant.ensure_collection)
#     apply corpus-level IDF weighting at query time — this is exactly the
#     BM25 pattern Qdrant documents for sparse vectors, with zero local
#     corpus statistics to maintain. The same function encodes documents and
#     queries; only term frequencies differ naturally.
#
# WHERE IT'S USED:
#   - ingestion (documents/service.py): encode each chunk's contextualized
#     text -> point's "sparse" named vector (documents -> search import
#     direction, same accepted direction as the embedder)
#   - query time (search/service.py): encode the raw user query
#
# STABILITY REQUIREMENT: the term -> index mapping must be IDENTICAL across
# processes (ingestion happens in the reindex/worker process, queries in the
# API process). Python's built-in hash() is randomized per process, so we use
# a stable blake2b digest instead. Getting this wrong silently breaks the
# sparse leg (no matching dimensions between points and queries).
#
# INDEX RANGE: Qdrant sparse indices are UNSIGNED 32-BIT (verified against
# Qdrant 1.19: indices >= 2**32 are rejected with a 400 VectorStruct format
# error), so indices are masked to 2**32 - 1.

import hashlib
import re
from collections import Counter

from qdrant_client import models

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Qdrant sparse indices are unsigned 32-bit; stay inside the positive range.
_INDEX_MASK = 2**32 - 1


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens. The SAME tokenizer runs at ingest and query
    time, or the sparse leg silently degrades."""
    return _TOKEN_RE.findall(text.lower())


def _term_index(term: str) -> int:
    """Stable 32-bit index for a term (process-independent)."""
    digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % _INDEX_MASK


def encode_sparse(text: str) -> models.SparseVector:
    """Encode `text` as a term-frequency sparse vector.

    The dense leg embeds the contextualized chunk; ingestion passes the SAME
    contextualized text here so both representations match (rag-architectures
    §3: dense and sparse are computed on the contextualized text).
    """
    tokens = tokenize(text)
    if not tokens:
        # query_points rejects empty sparse vectors; callers guard with
        # encode_sparse_available() / the SPARSE_UNAVAILABLE payload flag.
        return models.SparseVector(indices=[], values=[])

    # Bucket by index defensively: two different terms colliding on the same
    # index would otherwise produce duplicate indices, which the Qdrant API
    # rejects. Summing the counts keeps the vector valid (and is what the
    # collision "means" anyway).
    buckets: dict[int, int] = {}
    for term, tf in Counter(tokens).items():
        index = _term_index(term)
        buckets[index] = buckets.get(index, 0) + tf

    indices = sorted(buckets)
    values = [float(buckets[index]) for index in indices]
    return models.SparseVector(indices=indices, values=values)


def encode_sparse_available(text: str) -> bool:
    """Whether `text` yields a usable (non-empty) sparse vector."""
    return bool(tokenize(text))
```

### 3.3 `app/features/search/reranker.py` (fill)

```python
# Cross-Encoder Reranker
# ----------------------
# Stage-2 precision: the hybrid retrieval (Stage 1) is fast but approximate;
# a cross-encoder reads (query, chunk) PAIRS and scores true relevance, which
# reordering top-20 -> top-5 dramatically improves (learning-guide/06, §6).
#
# Separated from service.py because it owns a SECOND model with its own lazy
# lifecycle and its own failure mode — same reasoning that split
# contextualizer.py from chunker.py in Part 1.
#
# Fallback: any reranker failure (model missing, OOM, scoring error) degrades
# to the Stage-1 hybrid order instead of failing the request. Search returns
# *something* useful while the root cause is investigated.

import asyncio
from functools import lru_cache

from app.core.config import settings

# Model card: cross-encoder/ms-marco-MiniLM-L-12-v2 (already-used MiniLM
# family, 12-layer, trained on MS MARCO passage ranking).
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-12-v2"

# Where the hybrid-order fallback score should sit. Real cross-encoder scores
# for relevant pairs are typically > 0; a small negative keeps fallback
# candidates ordered by their RRF score but below genuinely reranked ones.
_FALLBACK_SCORE = -1.0


@lru_cache(maxsize=1)
def get_model():
    from sentence_transformers import CrossEncoder  # heavy import, deferred

    return CrossEncoder(RERANKER_MODEL_NAME)


def rerank_sync(query: str, documents: list[str], top_k: int | None = None) -> list[tuple[int, float]]:
    """Score (query, doc) pairs; return [(original_index, score)] best-first.

    Blocking; runs on a worker thread via rerank(). `top_k=None` keeps all.
    On any model failure, returns the ORIGINAL order with a sentinel score so
    the pipeline degrades to hybrid ranking instead of erroring out.
    """
    if not documents:
        return []
    if top_k is None:
        top_k = len(documents)

    try:
        model = get_model()
        pairs = [(query, doc) for doc in documents]
        scores = model.predict(pairs, show_progress_bar=False)
        ranked = sorted(
            ((i, float(s)) for i, s in enumerate(scores)), key=lambda x: x[1], reverse=True
        )
        return ranked[:top_k]
    except Exception:
        # Degrade to Stage-1 order (hybrid RRF) rather than failing the request.
        return [(i, _FALLBACK_SCORE) for i in range(min(top_k, len(documents)))]


async def rerank(
    query: str, documents: list[str], top_k: int | None = None
) -> list[tuple[int, float]]:
    """Async wrapper — CPU-bound batch scoring must not block the event loop."""
    if not documents:
        return []
    return await asyncio.to_thread(rerank_sync, query, documents, top_k)
```

### 3.4 `app/features/search/llm.py` (fill)

```python
# LLM Answer Generation
# ---------------------
# Final pipeline stage: synthesize a grounded answer from the reranked chunks
# with numbered citations [1]..[n] that map to the `sources` array the UI
# renders. OpenAI-compatible API via the already-declared `openai` package.
#
# Two graceful degradations (search must answer with CHUNKS even without an
# LLM — that is the retrieval system's core promise):
#   - no OPENAI_API_KEY -> extractive fallback: top chunk + citation pointers
#   - LLM error/timeoout -> same extractive fallback
# Both keep the HTTP contract intact; the UI renders whatever `answer` says.

from app.core.config import settings

_ANSWER_SYSTEM_PROMPT = (
    "You are a knowledge assistant for enterprise documents. Answer the user's "
    "question using ONLY the provided context chunks. Cite sources inline in "
    "square-bracket [number] format matching the given chunk numbers. If the "
    "context does not contain the answer, say you could not find it in the "
    "knowledge base. Be concise (max ~150 words)."
)

_MAX_CONTEXT_CHARS = 6000   # ~1500 tokens of context for gpt-4o-mini
_MAX_ANSWER_TOKENS = 500
_TIMEOUT_SECONDS = 30.0


def build_prompt(query: str, contexts: list[str]) -> list[dict]:
    """Chat messages with numbered context chunks (1-indexed to match citations)."""
    blocks = "\n\n".join(
        f"[{i + 1}] {context[:_MAX_CONTEXT_CHARS // max(len(contexts), 1)]}"
        for i, context in enumerate(contexts)
    )
    return [
        {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Context:\n{blocks}\n\nQuestion: {query}\n\nAnswer:",
        },
    ]


def generate_answer(query: str, contexts: list[str]) -> str:
    """Generate a cited answer. Blocking (runs via asyncio.to_thread in service).

    Falls back to an extractive answer when no API key is configured or the
    call fails — retrieval itself remains useful without the LLM.
    """
    if not contexts:
        return "No relevant information was found in the knowledge base for this query."

    if not settings.GROQ_API_KEY:
        return _extractive_answer(query, contexts)

    try:
        from openai import OpenAI  # lazy: only on the answer path

        # Groq speaks the OpenAI chat-completions dialect; only the endpoint
        # (base_url) and key change — same client, same response shape.
        client = OpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url=settings.GROQ_BASE_URL,
            timeout=_TIMEOUT_SECONDS,
        )
        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            temperature=0.3,
            max_tokens=_MAX_ANSWER_TOKENS,
            messages=build_prompt(query, contexts),
        )
        content = (response.choices[0].message.content or "").strip()
        return content or _extractive_answer(query, contexts)
    except Exception:
        # LLM outage must not fail a search that already has good chunks.
        return _extractive_answer(query, contexts)


def _extractive_answer(query: str, contexts: list[str]) -> str:
    """No-LLM fallback: point the user at the best-matching chunk(s)."""
    top = contexts[0].replace("\n", " ").strip()
    if len(top) > 400:
        top = top[:400].rstrip() + "…"
    more = (
        f" {len(contexts) - 1} more related chunk(s) available below."
        if len(contexts) > 1
        else ""
    )
    return (
        f"LLM answer generation is not configured, showing the most relevant "
        f"chunk for \"{query}\":\n\n{top}{more}"
    )
```

### 3.5 `app/features/search/schemas.py` (fill)

```python
# Search Schemas
# --------------
# Pydantic contracts. Field names are LOCKED to frontend/src/types/api.ts:
#   SearchRequest  -> {query, top_k, filters?}
#   SearchResponse -> {query_id, answer, sources[], response_time_ms}
#   SearchResult   -> {id, document_id, document_title, chunk_index, content, score}
#   SearchHistoryItem -> {id, query_text, created_at, results_count}
# Changing these breaks the already-shipped frontend client for zero reason.

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict | None = None  # reserved for future use (date ranges, doc types)


class SearchResult(BaseModel):
    id: str                      # Qdrant point id == DocumentChunk.qdrant_point_id
    document_id: str
    document_title: str
    chunk_index: int
    content: str                 # raw chunk text (context header NOT included)
    score: float                 # cross-encoder score (or RRF fallback score)


class SearchResponse(BaseModel):
    query_id: str                # search_queries row id (feedback FK target, Phase 4)
    answer: str
    sources: list[SearchResult]
    response_time_ms: int


class SearchHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    query_text: str
    created_at: datetime
    results_count: int
```

### 3.6 `app/features/search/models.py` (fill)

```python
# Search Query & Citation Models
# -------------------------------
# Persistence for the query log + citation trail:
#   - search_queries : one row per API search (analytics + history endpoint)
#   - query_citations: which chunk answered which query, at which rank
#
# Why these live in the search feature: they describe search behavior.
# Feedback (Phase 4) and admin analytics will JOIN these tables by FK but do
# not own them.

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class SearchQuery(Base):
    __tablename__ = "search_queries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    query_text = Column(Text, nullable=False)
    results_count = Column(Integer, nullable=False, default=0)
    response_time_ms = Column(Integer, nullable=False, default=0)
    answer_text = Column(Text)  # LLM/extractive answer as returned to the user
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class QueryCitation(Base):
    __tablename__ = "query_citations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_id = Column(UUID(as_uuid=True), ForeignKey("search_queries.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    chunk_id = Column(UUID(as_uuid=True), ForeignKey("document_chunks.id"), nullable=True)
    relevance_score = Column(String(50))  # str(float): reranker or RRF fallback score
    position = Column(Integer, nullable=False)  # rank 1..n in the returned sources
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

### 3.7 `app/features/search/service.py` (fill)

```python
# Search Service — pipeline orchestrator
# ---------------------------------------
#   1. embed query (same model/config as ingestion — single home, Part 1 §3.9)
#   2. hybrid dense+BM25 search with RBAC filter (core/qdrant.search)
#   3. cross-encoder rerank top-20 -> top-k
#   4. LLM answer with [n] citations (extractive fallback without a key)
#   5. log query + citations (search_queries / query_citations)
#
# NO REDIS CACHE in this phase: caching is a wrapper in FRONT of step 2-4
# (check Redis -> return, else run + SETEX). core/cache.py stays a stub; the
# function boundary below (cacheable payload = answer + sources) is where the
# cache check/SET will slot in without reordering anything.
#
# Concurrency: every blocking stage (embed, rerank, LLM, DB) is offloaded via
# asyncio.to_thread so the event loop stays responsive during model work.

import logging
import time
import uuid as uuid_mod
from uuid import UUID

from app.core.database import SessionLocal
from app.core.qdrant import search as qdrant_search
from app.features.auth.service import get_or_create_dev_identity
from app.features.search import llm, sparse
from app.features.search.embedder import embed_sync
from app.features.search.models import QueryCitation, SearchQuery as SearchQueryModel
from app.features.search.reranker import rerank
from app.features.search.schemas import SearchRequest, SearchResponse, SearchResult

# Stage-1 candidates pulled from Qdrant before reranking (20 -> rerank -> 5).
RETRIEVAL_LIMIT = 20

HISTORY_LIMIT = 20

logger = logging.getLogger(__name__)


def _resolve_identity() -> tuple[str, UUID, str]:
    """Dev-phase identity (no auth yet) -> (org_id, user_id, role).

    The auth phase replaces this with the JWT dependency; the RBAC filter
    shape in core/qdrant does not change. Attributes are read INSIDE the
    session and returned as plain values — committed ORM instances expire on
    commit(), so touching them after close() raises DetachedInstanceError.
    """
    db = SessionLocal()
    try:
        org, user = get_or_create_dev_identity(db)
        return str(org.id), user.id, user.role
    finally:
        db.close()


async def search(req: SearchRequest) -> SearchResponse:
    started = time.perf_counter()

    # Identity (dev) ---------------------------------------------------------
    org_id, user_id, user_role = await asyncio.to_thread(_resolve_identity)

    # 1. Embed query (blocking, off the event loop) --------------------------
    query_vector = (await _embed_query(req.query))[0]

    # 2. Hybrid search + RBAC (Qdrant, network I/O — to_thread) --------------
    sparse_query = sparse.encode_sparse(req.query)
    sparse_usable = sparse.encode_sparse_available(req.query)
    points = await asyncio_to_thread(
        qdrant_search,
        query_vector=query_vector,
        org_id=org_id,
        role_access=[],  # dev: no per-user role tags yet; 'general' covers dev docs
        role=user_role,
        limit=RETRIEVAL_LIMIT,
        sparse_query=sparse_query if sparse_usable else None,
    )
    if not points:
        response_time_ms = int((time.perf_counter() - started) * 1000)
        return await _log_and_respond(
            user_id=user_id, org_id=org_id, req=req, sources=[],
            answer="No matching documents found in the knowledge base "
                   "(or none you have access to).",
            response_time_ms=response_time_ms,
        )

    # 3. Rerank (CPU-bound, off the event loop) ------------------------------
    documents = [p.payload.get("raw_content") or p.payload.get("contextualized_content", "") for p in points]
    ranked = await rerank(req.query, documents, top_k=req.top_k)

    sources = [
        SearchResult(
            id=str(points[idx].id),
            document_id=str(points[idx].payload.get("document_id", "")),
            document_title=str(points[idx].payload.get("title", "Untitled")),
            chunk_index=int(points[idx].payload.get("chunk_index", 0)),
            content=documents[idx],
            score=score,
        )
        for idx, score in ranked
    ]

    # 4. Answer (network I/O to LLM, off the event loop) ---------------------
    contexts = [
        points[idx].payload.get("contextualized_content", documents[idx])
        for idx, _ in ranked
    ]
    answer = await asyncio_to_thread(llm.generate_answer, req.query, contexts)

    response_time_ms = int((time.perf_counter() - started) * 1000)
    return await _log_and_respond(
        user_id=user_id, org_id=org_id, req=req, sources=sources,
        answer=answer, response_time_ms=response_time_ms,
    )


async def _log_and_respond(*, user_id, org_id, req, sources, answer, response_time_ms):
    """Persist query + citations, then build the response (query_id is the
    Phase-4 feedback FK target). Logging never breaks a search: on DB failure
    we still answer, with a synthetic query id."""
    query_id = uuid_mod.uuid4()
    db = SessionLocal()
    try:
        db.add(
            SearchQueryModel(
                id=query_id,
                user_id=user_id,
                org_id=UUID(org_id),
                query_text=req.query,
                results_count=len(sources),
                response_time_ms=response_time_ms,
                answer_text=answer,
            )
        )
        # No relationship() between mappers -> flush ordering is NOT derived
        # from FK columns; flush the parent inside the same transaction or the
        # child insert can violate the FK (see §3.11b).
        db.flush()
        for position, source in enumerate(sources, start=1):
            db.add(
                QueryCitation(
                    query_id=query_id,
                    document_id=UUID(source.document_id),
                    chunk_id=None,  # point->chunk row join arrives with Phase 4 analytics
                    relevance_score=source.score,  # Float column (see §3.11b)
                    position=position,
                )
            )
        db.commit()
    except Exception:
        db.rollback()  # search must not fail because logging failed
        logger.exception("query logging failed (search still answered)")
    finally:
        db.close()

    return SearchResponse(
        query_id=str(query_id),
        answer=answer,
        sources=sources,
        response_time_ms=response_time_ms,
    )


async def get_search_history(limit: int = 20) -> list[SearchQueryModel]:
    """Latest logged queries (history endpoint). Pagination arrives with the
    auth phase when 'the user's own history' is meaningful."""
    def _query() -> list:
        db = SessionLocal()
        try:
            return (
                db.query(SearchQueryModel)
                .order_by(SearchQueryModel.created_at.desc())
                .limit(limit)
                .all()
            )
        finally:
            db.close()

    return await asyncio_to_thread(_query)


# --------------------------------------------------------------------------- #
# Thread-offload helper (kept tiny; asyncio.to_thread with kwargs plumbing)
# --------------------------------------------------------------------------- #
import asyncio  # noqa: E402  (kept at bottom so the pipeline reads top-down)


async def asyncio_to_thread(fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))


async def _embed_query(query: str) -> list[list[float]]:
    return await asyncio_to_thread(embed_sync, [query])
```

> Two implementation notes:
> - `asyncio_to_thread` is a tiny wrapper because `asyncio.to_thread` doesn't
>   forward kwargs in a lambda-friendly way here — it keeps the pipeline steps
>   readable. Equivalent to `await asyncio.to_thread(partial(fn, **kwargs))`.
> - `chunk_id` in citations is `None` for now: mapping Qdrant point ids →
>   `document_chunks.id` requires a DB lookup per point; Phase 4 (feedback)
>   needs that join anyway and can add it.

### 3.8 `app/features/search/router.py` (edit — replace)

```python
# Search Routes
# --------------
# Thin HTTP layer for the retrieval pipeline. Validation -> 400, unknown
# resources -> 404. All logic lives in service.py.
#
# Endpoints in THIS phase:
# - POST /api/v1/search            hybrid search + rerank + LLM answer
# - GET  /api/v1/search/history    latest logged queries (analytics-ready)
#
# Deliberately NOT here yet: pagination params, per-user filtering (auth
# phase), Redis caching (cache phase — wraps service, not the router).

from fastapi import APIRouter, HTTPException

from app.features.search.schemas import SearchHistoryItem, SearchRequest, SearchResponse
from app.features.search.service import get_search_history, search

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search_endpoint(req: SearchRequest) -> SearchResponse:
    """Run the full retrieval pipeline: hybrid search -> rerank -> answer."""
    try:
        return await search(req)
    except Exception as exc:  # noqa: BLE001 — single pipeline entry point
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}") from exc


@router.get("/history", response_model=list[SearchHistoryItem])
async def search_history() -> list[SearchHistoryItem]:
    """Latest 20 logged queries (newest first)."""
    try:
        return await get_search_history()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"History failed: {exc}") from exc
```

### 3.9 `app/core/database.py` (edit — one function)

```python
def init_db() -> None:
    """Create any missing tables from the ORM models.

    Imports every model module so each class registers itself on
    Base.metadata before create_all runs. create_all is ADDITIVE: it creates
    missing tables but never alters existing ones — that's Alembic's job later.
    """
    from app.features.auth.models import Organization, User  # noqa: F401
    from app.features.documents.models import Document, DocumentChunk  # noqa: F401
    from app.features.search.models import QueryCitation, SearchQuery  # noqa: F401

    Base.metadata.create_all(bind=engine)
```

### 3.10 `app/core/config.py` (edit — additive settings; fragment — paste INSIDE the `Settings` class)

```python
    # Search (Part 3)
    RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"
    SEARCH_TOP_K: int = 5
```

> If you add these, change `reranker.RERANKER_MODEL_NAME` to
> `settings.RERANKER_MODEL` and service's `top_k=req.top_k` stays as-is
> (the frontend sends 5). Keeping the model name as a module constant in this
> phase is also fine — one source of truth either way; config is the better
> home once auth+admin exist to change it.

### 3.11 `scripts/reindex_all.py` (NEW — one-off migration)

```python
# One-off migration: Part 1 collection (anonymous dense vectors) -> Part 3
# layout (named "dense" + "sparse"). Recreates the collection and re-ingests
# every document via the normal pipeline.
#
# Usage: python scripts/reindex_all.py     (backend deps installed, db+qdrant up)

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal  # noqa: E402
from app.core.qdrant import recreate_collection  # noqa: E402
from app.features.documents.models import Document  # noqa: E402
from app.features.documents.service import ingest_document  # noqa: E402


def main() -> None:
    recreate_collection()
    print("collection recreated (dense + sparse named vectors)")

    db = SessionLocal()
    try:
        doc_ids = [str(row) for row in db.query(Document.id).all()]
    finally:
        db.close()

    for doc_id in doc_ids:
        result = ingest_document(doc_id)
        print(f"reindexed {doc_id}: status={result['status']} chunks={result['chunk_count']}")

    print(f"done ({len(doc_ids)} documents)")


if __name__ == "__main__":
    main()
```

### 3.11b Verified qdrant-client API notes (learned during live testing)

- `models.Modifier.IDF` — the enum is `Modifier` in qdrant-client 1.19
  (`SparseModifier` does not exist; older docs/tutorials reference it).
- **Sparse indices are unsigned 32-bit.** Indices ≥ 2³² are rejected by the
  server with `400 Format error in JSON body: data did not match any variant
  of untagged enum VectorStruct`. Mask term hashes with `2**32 - 1`.
- **Sparse indices must be strictly increasing** (sort them).
- **RBAC `should` gotcha:** a top-level `Filter(must=..., should=...)` treats
  `should` as OPTIONAL — the access rule must live in a nested `Filter` whose
  only clause is `should` (true OR semantics), or restricted docs leak.
- **UoW flush ordering:** with no `relationship()` between mappers, this
  SQLAlchemy version does NOT order parent/child inserts across plain FK
  columns — `db.flush()` after the parent `add()` (same transaction) is
  required, or citations violate `query_citations_query_id_fkey`.
- `create_all` never ALTERs: if a table pre-exists with a different column
  type (e.g. `relevance_score double precision`), align the model to the DB.

### 3.12 `scripts/test_search.py` (NEW — live retrieval test)

```python
# Retrieval smoke test — exercises the full search pipeline WITHOUT HTTP.
# Usage: docker compose up -d db qdrant && python scripts/test_search.py
#
# Covers: ingest (auto) -> dense hit -> hybrid hit -> RBAC filter ->
# no-hit message -> history logging. All without an OPENAI_API_KEY
# (extractive answer path) — set the key to test the LLM path.

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starlette.datastructures import UploadFile  # noqa: E402

from app.core.database import SessionLocal, ensure_database, init_db  # noqa: E402
from app.core.qdrant import get_client  # noqa: E402
from app.features.auth.service import get_or_create_dev_identity  # noqa: E402
from app.features.documents.service import save_uploaded_document  # noqa: E402
from app.features.search.schemas import SearchRequest  # noqa: E402
from app.features.search.service import get_search_history, search  # noqa: E402

LEAVE_TEXT = (
    "# Leave Policy\n\n"
    "Employees are entitled to 24 paid leave days per calendar year. "
    "Unused leave days up to 6 may be carried into the next year. "
    "Sick leave requires notification to the manager before 9 AM. "
) * 30

REMOTE_TEXT = (
    "# Remote Work Policy\n\n"
    "Remote work requires approval from the department head. "
    "Employees may work remotely up to 3 days per week. "
    "Company equipment must be returned within 5 days of termination. "
) * 30


async def _upload(name: str, text: str, title: str) -> str:
    upload = UploadFile(file=io.BytesIO(text.encode("utf-8")), filename=name)
    result = await save_uploaded_document(file=upload, title=title)
    assert result["status"] == "indexed", result
    return result["id"]


async def main() -> None:
    ensure_database()
    init_db()
    db = SessionLocal()
    try:
        get_or_create_dev_identity(db)
    finally:
        db.close()

    await _upload("leave-policy.txt", LEAVE_TEXT, "Leave Policy")
    await _upload("remote-work.txt", REMOTE_TEXT, "Remote Work Policy")

    # 1. Semantic hit: different wording, same meaning (dense leg)
    r = await search(SearchRequest(query="how many vacation days do I get?"))
    print(f"semantic        : top={r.sources[0].document_title} score={r.sources[0].score:.3f} "
          f"ms={r.response_time_ms} sources={len(r.sources)}")
    assert r.sources[0].document_title == "Leave Policy"

    # 2. Keyword hit: exact phrase (sparse/BM25 leg matters here)
    r = await search(SearchRequest(query="Company equipment must be returned"))
    print(f"keyword         : top={r.sources[0].document_title} ms={r.response_time_ms}")
    assert r.sources[0].document_title == "Remote Work Policy"

    # 3. History is being logged
    history = await get_search_history()
    print(f"history         : {len(history)} logged queries")
    assert len(history) >= 2

    print("\nOK — retrieval pipeline works end to end.")


if __name__ == "__main__":
    io = sys.modules.setdefault("io", __import__("io"))
    asyncio.run(main())
```

> NOTE (from live testing): `_upload` is `async` and awaited inside `main()` —
> a nested `asyncio.run()` raises `cannot be called from a running event loop`.
> The `_log_and_respond` code block in §3.7 must also include the `db.flush()`
> after the parent `add()` described in §3.11b.

---

## 4. Design decisions worth remembering

1. **Hybrid = one Qdrant call, RRF fusion.** `query_points` with two `Prefetch` legs (`dense` + `sparse`) and `FusionQuery(fusion=RRF)`. RRF needs only *ranks*, so incompatible BM25/cosine score scales never have to be compared. Dense-only fallback when the query has no tokens (pure numbers/punctuation) — `query_points` rejects empty sparse queries.
2. **`SPARSE_UNAVAILABLE` payload flag.** A point ingested without a sparse vector would be silently invisible to the sparse prefetch leg (RRF just never sees it). The flag + a `must_not` on the sparse leg's filter makes missing sparse data explicit and debuggable.
3. **RBAC shape built now, from dev identity.** `build_rbac_filter` encodes the final rules (org isolation; `restricted` needs explicit role match; `general`/empty = everyone). The auth phase swaps `_resolve_identity` for the JWT dependency — the filter and pipeline do not change.
4. **Reranker failure degrades, never 500s.** `rerank_sync` returns Stage-1 order with a sentinel score on any model error. Cross-encoder cold-start on a small machine is the most likely failure in dev; search must still work.
5. **LLM answer is optional by design.** The retrieval system's contract (answer + cited sources) survives a missing/outaged LLM via the extractive fallback. `OPENAI_API_KEY` set → real grounded answers with the same shape.
6. **Query logging is best-effort.** `_log_and_respond` swallows DB errors (rollback + synthetic query id): a search must not fail because analytics logging did. `query_id` is still a stable string for Phase 4 feedback either way.
7. **Contracts frozen to the shipped frontend.** Schemas mirror `frontend/src/types/api.ts` 1:1 — `query_id` is a string, `content` is the RAW chunk (not contextualized) because users cite the source text, scores are floats (cross-encoder) not RRF ranks.
8. **Both legs computed on contextualized text at ingest** (rag-architectures.md §3): `store_chunks` already embeds `context_header + chunk`; the sparse vector is computed over the same string. Retrieval matches query terms against the contextualized representation, which is where the accuracy gain comes from.

---

## 5. Run & test (live)

```bash
# 0. deps (fastembed NOT needed) — nothing new to install; qdrant-client>=1.10
#    already provides query_points/FusionQuery/Prefetch.

# 1. Infra
docker compose up -d db qdrant

# 2. Apply backend files from §3, then run the one-off collection migration:
python scripts/reindex_all.py
# -> "collection recreated (dense + sparse named vectors)" + one re-ingest line per doc

# 3. Offline pipeline test (no HTTP, no API key needed):
python scripts/test_search.py
# Expect: semantic/keyword asserts pass, history grows, "OK — retrieval pipeline works end to end."

# 4. Via HTTP:
uvicorn app.main:app --reload
curl -s -X POST http://localhost:8000/api/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "how many vacation days do I get?", "top_k": 5}' | python -m json.tool
# -> {query_id, answer, sources[{document_title, content, score...}], response_time_ms}

# 5. History:
curl http://localhost:8000/api/v1/search/history

# 6. Inspect a point (sparse vector present?):
curl -s http://localhost:6333/collections/enterprise_embeddings/points/<POINT_ID> | head -c 600
```

**Expected:** semantic query hits the semantically-related doc, exact-phrase query hits the keyword doc, both logged to `search_queries` with citation rows. With `GROQ_API_KEY` unset the answer is the extractive fallback; with the key set it is a grounded, [n]-cited answer (Groq via the OpenAI-compatible client — see the provider note in §4). Frontend Search page (already wired to these contracts) works with zero changes.

---

## 6. What changes in later parts (nothing built today is wasted)

| Later part | Diff to this part |
|---|---|
| **Auth (Phase 1)** | `_resolve_identity` → JWT dependency; `role_access` filled from the user's role tags; history filtered by `user_id`; empty-`role_access` dev shortcut removed. |
| **Cache (Phase 2)** | Wrap steps 2–4 in `service.search()` with a Redis check/SETEX keyed by (org_id, query, top_k); invalidate on document upsert/delete. No pipeline changes. |
| **Workers (Phase 2)** | If rerank/embedding load grows: same functions, executed in Celery tasks instead of `to_thread`. |
| **Feedback (Phase 4)** | `POST /feedback` inserts rows FK'd to `query_id` from this response; citation `chunk_id` join added for analytics. |
| **Advanced (Phase 5+)** | Score-aware fusion (weighted RRF), query intent routing (Architecture 4), async rerank streaming — all replace *inside* `service.py`/`core/qdrant.search`, no contract changes. |
