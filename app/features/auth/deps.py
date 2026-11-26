# Auth dependencies
# -----------------
# JWT -> Principal -> RLS session. Routes depend on `get_current_principal` for
# identity and, when they need a session, on `get_db` (which already has
# app.org_id / app.role SET LOCAL for the request).
#
# Row visibility is still enforced by Postgres RLS (option B); a token only
# chooses which org/role the transaction runs as.

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.rls import rls_session
from app.core.security import CredentialsError, decode_access_token
from app.features.auth.service import Principal

_bearer_scheme = HTTPBearer(auto_error=False)

_NOT_AUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> Principal:
    """Verify the Bearer token and return the beta identity. 401 otherwise."""
    if credentials is None or (credentials.scheme or "").lower() != "bearer":
        raise _NOT_AUTHENTICATED
    try:
        payload = decode_access_token(credentials.credentials)
    except CredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    return Principal(
        org_id=payload.org_id,
        user_id=payload.user_id,
        role=payload.role,
    )


def require_manager_or_admin(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """JWT principal whose role may upload / delete / set document roles."""
    if principal.role not in {"manager", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires manager or admin role",
        )
    return principal


def get_db(principal: Principal = Depends(get_current_principal)) -> Session:
    """RLS-scoped session for the authenticated principal (one transaction)."""
    with rls_session(
        org_id=principal.org_id,
        role=principal.role,
        user_id=principal.user_id,
    ) as db:
        yield db
