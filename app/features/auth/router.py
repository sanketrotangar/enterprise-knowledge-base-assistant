# Auth Routes
# -----------
# Beta auth surface (Slice 2):
# - POST /api/v1/auth/login: email + password -> JWT (org_id, user_id, role)
# - GET  /api/v1/auth/me:    current identity (requires a valid token)
#
# Every other product route depends on `get_current_principal`, so a missing
# or invalid token is a 401 before any handler or DB query runs.

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.features.auth.deps import get_current_principal, get_db
from app.features.auth.models import User
from app.features.auth.schemas import LoginRequest, TokenResponse, UserResponse
from app.features.auth.service import (
    AmbiguousLoginError,
    InvalidCredentialsError,
    Principal,
    authenticate_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest) -> TokenResponse:
    try:
        authenticated = authenticate_user(
            email=req.email,
            password=req.password,
            org_id=req.org_id,
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except AmbiguousLoginError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    principal = authenticated.principal
    token = create_access_token(
        org_id=principal.org_id,
        user_id=principal.user_id,
        role=principal.role,
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse(
            id=principal.user_id,
            org_id=principal.org_id,
            email=authenticated.email,
            role=principal.role,
        ),
    )


@router.get("/me", response_model=UserResponse)
def me(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = db.get(User, principal.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return UserResponse(
        id=user.id,
        org_id=user.org_id,
        email=user.email,
        role=user.role,
    )
