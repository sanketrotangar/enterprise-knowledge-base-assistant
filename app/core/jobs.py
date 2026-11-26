# Durable job queue — publisher side (Slice 3) + shared key names (Slice 4)
# ------------------------------------------------------------------------
# Transport: Redis lists at CELERY_BROKER_URL (the broker Redis already used by
# docker-compose). Each job is one JSON object:
#   {"type": "ingest", "document_id": "<uuid>", "org_id": "<uuid>"}
#   {"type": "sync_chunk_roles", "document_id": "<uuid>", "org_id": "<uuid>"}
# The worker may add an "attempts" counter when it retries.
#
# `app/core/worker.py` consumes `ka:jobs`:
#   ka:jobs            pending jobs (FIFO: RPUSH, claimed from the left)
#   ka:jobs:processing claimed jobs; requeued on worker start (crash recovery)
#   ka:jobs:delayed    ZSET of retry jobs scored by ready-at (unix seconds)
#
# Durability rule from the plan: disk file + DB row are the source of truth.
# If Redis is unavailable the upload still commits (status `pending`) and the
# document can be re-enqueued by `doc_id` (POST /documents/{id}/process).

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

QUEUE_KEY = "ka:jobs"
PROCESSING_KEY = "ka:jobs:processing"
DELAYED_KEY = "ka:jobs:delayed"

JOB_INGEST = "ingest"
JOB_SYNC_CHUNK_ROLES = "sync_chunk_roles"


def _client() -> redis.Redis:
    return redis.Redis.from_url(
        settings.CELERY_BROKER_URL,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def _publish(job: dict[str, Any]) -> bool:
    try:
        _client().rpush(QUEUE_KEY, json.dumps(job))
        return True
    except redis.RedisError as exc:
        # Queue loss is recoverable (disk + DB keep the doc); do not fail the
        # HTTP write that already committed.
        logger.warning("Could not enqueue %s job: %s", job.get("type"), exc)
        return False


def enqueue_ingest(*, document_id: UUID | str, org_id: UUID | str) -> bool:
    return _publish(
        {
            "type": JOB_INGEST,
            "document_id": str(document_id),
            "org_id": str(org_id),
        }
    )


def enqueue_sync_chunk_roles(*, document_id: UUID | str, org_id: UUID | str) -> bool:
    return _publish(
        {
            "type": JOB_SYNC_CHUNK_ROLES,
            "document_id": str(document_id),
            "org_id": str(org_id),
        }
    )
