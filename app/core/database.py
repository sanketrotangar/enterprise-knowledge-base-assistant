# Database Configuration
# -----------------------
# SQLAlchemy engine setup and session management
#
# Responsibilities:
# - Create database engine with connection pooling
# - Provide session factory for dependency injection
# - Expose health check function
# - Expose declarative Base for all ORM models
# - Configure connection parameters
#
# Usage:
#   from app.core.database import engine, get_db, SessionLocal, Base
#
# Connection pooling:
# - Pool size: 10 connections
# - Max overflow: 20 additional connections
# - Pool timeout: 30 seconds
# - Pool recycle: 1800 seconds (30 min)


# Database Configuration
# -----------------------
# SQLAlchemy engine setup, session management, and dev bootstrap helpers.
#
# Startup order (see app/main.py):
#   1. ensure_database()          -> create the DB itself if missing (dev convenience)
#   2. check_database_connection()-> verify connectivity
#   3. init_db()                  -> create tables from ORM models
#
# Why not Alembic yet: the schema is still moving during the ingestion phase;
# `create_all` (additive, creates missing tables only) is cheaper. Introduce
# Alembic once the schema stabilizes (after the auth phase).

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# Create engine with connection pooling
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative base for all feature models
Base = declarative_base()


# FastAPI session dependency lives in app.features.auth.deps.get_db:
# it derives the RLS transaction from the verified JWT principal. No raw
# app_user session is ever handed to a route.


def ensure_database() -> None:
    """Create the database named in MIGRATION_DATABASE_URL if it does not exist.

    Ops/Alembic helper — not called from app startup (runtime is app_user).
    """
    url = make_url(settings.MIGRATION_DATABASE_URL)
    if not url.drivername.startswith("postgresql") or not url.database:
        return  # non-Postgres (e.g. sqlite in tests) manages its own files

    admin_url = url.set(database="postgres")  # always-present server DB
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            ).scalar()
            if not exists:
                # url.database comes from our own config, not user input;
                # double-quoting handles any hyphens in the name.
                conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin_engine.dispose()


def init_db() -> None:
    """No-op. Schema (including RLS) is applied only by Alembic.

    create_all as app_user would make app_user the table owner and bypass FORCE RLS.
    """
    return


def check_database_connection() -> None:
    """Raise an exception when PostgreSQL is unavailable."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
