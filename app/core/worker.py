# Durable queue worker (Slice 4)
# ------------------------------
# Consumes JSON jobs from `ka:jobs` (see app/core/jobs.py) and dispatches them
# to app/features/documents/tasks.py.
#
# Durability model:
# - Claiming a job atomically moves it to `ka:jobs:processing` (BLMOVE), so a
#   crash cannot lose it: it is either done and acked, or still in-flight.
# - On start the worker requeues anything left in `processing` (orphans from a
#   killed worker). Handlers are idempotent, so a rare double run is safe.
# - Transient failures are delayed in `ka:jobs:delayed` (ZSET scored by
#   ready-at) and retried up to `max_attempts`, then recorded as failed.
# - Document-level failures are acked immediately: retrying cannot help.
#
# Concurrency: one worker process is the supported deployment. Multiple workers
# are safe correctness-wise (idempotent handlers) but orphan recovery could
# duplicate another live worker's in-flight job.

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Protocol

import redis

from app.core.config import settings
from app.core.job_errors import JobDropped, JobFailed, JobRetryable
from app.core.jobs import DELAYED_KEY, PROCESSING_KEY, QUEUE_KEY

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_BASE_SECONDS = 5.0
RETRY_MAX_SECONDS = 60.0
BLOCK_SECONDS = 5


class QueueClient(Protocol):
    """The slice of redis-py the worker uses (FakeRedis implements it in tests)."""

    def lmove(
        self,
        first_list: str,
        second_list: str,
        timeout: float | None = None,
        src: str = "LEFT",
        dest: str = "RIGHT",
    ) -> str | None: ...

    def blmove(
        self,
        first_list: str,
        second_list: str,
        timeout: float | None = None,
        src: str = "LEFT",
        dest: str = "RIGHT",
    ) -> str | None: ...

    def lrem(self, name: str, count: int, value: str) -> int: ...

    def rpush(self, name: str, *values: str) -> int: ...

    def zadd(self, name: str, mapping: dict[str, float]) -> int: ...

    def zrangebyscore(
        self,
        name: str,
        min: float | str,
        max: float | str,
        start: int | None = None,
        num: int | None = None,
    ) -> list[str]: ...

    def zrem(self, name: str, *values: str) -> int: ...


def build_redis() -> redis.Redis:
    """Blocking-safe client: the socket timeout must exceed BLMOVE's block."""
    return redis.Redis.from_url(
        settings.CELERY_BROKER_URL,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=BLOCK_SECONDS + 30,
    )


