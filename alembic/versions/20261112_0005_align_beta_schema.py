"""Align physical schema to docs/diagrams/03-schema.drawio.

Revision ID: 20261112_0005
Revises: 20261112_0004
Create Date: 2026-11-12

Beta tables only: organizations, users, documents, document_role_access,
chunks, chunk_role_access. Drop parked history / Qdrant registry tables.
Keep org_id on *_role_access (RLS denorm; intentional vs diagram).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_0005"
down_revision: Union[str, Sequence[str], None] = "20261112_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "app_user"
ORG_MATCH = "NULLIF(current_setting('app.org_id', true), '')::uuid"
ROLE_MATCH = "NULLIF(current_setting('app.role', true), '')"

CHUNKS_SELECT = f"""
    org_id = {ORG_MATCH}
    AND EXISTS (
        SELECT 1 FROM chunk_role_access cra
        WHERE cra.chunk_id = chunks.id
          AND cra.role = {ROLE_MATCH}
    )
"""
CHUNKS_WRITE = f"""
    org_id = {ORG_MATCH}
    AND {ROLE_MATCH} IN ('manager', 'admin')
"""


def _column_exists(bind, table: str, column: str) -> bool:
    row = bind.execute(
        sa.text(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :t AND column_name = :c
            """
        ),
        {"t": table, "c": column},
    ).first()
    return row is not None


def _drop_policies(table: str) -> None:
    for name in (
        f"{table}_isolation",
        f"{table}_select",
        f"{table}_write",
        f"{table}_update",
        f"{table}_delete",
    ):
        op.execute(sa.text(f"DROP POLICY IF EXISTS {name} ON {table}"))


