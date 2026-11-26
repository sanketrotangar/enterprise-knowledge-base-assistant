#!/usr/bin/env python3
"""Ingest + role-sync worker (Slice 4).

Separate process from the API: it consumes the durable Redis queue that
`POST /documents/upload` and `PUT /documents/{id}/roles` publish to.

Usage:
  .venv/bin/python -m app.worker
  .venv/bin/python -m app.worker --once          # drain available jobs, exit
  .venv/bin/python -m app.worker --max-attempts 5 --retry-base-seconds 10

Requires the same .env (DATABASE_URL as app_user, CELERY_BROKER_URL for Redis)
as the API. Stop with Ctrl-C; the current job finishes, and any job interrupted
by a hard kill is requeued on the next start.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading

from app.core.database import check_database_connection
from app.core.rls import assert_runtime_role_is_safe
from app.core.worker import (
    MAX_ATTEMPTS,
    RETRY_BASE_SECONDS,
    JobWorker,
)

logger = logging.getLogger("app.worker")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Knowledge Assistant job worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="process currently available jobs and exit (useful for verification)",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=MAX_ATTEMPTS,
        help=f"total attempts per job before marking it failed (default {MAX_ATTEMPTS})",
    )
    parser.add_argument(
        "--retry-base-seconds",
        type=float,
        default=RETRY_BASE_SECONDS,
        help="first retry delay; doubles per attempt (default 5)",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Same safety bar as the API: the worker must never run as superuser /
    # BYPASSRLS / table owner, or RLS would stop protecting tenant data.
    try:
        check_database_connection()
        assert_runtime_role_is_safe()
    except Exception:
        logger.exception("Worker cannot start: database configuration is unsafe")
        return 1

    worker = JobWorker(
        max_attempts=args.max_attempts,
        retry_base_seconds=args.retry_base_seconds,
    )

    if args.once:
        recovered = worker.requeue_orphans()
        delayed = worker.drain_delayed()
        processed = worker.drain()
        logger.info(
            "One-shot run complete (recovered=%s delayed=%s processed=%s)",
            recovered,
            delayed,
            processed,
        )
        return 0

    stop = threading.Event()

    def _request_stop(signum: int, _frame) -> None:
        logger.info("Signal %s received: stopping after the current job", signum)
        stop.set()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    worker.run_forever(should_stop=stop.is_set)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
