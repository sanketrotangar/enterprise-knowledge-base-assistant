# Search Schemas
# --------------
# Pydantic contracts. Field names are LOCKED to frontend/src/types/api.ts:
#   SearchRequest     -> {query, top_k, filters?}
#   SearchResponse    -> {query_id, answer, sources[], response_time_ms}
#   SearchResult      -> {id, document_id, document_title, chunk_index, content, score}
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
    id: str  # Qdrant point id == DocumentChunk.qdrant_point_id
    document_id: str
    document_title: str
    chunk_index: int
    content: str  # raw chunk text (context header NOT included)
    score: float  # cross-encoder score (or RRF-order fallback score)


class SearchResponse(BaseModel):
    query_id: str  # search_queries row id (feedback FK target, Phase 4)
    answer: str
    sources: list[SearchResult]
    response_time_ms: int


class SearchHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    query_text: str
    created_at: datetime
    results_count: int
