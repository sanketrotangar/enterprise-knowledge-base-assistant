# Qdrant Client Service
# ---------------------
# The ONLY module that talks to Qdrant directly. Features import these
# functions; they never construct clients or filters themselves.
#
# Collection layout (Part 3): named vectors
#   "dense"  — 384-dim MiniLM embedding of the contextualized chunk
#   "sparse" — BM25-style sparse vector of the SAME contextualized text
# so query time runs both legs in ONE call and fuses with RRF
# (rag-architectures.md §3: dense and sparse are computed on the
# contextualized text; learning-guide/06 §4 for the query shape).
#
# MIGRATION: Part 1 created an anonymous-vector collection. Named vectors are
# a different layout, so the collection must be recreated ONCE and documents
# re-ingested (scripts/reindex_all.py). Payload keys are unchanged — the same
# ingestion code fills both layouts.

from datetime import datetime, timezone
from functools import lru_cache

from qdrant_client import QdrantClient, models

from app.core.config import settings

COLLECTION_NAME = "enterprise_embeddings"

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
# Payload flag marking points that LACK a sparse vector. The sparse prefetch
# leg must exclude them: RRF silently skips points a leg never sees, so an
# unflagged mixed corpus would drop chunks from hybrid results without any
# error. Written on EVERY point (True/False) so it can also be filtered on.
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
                # IDF weighting applied by Qdrant at query time over the
                # stored term-frequency vectors (see search/sparse.py).
                # (qdrant-client >=1.10: models.Modifier; older versions
                # exposed the same value as models.SparseModifier.)
                modifier=models.Modifier.IDF,
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
    # BOOL index for the sparse-availability flag (used in must_not filters).
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
    sparse_vectors: "list[models.SparseVector] | None" = None,
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
            "contextualized_content": f"{context}\n\n{chunk}".strip() if context else chunk,
            "raw_content": chunk,
            "context_header": context or "",
            "title": title,
            "sensitivity": sensitivity,
            "role_access": role_access,
            "source_type": source_type,
            "ingested_at": ingested_at,
            SPARSE_UNAVAILABLE: sparse is None,  # see flag docs above
        }

        vector_field: dict = {DENSE_VECTOR_NAME: vector}
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
    Documents with empty role_access are covered by the first branch (any
    non-restricted sensitivity); 'restricted' always needs an explicit grant.

    Qdrant gotcha: a top-level Filter's `should` becomes OPTIONAL once `must`
    is present — the access rule MUST live in a nested Filter whose only
    clause is `should` (= true OR semantics), or restricted documents leak.
    """
    role_any_of = list({*role_access, "general"}) if role_access else ["general"]
    access_clause = models.Filter(
        should=[
            models.Filter(  # sensitivity != restricted
                must_not=[
                    models.FieldCondition(
                        key="sensitivity", match=models.MatchValue(value="restricted")
                    )
                ]
            ),
            models.FieldCondition(
                key="role_access", match=models.MatchAny(any=role_any_of)
            ),
        ]
    )
    return models.Filter(
        must=[
            models.FieldCondition(key="org_id", match=models.MatchValue(value=org_id)),
            access_clause,
        ]
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

    Dense-only fallback when the query yields no sparse vector (query_points
    rejects empty sparse queries — e.g. pure numbers/punctuation).
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
        # Sparse leg sees only points that HAVE a sparse vector (RBAC still
        # applies) — see SPARSE_UNAVAILABLE for why this matters.
        sparse_filter = models.Filter(
            must=rbac.must,
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
