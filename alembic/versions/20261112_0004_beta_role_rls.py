"""Beta access model: org + role tables; RLS via document/chunk_role_access.

Revision ID: 20261112_0004
Revises: 20261101_0003
Create Date: 2026-11-12

Target (docs/diagrams/03-schema): user|manager|admin, document_role_access,
chunk_role_access. Session vars: app.org_id + app.role (app.tenant_id mirrored
for leftover legacy policies).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_0004"
down_revision: Union[str, Sequence[str], None] = "20261101_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "app_user"

ORG_MATCH = "NULLIF(current_setting('app.org_id', true), '')::uuid"
ROLE_MATCH = "NULLIF(current_setting('app.role', true), '')"

# SELECT: org + role grant. WRITE: manager/admin in org (ingest before cra rows exist).
CHUNKS_SELECT = f"""
    tenant_id = {ORG_MATCH}
    AND EXISTS (
        SELECT 1 FROM chunk_role_access cra
        WHERE cra.chunk_id = chunks.id
          AND cra.role = {ROLE_MATCH}
    )
"""
CHUNKS_WRITE = f"""
    tenant_id = {ORG_MATCH}
    AND {ROLE_MATCH} IN ('manager', 'admin')
"""

DOCS_SELECT = f"""
    org_id = {ORG_MATCH}
    AND (
        {ROLE_MATCH} IN ('manager', 'admin')
        OR EXISTS (
            SELECT 1 FROM document_role_access dra
            WHERE dra.document_id = documents.id
              AND dra.role = {ROLE_MATCH}
        )
    )
"""
DOCS_WRITE = f"""
    org_id = {ORG_MATCH}
    AND {ROLE_MATCH} IN ('manager', 'admin')
