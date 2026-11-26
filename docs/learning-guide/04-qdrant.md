# 04 — Qdrant: Vector Database for Semantic Search

> **Why learn this?** Qdrant stores document embeddings (numerical vectors) and performs lightning-fast similarity search. This is what makes "understanding" user queries possible — not just matching keywords, but understanding *meaning*.
>
> **Scope of learning:** What vectors are, how to store them, how to search, filtering. Skip distributed deployment, advanced indexing params, and custom scoring.

---

## What Problem Does Qdrant Solve?

### The Keyword Search Problem

```
User searches: "How much paid time off do I get?"

Document contains: "Annual leave entitlement is 20 days"

Keyword search (BM25): ❌ No match! (different words)
Vector search:         ✅ Match! (same meaning)
```

### How Vector Search Works

```
Step 1: Convert text to numbers (embeddings)
─────────────────────────────────────────

"Annual leave entitlement is 20 days"
    ↓ (embedding model)
[0.23, -0.45, 0.67, 0.12, -0.89, ...]  ← 384 numbers

"How much paid time off do I get?"
    ↓ (embedding model)
[0.25, -0.42, 0.71, 0.15, -0.85, ...]  ← Similar numbers!


Step 2: Find similar vectors
─────────────────────────────

Query vector:  [0.25, -0.42, 0.71, 0.15, -0.85, ...]

Compare with all stored vectors:
  Doc 1: [0.23, -0.45, 0.67, 0.12, -0.89, ...] → Similarity: 0.92 ✅
  Doc 2: [0.89, 0.12, -0.34, 0.56, 0.78, ...]  → Similarity: 0.23 ❌
  Doc 3: [0.24, -0.43, 0.69, 0.14, -0.87, ...] → Similarity: 0.95 ✅

Step 3: Return most similar results
───────────────────────────────────

Top 3 results:
  1. Doc 3 (0.95) — "Annual leave policy..."
  2. Doc 1 (0.92) — "Vacation days are..."
  3. Doc 5 (0.78) — "Time off benefits..."
```

---

## 1. Vectors Explained

### What Is a Vector?

A vector is just a list of numbers that represents something:

```python
# A word
"cat" → [0.2, 0.8, -0.1, 0.5, ...]   # 384 numbers

# A sentence
"The quick brown fox jumps over the lazy dog"
→ [0.12, -0.34, 0.56, 0.78, ...]      # 384 numbers

# Similar meanings have similar vectors
"cat"    → [0.2, 0.8, -0.1, 0.5, ...]
"kitten" → [0.21, 0.79, -0.12, 0.51, ...]  # Very close!
"dog"    → [0.5, 0.3, 0.7, -0.2, ...]      # Different
```

### Dimensionality

```python
# Different models produce different vector sizes
all-MiniLM-L6-v2     → 384 dimensions
all-mpnet-base-v2     → 768 dimensions
text-embedding-3-small → 1536 dimensions

# More dimensions = more detail, but more storage/compute
# 384 is a good balance for our use case
```

---

## 2. Qdrant Setup

### Installation

```bash
# Via Docker (recommended)
docker run -p 6333:6333 qdrant/qdrant

# Via pip
pip install qdrant-client
```

### Python Client

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

# Connect to Qdrant
client = QdrantClient(url="http://localhost:6333")

# Create a collection (like a table in PostgreSQL)
client.create_collection(
    collection_name="enterprise_embeddings",
    vectors_config=VectorParams(
        size=384,                    # Vector dimension
        distance=Distance.COSINE,    # How to measure similarity
    ),
)
```

### Distance Metrics

```
COSINE (our choice): Measures angle between vectors
  → Best for text embeddings (magnitude doesn't matter)
  → Range: -1 (opposite) to 1 (identical)

DOT PRODUCT: Measures dot product
  → Good for normalized vectors

EUCLIDEAN: Measures straight-line distance
  → Good for spatial data (not text)
```

---

## 3. Storing Vectors (Upsert)

### Basic Upsert

```python
from qdrant_client.models import PointStruct

# Store a document chunk with its embedding
client.upsert(
    collection_name="enterprise_embeddings",
    points=[
        PointStruct(
            id="chunk-001",                           # Unique ID
            vector=[0.23, -0.45, 0.67, ...],          # The embedding
            payload={                                  # Metadata
                "document_id": "doc-123",
                "content": "The leave policy states that...",
                "org_id": "org-abc",
                "sensitivity": "internal",
                "role_access": ["hr", "engineering"],
                "title": "Leave Policy 2024"
            }
        )
    ]
)
```

### Batch Upsert (Efficient)

```python
from qdrant_client.models import PointStruct
import uuid

# Store many chunks at once
points = []
for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
    points.append(
        PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding.tolist(),
            payload={
                "document_id": str(doc_id),
                "chunk_index": i,
                "content": chunk,
                "org_id": str(org_id),
                "sensitivity": sensitivity,
                "role_access": role_access,
            }
        )
    )

