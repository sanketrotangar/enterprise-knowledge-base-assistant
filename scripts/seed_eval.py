# Seed eval/corpus + eval/corpus_filler through the existing upload path as each
# doc's tenant.
# Uses rls_session (SET LOCAL). No superuser, no BYPASSRLS.
#
# Usage:
#   .venv/bin/python scripts/seed_eval.py
#   .venv/bin/python scripts/seed_eval.py --force

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starlette.datastructures import Headers, UploadFile

from app.core.eval_identity import (
    Principal,
    get_eval_tenant,
    get_or_create_eval_identity,
    get_or_create_eval_org,
    impersonate,
    impersonate_eval_user,
    load_eval_catalog,
)
from app.core.rls import rls_session_from_dev_identity
from app.features.auth.service import Principal as AuthPrincipal
from app.features.documents.models import Document
from app.features.documents.service import ingest_document, upload_documents
from scripts.eval_support import (
    SEED_CLEARANCE,
    load_seed_docs,
    write_manifest,
)


def _seed_identities() -> dict[str, dict]:
    tenants, users = load_eval_catalog()
    tenant_orgs: dict[str, str] = {}
    for tenant in tenants.values():
        with impersonate(
            Principal(
                tenant_id=tenant.uuid,
                department="general",
                clearance=SEED_CLEARANCE,
            )
        ):
            with rls_session_from_dev_identity() as db:
                org = get_or_create_eval_org(db, tenant)
                tenant_orgs[tenant.id] = str(org.id)
                print(f"tenant {tenant.id}: org={org.id}")

    user_rows: dict[str, dict] = {}
    for user in users.values():
        with impersonate_eval_user(user.id):
            with rls_session_from_dev_identity() as db:
                org, row = get_or_create_eval_identity(db, user)
                user_rows[user.id] = {
                    "id": str(row.id),
                    "org_id": str(org.id),
                    "tenant": user.tenant,
                    "department": user.department,
                }
                print(f"user {user.id}: {row.email} role={row.role}")
    return {"tenants": tenant_orgs, "users": user_rows}


def _uploader_id(tenant_key: str, user_rows: dict[str, dict]) -> str:
    for row in user_rows.values():
        if row["tenant"] == tenant_key:
            return row["id"]
    raise RuntimeError(f"no eval user in tenant {tenant_key}")


def _find_existing(title: str, org_id: str, department: str) -> Document | None:
    from uuid import UUID

    with impersonate(
        Principal(
            tenant_id=UUID(org_id),
            department=department,
            clearance=SEED_CLEARANCE,
        )
    ):
        with rls_session_from_dev_identity() as db:
            row = (
                db.query(Document)
                .filter(Document.org_id == UUID(org_id), Document.filename == title)
                .first()
            )
            if row is None:
                return None
            db.expunge(row)
            return row


async def _upload(doc: dict, org_id: str, uploaded_by: str) -> dict:
    from uuid import UUID

    tenant = get_eval_tenant(doc["tenant"])
    # Beta access is role-based; eval dept/clearance mapping rebuilt in Slice 7.
    payload = doc["body"].encode("utf-8")
    upload = UploadFile(
        file=io.BytesIO(payload),
        filename=f"{doc['id']}.md",
        headers=Headers({"content-type": "text/markdown"}),
        size=len(payload),
    )
    principal = AuthPrincipal(
        org_id=UUID(org_id),
        user_id=UUID(uploaded_by),
        role="admin",  # seeding is a manager/admin write
    )
    with impersonate(
        Principal(
            tenant_id=tenant.uuid,
            department=doc["department"],
            clearance=SEED_CLEARANCE,
        )
    ):
        # Upload now only enqueues; seeding runs ingest inline (Slice 7 will
        # rebuild this harness around JWT + the worker).
        result = await asyncio.to_thread(
            upload_documents,
            [upload],
            principal=principal,
            title=doc["title"],
            role_access_csv="",
        )
        return await asyncio.to_thread(
            ingest_document, result[0]["id"], principal=principal
        )


def _reingest(doc_id: str, org_id: str, uploaded_by: str, department: str) -> dict:
    from uuid import UUID

    with impersonate(
        Principal(
            tenant_id=UUID(org_id),
            department=department,
            clearance=SEED_CLEARANCE,
        )
    ):
        return ingest_document(
            doc_id,
            principal=AuthPrincipal(
                org_id=UUID(org_id),
                user_id=UUID(uploaded_by),
                role="admin",  # seeding is a manager/admin write
            ),
        )


def _stored_matches(existing: Document, body: str) -> bool:
    path = getattr(existing, "disk_path", None)
    if not path:
        return False
    stored = Path(path)
    if not stored.is_file():
        return False
    return stored.read_text(encoding="utf-8") == body


def _replace_stored_body(existing: Document, body: str) -> None:
    path = Path(existing.disk_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


async def _run(*, force: bool) -> None:
    identities = _seed_identities()
    corpus = load_seed_docs()
    manifest_docs: dict[str, dict] = {}

    for doc in corpus:
        org_id = identities["tenants"][doc["tenant"]]
        uploaded_by = _uploader_id(doc["tenant"], identities["users"])
        existing = _find_existing(doc["title"], org_id, doc["department"])
        if (
            existing is not None
            and existing.status == "ready"
            and not force
            and _stored_matches(existing, doc["body"])
        ):
            print(
                f"skip {doc['id']}: already ready as {existing.id} "
                f"({doc['word_count']} words)"
            )
            result_id = str(existing.id)
            status = existing.status
            chunk_count = 0
        elif existing is not None:
            print(f"re-ingest {doc['id']}: status={existing.status} force={force}")
            _replace_stored_body(existing, doc["body"])
            result = _reingest(
                str(existing.id), org_id, uploaded_by, doc["department"]
            )
            result_id = str(result["id"])
            status = result["status"]
            chunk_count = result["chunk_count"]
            print(f"  -> {result_id} status={status} chunks={chunk_count}")
        else:
            print(
                f"upload {doc['id']}: tenant={doc['tenant']} "
                f"dept={doc['department']} clearance={doc['clearance']} "
                f"({doc['word_count']} words)"
            )
            result = await _upload(doc, org_id, uploaded_by)
            result_id = str(result["id"])
            status = result["status"]
            chunk_count = result["chunk_count"]
            print(f"  -> {result_id} status={status} chunks={chunk_count}")

        manifest_docs[doc["id"]] = {
            "document_id": result_id,
            "title": doc["title"],
            "tenant": doc["tenant"],
            "department": doc["department"],
            "clearance": doc["clearance"],
            "doc_family": doc["doc_family"],
            "version": doc["version"],
            "canary": doc.get("canary") or "",
            "filler": bool(doc.get("filler")),
            "status": status,
            "chunk_count": chunk_count,
            "path": str(doc["path"].relative_to(doc["path"].parents[1])),
        }

    write_manifest({"docs": manifest_docs})
    print(f"wrote eval/seed_manifest.json ({len(manifest_docs)} docs)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed eval corpus via rls_session + upload path")
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-upload even if a document with the same title is already indexed",
    )
    args = parser.parse_args()
    asyncio.run(_run(force=args.force))


if __name__ == "__main__":
    main()
