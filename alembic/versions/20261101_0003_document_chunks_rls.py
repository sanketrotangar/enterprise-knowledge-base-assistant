"""Add tenant_id + RLS on document_chunks; RLS on organizations and users.

Revision ID: 20261101_0003
Revises: 20261031_0002
Create Date: 2026-11-01

document_chunks had no tenant_id — last tenant-data table without RLS.
organizations.id and users.org_id are tenant keys; same fail-closed policy.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261101_0003"
down_revision: Union[str, Sequence[str], None] = "20261031_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "app_user"
DEV_ORG_ID = "11111111-1111-1111-1111-111111111111"

TENANT_PRED = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
)
ORG_PRED = "id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
USER_PRED = "org_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


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
            CREATE TABLE IF NOT EXISTS document_chunks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                document_id UUID NOT NULL,
                qdrant_point_id UUID NOT NULL,
                chunk_index INTEGER NOT NULL,
                content_preview TEXT,
                context_header TEXT,
                contextualized_content TEXT,
                token_count INTEGER,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )

    if not _column_exists(bind, "document_chunks", "tenant_id"):
        op.execute(sa.text("ALTER TABLE document_chunks ADD COLUMN tenant_id UUID"))

    op.execute(
        sa.text(
            """
            UPDATE document_chunks dc
            SET tenant_id = d.org_id
            FROM documents d
            WHERE dc.document_id = d.id AND dc.tenant_id IS NULL
            """
        )
    )
    op.execute(sa.text("DELETE FROM document_chunks WHERE tenant_id IS NULL"))
    op.execute(
        sa.text(
            """
            ALTER TABLE document_chunks
            ALTER COLUMN tenant_id SET DEFAULT
                NULLIF(current_setting('app.tenant_id', true), '')::uuid
            """
        )
    )
    op.execute(
        sa.text("ALTER TABLE document_chunks ALTER COLUMN tenant_id SET NOT NULL")
    )

    op.execute(
        sa.text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE document_chunks TO {APP_ROLE}"
        )
    )

    _enable_force_rls("document_chunks")
    _policy("document_chunks", TENANT_PRED)

    # Stable id for the seeded default org so rls_session can SET LOCAL
    # before looking the row up (chicken-egg without a known tenant_id).
    op.execute(
        sa.text(
            f"""
            DO $$
            DECLARE
              old_id uuid;
              new_id uuid := '{DEV_ORG_ID}';
            BEGIN
              SELECT id INTO old_id FROM organizations WHERE slug = 'default';
              IF old_id IS NULL OR old_id = new_id THEN
                RETURN;
              END IF;
              IF EXISTS (SELECT 1 FROM organizations WHERE id = new_id) THEN
                RETURN;
              END IF;

              UPDATE organizations SET slug = 'default__legacy' WHERE id = old_id;

              INSERT INTO organizations (id, name, slug, settings, created_at, updated_at)
              SELECT new_id, name, 'default', settings, created_at, updated_at
              FROM organizations WHERE id = old_id;

              UPDATE documents SET org_id = new_id WHERE org_id = old_id;
              UPDATE users SET org_id = new_id WHERE org_id = old_id;
              UPDATE search_queries SET org_id = new_id WHERE org_id = old_id;
              UPDATE chunks SET tenant_id = new_id WHERE tenant_id = old_id;
              UPDATE query_citations SET tenant_id = new_id WHERE tenant_id = old_id;
              UPDATE document_chunks SET tenant_id = new_id WHERE tenant_id = old_id;

              DELETE FROM organizations WHERE id = old_id;
            END
            $$
            """
        )
    )

    _enable_force_rls("organizations")
    _policy("organizations", ORG_PRED)
    _enable_force_rls("users")
    _policy("users", USER_PRED)


def downgrade() -> None:
    for table in ("document_chunks", "organizations", "users"):
        op.execute(sa.text(f"DROP POLICY IF EXISTS {table}_isolation ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE document_chunks DROP COLUMN IF EXISTS tenant_id"))