def upgrade() -> None:
    bind = op.get_bind()

    # --- Drop non-beta tables (parked: history + Qdrant chunk registry) ---
    op.execute(sa.text("DROP TABLE IF EXISTS query_citations CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS search_queries CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS document_chunks CASCADE"))

    # --- organizations: id, name, created_at ---
    if _column_exists(bind, "organizations", "slug"):
        op.execute(sa.text("ALTER TABLE organizations DROP COLUMN slug"))
    if _column_exists(bind, "organizations", "settings"):
        op.execute(sa.text("ALTER TABLE organizations DROP COLUMN settings"))
    if _column_exists(bind, "organizations", "updated_at"):
        op.execute(sa.text("ALTER TABLE organizations DROP COLUMN updated_at"))

    # --- users: id, org_id, email, password_hash, role, created_at ---
    if _column_exists(bind, "users", "name"):
        op.execute(sa.text("ALTER TABLE users DROP COLUMN name"))
    if _column_exists(bind, "users", "department"):
        op.execute(sa.text("ALTER TABLE users DROP COLUMN department"))
    if _column_exists(bind, "users", "manager_id"):
        op.execute(sa.text("ALTER TABLE users DROP COLUMN manager_id"))
    if _column_exists(bind, "users", "is_active"):
        op.execute(sa.text("ALTER TABLE users DROP COLUMN is_active"))
    if _column_exists(bind, "users", "updated_at"):
        op.execute(sa.text("ALTER TABLE users DROP COLUMN updated_at"))

    # --- documents → diagram columns ---
    if _column_exists(bind, "documents", "title") and not _column_exists(
        bind, "documents", "filename"
    ):
        op.execute(sa.text("ALTER TABLE documents RENAME COLUMN title TO filename"))
    if _column_exists(bind, "documents", "storage_path") and not _column_exists(
        bind, "documents", "disk_path"
    ):
        op.execute(
            sa.text("ALTER TABLE documents RENAME COLUMN storage_path TO disk_path")
        )

    if not _column_exists(bind, "documents", "error_message"):
        op.execute(sa.text("ALTER TABLE documents ADD COLUMN error_message TEXT"))

    # Map legacy statuses → pending|ready|failed
    op.execute(
        sa.text(
            """
            UPDATE documents SET status = CASE
                WHEN lower(status) IN ('ready', 'indexed') THEN 'ready'
                WHEN lower(status) IN ('failed') THEN 'failed'
                ELSE 'pending'
            END
            """
        )
    )
    op.execute(sa.text("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check"))
    op.execute(
        sa.text(
            """
            ALTER TABLE documents ADD CONSTRAINT documents_status_check
                CHECK (status IN ('pending', 'ready', 'failed'))
            """
        )
    )
    op.execute(sa.text("ALTER TABLE documents ALTER COLUMN status SET DEFAULT 'pending'"))

    # Move last_error out of metadata JSON if present
    if _column_exists(bind, "documents", "metadata"):
        op.execute(
            sa.text(
                """
                UPDATE documents
                SET error_message = COALESCE(
                    error_message,
                    NULLIF(metadata->>'last_error', '')
                )
                WHERE metadata ? 'last_error'
                """
            )
        )

    for col in (
        "source_type",
        "file_size_bytes",
        "mime_type",
        "sensitivity",
        "role_access",
        "chunk_count",
        "department",
        "clearance",
        "tenant_id",
        "metadata",
    ):
        if _column_exists(bind, "documents", col):
            op.execute(sa.text(f"ALTER TABLE documents DROP COLUMN {col}"))

    # --- chunks → diagram columns ---
    # Drop generated tsv before reshaping source columns
    if _column_exists(bind, "chunks", "tsv"):
        op.execute(sa.text("ALTER TABLE chunks DROP COLUMN tsv"))

    if _column_exists(bind, "chunks", "tenant_id") and not _column_exists(
        bind, "chunks", "org_id"
    ):
        op.execute(sa.text("ALTER TABLE chunks RENAME COLUMN tenant_id TO org_id"))

    if not _column_exists(bind, "chunks", "chunk_index"):
        op.execute(
            sa.text(
                "ALTER TABLE chunks ADD COLUMN chunk_index INTEGER NOT NULL DEFAULT 0"
            )
        )
        # Best-effort order by id within document
        op.execute(
            sa.text(
                """
                WITH numbered AS (
                    SELECT id,
                           (ROW_NUMBER() OVER (PARTITION BY document_id ORDER BY id) - 1)
                             AS idx
                    FROM chunks
                )
                UPDATE chunks c SET chunk_index = n.idx
                FROM numbered n WHERE c.id = n.id
                """
            )
        )

    if not _column_exists(bind, "chunks", "created_at"):
        op.execute(
            sa.text(
                "ALTER TABLE chunks ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW()"
            )
        )

    # Prefer contextualized text as content when present
    if _column_exists(bind, "chunks", "contextualized_content"):
        op.execute(
            sa.text(
                """
                UPDATE chunks
                SET content = COALESCE(NULLIF(contextualized_content, ''), content)
                """
            )
        )

    for col in (
        "department",
        "clearance",
        "context_header",
        "contextualized_content",
        "doc_family_id",
        "version",
        "status",
    ):
        if _column_exists(bind, "chunks", col):
            op.execute(sa.text(f"ALTER TABLE chunks DROP COLUMN {col}"))

    op.execute(sa.text("ALTER TABLE chunks DROP CONSTRAINT IF EXISTS chunks_status_check"))

    # Recreate tsv from content
    op.execute(
        sa.text(
            """
            ALTER TABLE chunks ADD COLUMN tsv tsvector
            GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED
            """
        )
    )
    op.execute(sa.text("DROP INDEX IF EXISTS ix_chunks_tsv_gin"))
    op.execute(sa.text("CREATE INDEX ix_chunks_tsv_gin ON chunks USING gin (tsv)"))

    # FK document → cascade (hard delete)
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'chunks_document_id_fkey'
              ) THEN
                ALTER TABLE chunks
                  ADD CONSTRAINT chunks_document_id_fkey
                  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE;
              END IF;
            END $$
            """
        )
    )

    # --- RLS: chunks use org_id now ---
    _drop_policies("chunks")
    op.execute(
        sa.text(
            f"""
            CREATE POLICY chunks_select ON chunks
            FOR SELECT TO {APP_ROLE}
            USING ({CHUNKS_SELECT})
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE POLICY chunks_write ON chunks
            FOR INSERT TO {APP_ROLE}
            WITH CHECK ({CHUNKS_WRITE})
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE POLICY chunks_update ON chunks
            FOR UPDATE TO {APP_ROLE}
            USING ({CHUNKS_WRITE})
            WITH CHECK ({CHUNKS_WRITE})
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE POLICY chunks_delete ON chunks
            FOR DELETE TO {APP_ROLE}
            USING ({CHUNKS_WRITE})
            """
        )
    )


def downgrade() -> None:
    raise NotImplementedError("Beta schema alignment is not reversible")
