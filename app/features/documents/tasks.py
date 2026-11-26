# Worker job dispatch — `ka:jobs` (Slice 4)
# ----------------------------------------
# The API only publishes payloads (`app/core/jobs.py`); this module is the
# worker-side mapping from payload -> document service entry point:
#
#   ingest(doc_id)            -> ingest_document: parse -> chunk -> embed ->
#                                chunks + chunk_role_access -> ready | failed
#   sync_chunk_roles(doc_id)  -> sync_chunk_roles: rewrite chunk_role_access
#                                from document_role_access
#
# System principal: a job carries org_id + document_id, not a user. RLS allows
# chunk writes only to manager/admin, so the worker runs as `admin` scoped to
# the job's org. `app.user_id` is not used by any policy; the nil UUID keeps
# the session contract intact while making "no human actor" explicit.
#
# Outcomes are raised as JobDropped / JobFailed / JobRetryable so the queue
# worker can decide between ack, drop and retry.

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.core.job_errors import JobDropped, JobFailed, JobRetryable
from app.core.jobs import JOB_INGEST, JOB_SYNC_CHUNK_ROLES
from app.features.auth.service import Principal
from app.features.documents.service import (
    IngestPermanentError,
    IngestRetryableError,
    ingest_document,
    mark_document_failed,
    sync_chunk_roles,
)

logger = logging.getLogger(__name__)

SYSTEM_ROLE = "admin"
SYSTEM_USER_ID = uuid.UUID(int=0)


def principal_from_job(job: dict[str, Any]) -> Principal:
    """Build the system principal for a job payload (raises JobDropped)."""
    try:
        org_id = uuid.UUID(str(job.get("org_id")))
        document_id = uuid.UUID(str(job.get("document_id")))
    except (TypeError, ValueError) as exc:
        raise JobDropped(f"invalid job identifiers: {exc}") from exc

    return Principal(
        org_id=org_id,
        user_id=SYSTEM_USER_ID,
        role=SYSTEM_ROLE,
    )


def run_job(job: dict[str, Any]) -> None:
    """Execute one job. Success returns; every failure raises a job error."""
    if not isinstance(job, dict):
        raise JobDropped(f"job must be an object, got {type(job).__name__}")

    job_type = str(job.get("type") or "").strip()
    if not job_type:
        raise JobDropped("job has no type")

    principal = principal_from_job(job)
    document_id = str(uuid.UUID(str(job["document_id"])))

    if job_type == JOB_INGEST:
        try:
            ingest_document(document_id, principal=principal)
        except IngestPermanentError as exc:
            # The service already recorded `failed` + the message.
            raise JobFailed(str(exc)) from exc
        except IngestRetryableError as exc:
            raise JobRetryable(str(exc)) from exc
        return

    if job_type == JOB_SYNC_CHUNK_ROLES:
        try:
            sync_chunk_roles(document_id, principal=principal)
        except Exception as exc:  # DB/IO only — no document-level failures here
            raise JobRetryable(f"role sync failed: {exc}") from exc
        return

    raise JobDropped(f"unknown job type {job_type!r}")


def fail_job(job: dict[str, Any], error: str) -> None:
    """After the retry cap: record a clean `failed` state for an ingest job.

    Role-sync jobs have no document status to update, so they only log.
    """
    if str(job.get("type") or "").strip() != JOB_INGEST:
        logger.error(
            "Job %s gave up after retries: %s", job.get("type"), error
        )
        return

    try:
        principal = principal_from_job(job)
    except JobDropped:
        logger.error("Cannot record failure for malformed job: %r", job)
        return

    mark_document_failed(
        str(job["document_id"]), principal=principal, error=error
    )
