"""Slice 2 proofs: login -> JWT claims -> RLS session identity.

Covers:
- login returns a signed token carrying org_id / user_id / role
- missing, malformed, and expired tokens are 401 on protected routes
- wrong password is 401 with no identity leak
- a token for org A never reads org B rows (RLS, via the real /status route
  and via a direct RLS session built from the token claims)
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.rls import rls_session
from app.core.security import create_access_token, decode_access_token, hash_password
from app.features.auth.service import Principal
from tests.conftest import TENANT_A, TENANT_B

PASSWORD = "slice2-test-password"


def _seed_org_user(
    engine: Engine,
    *,
    org_id: str,
    email: str,
    role: str,
    name: str,
) -> str:
    user_id = str(uuid.uuid4())
    with rls_session(org_id=uuid.UUID(org_id), role="admin", engine=engine) as db:
        db.execute(
            text(
                "INSERT INTO organizations (id, name) VALUES (:id, :name) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": org_id, "name": name},
        )
        db.execute(
            text(
                """
                INSERT INTO users (id, org_id, email, role, password_hash)
                VALUES (:id, :org_id, :email, :role, :hash)
                """
            ),
            {
                "id": user_id,
                "org_id": org_id,
                "email": email,
                "role": role,
                "hash": hash_password(PASSWORD),
            },
        )
    return user_id


def _seed_document(engine: Engine, *, org_id: str, uploaded_by: str, title: str) -> str:
    doc_id = str(uuid.uuid4())
    with rls_session(org_id=uuid.UUID(org_id), role="admin", engine=engine) as db:
        db.execute(
            text(
                """
                INSERT INTO documents (
                    id, org_id, filename, disk_path, uploaded_by, status
                ) VALUES (
                    :id, :org_id, :filename, :path, :uploaded_by, 'ready'
                )
                """
            ),
            {
                "id": doc_id,
                "org_id": org_id,
                "filename": title,
                "path": f"/tmp/{doc_id}.txt",
                "uploaded_by": uploaded_by,
            },
        )
        for role in ("user", "manager", "admin"):
            db.execute(
                text(
                    "INSERT INTO document_role_access (document_id, role, org_id) "
                    "VALUES (:d, :r, :o)"
                ),
                {"d": doc_id, "r": role, "o": org_id},
            )
    return doc_id


@pytest.fixture
def identities(app_engine: Engine):
    # Unique emails: the DB (and the org+email unique index) outlives each test.
    suffix = uuid.uuid4().hex[:8]
    email_a = f"mgr-a-{suffix}@test"
    email_b = f"mgr-b-{suffix}@test"
    a_user = _seed_org_user(
        app_engine, org_id=TENANT_A, email=email_a, role="manager", name="Org A"
    )
    b_user = _seed_org_user(
        app_engine, org_id=TENANT_B, email=email_b, role="manager", name="Org B"
    )
    a_doc = _seed_document(app_engine, org_id=TENANT_A, uploaded_by=a_user, title="A doc")
    b_doc = _seed_document(app_engine, org_id=TENANT_B, uploaded_by=b_user, title="B doc")
    return {
        "org_a": TENANT_A,
        "org_b": TENANT_B,
        "a_user": a_user,
        "b_user": b_user,
        "a_email": email_a,
        "b_email": email_b,
        "a_doc": a_doc,
        "b_doc": b_doc,
    }


@pytest.fixture
def client(app_engine: Engine, monkeypatch):
    # The app module builds its engine from .env; point it at the test DB.
    import app.core.database as database

    monkeypatch.setattr(database, "engine", app_engine)

    from app.main import app

    yield TestClient(app)


def _login(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_login_returns_jwt_with_identity(client, identities) -> None:
    body = _login(client, identities["a_email"])

    assert body["token_type"] == "bearer"
    assert body["user"] == {
        "id": identities["a_user"],
        "org_id": identities["org_a"],
        "email": identities["a_email"],
        "role": "manager",
    }

    payload = decode_access_token(body["access_token"])
    assert str(payload.user_id) == identities["a_user"]
    assert str(payload.org_id) == identities["org_a"]
    assert payload.role == "manager"


def test_wrong_password_is_401(client, identities) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": identities["a_email"], "password": "not-the-password"},
    )
    assert response.status_code == 401
    assert "access_token" not in response.text


def test_missing_malformed_and_expired_tokens_are_401(client, identities) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nope"}).status_code
        == 401
    )

    expired = create_access_token(
        org_id=uuid.UUID(identities["org_a"]),
        user_id=uuid.UUID(identities["a_user"]),
        role="manager",
        expires_delta=timedelta(minutes=-5),
    )
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}
    )
    assert response.status_code == 401


def test_me_returns_token_identity(client, identities) -> None:
    token = _login(client, identities["a_email"])["access_token"]
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == identities["a_email"]
    assert response.json()["org_id"] == identities["org_a"]


def test_org_a_token_cannot_read_org_b_document(client, identities) -> None:
    token = _login(client, identities["a_email"])["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    own = client.get(f"/api/v1/documents/{identities['a_doc']}/status", headers=headers)
    assert own.status_code == 200, own.text

    other = client.get(
        f"/api/v1/documents/{identities['b_doc']}/status", headers=headers
    )
    assert other.status_code == 404


def test_token_principal_never_sees_other_org_chunks(app_engine, identities) -> None:
    token = _login_identity_token(identities, org="a")
    payload = decode_access_token(token)
    principal = Principal(
        org_id=payload.org_id, user_id=payload.user_id, role=payload.role
    )

    with rls_session(
        org_id=principal.org_id, role=principal.role, engine=app_engine
    ) as db:
        orgs = {
            str(row.org_id)
            for row in db.execute(text("SELECT org_id FROM documents")).fetchall()
        }
    assert orgs <= {identities["org_a"]}


def _login_identity_token(identities, *, org: str) -> str:
    return create_access_token(
        org_id=uuid.UUID(identities[f"org_{org}"]),
        user_id=uuid.UUID(identities[f"{org}_user"]),
        role="manager",
    )
