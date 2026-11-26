# Application Settings
# ---------------------
# Environment-based configuration using pydantic-settings
# All values loaded from environment variables or .env file
#
# Usage:
#   from app.core.config import settings
#   print(settings.DATABASE_URL)

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Enterprise Knowledge Assistant"
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    # JWT access token lifetime (minutes). 1440 = 24h.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Database
    # Runtime URL — MUST be app_user (not superuser, not BYPASSRLS, not table owner).
    DATABASE_URL: str = "postgresql+psycopg://app_user:app_user@localhost:5432/knowledge-assistant"
    # Owner/migrator URL. Alembic only. The running app must never use this.
    MIGRATION_DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/knowledge-assistant"
    APP_DB_USER: str = "app_user"
    APP_DB_PASSWORD: str = "app_user"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""

    # Retrieval: postgres (chunks hybrid, default) or qdrant (frozen baseline path).
    SEARCH_BACKEND: str = "postgres"

    # LLM (Groq — OpenAI-compatible API, spoken via the `openai` package)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-8b-instant"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

    # Embedding — EMBEDDING_DIM is the single source of truth for vector(N).
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384
    EMBEDDING_DIMENSION: int = 384  # kept for the existing embedder; synced from EMBEDDING_DIM

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # Storage
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 50

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @model_validator(mode="before")
    @classmethod
    def _embed_dim_from_legacy(cls, data):
        if isinstance(data, dict):
            dim = data.get("EMBEDDING_DIM")
            legacy = data.get("EMBEDDING_DIMENSION")
            if dim in (None, "") and legacy not in (None, ""):
                data["EMBEDDING_DIM"] = legacy
        return data

    @model_validator(mode="after")
    def _embedding_dim_is_source_of_truth(self):
        object.__setattr__(self, "EMBEDDING_DIMENSION", self.EMBEDDING_DIM)
        backend = (self.SEARCH_BACKEND or "postgres").strip().lower()
        if backend not in {"qdrant", "postgres"}:
            raise ValueError("SEARCH_BACKEND must be 'qdrant' or 'postgres'")
        object.__setattr__(self, "SEARCH_BACKEND", backend)
        return self


settings = Settings()
