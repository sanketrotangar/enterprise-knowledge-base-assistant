"""Slice 4 proofs: durable queue worker for ingest + role-sync jobs.

Covers:
- ingest job: parse -> chunk -> embed -> ready, chunks + chunk_role_access
- idempotency: replaying the same ingest job does not duplicate chunks
- corrupt document: failed (file kept), other document still ready
- transient failure: stays pending, job is retryable, a later attempt succeeds
- orphan recovery: a job left in `processing` by a killed worker is requeued
- retry/backoff: jobs move through the delayed set and fail after the cap
- sync_chunk_roles: chunk access follows document roles (RLS visibility flips)
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.job_errors import JobDropped, JobFailed, JobRetryable
from app.core.jobs import DELAYED_KEY, PROCESSING_KEY, QUEUE_KEY
from app.core.rls import rls_session
from app.core.security import hash_password
from app.core.worker import JobWorker
from app.features.documents.service import (
    IngestRetryableError,
    ingest_document,
)
from app.features.documents.tasks import run_job
from app.features.auth.service import Principal
from tests.conftest import EMBEDDING_DIM, TENANT_A

PASSWORD = "slice4-test-password"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _fake_embed(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    del batch_size
    return [[1.0] + [0.0] * (EMBEDDING_DIM - 1) for _ in texts]


def _seed_org(engine: Engine) -> None:
    with rls_session(org_id=uuid.UUID(TENANT_A), role="admin", engine=engine) as db:
        db.execute(
            text(
                "INSERT INTO organizations (id, name) VALUES (:id, 'Org A') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": TENANT_A},
        )


def _seed_user(engine: Engine, *, role: str, email: str) -> str:
    user_id = str(uuid.uuid4())
    with rls_session(org_id=uuid.UUID(TENANT_A), role="admin", engine=engine) as db:
        db.execute(
            text(
                """
                INSERT INTO users (id, org_id, email, role, password_hash)
                VALUES (:id, :org_id, :email, :role, :hash)
                """
            ),
            {
                "id": user_id,
                "org_id": TENANT_A,
                "email": email,
                "role": role,
                "hash": hash_password(PASSWORD),
            },
        )
    return user_id


def _job(doc_id: str, job_type: str = "ingest") -> dict:
    return {"type": job_type, "document_id": doc_id, "org_id": TENANT_A}


def _status(env: dict, doc_id: str) -> dict:
    response = env["client"].get(
        f"/api/v1/documents/{doc_id}/status", headers=env["manager_headers"]
    )
    assert response.status_code == 200, response.text
    return response.json()


def _chunk_count(env: dict, doc_id: str, *, role: str = "admin") -> int:
    with rls_session(
        org_id=uuid.UUID(TENANT_A), role=role, engine=env["engine"]
    ) as db:
        return int(
            db.execute(
                text("SELECT count(*) FROM chunks WHERE document_id = :d"),
                {"d": doc_id},
            ).scalar()
            or 0
        )


def _chunk_roles(env: dict, doc_id: str, *, role: str = "admin") -> set[str]:
    # Chunks are visible only to a role listed on chunk_role_access, so the
    # inspection session must run as a role that should see them.
    with rls_session(
        org_id=uuid.UUID(TENANT_A), role=role, engine=env["engine"]
    ) as db:
        rows = db.execute(
            text(
                """
                SELECT cra.role FROM chunk_role_access cra
                JOIN chunks c ON c.id = cra.chunk_id
                WHERE c.document_id = :d
                """
            ),
            {"d": doc_id},
        ).fetchall()
    return {row.role for row in rows}


@pytest.fixture
def env(app_engine: Engine, tmp_path: Path, monkeypatch):
    import app.core.database as database

    monkeypatch.setattr(database, "engine", app_engine)

    from app.core.config import settings

    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(upload_root))

    # The API enqueues; tests drive the worker directly.
    jobs: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "app.features.documents.service.enqueue_ingest",
        lambda **kw: jobs.append(("ingest", kw)) or True,
    )
    monkeypatch.setattr(
        "app.features.documents.service.enqueue_sync_chunk_roles",
        lambda **kw: jobs.append(("sync_chunk_roles", kw)) or True,
    )

    # No torch download in tests; deterministic 8-dim vectors.
    monkeypatch.setattr(
        "app.features.search.embedder.embed_sync", _fake_embed
    )

    _seed_org(app_engine)
    suffix = uuid.uuid4().hex[:8]
    manager_id = _seed_user(app_engine, role="manager", email=f"mgr-{suffix}@test")
    _seed_user(app_engine, role="user", email=f"user-{suffix}@test")

    from app.main import app

    client = TestClient(app)

    def login(who: str) -> dict[str, str]:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": f"{who}-{suffix}@test", "password": PASSWORD},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return {
        "engine": app_engine,
        "client": client,
        "manager_headers": login("mgr"),
        "user_headers": login("user"),
        "upload_root": upload_root,
        "jobs": jobs,
        "manager_id": manager_id,
    }


def _upload(env: dict, files: list[tuple[str, bytes, str]], **form) -> list[dict]:
    response = env["client"].post(
        "/api/v1/documents/upload",
        headers=env["manager_headers"],
        files=[("files", (name, body, mime)) for name, body, mime in files],
        data={"role_access": "user,manager,admin", **form},
    )
    assert response.status_code == 201, response.text
    return response.json()["documents"]


# --------------------------------------------------------------------------- #
# ingest
# --------------------------------------------------------------------------- #


def test_ingest_job_reaches_ready_with_chunks_and_roles(env) -> None:
    doc = _upload(env, [("policy.txt", b"vacation policy: 24 days", "text/plain")])[0]
    assert doc["status"] == "pending"

    run_job(_job(doc["id"]))

    assert _status(env, doc["id"])["status"] == "ready"
    chunks = _chunk_count(env, doc["id"])
    assert chunks > 0
    assert _chunk_roles(env, doc["id"]) == {"user", "manager", "admin"}

    # Replaying a job (lost ack, duplicate delivery) must be idempotent.
    run_job(_job(doc["id"]))
    assert _chunk_count(env, doc["id"]) == chunks


def test_corrupt_document_fails_without_affecting_the_other(env) -> None:
    docs = _upload(
        env,
        [
            ("good.txt", b"good document body", "text/plain"),
            ("broken.pdf", b"this is not a pdf", "application/pdf"),
        ],
    )
    good, broken = docs

    run_job(_job(good["id"]))
    with pytest.raises(JobFailed):
        run_job(_job(broken["id"]))

    assert _status(env, good["id"])["status"] == "ready"
    broken_status = _status(env, broken["id"])
    assert broken_status["status"] == "failed"
    assert broken_status["error"]
    assert _chunk_count(env, broken["id"]) == 0

    # Failed document keeps its file: an admin can fix/reprocess it later.
    good_file = list(env["upload_root"].glob(f"{TENANT_A}/{good['id']}*"))
    broken_file = list(env["upload_root"].glob(f"{TENANT_A}/{broken['id']}*"))
    assert len(good_file) == 1 and good_file[0].exists()
    assert len(broken_file) == 1 and broken_file[0].exists()


def test_transient_failure_stays_pending_then_retry_succeeds(env, monkeypatch) -> None:
    doc = _upload(env, [("retry.txt", b"retry me", "text/plain")])[0]

    def _embedding_down(texts: list[str], batch_size: int = 32):
        del texts, batch_size
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        "app.features.search.embedder.embed_sync", _embedding_down
    )

    with pytest.raises(JobRetryable):
        run_job(_job(doc["id"]))

    # Not a document error: status is still pending for the retry.
    assert _status(env, doc["id"])["status"] == "pending"
    assert _chunk_count(env, doc["id"]) == 0

    monkeypatch.setattr("app.features.search.embedder.embed_sync", _fake_embed)
    run_job(_job(doc["id"]))
    assert _status(env, doc["id"])["status"] == "ready"


def test_ingest_raises_retryable_for_transient_service_errors(env, monkeypatch) -> None:
    doc = _upload(env, [("svc.txt", b"service level", "text/plain")])[0]
    principal = Principal(
        org_id=uuid.UUID(TENANT_A),
        user_id=uuid.UUID(env["manager_id"]),
        role="admin",
    )

    def _boom(texts: list[str], batch_size: int = 32):
        del texts, batch_size
        raise RuntimeError("db hiccup")

    monkeypatch.setattr("app.features.search.embedder.embed_sync", _boom)
    with pytest.raises(IngestRetryableError):
        ingest_document(doc["id"], principal=principal)


# --------------------------------------------------------------------------- #
# role sync
# --------------------------------------------------------------------------- #


def test_sync_job_moves_chunk_access_between_roles(env) -> None:
    doc = _upload(env, [("sync.txt", b"role sync body", "text/plain")])[0]
    run_job(_job(doc["id"]))
    assert _chunk_roles(env, doc["id"]) == {"user", "manager", "admin"}
    assert _chunk_count(env, doc["id"], role="user") > 0

    # Manager restricts the document: API returns before the worker runs.
    response = env["client"].put(
        f"/api/v1/documents/{doc['id']}/roles",
        headers=env["manager_headers"],
        json={"roles": ["manager"]},
    )
    assert response.status_code == 200, response.text
    assert _chunk_roles(env, doc["id"]) == {"user", "manager", "admin"}

    run_job(_job(doc["id"], "sync_chunk_roles"))
    assert _chunk_roles(env, doc["id"], role="manager") == {"manager"}
    assert _chunk_count(env, doc["id"], role="user") == 0
    assert _chunk_count(env, doc["id"], role="manager") > 0

    # Grant it to `user`: after the sync job, chunks become visible to them.
    response = env["client"].put(
        f"/api/v1/documents/{doc['id']}/roles",
        headers=env["manager_headers"],
        json={"roles": ["user"]},
    )
    assert response.status_code == 200, response.text
    run_job(_job(doc["id"], "sync_chunk_roles"))

    assert _chunk_roles(env, doc["id"], role="user") == {"user"}
    assert _chunk_count(env, doc["id"], role="user") > 0
    assert _chunk_count(env, doc["id"], role="manager") == 0


def test_reingest_after_role_restriction_replaces_chunks_without_duplicates(env) -> None:
    doc = _upload(env, [("reingest.txt", b"reingest body", "text/plain")])[0]
    run_job(_job(doc["id"]))
    first_count = _chunk_count(env, doc["id"], role="user")
    assert first_count > 0

    # Roles now exclude the worker's admin role; the old chunks are invisible
    # to a plain admin SELECT, but re-ingest must still replace them.
    response = env["client"].put(
        f"/api/v1/documents/{doc['id']}/roles",
        headers=env["manager_headers"],
        json={"roles": ["user"]},
    )
    assert response.status_code == 200, response.text
    run_job(_job(doc["id"], "sync_chunk_roles"))
    run_job(_job(doc["id"]))

    assert _status(env, doc["id"])["status"] == "ready"
    assert _chunk_count(env, doc["id"], role="user") == first_count
    assert _chunk_roles(env, doc["id"], role="user") == {"user"}


def test_sync_job_for_deleted_document_is_a_noop(env) -> None:
    doc = _upload(env, [("gone.txt", b"delete soon", "text/plain")])[0]
    env["client"].delete(
        f"/api/v1/documents/{doc['id']}", headers=env["manager_headers"]
    )
    # No exception: the document was deleted before the job ran.
    run_job(_job(doc["id"], "sync_chunk_roles"))


# --------------------------------------------------------------------------- #
# queue mechanics (fake Redis)
# --------------------------------------------------------------------------- #


class FakeRedis:
    """Minimal in-memory stand-in for the redis-py calls the worker makes."""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.zsets: dict[str, dict[str, float]] = {}

    def _list(self, name: str) -> list[str]:
        return self.lists.setdefault(name, [])

    def lmove(
        self,
        first_list: str,
        second_list: str,
        timeout: float | None = None,
        src: str = "LEFT",
        dest: str = "RIGHT",
    ) -> str | None:
        del timeout
        source = self._list(first_list)
        target = self._list(second_list)
        if not source:
            return None
        value = source.pop(0) if src.upper() == "LEFT" else source.pop()
        if dest.upper() == "LEFT":
            target.insert(0, value)
        else:
            target.append(value)
        return value

    blmove = lmove

    def lrem(self, name: str, count: int, value: str) -> int:
        # The worker only ever removes one exact payload; `count` is unused.
        del count
        target = self._list(name)
        removed = 0
        while value in target:
            target.remove(value)
            removed += 1
        return removed

    def rpush(self, name: str, *values: str) -> int:
        target = self._list(name)
        target.extend(values)
        return len(target)

    def zadd(self, name: str, mapping: dict[str, float]) -> int:
        target = self.zsets.setdefault(name, {})
        added = 0
        for member, score in mapping.items():
            if member not in target:
                added += 1
            target[member] = score
        return added

    def zrangebyscore(
        self,
        name: str,
        min: float | str,
        max: float | str,
        start: int | None = None,
        num: int | None = None,
    ) -> list[str]:
        target = self.zsets.get(name, {})
        low = float("-inf") if min == "-inf" else float(min)
        high = float("inf") if max in ("+inf", float("inf")) else float(max)
        ordered = [
            member
            for _, member in sorted(
                (score, member) for member, score in target.items()
            )
            if low <= target[member] <= high
        ]
        if start is not None:
            ordered = ordered[start:]
        if num is not None:
            ordered = ordered[:num]
        return ordered

    def zrem(self, name: str, *values: str) -> int:
        target = self.zsets.setdefault(name, {})
        removed = 0
        for value in values:
            if value in target:
                del target[value]
                removed += 1
        return removed


def test_worker_requeues_orphaned_jobs() -> None:
    client = FakeRedis()
    raw = json.dumps(_job(str(uuid.uuid4())))
    client.rpush(PROCESSING_KEY, raw)

    worker = JobWorker(client=client, handler=lambda job: None)
    assert worker.requeue_orphans() == 1
    assert client.lists[QUEUE_KEY] == [raw]
    assert client.lists[PROCESSING_KEY] == []


def test_worker_retries_then_fails_after_the_cap() -> None:
    client = FakeRedis()
    now = [1_000.0]
    raw = json.dumps(_job(str(uuid.uuid4())))
    client.rpush(QUEUE_KEY, raw)

    seen: list[int] = []
    exhausted: list[str] = []

    def handler(job: dict) -> None:
        seen.append(int(job.get("attempts") or 0))
        raise JobRetryable("database unavailable")

    worker = JobWorker(
        client=client,
        handler=handler,
        on_exhausted=lambda job, error: exhausted.append(error),
        max_attempts=2,
        retry_base_seconds=5.0,
        clock=lambda: now[0],
    )

    assert worker.process_next() is True
    assert seen == [0]
    assert client.lists[PROCESSING_KEY] == []
    assert len(client.zsets[DELAYED_KEY]) == 1

    # Not due yet: the delayed set keeps it out of the queue.
    assert worker.drain_delayed() == 0
    assert client.lists[QUEUE_KEY] == []

    now[0] += 6
    assert worker.drain_delayed() == 1
    assert len(client.lists[QUEUE_KEY]) == 1

    assert worker.process_next() is True
    assert seen == [0, 1]
    assert exhausted == ["database unavailable"]
    assert client.lists[PROCESSING_KEY] == []
    assert client.zsets[DELAYED_KEY] == {}


def test_worker_drops_malformed_jobs() -> None:
    client = FakeRedis()
    client.rpush(QUEUE_KEY, "not json")
    worker = JobWorker(client=client, handler=lambda job: None)

    assert worker.process_next() is True
    assert client.lists[PROCESSING_KEY] == []
    assert client.lists[QUEUE_KEY] == []


def test_exhausted_ingest_is_marked_failed_with_the_error(env) -> None:
    from app.features.documents.tasks import fail_job

    doc = _upload(env, [("exhausted.txt", b"never embeds", "text/plain")])[0]
    fail_job(_job(doc["id"]), "model unavailable after 3 attempts")

    status = _status(env, doc["id"])
    assert status["status"] == "failed"
    assert "model unavailable" in (status["error"] or "")


def test_dispatch_rejects_unknown_job_types() -> None:
    with pytest.raises(JobDropped):
        run_job({"type": "nope", "document_id": str(uuid.uuid4()), "org_id": TENANT_A})
