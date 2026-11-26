"""Slice 3 proofs: disk store + document management API.

Covers:
- user role gets 403 on upload / delete / set roles
- upload writes disk + pending document + role rows, enqueues one job per file
  and returns before any ingestion
- list / preview are role-filtered by RLS (hidden document -> 404, no leak)
- delete removes the disk file and leaves no orphan chunks / role rows
- set-roles returns before chunks are re-copied; the sync handler converges
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.rls import rls_session
from app.core.security import hash_password
from app.features.auth.service import Principal
from app.features.documents.service import sync_chunk_roles
from tests.conftest import EMBEDDING_DIM, TENANT_A

PASSWORD = "slice3-test-password"


def _vec() -> str:
    return "[" + ",".join(["1.0"] + ["0.0"] * (EMBEDDING_DIM - 1)) + "]"


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


def _insert_chunk(engine: Engine, *, document_id: str, roles: list[str]) -> str:
    chunk_id = str(uuid.uuid4())
    with rls_session(org_id=uuid.UUID(TENANT_A), role="manager", engine=engine) as db:
        db.execute(
            text(
                """
                INSERT INTO chunks (
                    id, org_id, document_id, chunk_index, content, embedding
                ) VALUES (
                    :id, :org_id, :document_id, 0, 'chunk body',
                    CAST(:embedding AS vector)
                )
                """
            ),
            {
                "id": chunk_id,
                "org_id": TENANT_A,
                "document_id": document_id,
                "embedding": _vec(),
            },
        )
        for role in roles:
            db.execute(
                text(
                    "INSERT INTO chunk_role_access (chunk_id, role, org_id) "
                    "VALUES (:c, :r, :o)"
                ),
                {"c": chunk_id, "r": role, "o": TENANT_A},
            )
    return chunk_id


@pytest.fixture
def env(app_engine: Engine, tmp_path: Path, monkeypatch):
    import app.core.database as database

    monkeypatch.setattr(database, "engine", app_engine)

    from app.core.config import settings

    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(upload_root))

    jobs: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "app.features.documents.service.enqueue_ingest",
        lambda **kw: jobs.append(("ingest", kw)) or True,
    )
    monkeypatch.setattr(
        "app.features.documents.service.enqueue_sync_chunk_roles",
        lambda **kw: jobs.append(("sync_chunk_roles", kw)) or True,
    )

    _seed_org(app_engine)
    suffix = uuid.uuid4().hex[:8]
    identities = {
        "manager": _seed_user(
            app_engine, role="manager", email=f"mgr-{suffix}@test"
        ),
        "user": _seed_user(app_engine, role="user", email=f"user-{suffix}@test"),
        "manager_email": f"mgr-{suffix}@test",
        "user_email": f"user-{suffix}@test",
    }

    from app.main import app

    client = TestClient(app)
    identities["client"] = client
    identities["engine"] = app_engine
    identities["jobs"] = jobs
    identities["upload_root"] = upload_root
    return identities


def _login(env: dict, who: str) -> dict[str, str]:
    response = env["client"].post(
        "/api/v1/auth/login",
        json={"email": env[f"{who}_email"], "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(env: dict, headers: dict[str, str], files: list[tuple[str, bytes, str]], **form):
    data = {"role_access": "user,manager,admin", **form}
    payload = [("files", (name, body, mime)) for name, body, mime in files]
    return env["client"].post(
        "/api/v1/documents/upload",
        headers=headers,
        files=payload,
        data=data,
    )


def test_user_gets_403_on_upload_delete_and_set_roles(env) -> None:
    manager_headers = _login(env, "manager")
    user_headers = _login(env, "user")

    upload = _upload(env, user_headers, [("a.txt", b"hello", "text/plain")])
    assert upload.status_code == 403, upload.text

    created = _upload(env, manager_headers, [("b.txt", b"hello", "text/plain")])
    assert created.status_code == 201, created.text
    doc_id = created.json()["documents"][0]["id"]

    assert (
        env["client"].delete(
            f"/api/v1/documents/{doc_id}", headers=user_headers
        ).status_code
        == 403
    )
    assert (
        env["client"].put(
            f"/api/v1/documents/{doc_id}/roles",
            headers=user_headers,
            json={"roles": ["user"]},
        ).status_code
        == 403
    )
    assert env["jobs"] == [
        ("ingest", {"document_id": uuid.UUID(doc_id), "org_id": uuid.UUID(TENANT_A)})
    ]


def test_upload_is_multi_file_pending_and_enqueues_per_file(env) -> None:
    headers = _login(env, "manager")
    response = _upload(
        env,
        headers,
        [
            ("policy.txt", b"vacation policy text", "text/plain"),
            ("notes.md", b"# meeting notes", "text/markdown"),
        ],
        role_access="user,manager",
    )
    assert response.status_code == 201, response.text
    documents = response.json()["documents"]
    assert len(documents) == 2
    assert {doc["status"] for doc in documents} == {"pending"}
    assert all(doc["roles"] == ["manager", "user"] for doc in documents)
    assert [job[0] for job in env["jobs"]] == ["ingest", "ingest"]

    stored = sorted(
        str(path) for path in env["upload_root"].glob(f"{TENANT_A}/*")
    )
    assert len(stored) == 2
    assert all(Path(path).exists() for path in stored)
    bodies = {Path(path).read_bytes() for path in stored}
    assert bodies == {b"vacation policy text", b"# meeting notes"}

    with rls_session(
        org_id=uuid.UUID(TENANT_A), role="manager", engine=env["engine"]
    ) as db:
        for doc in documents:
            assert (
                db.execute(
                    text("SELECT count(*) FROM chunks WHERE document_id = :d"),
                    {"d": doc["id"]},
                ).scalar()
                == 0
            )


def test_list_and_preview_are_role_filtered(env) -> None:
    manager_headers = _login(env, "manager")
    user_headers = _login(env, "user")

    restricted = _upload(
        env,
        manager_headers,
        [("restricted.txt", b"restricted text", "text/plain")],
        role_access="manager,admin",
    )
    assert restricted.status_code == 201, restricted.text
    restricted_id = restricted.json()["documents"][0]["id"]

    shared = _upload(
        env,
        manager_headers,
        [("shared.txt", b"shared text", "text/plain")],
        role_access="user,manager,admin",
    )
    assert shared.status_code == 201, shared.text
    shared_id = shared.json()["documents"][0]["id"]

    listed = env["client"].get("/api/v1/documents", headers=user_headers)
    assert listed.status_code == 200, listed.text
    user_ids = {doc["id"] for doc in listed.json()}
    assert shared_id in user_ids
    assert restricted_id not in user_ids

    hidden = env["client"].get(
        f"/api/v1/documents/{restricted_id}/preview", headers=user_headers
    )
    assert hidden.status_code == 404

    visible = env["client"].get(
        f"/api/v1/documents/{shared_id}/preview", headers=user_headers
    )
    assert visible.status_code == 200, visible.text
    assert visible.json()["content"] == "shared text"
    assert visible.json()["truncated"] is False

    manager_list = env["client"].get("/api/v1/documents", headers=manager_headers)
    manager_ids = {doc["id"] for doc in manager_list.json()}
    assert {restricted_id, shared_id} <= manager_ids


def test_delete_removes_disk_file_and_leaves_no_chunks(env) -> None:
    headers = _login(env, "manager")
    created = _upload(
        env,
        headers,
        [("doomed.txt", b"delete me", "text/plain")],
        role_access="user,manager,admin",
    )
    doc_id = created.json()["documents"][0]["id"]

    stored = list(env["upload_root"].glob(f"{TENANT_A}/{doc_id}*"))
    assert len(stored) == 1 and stored[0].exists()

    _insert_chunk(env["engine"], document_id=doc_id, roles=["user", "manager", "admin"])

    deleted = env["client"].delete(
        f"/api/v1/documents/{doc_id}", headers=headers
    )
    assert deleted.status_code == 204, deleted.text

    assert not stored[0].exists()
    with rls_session(
        org_id=uuid.UUID(TENANT_A), role="manager", engine=env["engine"]
    ) as db:
        assert (
            db.execute(
                text("SELECT count(*) FROM chunks WHERE document_id = :d"),
                {"d": doc_id},
            ).scalar()
            == 0
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM document_role_access "
                    "WHERE document_id = :d"
                ),
                {"d": doc_id},
            ).scalar()
            == 0
        )
    assert (
        env["client"].get(
            f"/api/v1/documents/{doc_id}/preview", headers=headers
        ).status_code
        == 404
    )


def test_set_roles_returns_before_sync_then_worker_converges(env) -> None:
    headers = _login(env, "manager")
    created = _upload(
        env,
        headers,
        [("roles.txt", b"role sync body", "text/plain")],
        role_access="user,manager,admin",
    )
    doc_id = created.json()["documents"][0]["id"]
    _insert_chunk(
        env["engine"],
        document_id=doc_id,
        roles=["user", "manager", "admin"],
    )

    env["jobs"].clear()
    updated = env["client"].put(
        f"/api/v1/documents/{doc_id}/roles",
        headers=headers,
        json={"roles": ["manager"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["roles"] == ["manager"]
    assert env["jobs"] == [
        (
            "sync_chunk_roles",
            {"document_id": uuid.UUID(doc_id), "org_id": uuid.UUID(TENANT_A)},
        )
    ]

    # Chunks still carry the old copy: the API did not block on re-copying.
    def _chunk_roles() -> set[str]:
        with rls_session(
            org_id=uuid.UUID(TENANT_A), role="manager", engine=env["engine"]
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

    assert _chunk_roles() == {"user", "manager", "admin"}

    principal = Principal(
        org_id=uuid.UUID(TENANT_A),
        user_id=uuid.UUID(env["manager"]),
        role="manager",
    )
    assert sync_chunk_roles(doc_id, principal=principal) is True
    assert _chunk_roles() == {"manager"}

    # RLS: the user role loses the chunk after sync.
    with rls_session(
        org_id=uuid.UUID(TENANT_A), role="user", engine=env["engine"]
    ) as db:
        visible = db.execute(
            text("SELECT count(*) FROM chunks WHERE document_id = :d"),
            {"d": doc_id},
        ).scalar()
    assert visible == 0


def test_set_roles_empty_leaves_manager_admin_only(env) -> None:
    headers = _login(env, "manager")
    created = _upload(
        env,
        headers,
        [("closing.txt", b"closing doc", "text/plain")],
        role_access="user,manager,admin",
    )
    doc_id = created.json()["documents"][0]["id"]

    cleared = env["client"].put(
        f"/api/v1/documents/{doc_id}/roles",
        headers=headers,
        json={"roles": []},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["roles"] == []

    user_headers = _login(env, "user")
    assert (
        env["client"].get(
            f"/api/v1/documents/{doc_id}/preview", headers=user_headers
        ).status_code
        == 404
    )
    assert (
        env["client"].get(
            f"/api/v1/documents/{doc_id}/preview", headers=headers
        ).status_code
        == 200
    )


def test_manager_can_reprocess_without_inline_ingest(env) -> None:
    headers = _login(env, "manager")
    created = _upload(env, headers, [("later.txt", b"later", "text/plain")])
    doc_id = created.json()["documents"][0]["id"]
    env["jobs"].clear()

    response = env["client"].post(
        f"/api/v1/documents/{doc_id}/process", headers=headers
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "pending"
    assert [job[0] for job in env["jobs"]] == ["ingest"]
