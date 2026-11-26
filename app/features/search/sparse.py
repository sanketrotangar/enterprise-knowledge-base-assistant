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
