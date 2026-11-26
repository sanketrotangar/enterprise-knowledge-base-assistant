# Document management & ingestion — beta schema
# ----------------------------------------------
# Identity always comes from the JWT `Principal` (org / user / role); every DB
# operation runs inside `rls_session` so Postgres RLS decides visibility.
#
# Slice 3 surface (all synchronous DB work, async pipeline):
# - upload_documents: 1 file -> disk + pending row + role rows + ingest job
# - list_documents / preview_document: role-filtered by RLS
# - delete_document: hard delete (DB cascade) + wipe disk file
# - set_document_roles: rewrite document_role_access, enqueue sync job
#
# The worker entry points (`ingest_document`, `sync_chunk_roles`) live here too
# so Slice 4's consumer only has to dispatch job payloads to them.

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.file_store import (
    EmptyFileError,
    FileNotFoundInStoreError,
    FileTooLargeError,
    get_file_store,
)
from app.core.jobs import enqueue_ingest, enqueue_sync_chunk_roles
from app.core.rls import rls_session
from app.features.auth.service import Principal
from app.features.documents.chunker import chunk_text
from app.features.documents.models import Document, DocumentRoleAccess
from app.features.documents.parser import ParseError, parse_document
from app.features.documents.schemas import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    BETA_ROLES,
    PREVIEW_MAX_CHARS,
    DocumentNotFoundError,
    DocumentValidationError,
    UnsupportedFileTypeError,
)
from app.features.search.pg_chunks import Chunk, ChunkRoleAccess

logger = logging.getLogger(__name__)


class IngestPermanentError(Exception):
    """Document-level failure (corrupt file, empty text). Retrying cannot help."""


class IngestRetryableError(Exception):
    """Transient failure (DB/model/IO). The document stays `pending` to retry."""


def _validate_upload(file: UploadFile) -> str:
    """Return the lower-case suffix, or raise on type/size-safety problems."""
    original_name = file.filename or ""
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"File type '{suffix or 'unknown'}' not allowed. "
            f"Allowed: {sorted(ALLOWED_EXTENSIONS)}"
        )

    mime = (file.content_type or "").lower()
    if mime and mime != "application/octet-stream" and mime not in ALLOWED_MIME_TYPES:
        raise UnsupportedFileTypeError(f"Content type '{mime}' not allowed")
    return suffix


def _parse_beta_roles(role_access_csv: str) -> list[str]:
    return _validate_roles(
        [r.strip() for r in role_access_csv.split(",") if r.strip()],
        default_all=True,
    )


def _validate_roles(roles: list[str], *, default_all: bool = False) -> list[str]:
    invalid = [r for r in roles if r not in BETA_ROLES]
    if invalid:
        raise DocumentValidationError(
            f"Unknown roles: {invalid}. Allowed: {sorted(BETA_ROLES)}"
        )
    if not roles:
        # Upload without role_access keeps the legacy "open to all beta roles"
        # default; an explicit set-roles [] means manager/admin only.
        return sorted(BETA_ROLES) if default_all else []
    return sorted(set(roles))


def _doc_response(
    doc: Document,
    *,
    chunk_count: int = 0,
    roles: list[str] | None = None,
    file_size_bytes: int | None = None,
) -> dict:
    return {
        "id": doc.id,
        "title": doc.filename,
        "status": doc.status,
        "chunk_count": chunk_count,
        "file_size_bytes": file_size_bytes,
        "mime_type": None,
        "created_at": doc.created_at,
        "roles": roles or [],
    }


def _session(principal: Principal):
    return rls_session(
        org_id=principal.org_id,
        role=principal.role,
        user_id=principal.user_id,
    )


