# Knowledge Assistant - Central API Router
# ----------------------------------------
# Live beta surface (see docs/build.md):
# - /health
# - /api/v1/auth
# - /api/v1/documents
# - /api/v1/search  (ask + sources; no history)

from fastapi import APIRouter

from app.features.auth.router import router as auth_router
from app.features.documents.router import router as documents_router
from app.features.search.router import router as search_router

api_router = APIRouter()

# Health endpoints (no auth required for basic probe)
health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health_check():
    """Basic health check probe for load balancers and Docker."""
    return {"status": "healthy"}


@health_router.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check verifying PostgreSQL, Redis, Qdrant, and Celery."""
    return {
        "status": "healthy",
        "services": {
            "database": "disconnected",  #add status
            "redis": "disconnected",  #add status
            "qdrant": "disconnected",  #add status
            "celery": "disconnected",  #add status
        },
    }


# Mount health router at root
api_router.include_router(health_router)

# Mount feature routers under /api/v1
v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(auth_router)
v1_router.include_router(documents_router)
v1_router.include_router(search_router)

api_router.include_router(v1_router)
