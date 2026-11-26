# RLS session helper (beta: org + role)
# -------------------------------------
# Every DB query runs in a transaction with SET LOCAL:
#   app.org_id, app.role, and app.tenant_id (= org_id for legacy policies).
# Connect as `app_user` (not superuser, not BYPASSRLS).

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

BETA_ROLES = frozenset({"user", "manager", "admin"})

# Legacy role strings → beta (until JWT + cleaned seeds).
ROLE_ALIASES = {
    "admin": "admin",
    "manager": "manager",
    "user": "user",
    "employee": "user",
    "intern": "user",
}

APP_USER_OWNS_NO_TABLES_SQL = """
SELECT n.nspname AS schema_name, c.relname AS table_name
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_roles r ON r.oid = c.relowner
WHERE r.rolname = current_user
  AND n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
"""


class UnsafeDatabaseRoleError(RuntimeError):
    """Runtime DATABASE_URL is superuser, BYPASSRLS, or owns tables."""


def normalize_role(role: str) -> str:
    key = (role or "user").strip().lower()
    return ROLE_ALIASES.get(key, "user")


def get_app_engine() -> Engine:
    from app.core.database import engine

    return engine


def assert_runtime_role_is_safe(*, engine: Engine | None = None) -> None:
    bind = engine if engine is not None else get_app_engine()
    with bind.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT current_user AS role_name, rolsuper, rolbypassrls
                FROM pg_roles
                WHERE rolname = current_user
                """
            )
        ).one()
        if row.rolsuper:
            raise UnsafeDatabaseRoleError(
                f"runtime role {row.role_name!r} is superuser; "
                "DATABASE_URL must be app_user"
            )
        if row.rolbypassrls:
            raise UnsafeDatabaseRoleError(
                f"runtime role {row.role_name!r} has BYPASSRLS"
            )
        owned = conn.execute(text(APP_USER_OWNS_NO_TABLES_SQL)).fetchall()
        if owned:
            names = [f"{r.schema_name}.{r.table_name}" for r in owned]
            raise UnsafeDatabaseRoleError(
                f"runtime role {row.role_name!r} owns tables: {names}"
            )


def _set_rls_locals(
    connection, *, org_id: UUID, role: str, user_id: UUID | None = None
) -> None:
    role = normalize_role(role)
    if role not in BETA_ROLES:
        role = "user"
    oid = str(org_id)
    connection.execute(
        text("SELECT set_config('app.org_id', :v, true)"), {"v": oid}
    )
    if user_id is not None:
        connection.execute(
            text("SELECT set_config('app.user_id', :v, true)"),
            {"v": str(user_id)},
        )
    connection.execute(
        text("SELECT set_config('app.role', :v, true)"), {"v": role}
    )
    # Legacy policies still read app.tenant_id
    connection.execute(
        text("SELECT set_config('app.tenant_id', :v, true)"), {"v": oid}
    )


@contextmanager
def rls_session(
    *,
    org_id: UUID | None = None,
    role: str = "user",
    user_id: UUID | None = None,
    engine: Engine | None = None,
    # Backward-compatible aliases (old call sites / eval)
    tenant_id: UUID | None = None,
    department: str | None = None,
    clearance: int | None = None,
) -> Iterator[Session]:
    """Open a transaction, SET LOCAL RLS vars, yield an ORM Session."""
    del department, clearance  # unused in beta policies
    resolved_org = org_id or tenant_id
    if resolved_org is None:
        raise ValueError("rls_session requires org_id (or tenant_id alias)")

    bind = engine if engine is not None else get_app_engine()
    with bind.connect() as connection:
        with connection.begin():
            _set_rls_locals(
                connection, org_id=resolved_org, role=role, user_id=user_id
            )
            session = Session(bind=connection, join_transaction_mode="create_savepoint")
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()


@contextmanager
def rls_session_from_dev_identity(*, engine: Engine | None = None) -> Iterator[Session]:
    """Scripts only: seed/eval sessions built from eval/users.yaml or dev org.

    Product request paths use the verified JWT principal
    (app.features.auth.deps) and call rls_session directly. Do not wire this
    function into a router.
    """
    from app.core.eval_identity import current_principal, get_or_create_eval_identity
    from app.features.auth.service import (
        DEV_ORG_ID,
        get_or_create_dev_identity,
    )

    principal = current_principal()
    if principal is not None:
        eval_role = "user"
        if principal.eval_user is not None:
            eval_role = normalize_role(principal.eval_user.role)
            # Map high clearance eval users toward manager for seed paths
            if principal.eval_user.clearance >= 3 and eval_role == "user":
                eval_role = "manager"
        with rls_session(
            org_id=principal.tenant_id,
            role=eval_role,
            engine=engine,
        ) as session:
            if principal.eval_user is not None:
                get_or_create_eval_identity(session, principal.eval_user)
            yield session
        return

    with rls_session(org_id=DEV_ORG_ID, role="admin", engine=engine) as session:
        get_or_create_dev_identity(session)
        yield session