client.upsert(
    collection_name="enterprise_embeddings",
    points=points  # Bulk insert — much faster!
)
```

---

## 4. Searching

### Basic Search

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue

# Search for similar vectors
results = client.search(
    collection_name="enterprise_embeddings",
    query_vector=[0.25, -0.42, 0.71, ...],  # Query embedding
    limit=5,                                   # Top 5 results
)

# Results contain:
for result in results:
    print(result.id)          # "chunk-001"
    print(result.score)       # 0.92 (similarity score)
    print(result.payload)     # All metadata we stored
```

### Search with Filtering (RBAC)

```python
# Only search documents the user can access
results = client.search(
    collection_name="enterprise_embeddings",
    query_vector=query_embedding,
    limit=5,
    query_filter=Filter(
        must=[
            # Must be from user's organization
            FieldCondition(
                key="org_id",
                match=MatchValue(value=str(user_org_id))
            ),
            # Must be accessible to user's role
            FieldCondition(
                key="role_access",
                match=MatchAny(any=user_roles)  # user_roles = ["engineering", "general"]
            )
        ]
    )
)
```

### Filter Types

```python
from qdrant_client.models import (
    Filter, FieldCondition, MatchValue, MatchAny,
    Range, MatchText
)

# Exact match
FieldCondition(key="org_id", match=MatchValue(value="org-123"))

# Match any of several values
FieldCondition(key="role_access", match=MatchAny(any=["hr", "engineering"]))

# Range (for numbers)
FieldCondition(key="chunk_index", range=Range(gte=0, lte=10))

# Text search within payload
FieldCondition(key="content", match=MatchText(text="leave policy"))
```

---

## 5. Payload Indexes — Speed Up Filtering

### Without Index

```python
# ❌ Slow: Must check EVERY vector's payload
# If you have 1M vectors, it checks all 1M payloads
results = client.search(
    collection_name="enterprise_embeddings",
    query_vector=query_embedding,
    query_filter=Filter(must=[
        FieldCondition(key="org_id", match=MatchValue(value="org-123"))
    ])
)
```

### With Index

```python
# ✅ Fast: Index allows direct lookup
client.create_payload_index(
    collection_name="enterprise_embeddings",
    field_name="org_id",
    field_schema="keyword"  # Exact match index
)

client.create_payload_index(
    collection_name="enterprise_embeddings",
    field_name="sensitivity",
    field_schema="keyword"
)

client.create_payload_index(
    collection_name="enterprise_embeddings",
    field_name="role_access",
    field_schema="keyword"
)
```

### Index Types

```
keyword     → Exact match (WHERE org_id = 'abc')
text        → Full-text search (LIKE '%policy%')
integer     → Numeric range (WHERE chunk_index > 5)
float       → Numeric range
bool        → True/False
```

---

## 6. Complete Qdrant Service

### Our Project's Qdrant Client

