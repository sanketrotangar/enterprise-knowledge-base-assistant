# Search Routes
# --------------
# Thin HTTP layer for the retrieval pipeline. Validation -> 400 (FastAPI),
# pipeline failure -> 500. All logic lives in service.py.
#
# Live: POST /api/v1/search  (ask + sources in response)

from fastapi import APIRouter, Depends, HTTPException, Query

from app.features.auth.deps import get_current_principal
from app.features.auth.service import Principal
from app.features.search.schemas import SearchRequest, SearchResponse
from app.features.search.service import search

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search_endpoint(
    req: SearchRequest,
    principal: Principal = Depends(get_current_principal),
    search_backend: str | None = Query(
        default=None,
        description="TEMPORARY eval override: qdrant|postgres. Default is SEARCH_BACKEND.",
    ),
) -> SearchResponse:
    """Run the full retrieval pipeline: hybrid search -> rerank -> answer."""
    try:
        return await search(req, principal=principal, backend=search_backend)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — single pipeline entry point
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}") from exc
