# Security & Access Control Module
# ---------------------------------
# Authentication primitives shared by the auth feature:
# - bcrypt password hashing (12 salt rounds)
# - JWT access token creation / validation (HS256, SECRET_KEY)
#
# Tokens carry the beta identity used to SET LOCAL on every DB transaction:
#   sub      -> user_id
#   org_id   -> organization / tenant
#   role     -> user | manager | admin
#
# Authorization (which role may call which endpoint) stays in FastAPI
# dependencies; row-level access is enforced by Postgres RLS (option B).

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings
from app.core.rls import BETA_ROLES

ALGORITHM = "HS256"
BCRYPT_ROUNDS = 12
MAX_PASSWORD_BYTES = 72  # bcrypt limit

ACCESS_TOKEN_TYPE = "access"


class CredentialsError(Exception):
    """Invalid, expired, or malformed credentials (maps to HTTP 401)."""


@dataclass(frozen=True)
class TokenPayload:
    user_id: UUID
    org_id: UUID
    role: str


def _password_bytes(password: str) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password must be at most {MAX_PASSWORD_BYTES} bytes")
    return encoded


def hash_password(password: str) -> str:
    """Hash a password with bcrypt. Raises ValueError if it exceeds 72 bytes."""
    return bcrypt.hashpw(
        _password_bytes(password), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    ).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time bcrypt check. Any malformed input is a failed login."""
    try:
        return bcrypt.checkpw(
            _password_bytes(plain_password), hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


def create_access_token(
    *,
    org_id: UUID,
    user_id: UUID,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Mint a signed access token for one beta identity."""
    if role not in BETA_ROLES:
        raise ValueError(f"unknown beta role {role!r}")
    now = datetime.now(timezone.utc)
    expires = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    claims = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "role": role,
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> TokenPayload:
    """Verify signature/expiry and return the identity. Raises CredentialsError."""
    try:
        claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise CredentialsError("invalid or expired token") from exc

    if claims.get("type") != ACCESS_TOKEN_TYPE:
        raise CredentialsError("not an access token")
    role = claims.get("role")
    if role not in BETA_ROLES:
        raise CredentialsError("token role is not a beta role")
    try:
        return TokenPayload(
            user_id=UUID(str(claims["sub"])),
            org_id=UUID(str(claims["org_id"])),
            role=role,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise CredentialsError("token is missing identity claims") from exc
