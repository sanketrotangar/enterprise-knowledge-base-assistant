"""ENABLE+FORCE RLS on documents, search_queries, query_citations.

Revision ID: 20261031_0002
Revises: 20261031_0001
Create Date: 2026-10-31

Policy uses tenant_id = current_setting('app.tenant_id') (fail closed).
documents also gets the chunks clearance/department rule.
All policies include WITH CHECK so writes cannot smuggle another tenant.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261031_0002"
down_revision: Union[str, Sequence[str], None] = "20261031_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "app_user"

TENANT_PRED = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
)
DOCS_PRED = f"""
    {TENANT_PRED}
    AND clearance <= NULLIF(current_setting('app.clearance', true), '')::int
    AND (
        department = NULLIF(current_setting('app.department', true), '')
        OR department = 'general'
    )
"""


def _column_exists(bind, table: str, column: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :t AND column_name = :c
                """
            ),
            {"t": table, "c": column},
        ).scalar()
    )


def _grant(table: str) -> None:
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
              IF to_regclass('public.{table}') IS NOT NULL THEN
                EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {APP_ROLE}';
              END IF;
            END
            $$
            """
        )
    )


def _enable_force_rls(table: str) -> None:
    op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))


def _policy(table: str, predicate: str) -> None:
    op.execute(sa.text(f"DROP POLICY IF EXISTS {table}_isolation ON {table}"))
    op.execute(
        sa.text(
            f"""
            CREATE POLICY {table}_isolation ON {table}
            FOR ALL
            TO {APP_ROLE}
            USING ({predicate})
            WITH CHECK ({predicate})
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(255) NOT NULL,
                slug VARCHAR(100) NOT NULL UNIQUE,
                settings JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                org_id UUID NOT NULL,
                email VARCHAR(255) NOT NULL,
                name VARCHAR(255) NOT NULL,
                role VARCHAR(50) NOT NULL DEFAULT 'employee',
                department VARCHAR(100),
                manager_id UUID,
                password_hash VARCHAR(255) NOT NULL DEFAULT 'dev-only-not-a-real-hash',
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )

    # --- documents: create if this DB only had the chunks migration ---
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                org_id UUID NOT NULL,
                title VARCHAR(500) NOT NULL DEFAULT 'untitled',
                source_type VARCHAR(50) NOT NULL DEFAULT 'upload',
                storage_path VARCHAR(1000) NOT NULL DEFAULT '',
                file_size_bytes BIGINT,
                mime_type VARCHAR(100),
                uploaded_by UUID NOT NULL DEFAULT gen_random_uuid(),
                sensitivity VARCHAR(50) NOT NULL DEFAULT 'internal',
                role_access VARCHAR(50)[] NOT NULL DEFAULT '{}',
                status VARCHAR(50) NOT NULL DEFAULT 'uploaded',
                chunk_count INTEGER NOT NULL DEFAULT 0,
                metadata JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    if not _column_exists(bind, "documents", "department"):
        op.execute(
            sa.text(
                "ALTER TABLE documents ADD COLUMN department TEXT NOT NULL DEFAULT 'general'"
            )
        )
    if not _column_exists(bind, "documents", "clearance"):
        op.execute(
            sa.text(
                "ALTER TABLE documents ADD COLUMN clearance INTEGER NOT NULL DEFAULT 1"
            )
        )
    if not _column_exists(bind, "documents", "tenant_id"):
        op.execute(
            sa.text(
                "ALTER TABLE documents ADD COLUMN tenant_id UUID "
                "GENERATED ALWAYS AS (org_id) STORED"
            )
        )

    # --- search_queries ---
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS search_queries (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL DEFAULT gen_random_uuid(),
                org_id UUID NOT NULL,
                query_text TEXT NOT NULL,
                results_count INTEGER NOT NULL DEFAULT 0,
                response_time_ms INTEGER NOT NULL DEFAULT 0,
                answer_text TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    if not _column_exists(bind, "search_queries", "tenant_id"):
        op.execute(
            sa.text(
                "ALTER TABLE search_queries ADD COLUMN tenant_id UUID "
                "GENERATED ALWAYS AS (org_id) STORED"
            )
        )

    # --- query_citations ---
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS query_citations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                query_id UUID NOT NULL,
                document_id UUID NOT NULL,
                chunk_id UUID,
                relevance_score DOUBLE PRECISION,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    if not _column_exists(bind, "query_citations", "tenant_id"):
        op.execute(
            sa.text(
                """
                ALTER TABLE query_citations ADD COLUMN tenant_id UUID
                DEFAULT NULLIF(current_setting('app.tenant_id', true), '')::uuid
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE query_citations c
                SET tenant_id = s.org_id
                FROM search_queries s
                WHERE c.query_id = s.id AND c.tenant_id IS NULL
                """
            )
        )

    for table in (
        "chunks",
        "documents",
        "search_queries",
        "query_citations",
        "organizations",
        "users",
        "document_chunks",
    ):
        _grant(table)

    _enable_force_rls("documents")
    _enable_force_rls("search_queries")
    _enable_force_rls("query_citations")
    _enable_force_rls("chunks")

    _policy("documents", DOCS_PRED)
    _policy("search_queries", TENANT_PRED)
    _policy("query_citations", TENANT_PRED)
    _policy("chunks", DOCS_PRED)  # recreate so WITH CHECK is explicit


def downgrade() -> None:
    for table in ("documents", "search_queries", "query_citations", "chunks"):
        op.execute(sa.text(f"DROP POLICY IF EXISTS {table}_isolation ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
    # Recreate chunks policy from 0001 so downgrade lands on that revision's shape.
    _enable_force_rls("chunks")
    _policy("chunks", DOCS_PRED)