"""

ORG_PRED = f"id = {ORG_MATCH}"
USER_PRED = f"org_id = {ORG_MATCH}"

DRA_PRED = f"org_id = {ORG_MATCH}"
CRA_PRED = f"org_id = {ORG_MATCH}"

# Legacy tables: org isolation only (not product surface for beta).
TENANT_ONLY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
)
ORG_ID_ONLY = f"org_id = {ORG_MATCH}"


def _policy_all(table: str, predicate: str) -> None:
    op.execute(sa.text(f"DROP POLICY IF EXISTS {table}_isolation ON {table}"))
    op.execute(sa.text(f"DROP POLICY IF EXISTS {table}_select ON {table}"))
    op.execute(sa.text(f"DROP POLICY IF EXISTS {table}_write ON {table}"))
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


def _policy_select_write(table: str, select_pred: str, write_pred: str) -> None:
    op.execute(sa.text(f"DROP POLICY IF EXISTS {table}_isolation ON {table}"))
    op.execute(sa.text(f"DROP POLICY IF EXISTS {table}_select ON {table}"))
    op.execute(sa.text(f"DROP POLICY IF EXISTS {table}_write ON {table}"))
    op.execute(
        sa.text(
            f"""
            CREATE POLICY {table}_select ON {table}
            FOR SELECT TO {APP_ROLE}
            USING ({select_pred})
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE POLICY {table}_write ON {table}
            FOR INSERT TO {APP_ROLE}
            WITH CHECK ({write_pred})
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE POLICY {table}_update ON {table}
            FOR UPDATE TO {APP_ROLE}
            USING ({write_pred})
            WITH CHECK ({write_pred})
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE POLICY {table}_delete ON {table}
            FOR DELETE TO {APP_ROLE}
            USING ({write_pred})
            """
        )
    )


def _grant(table: str) -> None:
    op.execute(
        sa.text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {APP_ROLE}"
        )
    )


def _enable_force(table: str) -> None:
    op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))


def upgrade() -> None:
    # --- role access tables ---
    # org_id denormalized so RLS does not join back to documents/chunks
    # (avoids infinite policy recursion).
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS document_role_access (
                document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                role VARCHAR(50) NOT NULL,
                org_id UUID NOT NULL,
                PRIMARY KEY (document_id, role),
                CONSTRAINT document_role_access_role_check
                    CHECK (role IN ('user', 'manager', 'admin'))
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS chunk_role_access (
                chunk_id UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
                role VARCHAR(50) NOT NULL,
                org_id UUID NOT NULL,
                PRIMARY KEY (chunk_id, role),
                CONSTRAINT chunk_role_access_role_check
                    CHECK (role IN ('user', 'manager', 'admin'))
            )
            """
        )
    )

    # Remap legacy user roles → beta set
    op.execute(
        sa.text(
            """
            UPDATE users SET role = CASE
                WHEN lower(role) IN ('admin') THEN 'admin'
                WHEN lower(role) IN ('manager') THEN 'manager'
                ELSE 'user'
            END
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
            ALTER TABLE users ADD CONSTRAINT users_role_check
                CHECK (role IN ('user', 'manager', 'admin'));
            """
        )
    )

    # Backfill document_role_access from legacy role_access[] / defaults
    op.execute(
        sa.text(
            """
            INSERT INTO document_role_access (document_id, role, org_id)
            SELECT d.id, r.role, d.org_id
            FROM documents d
            CROSS JOIN LATERAL (
                SELECT DISTINCT
                    CASE
                        WHEN lower(x) IN ('admin') THEN 'admin'
                        WHEN lower(x) IN ('manager') THEN 'manager'
                        WHEN lower(x) IN ('user', 'employee', 'intern', 'general') THEN 'user'
                        ELSE NULL
                    END AS role
                FROM unnest(COALESCE(d.role_access, ARRAY[]::varchar[])) AS x
            ) r
            WHERE r.role IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )
    )
    # Docs with empty role_access → all three roles (legacy "open" docs)
    op.execute(
        sa.text(
            """
            INSERT INTO document_role_access (document_id, role, org_id)
            SELECT d.id, v.role, d.org_id
            FROM documents d
            CROSS JOIN (VALUES ('user'), ('manager'), ('admin')) AS v(role)
            WHERE COALESCE(cardinality(d.role_access), 0) = 0
            ON CONFLICT DO NOTHING
            """
        )
    )

    # Backfill chunk_role_access from parent document roles
    op.execute(
        sa.text(
            """
            INSERT INTO chunk_role_access (chunk_id, role, org_id)
            SELECT c.id, dra.role, c.tenant_id
            FROM chunks c
            JOIN document_role_access dra ON dra.document_id = c.document_id
            ON CONFLICT DO NOTHING
            """
        )
    )
    # Orphan chunks (no doc roles): allow all roles so data is not invisible
    op.execute(
        sa.text(
            """
            INSERT INTO chunk_role_access (chunk_id, role, org_id)
            SELECT c.id, v.role, c.tenant_id
            FROM chunks c
            CROSS JOIN (VALUES ('user'), ('manager'), ('admin')) AS v(role)
            WHERE NOT EXISTS (
                SELECT 1 FROM chunk_role_access cra WHERE cra.chunk_id = c.id
            )
            ON CONFLICT DO NOTHING
            """
        )
    )

    _grant("document_role_access")
    _grant("chunk_role_access")
    _enable_force("document_role_access")
    _enable_force("chunk_role_access")

    # Replace RLS policies on core tables
    _policy_select_write("chunks", CHUNKS_SELECT, CHUNKS_WRITE)
    _policy_select_write("documents", DOCS_SELECT, DOCS_WRITE)
    _policy_all("organizations", ORG_PRED)
    _policy_all("users", USER_PRED)
    _policy_all("document_role_access", DRA_PRED)
    _policy_all("chunk_role_access", CRA_PRED)

    # Legacy tables: keep org isolation; mirror tenant_id from app.org_id in app code
    for table, pred in (
        ("document_chunks", TENANT_ONLY),
        ("search_queries", ORG_ID_ONLY),
        ("query_citations", TENANT_ONLY),
    ):
        op.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                  IF to_regclass('public.{table}') IS NOT NULL THEN
                    EXECUTE 'DROP POLICY IF EXISTS {table}_isolation ON {table}';
                    EXECUTE $p$
                      CREATE POLICY {table}_isolation ON {table}
                      FOR ALL TO {APP_ROLE}
                      USING ({pred})
                      WITH CHECK ({pred})
                    $p$;
                  END IF;
                END
                $$
                """
            )
        )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS chunk_role_access"))
    op.execute(sa.text("DROP TABLE IF EXISTS document_role_access"))
    # Policies from prior revisions are not fully restored; re-run 0002/0003 if needed.
