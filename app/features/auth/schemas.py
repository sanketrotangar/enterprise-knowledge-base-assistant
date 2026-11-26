# Auth Schemas
# ------------
# Beta contracts for Slice 2.
#
# POST /api/v1/auth/login  -> TokenResponse (JWT + identity)
# GET  /api/v1/auth/me     -> UserResponse
#
# The JWT carries org_id, user_id, role; those are the only identity values
# applied to RLS sessions. org_id on LoginRequest is only needed when the same
# email exists in more than one organization.

from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=72)  # bcrypt byte limit
    org_id: UUID | None = None


class UserResponse(BaseModel):
    id: UUID
    org_id: UUID
    email: str
    role: str  # user | manager | admin


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: UserResponse
