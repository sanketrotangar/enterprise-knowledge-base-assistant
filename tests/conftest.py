"""Real Postgres + pgvector for RLS leak tests. No superuser queries on chunks."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from testcontainers.postgres import PostgresContainer

ROOT = Path(__file__).resolve().parents[1]
APP_PASSWORD = "app_user"
EMBEDDING_DIM = 8

TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TENANT_NONE = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _psycopg_url(url: str) -> str:
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+psycopg://" + url[len("postgresql+psycopg2://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


@pytest.fixture(scope="session")
def pg_urls():
    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        owner_url = _psycopg_url(postgres.get_connection_url())

        from app.core.config import settings

        app_url = (
            make_url(owner_url)
            .set(username="app_user", password=APP_PASSWORD)
            .render_as_string(hide_password=False)
        )
        settings.MIGRATION_DATABASE_URL = owner_url
        settings.DATABASE_URL = app_url
        settings.APP_DB_PASSWORD = APP_PASSWORD
        settings.APP_DB_USER = "app_user"
        settings.EMBEDDING_DIM = EMBEDDING_DIM
        settings.EMBEDDING_DIMENSION = EMBEDDING_DIM

        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", owner_url)
        command.upgrade(cfg, "head")

        yield {"owner": owner_url, "app": app_url}


@pytest.fixture
def owner_engine(pg_urls) -> Engine:
    engine = create_engine(pg_urls["owner"], pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def app_engine(pg_urls) -> Engine:
    engine = create_engine(
        pg_urls["app"],
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
    )
    try:
        yield engine
    finally:
        engine.dispose()
