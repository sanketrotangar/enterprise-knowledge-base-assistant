# 05 — Sentence-Transformers: Converting Text to Vectors

> **Why learn this?** This is the "brain" that converts human language into numbers that Qdrant can search. Without embeddings, vector search is impossible. This is what makes our system understand *meaning*, not just keywords.
>
> **Scope of learning:** Loading models, encoding text, choosing models, batch processing. Skip training/fine-tuning, model architecture internals.

---

## What Sentence-Transformers Does

```
Input:  "What is the company's leave policy?"
                │
                ▼
┌───────────────────────────────────────┐
│     Sentence-Transformer Model        │
│                                       │
│  "all-MiniLM-L6-v2"                  │
│                                       │
│  Converts text → 384 numbers          │
│  (embeddings that capture meaning)    │
│                                       │
└───────────────────────────────────────┘
                │
                ▼
Output: [0.023, -0.045, 0.067, 0.012, ...] (384 floats)
```

---

## 1. Installation & Setup

```bash
pip install sentence-transformers
```

### First Run (Downloads Model)

```python
from sentence_transformers import SentenceTransformer

# First time: downloads ~80MB model
model = SentenceTransformer("all-MiniLM-L6-v2")

# Subsequent runs: loads from cache (instant)
```

---

## 2. Basic Usage

### Encode a Single Text

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

# Convert text to vector
text = "What is the company's leave policy?"
embedding = model.encode(text)

print(type(embedding))  # <class 'numpy.ndarray'>
print(embedding.shape)  # (384,)
print(embedding[:5])    # [ 0.023, -0.045, 0.067, 0.012, -0.089]
```

### Encode Multiple Texts (Batch)

```python
texts = [
    "What is the leave policy?",
    "How do I configure VPN?",
    "What is the reimbursement process?",
    "Where is the API documentation?",
]

# Batch encoding — much faster than one-by-one!
embeddings = model.encode(texts)

print(embeddings.shape)  # (4, 384) — 4 texts, 384 dimensions each
```

### Similarity Search

```python
import numpy as np
from sentence_transformers import SentenceTransformer, util

model = SentenceTransformer("all-MiniLM-L6-v2")

# Documents in our knowledge base
documents = [
    "Annual leave: 20 days per year, must be booked 2 weeks in advance",
    "VPN setup: Contact IT support, they will provide credentials",
    "Reimbursement: Submit receipt within 30 days via the finance portal",
    "API docs: Available at docs.company.com/api/v2",
]

# User's query
query = "How many vacation days do I get?"

# Encode everything
doc_embeddings = model.encode(documents)
query_embedding = model.encode(query)

# Compute similarity
similarities = util.cos_sim(query_embedding, doc_embeddings)

print(similarities)
# [[0.72, 0.12, 0.18, 0.08]]
#  ^^^^
#  Highest! The leave policy document is most relevant.

# Get top result
top_idx = similarities.argmax()
print(f"Most relevant: {documents[top_idx]}")
# "Annual leave: 20 days per year, must be booked 2 weeks in advance"
```

---

## 3. Converting to Qdrant Format

```python
import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

# Our chunks
chunks = [
    "The leave policy states that employees are entitled to 20 days of annual leave.",
    "VPN access must be requested through the IT portal. Credentials are valid for 90 days.",
    "Reimbursement claims must include original receipts and be submitted within 30 days.",
]

# Generate embeddings
embeddings = model.encode(chunks)

# Convert to list of lists (Qdrant format)
embedding_lists = embeddings.tolist()

# Now we can store in Qdrant
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

client = QdrantClient(url="http://localhost:6333")

points = [
    PointStruct(
        id=f"chunk-{i}",
        vector=embedding_lists[i],
        payload={"content": chunks[i]}
    )
    for i in range(len(chunks))
]

client.upsert(collection_name="enterprise_embeddings", points=points)
```

---

## 4. Choosing a Model

### Model Comparison

```
┌─────────────────────────┬────────┬──────────┬──────────────────┐
│ Model                   │ Dims   │ Size     │ Speed (1K texts) │
├─────────────────────────┼────────┼──────────┼──────────────────┤
│ all-MiniLM-L6-v2        │ 384    │ 80 MB    │ ~2 sec           │ ← Our choice
│ all-mpnet-base-v2       │ 768    │ 420 MB   │ ~5 sec           │
│ all-MiniLM-L12-v2       │ 384    │ 130 MB   │ ~3 sec           │
│ paraphrase-MiniLM-L6-v2 │ 384    │ 80 MB    │ ~2 sec           │
└─────────────────────────┴────────┴──────────┴──────────────────┘
```

### Why We Chose all-MiniLM-L6-v2

```
✅ Fast (384 dims = less memory, faster search)
✅ Good quality (trained on large corpus)
✅ Small model (80MB, loads quickly)
✅ CPU-friendly (no GPU needed)
✅ Widely used (battle-tested)

❌ Not the highest quality (mpnet is better)
❌ English only (no multilingual support)
```

---

## 5. Text Chunking Before Embedding

### Why Chunk?

```
❌ DON'T: Embed entire document
┌─────────────────────────────────────┐
│  Leave Policy (5 pages)             │
│                                     │
│  Page 1: Introduction...            │  → ONE vector for everything
│  Page 2: Eligibility...             │     (too vague, loses detail)
│  Page 3: Application process...     │
│  Page 4: Carry-over rules...        │
│  Page 5: FAQ...                     │
└─────────────────────────────────────┘

