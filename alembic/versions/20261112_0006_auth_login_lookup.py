"""Slice 2: SECURITY DEFINER login lookup.

Revision ID: 20261112_0006
Revises: 20261112_0005
Create Date: 2026-11-12

`users` is protected by FORCE RLS keyed on `app.org_id`, but login cannot
know the org until it has found the user. The lookup therefore runs through a
SECURITY DEFINER function owned by the migrator (the only role allowed to see
rows before SET LOCAL). It returns exactly the columns login needs and is
executable by app_user only.

Why this is safe:
- SECURITY DEFINER executes with the owner's rights (bypasses RLS); ownership
  stays with the migration role, never app_user.
- search_path is pinned so the definer body cannot be shadowed.
- EXECUTE is revoked from PUBLIC and granted to app_user.
- It exposes only (id, org_id, role, password_hash) for an exact email, which
  is the same data a successful login must verify anyway.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_0006"
down_revision: Union[str, Sequence[str], None] = "20261112_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "app_user"


def upgrade() -> None:
    # Login assumes one user per (org, email). The ORM declares this constraint
    # but no earlier migration created it; enforce it here (case-insensitive).
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_org_email "
            "ON users (org_id, lower(email))"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_users_email_lower "
            "ON users (lower(email))"
        )
    )

    # p_org_id disambiguates the same email registered in two orgs.
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION login_lookup_user(
                p_email TEXT,
                p_org_id UUID DEFAULT NULL
            )
            RETURNS TABLE (
                user_id UUID,
                org_id UUID,
                email TEXT,
                role TEXT,
                password_hash TEXT
            )
            LANGUAGE sql
            STABLE
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
                SELECT u.id, u.org_id, u.email, u.role, u.password_hash
                FROM users u
                WHERE lower(u.email) = lower(p_email)
                  AND (p_org_id IS NULL OR u.org_id = p_org_id)
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"REVOKE ALL ON FUNCTION login_lookup_user(TEXT, UUID) FROM PUBLIC"
        )
    )
    op.execute(
        sa.text(f"GRANT EXECUTE ON FUNCTION login_lookup_user(TEXT, UUID) TO {APP_ROLE}")
    )


def downgrade() -> None:
    op.execute(sa.text("DROP FUNCTION IF EXISTS login_lookup_user(TEXT, UUID)"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_users_email_lower"))
    op.execute(sa.text("DROP INDEX IF EXISTS uq_users_org_email"))
