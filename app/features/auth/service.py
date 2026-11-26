# Auth Service
# -------------
# Beta login (email + password) -> Principal -> JWT.
#
# `users` is protected by FORCE RLS keyed on app.org_id, and login runs before
# any org is known, so the lookup goes through the SECURITY DEFINER function
# `login_lookup_user` (migration 20261112_0006). That function returns only
# the identity columns login needs; all later reads use a normal RLS session.
#
# Also keeps the dev identity bootstrap used by local seed scripts; product
# paths no longer call it now that JWT is live.

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.config import settings
from app.core.security import verify_password

DEV_ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
DEV_USER_EMAIL = "dev@local"


class InvalidCredentialsError(Exception):
    """Bad email/password. Always maps to 401 with no detail."""


class AmbiguousLoginError(Exception):
    """The email is registered in more than one org; org_id is required."""


@dataclass(frozen=True)
class Principal:
    """Authenticated identity used to SET LOCAL on each RLS transaction."""

    org_id: uuid.UUID
    user_id: uuid.UUID
    role: str  # user | manager | admin


@dataclass(frozen=True)
class AuthenticatedUser:
    principal: Principal
    email: str


def _login_engine() -> Engine:
    from app.core.database import engine

    return engine


def authenticate_user(
    *,
    email: str,
    password: str,
    org_id: uuid.UUID | None = None,
    engine: Engine | None = None,
) -> AuthenticatedUser:
    """Verify credentials and return the beta identity.

    Runs the SECURITY DEFINER lookup outside rls_session because the org is not
    known yet. Never used for reads/writes of any other table.
    """
    bind = engine if engine is not None else _login_engine()
    with bind.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT user_id, org_id, email, role, password_hash
                FROM login_lookup_user(:email, CAST(:org_id AS uuid))
                """
            ),
            {"email": email.strip(), "org_id": str(org_id) if org_id else None},
        ).fetchall()

    if not rows:
        raise InvalidCredentialsError("invalid email or password")
    if len(rows) > 1:
        raise AmbiguousLoginError(
            "this email is registered in multiple organizations; include org_id"
        )

    row = rows[0]
    if not verify_password(password, row.password_hash):
        raise InvalidCredentialsError("invalid email or password")

    return AuthenticatedUser(
        principal=Principal(
            org_id=row.org_id,
            user_id=row.user_id,
            role=row.role,
        ),
        email=row.email,
    )


def get_or_create_dev_identity(db):
    """Return (organization, user) for local development, creating them once.

    Script-only bootstrap (seed/eval). Product requests authenticate with JWT
    and never call this. Caller must already be in
    rls_session(org_id=DEV_ORG_ID). Flush only. Idempotent.
    """
    from app.features.auth.models import Organization, User

    org = db.get(Organization, DEV_ORG_ID)
    if org is None:
        org = Organization(
            id=DEV_ORG_ID,
            name="Default Organization",
        )
        db.add(org)
        db.flush()

    user = db.query(User).filter_by(org_id=org.id, email=DEV_USER_EMAIL).first()
    if user is None:
        user = User(
            org_id=org.id,
            email=DEV_USER_EMAIL,
            role="admin",
            password_hash="dev-only-not-a-real-hash",
        )
        db.add(user)
        db.flush()

    return org, user