class JobWorker:
    def __init__(
        self,
        *,
        client: QueueClient | None = None,
        handler: Callable[[dict[str, Any]], None] | None = None,
        on_exhausted: Callable[[dict[str, Any], str], None] | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        retry_base_seconds: float = RETRY_BASE_SECONDS,
        retry_max_seconds: float = RETRY_MAX_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.client: QueueClient = client or build_redis()
        self._handler = handler
        self._on_exhausted = on_exhausted
        self.max_attempts = max_attempts
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.clock = clock

    # ------------------------------------------------------------------ queue

    def requeue_orphans(self) -> int:
        """Move jobs left in `processing` by a dead worker back onto the queue."""
        moved = 0
        while True:
            raw = self.client.lmove(PROCESSING_KEY, QUEUE_KEY, src="RIGHT", dest="LEFT")
            if raw is None:
                break
            moved += 1
        if moved:
            logger.warning(
                "Re-queued %s orphaned job(s) from %s", moved, PROCESSING_KEY
            )
        return moved

    def drain_delayed(self) -> int:
        """Promote delayed jobs whose backoff has elapsed."""
        moved = 0
        now = self.clock()
        while True:
            due = self.client.zrangebyscore(
                DELAYED_KEY, "-inf", now, start=0, num=1
            )
            if not due:
                break
            raw = due[0]
            # ZREM is the claim: only one worker may move this member.
            if not self.client.zrem(DELAYED_KEY, raw):
                continue
            self.client.rpush(QUEUE_KEY, raw)
            moved += 1
        return moved

    def process_next(self) -> bool:
        """Claim one queued job and handle it. False when the queue is empty."""
        raw = self.client.lmove(QUEUE_KEY, PROCESSING_KEY, src="LEFT", dest="RIGHT")
        if raw is None:
            return False
        self.handle_raw(raw)
        return True

    def drain(self) -> int:
        """Process every currently available job (non-blocking; for --once)."""
        processed = 0
        while self.process_next():
            processed += 1
        return processed

    def run_forever(
        self, *, should_stop: Callable[[], bool] | None = None
    ) -> None:
        recovered = self.requeue_orphans()
        logger.info(
            "Worker started (queue=%s recovered=%s)", QUEUE_KEY, recovered
        )
        while not (should_stop and should_stop()):
            self.drain_delayed()
            try:
                raw = self.client.blmove(
                    QUEUE_KEY,
                    PROCESSING_KEY,
                    timeout=BLOCK_SECONDS,
                    src="LEFT",
                    dest="RIGHT",
                )
            except redis.TimeoutError:
                continue
            except redis.RedisError as exc:
                logger.warning("Redis unavailable (%s); retrying in 2s", exc)
                time.sleep(2)
                continue
            if raw is None:
                continue
            self.handle_raw(raw)
        logger.info("Worker stopped")

    # --------------------------------------------------------------- handling

    def handle_raw(self, raw: str) -> None:
        try:
            job = json.loads(raw)
            if not isinstance(job, dict):
                raise ValueError("job is not a JSON object")
        except (TypeError, ValueError) as exc:
            logger.error("Dropping malformed job %r: %s", raw, exc)
            self._ack(raw)
            return

        try:
            self._dispatch(job)
        except JobDropped as exc:
            logger.warning("Dropping job %s: %s", job.get("type"), exc)
            self._ack(raw)
        except JobFailed as exc:
            logger.error("Job %s permanently failed: %s", job.get("type"), exc)
            self._ack(raw)
        except JobRetryable as exc:
            self._retry(raw, job, str(exc))
        except Exception as exc:  # defensive: never kill the loop
            logger.exception("Unexpected job error; treating as transient")
            self._retry(raw, job, f"{type(exc).__name__}: {exc}")
        else:
            self._ack(raw)

    def _dispatch(self, job: dict[str, Any]) -> None:
        if self._handler is not None:
            self._handler(job)
            return
        # Imported lazily so core stays free of feature imports at module load.
        from app.features.documents.tasks import run_job

        run_job(job)

    def _retry(self, raw: str, job: dict[str, Any], error: str) -> None:
        attempts = int(job.get("attempts") or 0) + 1
        if attempts >= self.max_attempts:
            try:
                self._fail(job, error)
            except Exception:  # noqa: BLE001 — ack anyway to avoid a poison loop
                logger.exception(
                    "Could not record failed state for job %s", job.get("document_id")
                )
            self._ack(raw)
            logger.error(
                "Job %s failed after %s attempt(s): %s",
                job.get("type"),
                attempts,
                error,
            )
            return

        job["attempts"] = attempts
        delay = min(
            self.retry_base_seconds * (2 ** (attempts - 1)),
            self.retry_max_seconds,
        )
        ready_at = self.clock() + delay
        self.client.zadd(DELAYED_KEY, {json.dumps(job): ready_at})
        self._ack(raw)
        logger.warning(
            "Retrying job %s in %.1fs (attempt %s/%s): %s",
            job.get("type"),
            delay,
            attempts,
            self.max_attempts,
            error,
        )

    def _fail(self, job: dict[str, Any], error: str) -> None:
        if self._on_exhausted is not None:
            self._on_exhausted(job, error)
            return
        from app.features.documents.tasks import fail_job

        fail_job(job, error)

    def _ack(self, raw: str) -> None:
        self.client.lrem(PROCESSING_KEY, 1, raw)