def _roles_for(db: Session, doc_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    if not doc_ids:
        return {}
    rows = (
        db.query(DocumentRoleAccess)
        .filter(DocumentRoleAccess.document_id.in_(doc_ids))
        .all()
    )
    roles: dict[uuid.UUID, list[str]] = defaultdict(list)
    for row in rows:
        roles[row.document_id].append(row.role)
    return {doc_id: sorted(values) for doc_id, values in roles.items()}


def _chunk_ids_for_document(
    db: Session, document_id: uuid.UUID
) -> list[uuid.UUID]:
    """All chunk ids of a document, independent of the caller's role grants.

    A plain SELECT is filtered by `chunks_select`, which requires a matching
    `chunk_role_access` row. Role sync exists precisely to change those rows,
    so it cannot rely on them; the SECURITY DEFINER lookup (migration 0007)
    returns ids only, scoped to the session's app.org_id.
    """
    rows = db.execute(
        text("SELECT id FROM list_document_chunk_ids(:d)"),
        {"d": str(document_id)},
    ).fetchall()
    return [row.id for row in rows]


def _chunk_counts(db: Session, doc_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not doc_ids:
        return {}
    rows = (
        db.query(Chunk.document_id, func.count())
        .filter(Chunk.document_id.in_(doc_ids))
        .group_by(Chunk.document_id)
        .all()
    )
    return {doc_id: count for doc_id, count in rows}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
def upload_documents(
    files: list[UploadFile],
    *,
    principal: Principal,
    role_access_csv: str = "",
    title: str | None = None,
) -> list[dict]:
    """Accept 1..N files: each becomes an independent pending document + job.

    Identity (org + uploader) comes from the JWT principal, never the form.
    Validation failures reject the request before anything is written.
    """
    if not files:
        raise DocumentValidationError("No files provided")

    roles = _parse_beta_roles(role_access_csv)
    prepared: list[tuple[UploadFile, str, str]] = []
    for file in files:
        suffix = _validate_upload(file)
        original_name = Path(file.filename or "untitled").name
        prepared.append((file, suffix, original_name))

    # A title override is only meaningful for a single file.
    single_title = title if len(prepared) == 1 else None
    results: list[dict] = []
    for file, suffix, original_name in prepared:
        results.append(
            _store_one(
                file,
                suffix=suffix,
                original_name=original_name,
                principal=principal,
                roles=roles,
                title=single_title,
            )
        )
    return results


def _store_one(
    file: UploadFile,
    *,
    suffix: str,
    original_name: str,
    principal: Principal,
    roles: list[str],
    title: str | None,
) -> dict:
    doc_id = uuid.uuid4()
    key = f"{principal.org_id}/{doc_id}{suffix}"
    store = get_file_store()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    try:
        stored = store.save(key, file.file, max_bytes=max_bytes)
    except FileTooLargeError as exc:
        raise DocumentValidationError(str(exc)) from exc
    except EmptyFileError as exc:
        raise DocumentValidationError(str(exc)) from exc

    try:
        with _session(principal) as db:
            db.add(
                Document(
                    id=doc_id,
                    org_id=principal.org_id,
                    uploaded_by=principal.user_id,
                    filename=(title or original_name)[:500],
                    disk_path=stored.path,
                    status="pending",
                )
            )
            for role in roles:
                db.add(
                    DocumentRoleAccess(
                        document_id=doc_id,
                        role=role,
                        org_id=principal.org_id,
                    )
                )
            db.flush()
            doc = db.get(Document, doc_id)
            response = _doc_response(
                doc, roles=roles, file_size_bytes=stored.size
            )
    except Exception:
        store.delete(stored.path)
        raise

    # UI must not wait on ingest: only publish the job and return `pending`.
    enqueue_ingest(document_id=doc_id, org_id=principal.org_id)
    return response


def reprocess_document(doc_id: str, *, principal: Principal) -> dict:
    """Re-enqueue ingestion by doc_id (disk + DB are the source of truth)."""
    parsed_id = uuid.UUID(str(doc_id))
    with _session(principal) as db:
        doc = db.get(Document, parsed_id)
        if doc is None:
            raise DocumentNotFoundError(f"Document {doc_id} not found")
        if doc.status == "failed":
            doc.error_message = None
            doc.status = "pending"
        response = _doc_response(
            doc,
            chunk_count=count_chunks(db, doc.id),
            roles=_roles_for(db, [doc.id]).get(doc.id, []),
        )
    enqueue_ingest(document_id=parsed_id, org_id=principal.org_id)
    return response


# ---------------------------------------------------------------------------
# List / preview
# ---------------------------------------------------------------------------
def list_documents(*, principal: Principal) -> list[dict]:
    """Documents the caller's role may see (RLS filters the rows)."""
    with _session(principal) as db:
        docs = db.query(Document).order_by(Document.created_at.desc()).all()
        ids = [doc.id for doc in docs]
        roles = _roles_for(db, ids)
        counts = _chunk_counts(db, ids)
        return [
            _doc_response(
                doc,
                chunk_count=counts.get(doc.id, 0),
                roles=roles.get(doc.id, []),
            )
            for doc in docs
        ]


def preview_document(doc_id: str, *, principal: Principal) -> dict:
    """Metadata + a text excerpt, only if the caller may see the document."""
    parsed_id = uuid.UUID(str(doc_id))
    with _session(principal) as db:
        doc = db.get(Document, parsed_id)
        if doc is None:
            # RLS-hidden and absent are indistinguishable: no existence leak.
            raise DocumentNotFoundError("Document not found")
        roles = _roles_for(db, [doc.id]).get(doc.id, [])
        chunk_count = count_chunks(db, doc.id)
        disk_path = doc.disk_path
        status = doc.status
        error = doc.error_message
        response = _doc_response(doc, chunk_count=chunk_count, roles=roles)

    try:
        raw_text = parse_document(get_file_store().local_path(disk_path))
    except (ParseError, FileNotFoundInStoreError) as exc:
        raise DocumentValidationError(f"Could not read file: {exc}") from exc

    truncated = len(raw_text) > PREVIEW_MAX_CHARS
    response.update(
        {
            "content": raw_text[:PREVIEW_MAX_CHARS],
            "truncated": truncated,
            "error": error if status == "failed" else None,
        }
    )
    return response


# ---------------------------------------------------------------------------
# Delete / roles
# ---------------------------------------------------------------------------
def delete_document(doc_id: str, *, principal: Principal) -> None:
    """Hard delete: DB row (chunks + role rows cascade), then wipe the file."""
    parsed_id = uuid.UUID(str(doc_id))
    with _session(principal) as db:
        doc = db.get(Document, parsed_id)
        if doc is None:
            raise DocumentNotFoundError("Document not found")
        disk_path = doc.disk_path
        db.delete(doc)
        db.flush()

    try:
        get_file_store().delete(disk_path)
    except OSError as exc:
        logger.warning("Document %s deleted but file %s remains: %s", doc_id, disk_path, exc)


def set_document_roles(
    doc_id: str, roles: list[str], *, principal: Principal
) -> dict:
    """Rewrite document_role_access now; let the worker re-copy to chunks."""
    parsed_id = uuid.UUID(str(doc_id))
    new_roles = _validate_roles([r.strip() for r in roles if r.strip()])

    with _session(principal) as db:
        doc = db.get(Document, parsed_id)
        if doc is None:
            raise DocumentNotFoundError("Document not found")
        db.query(DocumentRoleAccess).filter(
            DocumentRoleAccess.document_id == parsed_id
        ).delete(synchronize_session=False)
        for role in new_roles:
            db.add(
                DocumentRoleAccess(
                    document_id=parsed_id, role=role, org_id=principal.org_id
                )
            )
        db.flush()

    # Async on purpose: chunk_role_access converges in the role-sync worker.
    enqueue_sync_chunk_roles(document_id=parsed_id, org_id=principal.org_id)
    return {"id": parsed_id, "roles": new_roles}


# ---------------------------------------------------------------------------
# Worker entry points (Slice 4 dispatches to these)
# ---------------------------------------------------------------------------
def ingest_document(doc_id: str, *, principal: Principal) -> dict:
    """Parse → chunk → embed → store chunks + chunk_role_access. Idempotent."""
    parsed_id = uuid.UUID(str(doc_id))
    try:
        with _session(principal) as db:
            doc = db.get(Document, parsed_id)
            if doc is None:
                raise DocumentNotFoundError(f"Document {doc_id} not found")

            doc.status = "pending"
            doc.error_message = None
            db.flush()

            raw_text = parse_document(doc.disk_path)
            chunks = chunk_text(raw_text)
            if not chunks:
                raise DocumentValidationError("No content left after chunking")

            from app.features.search.embedder import embed_sync

            vectors = embed_sync(chunks)

            # Replace prior chunks (cascade removes chunk_role_access). This
            # cannot be a normal DELETE: Postgres applies chunks_select to the
            # scanned rows, and the old chunks may no longer be granted to this
            # worker role. The definer helper is scoped to this org+document.
            db.execute(
                text("SELECT delete_document_chunks(:d)"),
                {"d": str(doc.id)},
            )

            dra_roles = _roles_for(db, [doc.id]).get(doc.id) or sorted(BETA_ROLES)

            for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
                # Set id + created_at client-side on purpose: relying on the
                # created_at server default makes SQLAlchemy emit
                # `INSERT ... RETURNING`, and Postgres checks RETURNING against
                # the chunks SELECT policy — which needs chunk_role_access rows
                # that cannot exist until after this insert.
                row = Chunk(
                    id=uuid.uuid4(),
                    document_id=doc.id,
                    org_id=doc.org_id,
                    chunk_index=index,
                    content=chunk,
                    embedding=vector,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(row)
                db.flush()
                for role in dra_roles:
                    db.add(
                        ChunkRoleAccess(
                            chunk_id=row.id,
                            role=role,
                            org_id=doc.org_id,
                        )
                    )

            doc.status = "ready"
            doc.error_message = None
            db.flush()
            return _doc_response(
                doc, chunk_count=len(chunks), roles=dra_roles
            )

    except DocumentNotFoundError as exc:
        # Deleted between enqueue and execution: nothing to ingest or mark.
        raise IngestPermanentError(str(exc)) from exc
    except (ParseError, DocumentValidationError, FileNotFoundInStoreError) as exc:
        # Document-level failure: record it and keep the file on disk.
        _record_failure(parsed_id, principal, exc)
        raise IngestPermanentError(str(exc)) from exc
    except IngestRetryableError:
        raise
    except Exception as exc:
        # Transient (DB, model load, disk IO): leave status `pending` so the
        # worker can retry this document without touching the others.
        logger.warning("Transient ingest failure for %s: %s", doc_id, exc)
        raise IngestRetryableError(str(exc)) from exc


def sync_chunk_roles(doc_id: str, *, principal: Principal) -> bool:
    """Make chunk_role_access match document_role_access for one document."""
    parsed_id = uuid.UUID(str(doc_id))
    with _session(principal) as db:
        doc = db.get(Document, parsed_id)
        if doc is None:
            return False  # deleted before the job ran: nothing to sync

        roles = _roles_for(db, [doc.id]).get(doc.id, [])
        # Same reason as ingest: the current grants may not include the worker
        # role, so a plain chunks SELECT would hide the rows to be rewritten.
        chunk_ids = _chunk_ids_for_document(db, doc.id)
        if not chunk_ids:
            return True

        db.query(ChunkRoleAccess).filter(
            ChunkRoleAccess.chunk_id.in_(chunk_ids)
        ).delete(synchronize_session=False)
        for chunk_id in chunk_ids:
            for role in roles:
                db.add(
                    ChunkRoleAccess(
                        chunk_id=chunk_id, role=role, org_id=doc.org_id
                    )
                )
        db.flush()
    return True


def _record_failure(
    document_id: uuid.UUID, principal: Principal, exc: BaseException
) -> None:
    """Write `failed` + the error message in a fresh transaction.

    The ingest transaction has already rolled back, so this must be its own
    session. If even this write fails, surface it as retryable so the worker
    does not lose the failure state.
    """
    try:
        with _session(principal) as db:
            doc = db.get(Document, document_id)
            if doc is None:
                return
            doc.status = "failed"
            doc.error_message = str(exc)[:500]
            db.flush()
    except Exception as mark_exc:
        raise IngestRetryableError(
            f"could not record failure: {mark_exc}"
        ) from exc


def mark_document_failed(
    doc_id: str, *, principal: Principal, error: str
) -> None:
    """Worker helper: mark a document failed after retries are exhausted."""
    _record_failure(uuid.UUID(str(doc_id)), principal, RuntimeError(error))


def count_chunks(db: Session, document_id: uuid.UUID) -> int:
    return (
        db.query(func.count())
        .select_from(Chunk)
        .filter(Chunk.document_id == document_id)
        .scalar()
        or 0
    )
