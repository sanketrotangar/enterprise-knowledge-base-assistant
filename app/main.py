# Enterprise Knowledge Assistant - Main Application Entry Point
# ---------------------------------------------------------------
# Responsibilities:
# - Initialize FastAPI application
# - Configure lifespan events (startup/shutdown)
# - Include all API routers via central api_router
# - Add middleware (CORS, auth, rate limiting)
# - Health check on startup
#
# Routers (beta live): /health, /api/v1/auth, /documents, /search

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import check_database_connection
from app.core.rls import assert_runtime_role_is_safe
from app.api import api_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Runtime DATABASE_URL is app_user only. Schema lives in Alembic
    # (MIGRATION_DATABASE_URL). Never create_all, never connect as owner.
    check_database_connection()
    assert_runtime_role_is_safe()

    # 3. Preload and warm up ML models (embedding + reranker) so incoming queries run instantly
    from app.features.search.embedder import warmup as warmup_embedder
    from app.features.search.reranker import warmup as warmup_reranker

    warmup_embedder()
    warmup_reranker()

    yield
    # Shutdown: cleanup resources


app = FastAPI(
    title="Enterprise Knowledge Assistant",
    version="0.1.0",
    description="RAG-based enterprise knowledge search with RBAC",
    lifespan=lifespan,
)

# Auth: every product route reads the JWT (see app/features/auth/deps.py).
# The old X-Eval-User impersonation header is no longer installed; the eval
# harness is rebuilt against JWT in Slice 7.

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS.split(","),  # configurable, not hardcoded
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include central API router
app.include_router(api_router)
