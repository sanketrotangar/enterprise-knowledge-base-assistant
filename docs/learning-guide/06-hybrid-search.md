# 06 — Hybrid Search: BM25 + Vector

> **Why learn this?** Neither keyword search nor vector search alone is perfect. Hybrid search combines both to get the best of both worlds — keyword precision + semantic understanding. This is what makes our search actually useful.
>
> **Scope of learning:** How BM25 works, how vector search works, how to combine them (RRF), practical implementation. Skip advanced scoring algorithms, custom tokenizers.

---

## The Problem with Single-Mode Search

### BM25 (Keyword Search) Alone

```
Query: "How much paid time off do I get?"
Document: "Annual leave entitlement is 20 days per year"

BM25 Result: ❌ LOW SCORE
Reason: No keyword overlap (paid ≠ leave, time ≠ entitlement, off ≠ days)
```

### Vector Search Alone

```
Query: "What is policy-v2.3?"
Document: "Policy version 2.3 states that..."

Vector Result: ⚠️ MEDIUM SCORE
Reason: Semantic similarity is moderate, but misses exact version number
```

### Hybrid Search (Both Combined)

```
Query: "What is policy-v2.3?"
  ├── BM25 finds: "Policy version 2.3 states..." (exact match!)
  └── Vector finds: "Leave policy v2.3..." (semantic match)

Combined: ✅ HIGH SCORE — Gets the exact document
```

---

## 1. BM25 Explained

### What Is BM25?

BM25 is a ranking function that scores documents based on keyword matching. It's been the standard for search engines for 30+ years.

### How It Works (Simplified)

```
Query: "leave policy"

Document 1: "The leave policy states that employees get 20 days"
  - "leave" appears 1 time
  - "policy" appears 1 time
  - Score: 0.85 ✅

Document 2: "VPN configuration guide for remote access"
  - "leave" appears 0 times
  - "policy" appears 0 times
  - Score: 0.02 ❌

Document 3: "Annual leave policy and vacation entitlements"
  - "leave" appears 1 time
  - "policy" appears 1 time
  - Score: 0.82 ✅
```

### Key Factors

```
BM25 considers:
1. Term Frequency (TF):    How often the word appears in the document
2. Inverse Document Freq:  How rare the word is across all documents
3. Document Length:         Normalizes for document size

Rare words (like "reimbursement") score higher than common words (like "the")
```

### BM25 in Qdrant

```python
# Qdrant supports BM25 via sparse vectors
from qdrant_client.models import SparseVector

# Sparse vector: only non-zero values stored
# "leave policy" → {0: 0.8, 5: 0.9}  (word indices + scores)
# Most positions are 0 → sparse!
```

---

## 2. Vector Search Recap

```
Query: "How much paid time off do I get?"
  → Embedding: [0.25, -0.42, 0.71, ...]

Document: "Annual leave entitlement is 20 days"
  → Embedding: [0.23, -0.45, 0.67, ...]

Cosine Similarity: 0.92 ✅ (semantically similar!)
```

---

## 3. Combining Results: Reciprocal Rank Fusion (RRF)

### The Problem

BM25 and Vector search return different ranked lists. How do we combine them?

```
BM25 Results:                    Vector Results:
  1. Doc A (score: 0.85)           1. Doc C (score: 0.92)
  2. Doc C (score: 0.82)           2. Doc A (score: 0.88)
  3. Doc B (score: 0.45)           3. Doc B (score: 0.41)
```

### RRF Formula

```
RRF_score(doc) = 1/(k + rank_bm25) + 1/(k + rank_vector)

where k = 60 (constant, usually 60)
```

### Example Calculation

```
Doc A:
  BM25 rank: 1st → 1/(60+1) = 0.0164
  Vector rank: 2nd → 1/(60+2) = 0.0161
  RRF score: 0.0164 + 0.0161 = 0.0325

Doc C:
  BM25 rank: 2nd → 1/(60+2) = 0.0161
  Vector rank: 1st → 1/(60+1) = 0.0164
  RRF score: 0.0161 + 0.0164 = 0.0325

Doc B:
  BM25 rank: 3rd → 1/(60+3) = 0.0159
  Vector rank: 3rd → 1/(60+3) = 0.0159
  RRF score: 0.0159 + 0.0159 = 0.0318

Final ranking: Doc A = Doc C > Doc B
```

