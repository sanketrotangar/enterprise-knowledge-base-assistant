# Postgres hybrid retrieval on `chunks`
# Vector + tsvector fused with RRF. Access control is RLS only.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.rls import rls_session

VECTOR_LIMIT = 40
KEYWORD_LIMIT = 40
RRF_K = 60
FUSED_LIMIT = 20


@dataclass
class RetrievedHit:
    id: str
    document_id: str
    document_title: str
    chunk_index: int
    content: str
    contextualized_content: str


def _vec_literal(values: list[float]) -> str:
    return "[" + ",".join(str(float(v)) for v in values) + "]"


def _rrf_fuse(ranked_id_lists: list[list[UUID]], k: int = RRF_K) -> list[UUID]:
    scores: dict[UUID, float] = {}
    for ids in ranked_id_lists:
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return [
        chunk_id
        for chunk_id, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]


def _row_to_hit(row: Any) -> RetrievedHit:
    content = str(row.content or "")
    return RetrievedHit(
        id=str(row.id),
        document_id=str(row.document_id),
        document_title=str(row.filename or "Untitled"),
        chunk_index=int(row.chunk_index or 0),
        content=content,
        contextualized_content=content,
    )


def retrieve(
    *,
    query: str,
    query_vector: list[float],
    org_id: UUID,
    role: str,
    user_id: UUID | None = None,
    limit: int = FUSED_LIMIT,
) -> list[RetrievedHit]:
    """Hybrid retrieve inside an RLS session for the JWT org/role."""
    take = max(1, min(int(limit), FUSED_LIMIT))
    with rls_session(org_id=org_id, role=role, user_id=user_id) as db:
        try:
            with db.begin_nested():
                db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        except Exception:
            pass

        vector_rows = db.execute(
            text(
                """
                SELECT c.id, c.document_id, c.chunk_index, c.content,
                       d.filename AS filename
                FROM chunks c
                LEFT JOIN documents d ON d.id = c.document_id
                ORDER BY c.embedding <=> CAST(:qvec AS vector)
                LIMIT :lim
                """
            ),
            {"qvec": _vec_literal(query_vector), "lim": VECTOR_LIMIT},
        ).fetchall()

        keyword_rows: list[Any] = []
        try:
            tsquery = db.execute(
                text("SELECT websearch_to_tsquery('english', :q)"),
                {"q": query},
            ).scalar()
        except Exception:
            tsquery = None
        if tsquery:
            keyword_rows = db.execute(
                text(
                    """
                    SELECT c.id, c.document_id, c.chunk_index, c.content,
                           d.filename AS filename,
                           ts_rank_cd(c.tsv, websearch_to_tsquery('english', :q)) AS rank
                    FROM chunks c
                    LEFT JOIN documents d ON d.id = c.document_id
                    WHERE c.tsv @@ websearch_to_tsquery('english', :q)
                    ORDER BY rank DESC
                    LIMIT :lim
                    """
                ),
                {"q": query, "lim": KEYWORD_LIMIT},
            ).fetchall()

        by_id: dict[UUID, Any] = {}
        for row in [*vector_rows, *keyword_rows]:
            by_id[row.id] = row

        fused_ids = _rrf_fuse(
            [
                [row.id for row in vector_rows],
                [row.id for row in keyword_rows],
            ]
        )
        hits = []
        for chunk_id in fused_ids[:take]:
            row = by_id.get(chunk_id)
            if row is not None:
                hits.append(_row_to_hit(row))
        return hits
