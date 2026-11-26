"""Add chunks table with pgvector, tsvector, and RLS.

Revision ID: 20261031_0001
Revises:
Create Date: 2026-10-31

Vector width comes from settings.EMBEDDING_DIM at upgrade time — not hardcoded.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision: str = "20261031_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "app_user"


def upgrade() -> None:
    dim = int(settings.EMBEDDING_DIM)
    if dim < 1:
        raise ValueError("EMBEDDING_DIM must be a positive integer")

    bind = op.get_bind()
    db_name = bind.execute(sa.text("SELECT current_database()")).scalar()
    db_ident = db_name.replace('"', '""')

    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    op.execute(
        sa.text(
            f"""
            CREATE TABLE chunks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                document_id UUID NOT NULL,
                department TEXT NOT NULL,
                clearance INTEGER NOT NULL,
                content TEXT NOT NULL,
                context_header TEXT,
                contextualized_content TEXT NOT NULL,
                embedding vector({dim}) NOT NULL,
                tsv tsvector GENERATED ALWAYS AS (
                    to_tsvector('english', contextualized_content)
                ) STORED,
                doc_family_id UUID NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL,
                CONSTRAINT chunks_status_check
                    CHECK (status IN ('active', 'superseded'))
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE INDEX ix_chunks_embedding_hnsw
            ON chunks USING hnsw (embedding vector_cosine_ops)
            """
        )
    )
    op.execute(sa.text("CREATE INDEX ix_chunks_tsv_gin ON chunks USING gin (tsv)"))

    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN
                  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
              ELSE
                ALTER ROLE {APP_ROLE} WITH LOGIN NOSUPERUSER NOBYPASSRLS;
              END IF;
            END
            $$
            """
        )
    )

    op.execute(sa.text(f'GRANT CONNECT ON DATABASE "{db_ident}" TO {APP_ROLE}'))
    op.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
    op.execute(
        sa.text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE chunks TO {APP_ROLE}"
        )
    )

    op.execute(sa.text("ALTER TABLE chunks ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE chunks FORCE ROW LEVEL SECURITY"))

    # Custom GUCs often come back as '' (not NULL) after SET LOCAL ends.
    # NULLIF makes that fail closed: 0 rows, not a cast error.
    op.execute(
        sa.text(
            f"""
            CREATE POLICY chunks_isolation ON chunks
            FOR ALL
            TO {APP_ROLE}
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                AND clearance <= NULLIF(current_setting('app.clearance', true), '')::int
                AND (
                    department = NULLIF(current_setting('app.department', true), '')
                    OR department = 'general'
                )
            )
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                AND clearance <= NULLIF(current_setting('app.clearance', true), '')::int
                AND (
                    department = NULLIF(current_setting('app.department', true), '')
                    OR department = 'general'
                )
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS chunks_isolation ON chunks"))
    op.execute(sa.text("DROP TABLE IF EXISTS chunks"))
    # Leave app_user and the vector extension in place: both may be shared.