### Why RRF Is Great

```
✅ Parameter-free (no weights to tune)
✅ Works well across different query types
✅ Handles different score scales (BM25: 0-1, Vector: -1 to 1)
✅ Robust to outliers
```

---

## 4. Hybrid Search Implementation

### Using Qdrant's Built-in Hybrid Search

```python
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Prefetch, Query, Fusion, Filter, FieldCondition, MatchValue
)

client = QdrantClient(url="http://localhost:6333")

# Hybrid search with RRF fusion
results = client.query_points(
    collection_name="enterprise_embeddings",
    query=Query(
        fusion=Fusion.RRF  # Reciprocal Rank Fusion
    ),
    prefetch=[
        # Dense vector search
        Prefetch(
            query=query_embedding,  # From sentence-transformers
            using="dense",         # Dense vector field
            limit=20,
        ),
        # Sparse vector search (BM25)
        Prefetch(
            query=sparse_embedding,  # BM25 sparse vector
            using="sparse",          # Sparse vector field
            limit=20,
        ),
    ],
    limit=5,  # Final top 5
    query_filter=Filter(
        must=[
            FieldCondition(key="org_id", match=MatchValue(value=org_id))
        ]
    ),
)
```

### Custom Hybrid Search (More Control)

```python
import numpy as np
from typing import List, Dict

class HybridSearchService:
    def __init__(self, qdrant_client, embedding_service):
        self.qdrant = qdrant_client
        self.embedder = embedding_service

    async def search(
        self,
        query: str,
        org_id: str,
        user_roles: List[str],
        limit: int = 5,
    ) -> List[Dict]:
        # Step 1: Get query embedding
        query_vector = await self.embedder.embed_single(query)

        # Step 2: Vector search (top 20)
        vector_results = self.qdrant.search(
            collection_name="enterprise_embeddings",
            query_vector=query_vector,
            limit=20,
            query_filter=self._build_filter(org_id, user_roles),
        )

        # Step 3: BM25 search (top 20)
        bm25_results = self._bm25_search(query, org_id, user_roles, limit=20)

        # Step 4: Fuse with RRF
        fused_results = self._rrf_fusion(vector_results, bm25_results, k=60)

        # Step 5: Return top N
        return fused_results[:limit]

    def _rrf_fusion(
        self,
        vector_results: List,
        bm25_results: List,
        k: int = 60,
    ) -> List[Dict]:
        """Combine results using Reciprocal Rank Fusion."""
        scores = {}

        # Process vector results
        for rank, result in enumerate(vector_results):
            doc_id = result.id
            rrf_score = 1 / (k + rank + 1)
            scores[doc_id] = {
                "id": doc_id,
                "content": result.payload["content"],
                "vector_rank": rank + 1,
                "bm25_rank": None,
                "rrf_score": rrf_score,
            }

        # Process BM25 results
        for rank, result in enumerate(bm25_results):
            doc_id = result["id"]
            rrf_score = 1 / (k + rank + 1)

            if doc_id in scores:
                scores[doc_id]["bm25_rank"] = rank + 1
                scores[doc_id]["rrf_score"] += rrf_score
            else:
                scores[doc_id] = {
                    "id": doc_id,
                    "content": result["content"],
                    "vector_rank": None,
                    "bm25_rank": rank + 1,
                    "rrf_score": rrf_score,
                }

        # Sort by RRF score (descending)
        sorted_results = sorted(
            scores.values(),
            key=lambda x: x["rrf_score"],
            reverse=True,
        )

        return sorted_results

    def _build_filter(self, org_id: str, user_roles: List[str]):
        """Build Qdrant filter for RBAC."""
        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny
        return Filter(
            must=[
                FieldCondition(key="org_id", match=MatchValue(value=org_id)),
                FieldCondition(key="role_access", match=MatchAny(any=user_roles)),
            ]
        )
```

---

## 5. Complete Search Pipeline