✅ DO: Chunk then embed
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Chunk 1     │  │  Chunk 2     │  │  Chunk 3     │
│  (512 tokens)│  │  (512 tokens)│  │  (512 tokens)│
│  + overlap   │  │  + overlap   │  │  + overlap   │
└──────────────┘  └──────────────┘  └──────────────┘
       │                │                │
       ▼                ▼                ▼
  Vector 1          Vector 2          Vector 3
  (specific)        (specific)        (specific)
```

### Chunking Implementation

```python
def chunk_text(text: str, chunk_size: int = 512, overlap: int = 50) -> list[str]:
    """
    Split text into overlapping chunks.

    Args:
        text: Full document text
        chunk_size: Max tokens per chunk
        overlap: Tokens to overlap between chunks
    """
    words = text.split()
    chunks = []

    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)

    return chunks

# Example
text = "The leave policy..." * 1000  # Long document
chunks = chunk_text(text, chunk_size=512, overlap=50)

print(f"Document: {len(text.split())} words")
print(f"Chunks: {len(chunks)}")
# Document: 1000 words
# Chunks: 3
```

---

## 6. Complete Embedding Service

```python
# app/services/embedder.py

from sentence_transformers import SentenceTransformer
import asyncio
from typing import List

class EmbeddingService:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    @property
    def model(self) -> SentenceTransformer:
        """Lazy load model on first use."""
        if self._model is None:
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed_sync(self, texts: List[str]) -> List[List[float]]:
        """Synchronous embedding (CPU-bound)."""
        embeddings = self.model.encode(
            texts,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embeddings.tolist()

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Async wrapper — runs in thread pool to not block event loop."""
        return await asyncio.to_thread(self.embed_sync, texts)

    async def embed_single(self, text: str) -> List[float]:
        """Embed a single text."""
        results = await self.embed([text])
        return results[0]

# Singleton instance
embedding_service = EmbeddingService()
```

### Usage in Pipeline

```python
# In the document processing pipeline
from app.services.embedder import embedding_service

async def process_document(doc_id: str, chunks: List[str]):
    # Generate embeddings for all chunks
    embeddings = await embedding_service.embed(chunks)

    # Store in Qdrant
    await qdrant_service.store_chunks(
        doc_id=doc_id,
        chunks=chunks,
        embeddings=embeddings,
    )
```

---

## 7. Performance Considerations

### Batch Size Matters

```python
# ❌ Slow: One at a time
for text in texts:
    embedding = model.encode([text])  # 1000 calls

# ✅ Fast: Batch
embeddings = model.encode(texts, batch_size=32)  # 32 calls
```

### CPU vs GPU

```python
# CPU (default) — fine for <10K texts
model = SentenceTransformer("all-MiniLM-L6-v2")
embeddings = model.encode(texts)

# GPU — needed for >10K texts or real-time
import torch
device = "cuda" if torch.cuda.is_available() else "cpu"
model = SentenceTransformer("all-MiniLM-L6-v2", device=device)
embeddings = model.encode(texts)
```

### Memory Usage

```python
# 1000 chunks × 384 dimensions × 4 bytes (float32) = 1.5 MB
# 100K chunks = 150 MB — manageable

# Monitor during batch processing
import psutil
process = psutil.Process()
print(f"Memory: {process.memory_info().rss / 1024 / 1024:.1f} MB")
```

---

## Visual Summary

```
┌─────────────────────────────────────────────────────────────┐
│              SENTENCE-TRANSFORMERS PIPELINE                  │
│                                                             │
│  Input Text                                                 │
│  "The leave policy states that employees                    │
│   are entitled to 20 days of annual leave."                 │
│                                                             │
│              │                                              │
│              ▼                                              │
│  ┌─────────────────────────────────────────┐               │
│  │  Tokenizer                              │               │
│  │  ["the", "leave", "policy", "states",   │               │
│  │   "that", "employees", "are", ...]      │               │
│  └─────────────────────────────────────────┘               │
│              │                                              │
│              ▼                                              │
│  ┌─────────────────────────────────────────┐               │
│  │  Transformer Model (6 layers)           │               │
│  │                                         │               │
│  │  Input: [CLS] the leave policy ... [SEP]│               │
│  │  Output: 384-dimensional vector         │               │
│  │                                         │               │
│  │  [0.023, -0.045, 0.067, 0.012, ...]    │               │
│  └─────────────────────────────────────────┘               │
│              │                                              │
│              ▼                                              │
│  Embedding Vector (384 floats)                              │
│  Ready to store in Qdrant!                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Try It Yourself

### Exercise 1: Basic Embedding
1. Load the all-MiniLM-L6-v2 model
2. Encode these 3 texts:
   - "How do I reset my password?"
   - "What is the vacation policy?"
   - "How to submit an expense report?"
3. Print the shape of the result

### Exercise 2: Similarity
1. Take the 3 texts above
2. Encode them
3. Compute pairwise similarity between all pairs
4. Which two texts are most similar?

### Exercise 3: Query Search
1. Create 5 fake document chunks about company policies
2. Embed all chunks
3. Embed the query "How many days off can I take?"
4. Find the most similar chunk

---

## Common Pitfalls

| Mistake | Why It's Bad | Fix |
|---------|-------------|-----|
| Loading model in request handler | Slow! Model loads every request | Load once, reuse (singleton) |
| Not batching | 1000 individual calls = slow | Use `model.encode(texts)` with list |
| Embedding entire documents | Too vague, loses specificity | Chunk first, then embed |
| Wrong model for language | Bad embeddings for non-English | Use multilingual model if needed |
| Ignoring dimension mismatch | Qdrant rejects vectors | Match model dims to collection config |

---

*Continue to [06-hybrid-search.md](06-hybrid-search.md) →*
