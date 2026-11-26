# Search Service — pipeline orchestrator
# ---------------------------------------
#   1. embed query (same model/config as ingestion — single home, Part 1 §3.9)
#   2. hybrid dense+BM25 search with RBAC filter (core/qdrant.search)
#   3. cross-encoder rerank top-20 -> top-k
#   4. LLM answer with [n] citations (extractive fallback without a key)
#   5. return answer + sources (no DB history)
#
# NO REDIS CACHE in this phase: caching is a wrapper IN FRONT of steps 2-4
# (check Redis -> return, else run + SETEX). core/cache.py stays a stub; the
# cacheable payload (query_id + answer + sources) is already a single return
# value, so the cache slots in without reordering anything.
#
# Concurrency: every blocking stage (embed, rerank, LLM, Qdrant, DB) runs via
# asyncio.to_thread so the event loop stays responsive during model work.

import asyncio
import time
import uuid as uuid_mod

from app.core.config import settings
from app.core.qdrant import search as qdrant_search
from app.features.auth.service import Principal
from app.features.search import llm, sparse
from app.features.search.embedder import embed_sync
from app.features.search.pg_retrieve import RetrievedHit, retrieve as pg_retrieve
from app.features.search.reranker import rerank
from app.features.search.schemas import SearchRequest, SearchResponse, SearchResult

# Stage-1 candidates pulled from Qdrant before reranking (20 -> rerank -> 5).
RETRIEVAL_LIMIT = 20

def _normalize_backend(backend: str | None) -> str:
    chosen = (backend or settings.SEARCH_BACKEND or "postgres").strip().lower()
    if chosen not in {"qdrant", "postgres"}:
        raise ValueError("search backend must be 'qdrant' or 'postgres'")
    return chosen


def _hits_from_qdrant(points) -> list[RetrievedHit]:
    hits: list[RetrievedHit] = []
    for point in points:
        payload = point.payload or {}
        raw = str(payload.get("raw_content") or payload.get("contextualized_content") or "")
        contextualized = str(payload.get("contextualized_content") or raw)
        hits.append(
            RetrievedHit(
                id=str(point.id),
                document_id=str(payload.get("document_id") or ""),
                document_title=str(payload.get("title") or "Untitled"),
                chunk_index=int(payload.get("chunk_index") or 0),
                content=raw,
                contextualized_content=contextualized,
            )
        )
    return hits


def _retrieve_hits(
    *,
    backend: str,
    query: str,
    query_vector: list[float],
    principal: Principal,
) -> list[RetrievedHit]:
    if backend == "postgres":
        return pg_retrieve(
            query=query,
            query_vector=query_vector,
            org_id=principal.org_id,
            role=principal.role,
            user_id=principal.user_id,
            limit=RETRIEVAL_LIMIT,
        )

    sparse_usable = sparse.encode_sparse_available(query)
    points = qdrant_search(
        query_vector=query_vector,
        org_id=str(principal.org_id),
        role_access=[],  # dev: no per-user role tags yet; 'general' covers dev docs
        role=principal.role,
        limit=RETRIEVAL_LIMIT,
        sparse_query=sparse.encode_sparse(query) if sparse_usable else None,
    )
    return _hits_from_qdrant(points)


async def search(
    req: SearchRequest,
    *,
    principal: Principal,
    backend: str | None = None,
) -> SearchResponse:
    """Full retrieval pipeline. Never raises for empty results; unexpected
    errors propagate to the router (mapped to 500).

    `principal` comes from the JWT: retrieval runs under that org/role, so RLS
    decides what can be seen.
    """
    started = time.perf_counter()
    backend = _normalize_backend(backend)

    # 1. Embed query (CPU-bound model work -> thread) ------------------------
    query_vector = (await asyncio.to_thread(embed_sync, [req.query]))[0]

    # 2. Hybrid search (Qdrant RBAC filter, or Postgres chunks + RLS) --------
    hits = await asyncio.to_thread(
        _retrieve_hits,
        backend=backend,
        query=req.query,
        query_vector=query_vector,
        principal=principal,
    )
    response_time_ms = int((time.perf_counter() - started) * 1000)

    if not hits:
        return _respond(
            sources=[],
            answer=(
                "No matching documents found in the knowledge base "
                "(or none you have access to)."
            ),
            response_time_ms=response_time_ms,
        )

    # Stage-1 candidates (keep payload texts for rerank/answer stages) -------
    documents = [hit.content for hit in hits]

    # 3. Rerank (CPU-bound batch scoring -> thread) --------------------------
    ranked = await rerank(req.query, documents, top_k=req.top_k)

    sources = [
        SearchResult(
            id=hits[idx].id,
            document_id=hits[idx].document_id,
            document_title=hits[idx].document_title,
            chunk_index=hits[idx].chunk_index,
            content=documents[idx],
            score=float(score),
        )
        for idx, score in ranked
    ]

    # 4. Answer (network I/O to LLM -> thread); context = what was embedded --
    contexts = [
        hits[idx].contextualized_content or documents[idx] for idx, _ in ranked
    ]
    answer = await asyncio.to_thread(llm.generate_answer, req.query, contexts)

    response_time_ms = int((time.perf_counter() - started) * 1000)
    return _respond(
        sources=sources,
        answer=answer,
        response_time_ms=response_time_ms,
    )


def _respond(
    *,
    sources: list[SearchResult],
    answer: str,
    response_time_ms: int,
) -> SearchResponse:
    """Ask response with sources. No search_queries persistence (beta)."""
    return SearchResponse(
        query_id=str(uuid_mod.uuid4()),
        answer=answer,
        sources=sources,
        response_time_ms=response_time_ms,
    )

