# Document schemas & validation — beta roles (user|manager|admin)

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/octet-stream",
}
# Beta document visibility roles (document_role_access)
BETA_ROLES = {"user", "manager", "admin"}

PREVIEW_MAX_CHARS = 5000


class DocumentValidationError(ValueError):
    """Bad input from the client (maps to HTTP 400 in the router)."""


class UnsupportedFileTypeError(DocumentValidationError):
    """File extension or content type outside the allowlist."""


class DocumentNotFoundError(ValueError):
    """Document is absent or invisible to the caller under RLS (maps to 404)."""


class DocumentResponse(BaseModel):
    """Upload / process response. title = filename for existing UI contracts."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str = Field(description="Display name; DB column filename")
    status: str  # pending|ready|failed
    chunk_count: int = 0
    file_size_bytes: int | None = None
    mime_type: str | None = None
    created_at: datetime | None = None
    roles: list[str] = Field(default_factory=list)


class UploadDocumentsResponse(BaseModel):
    """One entry per accepted file; each is an independent document/job."""

    documents: list[DocumentResponse]


class DocumentPreviewResponse(DocumentResponse):
    content: str
    truncated: bool = False
    error: str | None = None


class DocumentStatusResponse(BaseModel):
    id: UUID
    status: str
    chunk_count: int
    error: str | None = None


class DocumentRolesRequest(BaseModel):
    roles: list[str] = Field(
        description="Beta roles allowed to see the document: user, manager, admin"
    )


class DocumentRolesResponse(BaseModel):
    id: UUID
    roles: list[str]
