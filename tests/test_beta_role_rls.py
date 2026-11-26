"""Slice 1 proofs: org isolation + chunk_role_access via app_user (no BYPASSRLS)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.rls import (
    UnsafeDatabaseRoleError,
    assert_runtime_role_is_safe,
    rls_session,
)
from tests.conftest import EMBEDDING_DIM, TENANT_A, TENANT_B


def _vec(seed: float) -> str:
    values = [seed] + [0.0] * (EMBEDDING_DIM - 1)
    return "[" + ",".join(str(v) for v in values) + "]"


def _ensure_org(engine: Engine, org_id: str, name: str) -> None:
    with rls_session(org_id=uuid.UUID(org_id), role="admin", engine=engine) as db:
        db.execute(
            text(
                """
                INSERT INTO organizations (id, name)
                VALUES (:id, :name)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": org_id, "name": name},
        )


def _ensure_user(engine: Engine, org_id: str) -> str:
    user_id = str(uuid.uuid4())
    with rls_session(org_id=uuid.UUID(org_id), role="admin", engine=engine) as db:
        existing = db.execute(
            text("SELECT id FROM users WHERE org_id = :o LIMIT 1"),
            {"o": org_id},
        ).scalar()
        if existing:
            return str(existing)
        db.execute(
            text(
                """
                INSERT INTO users (id, org_id, email, role, password_hash)
                VALUES (:id, :org_id, :email, 'admin', 'dev-only-not-a-real-hash')
                """
            ),
            {
                "id": user_id,
                "org_id": org_id,
                "email": f"admin-{org_id[:8]}@test",
            },
        )
    return user_id


def _insert_chunk(
    engine: Engine,
    *,
    org_id: str,
    content: str,
    roles: list[str],
) -> str:
    chunk_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    uploaded_by = _ensure_user(engine, org_id)
    with rls_session(org_id=uuid.UUID(org_id), role="admin", engine=engine) as db:
        db.execute(
            text(
                """
                INSERT INTO documents (
                    id, org_id, filename, disk_path, uploaded_by, status
                ) VALUES (
                    :id, :org_id, :filename, :path, :uploaded_by, 'ready'
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": doc_id,
                "org_id": org_id,
                "filename": content,
                "path": f"/tmp/{doc_id}",
                "uploaded_by": uploaded_by,
            },
        )
        for role in roles:
            db.execute(
                text(
                    """
                    INSERT INTO document_role_access (document_id, role, org_id)
                    VALUES (:d, :r, :o) ON CONFLICT DO NOTHING
                    """
                ),
                {"d": doc_id, "r": role, "o": org_id},
            )
        db.execute(
            text(
                """
                INSERT INTO chunks (
                    id, org_id, document_id, chunk_index, content, embedding
                ) VALUES (
                    :id, :org_id, :document_id, 0, :content,
                    CAST(:embedding AS vector)
                )
                """
            ),
            {
                "id": chunk_id,
                "org_id": org_id,
                "document_id": doc_id,
                "content": content,
                "embedding": _vec(1.0),
            },
        )
        for role in roles:
            db.execute(
                text(
                    """
                    INSERT INTO chunk_role_access (chunk_id, role, org_id)
                    VALUES (:c, :r, :o) ON CONFLICT DO NOTHING
                    """
                ),
                {"c": chunk_id, "r": role, "o": org_id},
            )
    return chunk_id


def test_runtime_role_is_app_user(app_engine: Engine) -> None:
    assert_runtime_role_is_safe(engine=app_engine)


def test_user_cannot_select_other_org_chunks(app_engine: Engine) -> None:
    _ensure_org(app_engine, TENANT_A, "Org A")
    _ensure_org(app_engine, TENANT_B, "Org B")
    _insert_chunk(
        app_engine, org_id=TENANT_A, content="a-secret", roles=["user", "manager", "admin"]
    )
    _insert_chunk(
        app_engine, org_id=TENANT_B, content="b-secret", roles=["user", "manager", "admin"]
    )

    with rls_session(org_id=uuid.UUID(TENANT_A), role="user", engine=app_engine) as db:
        rows = db.execute(text("SELECT content FROM chunks")).fetchall()
    got = {r.content for r in rows}
    assert "a-secret" in got
    assert "b-secret" not in got


def test_user_cannot_select_chunks_without_user_role(app_engine: Engine) -> None:
    _ensure_org(app_engine, TENANT_A, "Org A")
    _insert_chunk(
        app_engine, org_id=TENANT_A, content="managers-only", roles=["manager", "admin"]
    )
    _insert_chunk(
        app_engine,
        org_id=TENANT_A,
        content="all-roles",
        roles=["user", "manager", "admin"],
    )

    with rls_session(org_id=uuid.UUID(TENANT_A), role="user", engine=app_engine) as db:
        rows = db.execute(text("SELECT content FROM chunks")).fetchall()
    got = {r.content for r in rows}
    assert "all-roles" in got
    assert "managers-only" not in got


def test_manager_sees_manager_allowed_chunk(app_engine: Engine) -> None:
    _ensure_org(app_engine, TENANT_A, "Org A")
    _insert_chunk(app_engine, org_id=TENANT_A, content="mgr-doc", roles=["manager"])

    with rls_session(org_id=uuid.UUID(TENANT_A), role="manager", engine=app_engine) as db:
        rows = db.execute(text("SELECT content FROM chunks")).fetchall()
    assert "mgr-doc" in {r.content for r in rows}


def test_superuser_url_rejected(owner_engine: Engine) -> None:
    with pytest.raises(UnsafeDatabaseRoleError):
        assert_runtime_role_is_safe(engine=owner_engine)