```
User Query: "How much paid time off do I get?"
    │
    ▼
┌─────────────────────────────────────┐
│ 1. Embed Query                      │
│    sentence-transformers            │
│    → [0.25, -0.42, 0.71, ...]       │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ 2. Parallel Search                  │
│                                     │
│  ┌─────────────┐  ┌─────────────┐  │
│  │ Vector Search│  │ BM25 Search │  │
│  │ (semantic)   │  │ (keyword)   │  │
│  │              │  │             │  │
│  │ Top 20 docs  │  │ Top 20 docs │  │
│  └─────────────┘  └─────────────┘  │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ 3. Reciprocal Rank Fusion (RRF)     │
│                                     │
│  Combine rankings, compute scores   │
│  → Top 10 candidates                │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ 4. RBAC Filtering                   │
│                                     │
│  Remove results user can't access   │
│  → Top 8 filtered results           │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ 5. Cross-Encoder Reranking          │
│                                     │
│  Score each candidate with BERT     │
│  → Top 5 final results              │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ 6. LLM Generation                   │
│                                     │
│  Generate answer with citations     │
│  → "According to the leave policy,  │
│     employees get 20 days..."       │
└─────────────────────────────────────┘
```

---

## 6. Cross-Encoder Reranking

### Why Rerank?

```
Initial retrieval (hybrid search):
  - Fast but approximate
  - Might miss the best result
  - Returns top 20

Reranking:
  - Slow but precise
  - Compares query to each document directly
  - Returns top 5 with high precision
```

### Implementation

```python
from sentence_transformers import CrossEncoder

# Load reranker model
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-12-v2")

def rerank(query: str, documents: list[dict], top_k: int = 5) -> list[dict]:
    """
    Rerank documents using cross-encoder.

    Args:
        query: User's search query
        documents: List of documents with 'content' field
        top_k: Number of results to return
    """
    # Create query-document pairs
    pairs = [(query, doc["content"]) for doc in documents]

    # Score each pair
    scores = reranker.predict(pairs)

    # Attach scores and sort
    for i, doc in enumerate(documents):
        doc["rerank_score"] = float(scores[i])

    # Return top k
    return sorted(documents, key=lambda x: x["rerank_score"], reverse=True)[:top_k]

# Example
query = "How much paid time off do I get?"
docs = [
    {"id": "1", "content": "Annual leave: 20 days per year"},
    {"id": "2", "content": "VPN setup guide"},
    {"id": "3", "content": "Vacation policy details"},
]

reranked = rerank(query, docs, top_k=2)
# Returns docs 1 and 3 (most relevant)
```

---

## 7. When to Use What

```
┌─────────────────────────────────────────────────────────────┐
│                    SEARCH STRATEGY GUIDE                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  User Query: "policy-v2.3"                                  │
│  → BM25: ✅ Finds exact match                               │
│  → Vector: ⚠️ Might miss exact version                      │
│  → Hybrid: ✅ Gets it right                                 │
│                                                             │
│  User Query: "How much time off can I take?"                │
│  → BM25: ❌ No keyword overlap                              │
│  → Vector: ✅ Understands "time off" = "leave"              │
│  → Hybrid: ✅ Gets it right                                 │
│                                                             │
│  User Query: "reimbursement receipt deadline"               │
│  → BM25: ✅ Exact keywords                                  │
│  → Vector: ✅ Understands context                           │
│  → Hybrid: ✅ Best of both                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Try It Yourself

### Exercise 1: BM25 vs Vector
1. Create 5 documents about different company policies
2. Search with BM25 only for "paid time off"
3. Search with vector only for "paid time off"
4. Compare results — which is better?

### Exercise 2: RRF Fusion
1. Get BM25 top 5 and Vector top 5 for a query
2. Implement RRF fusion manually
3. Compare fused results to individual results

### Exercise 3: Reranking
1. Get top 10 results from hybrid search
2. Rerank with cross-encoder
3. Did the order change? Which results improved?

---

## Common Pitfalls

| Mistake | Why It's Bad | Fix |
|---------|-------------|-----|
| Using only BM25 | Misses semantic queries | Add vector search |
| Using only Vector | Misses exact terms | Add BM25 |
| Not fusing properly | One search dominates | Use RRF (parameter-free) |
| Reranking too many docs | Slow (cross-encoder is O(n)) | Limit to top 20 before reranking |
| Ignoring RBAC in search | Data leakage | Filter before reranking |

---

*Continue to [07-celery-redis.md](07-celery-redis.md) →*