```python
# app/services/qdrant_client.py

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue, MatchAny
)
import uuid

COLLECTION_NAME = "enterprise_embeddings"
VECTOR_SIZE = 384  # all-MiniLM-L6-v2

class QdrantService:
    def __init__(self, url: str = "http://localhost:6333"):
        self.client = QdrantClient(url=url)

    def ensure_collection(self):
        """Create collection if it doesn't exist."""
        collections = self.client.get_collections().collections
        collection_names = [c.name for c in collections]

        if COLLECTION_NAME not in collection_names:
            self.client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=VECTOR_SIZE,
                    distance=Distance.COSINE,
                ),
            )
            # Create indexes for filtering
            for field in ["org_id", "sensitivity", "role_access"]:
                self.client.create_payload_index(
                    collection_name=COLLECTION_NAME,
                    field_name=field,
                    field_schema="keyword",
                )

    def store_chunks(
        self,
        doc_id: str,
        org_id: str,
        chunks: list[str],
        embeddings: list[list[float]],
        sensitivity: str = "internal",
        role_access: list[str] = None,
    ) -> list[str]:
        """Store document chunks with embeddings."""
        points = []
        point_ids = []

        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            point_id = str(uuid.uuid4())
            point_ids.append(point_id)

            points.append(
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "document_id": doc_id,
                        "chunk_index": i,
                        "content": chunk,
                        "org_id": org_id,
                        "sensitivity": sensitivity,
                        "role_access": role_access or [],
                    }
                )
            )

        self.client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
        )
        return point_ids

    def search(
        self,
        query_embedding: list[float],
        org_id: str,
        user_roles: list[str],
        limit: int = 10,
    ) -> list[dict]:
        """Search with RBAC filtering."""
        results = self.client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            limit=limit,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="org_id",
                        match=MatchValue(value=org_id)
                    ),
                    FieldCondition(
                        key="role_access",
                        match=MatchAny(any=user_roles)
                    )
                ]
            ),
        )

        return [
            {
                "id": r.id,
                "score": r.score,
                "content": r.payload["content"],
                "document_id": r.payload["document_id"],
                "chunk_index": r.payload["chunk_index"],
            }
            for r in results
        ]

    def delete_document(self, doc_id: str):
        """Delete all chunks for a document."""
        self.client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=doc_id)
                    )
                ]
            ),
        )
```

---

## 7. Qdrant REST API

### Useful Endpoints

```bash
# Check if Qdrant is running
curl http://localhost:6333/healthz

# Get collection info
curl http://localhost:6333/collections/enterprise_embeddings

# Count vectors
curl http://localhost:6333/collections/enterprise_embeddings/points/count

# Search via REST
curl -X POST http://localhost:6333/collections/enterprise_embeddings/points/search \
  -H "Content-Type: application/json" \
  -d '{
    "vector": [0.1, 0.2, ...],
    "limit": 5,
    "filter": {
      "must": [
        {"key": "org_id", "match": {"value": "org-123"}}
      ]
    }
  }'
```

---

## Visual Summary

```
┌─────────────────────────────────────────────────────────────┐
│                      QDRANT                                 │
│                                                             │
│  Collection: "enterprise_embeddings"                        │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Point 1                                            │   │
│  │  ID: "chunk-001"                                    │   │
│  │  Vector: [0.23, -0.45, 0.67, ...] (384 numbers)    │   │
│  │  Payload:                                           │   │
│  │    document_id: "doc-123"                           │   │
│  │    content: "The leave policy states..."            │   │
│  │    org_id: "org-abc"                                │   │
│  │    sensitivity: "internal"                          │   │
│  │    role_access: ["hr", "engineering"]               │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Point 2                                            │   │
│  │  ID: "chunk-002"                                    │   │
│  │  Vector: [0.45, -0.12, 0.89, ...]                  │   │
│  │  Payload: { ... }                                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ... thousands more points ...                              │
│                                                             │
│  Indexes:                                                   │
│  - org_id (keyword) — fast org filtering                    │
│  - sensitivity (keyword) — fast access control              │
│  - role_access (keyword) — fast role filtering              │
└─────────────────────────────────────────────────────────────┘
```

---

## Try It Yourself

### Exercise 1: Store and Search
1. Create a Qdrant collection with 384 dimensions
2. Store 5 fake document chunks with embeddings
3. Search for the most similar chunk to a query vector
4. Filter by a payload field

### Exercise 2: RBAC Filtering
1. Store chunks from 2 different organizations
2. Search but only return chunks from org_id = "org-1"
3. Verify you don't see chunks from other orgs

### Exercise 3: Delete
1. Store 10 chunks for document "doc-1"
2. Delete all chunks for "doc-1"
3. Verify search no longer returns those chunks

---

## Common Pitfalls

| Mistake | Why It's Bad | Fix |
|---------|-------------|-----|
| No payload indexes | Filtering is O(n) — slow at scale | Create indexes on filtered fields |
| Storing full documents | Wastes memory, slows search | Store only chunks + metadata |
| Wrong distance metric | Bad search results | Use COSINE for text embeddings |
| Not filtering by org | Data leakage between tenants | Always filter by org_id |
| Large vectors without compression | Memory exhaustion | Use scalar quantization for large scale |

---

*Continue to [05-sentence-transformers.md](05-sentence-transformers.md) →*
