"""Worker chunk-id lookup for role sync + re-ingest.

Revision ID: 20261126_0007
Revises: 20261112_0006
Create Date: 2026-11-26

Why this exists (Slice 4):
`chunks_select` only exposes chunks whose `chunk_role_access` contains the
session role. Once a document's roles exclude `admin`, the worker (which runs
as admin for write permission) cannot SELECT those chunks, so it could not
re-copy roles or replace old chunks on re-ingest. Postgres also applies the
SELECT policy to rows scanned by a DELETE ... WHERE, so even a permitted
DELETE matches nothing.

Two scoped helpers, both limited to one document in the session's `app.org_id`:
  - list_document_chunk_ids(doc)   -> ids only (role sync)
  - delete_document_chunks(doc)    -> deletes that document's chunks; cascades
                                      chunk_role_access (re-ingest)

Both are SECURITY DEFINER (owned by the migration role, which bypasses RLS)
with a pinned search_path, and EXECUTE is granted to `app_user` only. Same
pattern as `login_lookup_user` in 0006. They are not reachable from HTTP
directly; the document service calls them inside an RLS session. Neither
returns chunk content.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261126_0007"
down_revision: Union[str, Sequence[str], None] = "20261112_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "app_user"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION list_document_chunk_ids(p_document_id uuid)
            RETURNS TABLE (id uuid)
            LANGUAGE sql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
                SELECT c.id
                FROM chunks c
                WHERE c.document_id = p_document_id
                  AND c.org_id =
                      NULLIF(current_setting('app.org_id', true), '')::uuid
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION delete_document_chunks(p_document_id uuid)
            RETURNS integer
            LANGUAGE sql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
                WITH removed AS (
                    DELETE FROM chunks
                    WHERE document_id = p_document_id
                      AND org_id =
                          NULLIF(current_setting('app.org_id', true), '')::uuid
                    RETURNING 1
                )
                SELECT count(*)::integer FROM removed
            $$
            """
        )
    )
    for signature in (
        "list_document_chunk_ids(uuid)",
        "delete_document_chunks(uuid)",
    ):
        op.execute(
            sa.text(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        )
        op.execute(
            sa.text(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")
        )


def downgrade() -> None:
    op.execute(sa.text("DROP FUNCTION IF EXISTS delete_document_chunks(uuid)"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS list_document_chunk_ids(uuid)"))
