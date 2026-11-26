# Document Routes
# ----------------
# Thin HTTP layer: parse forms, map service errors to status codes, return
# schemas. No business logic here — that lives in service.py.
#
# Every route requires a valid JWT. Identity (org, uploader, role) comes from
# the token, never from the request body. Write routes additionally require
# manager/admin (defense in depth: RLS enforces the same rule in the DB).
#
# Endpoints (Slice 3):
# - POST   /api/v1/documents/upload           manager/admin, 1..N files
# - GET    /api/v1/documents                  list (role-filtered by RLS)
# - GET    /api/v1/documents/{id}/preview     metadata + text excerpt
# - GET    /api/v1/documents/{id}/status      processing status for polling
# - DELETE /api/v1/documents/{id}             manager/admin, hard delete
# - PUT    /api/v1/documents/{id}/roles       manager/admin, async chunk re-copy
# - POST   /api/v1/documents/{id}/process     manager/admin, re-enqueue ingest

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from app.core.rls import rls_session
from app.features.auth.deps import get_current_principal, require_manager_or_admin
from app.features.auth.service import Principal
from app.features.documents.models import Document
from app.features.documents.schemas import (
    DocumentNotFoundError,
    DocumentPreviewResponse,
    DocumentResponse,
    DocumentRolesRequest,
    DocumentRolesResponse,
    DocumentStatusResponse,
    DocumentValidationError,
    UploadDocumentsResponse,
)
from app.features.documents.service import (
    count_chunks,
    delete_document,
    list_documents,
    preview_document,
    reprocess_document,
    set_document_roles,
    upload_documents,
)

router = APIRouter(prefix="/documents", tags=["documents"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DocumentNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, DocumentValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Document operation failed")


@router.post(
    "/upload", response_model=UploadDocumentsResponse, status_code=201
)
async def upload_documents_endpoint(
    files: list[UploadFile] | None = File(None),
    file: UploadFile | None = File(None),  # single-file compatibility
    title: str | None = Form(None),
    sensitivity: str = Form("internal"),  # ignored; kept for form compat
    role_access: str = Form(""),  # comma-separated beta roles: user,manager,admin
    principal: Principal = Depends(require_manager_or_admin),
):
    """Accept files: each becomes an independent pending document + ingest job."""
    del sensitivity  # beta: access is document_role_access only
    uploads = list(files or [])
    if file is not None:
        uploads.append(file)

    try:
        documents = await asyncio.to_thread(
            upload_documents,
            uploads,
            principal=principal,
            role_access_csv=role_access,
            title=title,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return UploadDocumentsResponse(documents=documents)


@router.get("", response_model=list[DocumentResponse])
async def list_documents_endpoint(
    principal: Principal = Depends(get_current_principal),
):
    """List documents visible to the caller's role (RLS-filtered)."""
    try:
        return await asyncio.to_thread(list_documents, principal=principal)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/{doc_id}/preview", response_model=DocumentPreviewResponse)
async def preview_document_endpoint(
    doc_id: UUID,
    principal: Principal = Depends(get_current_principal),
):
    """Preview metadata + text, only if the caller's role may see the document."""
    try:
        return await asyncio.to_thread(
            preview_document, str(doc_id), principal=principal
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/{doc_id}/status", response_model=DocumentStatusResponse)
def get_document_status(
    doc_id: UUID,
    principal: Principal = Depends(get_current_principal),
):
    with rls_session(
        org_id=principal.org_id,
        role=principal.role,
        user_id=principal.user_id,
    ) as db:
        doc = db.get(Document, doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return DocumentStatusResponse(
            id=doc.id,
            status=doc.status,
            chunk_count=count_chunks(db, doc.id),
            error=doc.error_message,
        )


@router.delete("/{doc_id}", status_code=204)
async def delete_document_endpoint(
    doc_id: UUID,
    principal: Principal = Depends(require_manager_or_admin),
):
    """Hard delete: document row, chunks, role rows, and the disk file."""
    try:
        await asyncio.to_thread(delete_document, str(doc_id), principal=principal)
    except Exception as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)


@router.put("/{doc_id}/roles", response_model=DocumentRolesResponse)
async def set_document_roles_endpoint(
    doc_id: UUID,
    body: DocumentRolesRequest,
    principal: Principal = Depends(require_manager_or_admin),
):
    """Update document_role_access now; chunk re-copy happens in the worker."""
    try:
        return await asyncio.to_thread(
            set_document_roles, str(doc_id), body.roles, principal=principal
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{doc_id}/process", response_model=DocumentResponse, status_code=202)
async def process_document_endpoint(
    doc_id: UUID,
    principal: Principal = Depends(require_manager_or_admin),
):
    """Re-enqueue ingestion by doc_id (idempotent; does not block on the worker)."""
    try:
        return await asyncio.to_thread(
            reprocess_document, str(doc_id), principal=principal
        )
    except Exception as exc:
        raise _http_error(exc) from exc
