# TEMPORARY — remove when JWT lands.
# ---------------------------------------------------------------------------
# Dev-only impersonation for the eval harness. A request may send
#   header  X-Eval-User: intern-hr
#   or query param  eval_user=intern-hr
# to run as a user from eval/users.yaml. Production (APP_ENV != development)
# ignores both. Never a superuser, never BYPASSRLS: we only pick which
# SET LOCAL values rls_session already applies.
# ---------------------------------------------------------------------------

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from uuid import UUID

from urllib.parse import parse_qs

from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

EVAL_USER_HEADER = "X-Eval-User"
EVAL_USER_PARAM = "eval_user"

# YAML clearance is 0-3. documents/chunks store 1-4 (public..restricted).
def eval_clearance_to_db(clearance: int) -> int:
    return int(clearance) + 1

REPO_ROOT = Path(__file__).resolve().parents[2]
USERS_YAML = REPO_ROOT / "eval" / "users.yaml"


@dataclass(frozen=True)
class EvalTenant:
    id: str
    uuid: UUID
    name: str
    slug: str


@dataclass(frozen=True)
class EvalUser:
    id: str
    tenant: str
    tenant_uuid: UUID
    name: str
    email: str
    department: str
    clearance: int
    role: str


@dataclass(frozen=True)
class Principal:
    """Who the current request/script SET LOCALs as."""

    tenant_id: UUID
    department: str
    clearance: int
    eval_user: EvalUser | None = None


_principal: ContextVar[Principal | None] = ContextVar("eval_principal", default=None)
_catalog: tuple[dict[str, EvalTenant], dict[str, EvalUser]] | None = None


def current_principal() -> Principal | None:
    return _principal.get()


def current_eval_user() -> EvalUser | None:
    principal = _principal.get()
    return None if principal is None else principal.eval_user


@contextmanager
def impersonate(principal: Principal) -> Iterator[None]:
    """Scripts: run a block as this principal (upload seed, in-process checks)."""
    token = _principal.set(principal)
    try:
        yield
    finally:
        _principal.reset(token)


@contextmanager
def impersonate_eval_user(user_id: str) -> Iterator[EvalUser]:
    user = get_eval_user(user_id)
    with impersonate(
        Principal(
            tenant_id=user.tenant_uuid,
            department=user.department,
            clearance=eval_clearance_to_db(user.clearance),
            eval_user=user,
        )
    ):
        yield user


def load_eval_catalog() -> tuple[dict[str, EvalTenant], dict[str, EvalUser]]:
    global _catalog
    if _catalog is not None:
        return _catalog

    import yaml

    if not USERS_YAML.is_file():
        raise FileNotFoundError(f"eval users file missing: {USERS_YAML}")

    raw = yaml.safe_load(USERS_YAML.read_text(encoding="utf-8")) or {}
    tenants: dict[str, EvalTenant] = {}
    for row in raw.get("tenants") or []:
        tenant = EvalTenant(
            id=str(row["id"]),
            uuid=UUID(str(row["uuid"])),
            name=str(row["name"]),
            slug=str(row["slug"]),
        )
        tenants[tenant.id] = tenant

    users: dict[str, EvalUser] = {}
    for row in raw.get("users") or []:
        tenant_id = str(row["tenant"])
        if tenant_id not in tenants:
            raise ValueError(f"eval user {row.get('id')!r} references unknown tenant {tenant_id!r}")
        tenant = tenants[tenant_id]
        user = EvalUser(
            id=str(row["id"]),
            tenant=tenant_id,
            tenant_uuid=tenant.uuid,
            name=str(row["name"]),
            email=str(row["email"]),
            department=str(row["department"]),
            clearance=int(row["clearance"]),
            role=str(row["role"]),
        )
        if not (0 <= user.clearance <= 3):
            raise ValueError(f"eval user {user.id}: clearance must be 0-3")
        users[user.id] = user

    _catalog = (tenants, users)
    return _catalog


def get_eval_user(user_id: str) -> EvalUser:
    _tenants, users = load_eval_catalog()
    if user_id not in users:
        known = ", ".join(sorted(users)) or "(none)"
        raise ValueError(f"unknown eval user {user_id!r}. Known: {known}")
    return users[user_id]


def get_eval_tenant(tenant_id: str) -> EvalTenant:
    tenants, _users = load_eval_catalog()
    try:
        return tenants[tenant_id]
    except KeyError as exc:
        known = ", ".join(sorted(tenants)) or "(none)"
        raise KeyError(f"unknown eval tenant {tenant_id!r}. Known: {known}") from exc


def get_or_create_eval_org(db: Session, tenant: EvalTenant):
    """Caller must already be in rls_session(tenant_id=tenant.uuid). Flush only."""
    from app.features.auth.models import Organization

    org = db.get(Organization, tenant.uuid)
    if org is None:
        org = Organization(
            id=tenant.uuid,
            name=tenant.name,
        )
        db.add(org)
        db.flush()
    return org


def get_or_create_eval_identity(db: Session, user: EvalUser):
    """Caller must already be in rls_session for this user's tenant. Flush only."""
    from app.features.auth.models import User

    tenant = get_eval_tenant(user.tenant)
    org = get_or_create_eval_org(db, tenant)
    # Map eval dept/clearance personas onto beta roles until eval world is rebuilt.
    beta_role = user.role if user.role in ("user", "manager", "admin") else "user"
    row = db.query(User).filter_by(org_id=org.id, email=user.email).first()
    if row is None:
        row = User(
            org_id=org.id,
            email=user.email,
            role=beta_role,
            password_hash="dev-only-not-a-real-hash",
        )
        db.add(row)
        db.flush()
    return org, row


def install_eval_user_middleware(app) -> None:
    """TEMPORARY. No-op unless APP_ENV=development."""
    from app.core.config import settings

    if settings.APP_ENV != "development":
        return
    app.add_middleware(EvalUserMiddleware)


class EvalUserMiddleware:
    """TEMPORARY — strip when JWT lands.

    Pure ASGI (not BaseHTTPMiddleware) so the ContextVar is visible to the
    request handler. Production never installs this.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers") or []
        }
        user_id = headers.get(EVAL_USER_HEADER.lower())
        if not user_id:
            qs = parse_qs(scope.get("query_string", b"").decode("latin-1"))
            user_id = (qs.get(EVAL_USER_PARAM) or [None])[0]
        if not user_id:
            await self.app(scope, receive, send)
            return

        try:
            user = get_eval_user(user_id.strip())
        except (KeyError, FileNotFoundError, ValueError) as exc:
            response = JSONResponse(status_code=400, content={"detail": str(exc)})
            await response(scope, receive, send)
            return

        token: Token = _principal.set(
            Principal(
                tenant_id=user.tenant_uuid,
                department=user.department,
                clearance=eval_clearance_to_db(user.clearance),
                eval_user=user,
            )
        )
        try:
            await self.app(scope, receive, send)
        finally:
            _principal.reset(token)
