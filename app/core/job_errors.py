# Job outcome exceptions (Slice 4)
# --------------------------------
# Kept in core so the queue worker and the job dispatcher can share them
# without importing each other (core must not import feature modules).
#
#   JobDropped   -> malformed/unknown payload; ack and log, no retry
#   JobFailed    -> document-level failure already recorded; ack, no retry
#   JobRetryable -> transient failure; delay and retry up to the attempt cap


class JobError(Exception):
    """Base class for a non-successful job outcome."""


class JobDropped(JobError):
    """The payload is unusable (bad JSON shape, unknown type). Drop it."""


class JobFailed(JobError):
    """The job hit a permanent condition (bad file, empty content)."""


class JobRetryable(JobError):
    """A transient condition (DB/model/IO); the job may succeed later."""
