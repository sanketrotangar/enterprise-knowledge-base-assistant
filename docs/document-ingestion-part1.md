# Part 1 — Document Ingestion Layer (with Contextual RAG)

> Scope: **upload → validate → metadata → parse → chunk → contextualize → embed → store (Postgres + Qdrant)**.
> No workers, no auth, no middlewares, no search — those come in later parts, per `md-files/technical-analysis.md`.

---

## 1. What we are and are NOT building now

| In this part | Explicitly deferred (and why) |
|---|---|
| DB creation (`ekb` database + tables, auto-created on startup) | **Celery/Redis workers** — the pipeline is a plain function; `tasks.py` stays a stub. When Celery arrives, a task just calls `ingest_document()`. No rewrite. |
| `organizations` + `users` tables (schema only — FK targets for uploads) | **Auth/RBAC** — no login, no middleware. Dev seed creates a default org/user. |
| Upload endpoint with validation + metadata | **Alembic migrations** — schema is still moving; `create_all` is cheaper during this phase. Introduce Alembic when the schema stabilizes (after auth). |
| PDF / TXT / MD parsing | **BM25/sparse vectors** — belongs to the search slice (Part 3). Dense-only now; collection is trivially recreated later. |
| Fixed-size chunking with overlap + sentence breaks | **Search/rerank/LLM-answer endpoints** — Parts 3–4. |
| Contextual chunk enrichment (Contextual RAG, LLM with heuristic fallback) | **S3 storage, caching, rate limiting, audit logs** — later phases per the analysis doc. |
| Embedding via `sentence-transformers` (all-MiniLM-L6-v2, 384-dim) | **List/delete document endpoints** — deletion semantics need RBAC; re-indexing is already covered by `POST /documents/{id}/process`. |
| Qdrant collection + chunk upsert + chunk rows in Postgres | **psql/Alembic seed scripts** — startup does it. |
| Smoke-test script + curl test flow | | 

**Contextual RAG in one paragraph** (the "contextual" part of this part): naive chunks lose context ("This applies to **them**" — who?). We prepend a short, LLM-generated *situation blurb* to every chunk before embedding (Anthropic's "contextual retrieval" approach). If `GROQ_API_KEY` is unset — or the LLM call fails — we fall back to a deterministic heuristic context (document title + tail of previous chunk + head of next chunk), so the pipeline is **fully testable offline** and upgrades to LLM context with zero code change.

---

## 2. File-by-file map — where code goes, and why

| # | File | Action | Why here / why not elsewhere |
|---|------|--------|------------------------------|
| 1 | `app/core/database.py` | **Edit** | Add `ensure_database()` + `init_db()`. DB bootstrap is core infrastructure, not a feature concern. Kept out of `main.py` (main only orchestrates startup). |
| 2 | `app/core/config.py` | **No change** | Already has everything (`DATABASE_URL`, `QDRANT_URL`, `EMBEDDING_*`, `UPLOAD_DIR`, `MAX_UPLOAD_SIZE_MB`; LLM key is now `GROQ_API_KEY` — see Part 3's provider note). |
| 3 | `app/features/auth/models.py` | **Fill** (currently comments) | `Organization` + `User` tables must exist before `documents` (FKs). The auth *feature* owns org/user domain models even while auth endpoints don't exist. Not put in `documents/models.py` — that would put another feature's domain inside this one. |
| 4 | `app/features/auth/service.py` | **Fill** (currently comments) | Dev-only identity seed (`get_or_create_dev_identity`). It creates org/user rows — that's auth-domain logic, so it lives here, clearly marked to be deleted/replaced in the auth phase. |
| 5 | `app/features/documents/models.py` | **Fill** | `Document` + `DocumentChunk` ORM models. Postgres is the source of truth for metadata; Qdrant only holds vectors+search payload. |
| 6 | `app/features/documents/parser.py` | **Fill** | Parsing is a documents-feature concern. Pure function of `(file_path) -> text`, no DB/Qdrant imports → unit-testable in isolation. |
| 7 | `app/features/documents/chunker.py` | **Fill** | Pure splitter, no I/O, no LLM. Deliberately kept LLM-free so it stays offline-testable (see #8). |
| 8 | `app/features/documents/contextualizer.py` | **New file** (only new file in `app/`) | Contextual RAG enrichment. **Name comes from the workspace's own spec** — `md-files/rag-architectures.md` §3, Step 2.1 mandates exactly this module; we stick to it. **Why a separate file:** the chunker must remain a pure, deterministic splitter; this module may call OpenAI and has fallback logic — different failure modes, different tests. **Deviation from the spec, on purpose:** the workspace version instantiates `AsyncOpenAI` at import time and has no failure path; ours adds a deterministic heuristic fallback so ingestion works (and is testable) offline and survives LLM outages. Everything else follows the spec. |
| 9 | `app/features/documents/schemas.py` | **Fill** | Pydantic request/response contracts + validation constants (allowed types, sensitivity levels, role tags). Router-layer contracts belong in schemas; constants here too so service can import them without hardcoding. |
| 10 | `app/features/documents/service.py` | **Fill** | `save_uploaded_document()` + `ingest_document()` — the orchestrator. **Why the pipeline lives here and not `tasks.py`:** `tasks.py` is Celery-shaped (retries, broker serialization, status plumbing). Without workers, using it would be fake async. The function boundary is already correct: a future Celery task wraps `ingest_document()` and nothing else changes. |
| 11 | `app/features/documents/router.py` | **Edit** | Thin HTTP layer: form parsing, status codes, `HTTPException` mapping. Business logic stays in service. |
| 12 | `app/features/search/embedder.py` | **Fill** | Embedding model loader + `embed()`. **Why in `search` and not `documents`:** per the analysis doc (T9), and because the *same model config* must embed queries at search time — one home prevents model/dimension drift. Import direction `documents → search` is accepted for now; if it bothers you later, move to `core/` (a 2-line change). |
| 13 | `app/core/qdrant.py` | **Fill** | Collection management + upsert + delete-by-document. All Qdrant access goes through this core module — features never build a raw client. |
| 14 | `app/main.py` | **Edit** | Lifespan calls `ensure_database → check_database_connection → init_db → dev seed`. Startup orchestration only. |
| 15 | `scripts/test_ingestion.py` | **New** (optional) | End-to-end smoke test that runs the pipeline directly (no HTTP). Lives outside `app/` because it's a dev tool, not shipping code. |

**Files deliberately left untouched** (all still comment-only stubs):

- `app/core/celery.py`, `app/features/documents/tasks.py` — no workers this phase.
- `app/core/cache.py`, `app/core/security.py` — no Redis usage, no auth this phase.
- `app/features/search/{router,service,schemas,reranker,llm,models}.py` — search is Part 3.
- `app/features/feedback/*`, `app/features/admin/*`, `app/features/audit/*` — later parts.
- `app/api.py` — already wires `documents_router`; nothing to change.
- `requirements.txt` — everything needed is already declared (including `openai` for contextual RAG).
- `docker-compose.yml` — unchanged, but see the warning in §5.

---

## 3. The code

Paste each block into the listed file, replacing the comment stubs.

### 3.1 `app/core/database.py` (edit — add two functions)

```python
# Database Configuration
# -----------------------
# SQLAlchemy engine setup, session management, and dev bootstrap helpers.
#
# Startup order (see app/main.py):
#   1. ensure_database()          -> create the DB itself if missing (dev convenience)
#   2. check_database_connection()-> verify connectivity
#   3. init_db()                  -> create tables from ORM models
#
# Why not Alembic yet: the schema is still moving during the ingestion phase;
# `create_all` (additive, creates missing tables only) is cheaper. Introduce
# Alembic once the schema stabilizes (after the auth phase).

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# Create engine with connection pooling
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative base for all feature models
Base = declarative_base()


def get_db():
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_database() -> None:
    """Create the database named in DATABASE_URL if it does not exist.

    Dev bootstrap convenience: a fresh Docker volume would otherwise fail the
    very first connect with 'database does not exist'. In production the DB is
    provisioned externally; guard this call with APP_ENV there if desired.
    """
    url = make_url(settings.DATABASE_URL)
    if not url.drivername.startswith("postgresql") or not url.database:
        return  # non-Postgres (e.g. sqlite in tests) manages its own files

    admin_url = url.set(database="postgres")  # always-present server DB
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            ).scalar()
            if not exists:
                # url.database comes from our own config, not user input;
                # double-quoting handles any hyphens in the name.
                conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin_engine.dispose()


def init_db() -> None:
    """Create any missing tables from the ORM models.

    Imports every model module so each class registers itself on
    Base.metadata before create_all runs. create_all is ADDITIVE: it creates
    missing tables but never alters existing ones — that's Alembic's job later.
    """
    from app.features.auth.models import Organization, User  # noqa: F401
    from app.features.documents.models import Document, DocumentChunk  # noqa: F401

    Base.metadata.create_all(bind=engine)


def check_database_connection() -> None:
    """Raise an exception when PostgreSQL is unavailable."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
```

### 3.2 `app/features/auth/models.py` (fill — schema only, no auth logic)

```python
# Organization & User Models (schema only)
# ----------------------------------------
# These two tables exist in THIS phase for one reason: `documents` has FK
# columns (org_id, uploaded_by) that need real target tables. Defining them
# now avoids painful ALTER TABLE migrations later and matches the schema in
# md-files/technical-analysis.md §3.1.
#
# There is NO auth logic here yet (no register/login/JWT). That arrives in the
# auth phase; only router/service/schemas in this feature will change.

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True)
    settings = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_users_org_email"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="employee")  # admin|manager|employee|intern
    department = Column(String(100))  # hr|engineering|finance|general
    manager_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    password_hash = Column(String(255), nullable=False, default="dev-only-not-a-real-hash")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

Note: **no `relationship()` declarations** anywhere in this phase — we navigate by FK ids (`doc.org_id`, `doc.uploaded_by`). Cross-feature relationships create import coupling between feature packages for zero benefit right now.

### 3.3 `app/features/auth/service.py` (fill — dev seed only)

```python
# Auth Feature Services
# ---------------------
# In this phase the ONLY function here is a dev-only identity bootstrap, used
# because uploads require valid org/user FK targets and auth does not exist
# yet. It is gated behind APP_ENV=development (see app/main.py) and will be
# deleted/replaced by real register/login logic in the auth phase.

from app.core.config import settings

DEV_ORG_SLUG = "default"
DEV_USER_EMAIL = "dev@local"


def get_or_create_dev_identity(db):
    """Return (organization, user) for local development, creating them once.

    Idempotent: safe to call on every startup and before every upload.
    """
    from app.features.auth.models import Organization, User

    org = db.query(Organization).filter_by(slug=DEV_ORG_SLUG).first()
    if org is None:
        org = Organization(name="Default Organization", slug=DEV_ORG_SLUG)
        db.add(org)
        db.flush()  # assign org.id before inserting the user

    user = db.query(User).filter_by(org_id=org.id, email=DEV_USER_EMAIL).first()
    if user is None:
        user = User(
            org_id=org.id,
            email=DEV_USER_EMAIL,
            name="Dev User",
            role="admin",
            department="general",
            password_hash="dev-only-not-a-real-hash",
        )
        db.add(user)

    db.commit()
    return org, user
```

### 3.4 `app/features/documents/models.py` (fill)

```python
# Document & Chunk Models
# -----------------------
# Postgres is the source of truth for document metadata and the chunk registry;
# Qdrant only holds vectors + a search payload. Two stores, on purpose:
#   - document_chunks maps doc -> qdrant point ids (enables deletes/re-index)
#   - payload in Qdrant carries what search needs at query time (Part 3)
#
# Gotcha: `metadata` is a RESERVED attribute name on SQLAlchemy's declarative
# Base, so the JSONB column named "metadata" is mapped under the attribute
# `meta`. Use doc.meta in code; the DB column is still `metadata`.

import uuid

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.core.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    source_type = Column(String(50), nullable=False, default="upload")  # upload|google_drive|notion|url
    storage_path = Column(String(1000), nullable=False)
    file_size_bytes = Column(BigInteger)
    mime_type = Column(String(100))
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    sensitivity = Column(String(50), nullable=False, default="internal", index=True)
    role_access = Column(ARRAY(String(50)), nullable=False, default=list)  # empty = all roles
    status = Column(String(50), nullable=False, default="uploaded", index=True)  # uploaded|processing|indexed|failed
    chunk_count = Column(Integer, nullable=False, default=0)
    meta = Column("metadata", JSONB, nullable=False, default=dict)  # see gotcha above
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    qdrant_point_id = Column(UUID(as_uuid=True), nullable=False, unique=True)  # point id in Qdrant
    chunk_index = Column(Integer, nullable=False)
    content_preview = Column(Text)          # first ~200 chars of the raw chunk
    context_header = Column(Text)           # LLM/heuristic context blurb (rag-architectures.md Step 2.2)
    contextualized_content = Column(Text)   # context_header + "\n\n" + raw chunk = what was embedded
    token_count = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

Why `role_access` is a Postgres `ARRAY` (not JSONB): the design doc says `VARCHAR(50)[]`, it validates element types, and we are Postgres-only (`psycopg` driver) so there's no portability concern.

### 3.5 `app/features/documents/parser.py` (fill)

```python
# Document Parser Service
# -----------------------
# Extracts raw text from stored files. Pure function of (file_path) -> text:
# no DB, no Qdrant, no network. That makes it trivially testable and lets the
# ingestion pipeline treat "get text" as a black box.
#
# Why pypdf and not unstructured/pymupdf: pypdf is already in requirements.txt,
# pure-Python (no system deps in Docker), and good enough for policy-style
# PDFs. Swap the implementation here later without touching the pipeline.

from pathlib import Path


class ParseError(Exception):
    """Raised when a file cannot be parsed."""


class UnsupportedFormatError(ParseError):
    """Raised for file types outside the allowlist."""


class EmptyDocumentError(ParseError):
    """Raised when a parsed document contains no extractable text."""


def parse_document(file_path: str | Path) -> str:
    """Extract text from a stored document. Raises a ParseError subclass on failure."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        text = _parse_pdf(path)
    elif suffix in {".txt", ".md"}:
        text = _parse_text(path)
    else:
        raise UnsupportedFormatError(f"Unsupported file type: '{suffix}'")

    if not text.strip():
        raise EmptyDocumentError("Document contains no extractable text")

    return text


def _parse_pdf(path: Path) -> str:
    # Imported lazily: pypdf (+ its deps) is only needed when a PDF is parsed.
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        # Join pages with a blank line so page boundaries don't glue sentences together.
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except ParseError:
        raise
    except Exception as exc:  # pypdf raises many unrelated exception types
        raise ParseError(f"Failed to parse PDF '{path.name}': {exc}") from exc


def _parse_text(path: Path) -> str:
    try:
        # errors="replace": never fail ingestion over one bad byte in a text file.
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ParseError(f"Failed to read text file '{path.name}': {exc}") from exc
```

### 3.6 `app/features/documents/chunker.py` (fill)

```python
# Text Chunker Service
# ---------------------
# Fixed-size, word-based chunking with overlap and sentence-boundary snapping.
# Deterministic and dependency-free (this module intentionally never touches
# the network or the LLM — see contextualizer.py for why that's separate).
#
# Why words, not exact tokens: MiniLM's limit is 512 tokens, and English text
# averages ~1.3 tokens/word, so 320 words ≈ 420 tokens sits safely under the
# cap without shipping a tokenizer dependency just for counting.
# Why overlap: a fact split across a boundary lives fully in at least one chunk.

CHUNK_SIZE_WORDS = 320   # ≈ 420 tokens, safely under MiniLM's 512-token limit
CHUNK_OVERLAP_WORDS = 40
_SENTENCE_CUT_ZONE = 0.8  # only shorten a window if a sentence ends in its last 20%
_SENTENCE_ENDINGS = (".", "!", "?")
_AVERAGE_TOKENS_PER_WORD = 1.3


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE_WORDS,
    overlap: int = CHUNK_OVERLAP_WORDS,
) -> list[str]:
    """Split text into overlapping word-window chunks.

    Each chunk is at most `chunk_size` words; when a sentence boundary appears
    near the end of a window, the window is shortened to end there. Adjacent
    chunks overlap by `overlap` words.
    """
    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        window = words[start:end]

        # Prefer cutting at a sentence boundary (only shortens the window).
        if end < len(words):
            cut = _last_sentence_end(window)
            if cut is not None:
                end = start + cut
                window = words[start:end]

        chunks.append(" ".join(window).strip())
        if end >= len(words):
            break
        start = max(end - overlap, start + 1)  # +1 guarantees forward progress

    return [c for c in chunks if c]


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token) stored on each chunk row."""
    return max(1, len(text) // 4)


def _last_sentence_end(window: list[str]) -> int | None:
    """Index just past the last sentence-ending word in the tail of `window`."""
    zone = int(len(window) * _SENTENCE_CUT_ZONE)
    for i in range(len(window) - 1, zone - 1, -1):
        if window[i].endswith(_SENTENCE_ENDINGS):
            return i + 1
    return None
```

### 3.7 `app/features/documents/contextualizer.py` (NEW file)

> Implements `md-files/rag-architectures.md` §3 (Architecture 2), Step 2.1 — with one deliberate addition: a heuristic fallback so the pipeline is testable without an API key.

```python
# Contextualizer — Contextual Chunk Enrichment (Contextual RAG)
# -------------------------------------------------------------
# Naive chunks lose context ("This applies to them" — who?). Per the
# contextual-retrieval approach (rag-architectures.md §3), we prepend a short
# blurb to every chunk that situates it within the document, and embed
# context + chunk together. All three texts are stored (Postgres columns
# context_header / contextualized_content + Qdrant payload keys) so search can
# use either representation later.
#
# Two strategies, chosen automatically:
#   1. LLM (Groq)    — used when GROQ_API_KEY is set; best quality. Groq speaks
#      the OpenAI API dialect, so the `openai` package works with a base_url.
#   2. Heuristic     — deterministic fallback (title + neighbor hints); used
#      when no API key is set OR the LLM call fails. This keeps ingestion
#      working (and testable) fully offline, and makes LLM outages non-fatal.
#
# Why a separate file: chunker.py must stay pure/deterministic; this module
# has network I/O, a prompt, and a fallback path — different failure modes,
# different tests.

from app.core.config import settings

# Only send the head of the document to the LLM: enough to situate typical
# policy docs, keeps per-chunk cost bounded for large files.
_MAX_DOC_CHARS_FOR_LLM = 8000
_MAX_CONTEXT_TOKENS = 120


def contextualize_chunks(title: str, full_text: str, chunks: list[str]) -> list[str]:
    """Return one context blurb per chunk (same order/length as `chunks`).

    Thin orchestrator over the spec's generate_chunk_context() (Step 2.1):
    batched here so a document is contextualized in one call, with a
    deterministic fallback when no API key is set or the LLM fails.
    """
    if not chunks:
        return []
    if settings.GROQ_API_KEY:
        try:
            return _llm_contexts(title, full_text, chunks)
        except Exception:
            pass  # ingestion must not die on an LLM outage — fall back below
    return _heuristic_contexts(title, chunks)


# --------------------------------------------------------------------------- #
# Strategy 1: LLM-generated context (rag-architectures.md Step 2.1)
# --------------------------------------------------------------------------- #

_LLM_SYSTEM_PROMPT = (
    "You write concise situating context for document chunks in a search index. "
    "Given a document and one chunk from it, reply with 2-3 sentences that place "
    "the chunk in context: what document it is from, what section/topic it covers, "
    "and what it applies to. Reply with the context ONLY — no preamble, no quotes."
)


def _llm_contexts(title: str, full_text: str, chunks: list[str]) -> list[str]:
    from openai import OpenAI  # lazy import: only when a key is configured

    # Groq hosts the same chat-completions API shape; only the endpoint moves.
    client = OpenAI(
        api_key=settings.GROQ_API_KEY, base_url=settings.GROQ_BASE_URL
    )
    doc_excerpt = full_text[:_MAX_DOC_CHARS_FOR_LLM]

    contexts: list[str] = []
    for chunk in chunks:
        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            temperature=0,
            max_tokens=_MAX_CONTEXT_TOKENS,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"<document>\n<title>{title}</title>\n{doc_excerpt}\n</document>\n"
                        f"Here is the chunk:\n<chunk>\n{chunk}\n</chunk>"
                    ),
                },
            ],
        )
        contexts.append(response.choices[0].message.content.strip())
    return contexts


# --------------------------------------------------------------------------- #
# Strategy 2: deterministic heuristic fallback
# --------------------------------------------------------------------------- #

_NEIGHBOR_WORDS = 12


def _heuristic_contexts(title: str, chunks: list[str]) -> list[str]:
    contexts: list[str] = []
    for i, chunk in enumerate(chunks):
        parts = [f"[Document: {title}]"]
        if i > 0:
            tail = " ".join(chunks[i - 1].split()[-_NEIGHBOR_WORDS:])
            parts.append(f"Continues from: ...{tail}")
        if i < len(chunks) - 1:
            head = " ".join(chunks[i + 1].split()[:_NEIGHBOR_WORDS])
            parts.append(f"Leads into: {head}...")
        contexts.append(" ".join(parts))
    return contexts
```

### 3.8 `app/features/documents/schemas.py` (fill)

```python
# Document Schemas & Validation Constants
# ---------------------------------------
# Pydantic response contracts + the validation allowlists shared by router and
# service. Keeping constants here (not in config) is deliberate: they are
# domain rules, not environment settings.

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# --- Validation constants -------------------------------------------------- #

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/octet-stream",  # common "unknown" type from curl/browsers; extension rules still apply
}
SENSITIVITY_LEVELS = {"public", "internal", "confidential", "restricted"}
ROLE_TAGS = {"hr", "engineering", "finance", "general"}


# --- Errors ---------------------------------------------------------------- #

class DocumentValidationError(ValueError):
    """Bad input from the client (maps to HTTP 400 in the router)."""


class UnsupportedFileTypeError(DocumentValidationError):
    """File extension or content type outside the allowlist."""


# --- Responses ------------------------------------------------------------- #

class DocumentResponse(BaseModel):
    """Returned by upload, process, and (fields subset) status."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    status: str
    chunk_count: int = 0
    file_size_bytes: int | None = None
    mime_type: str | None = None
    created_at: datetime | None = None


class DocumentStatusResponse(BaseModel):
    """Lightweight processing-status payload for polling."""

    id: UUID
    status: str
    chunk_count: int
    error: str | None = None  # metadata['last_error'], set when status == 'failed'
```

### 3.9 `app/features/search/embedder.py` (fill)

```python
# Embedding Service
# -----------------
# Single home for the embedding model so ingestion (chunk indexing) and search
# (query embedding) can never drift apart on model name or dimension.
#
# Lazy loading on purpose: importing sentence-transformers pulls in torch
# (~seconds + RAM). Uploads with process_now=False never pay that cost, and
# the model is loaded exactly once per process.

import asyncio
from functools import lru_cache

from app.core.config import settings

# NOTE: EMBEDDING_DIMENSION in config must match this model (384 for
# all-MiniLM-L6-v2). If you change the model, update the config AND delete the
# Qdrant collection (curl -X DELETE $QDRANT_URL/collections/enterprise_embeddings)
# so it is recreated with the right size.


@lru_cache(maxsize=1)
def get_model():
    from sentence_transformers import SentenceTransformer  # heavy import, deferred

    return SentenceTransformer(settings.EMBEDDING_MODEL)


def embed_sync(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Batch-encode texts (blocking). Used directly by workers/threads."""
    if not texts:
        return []
    vectors = get_model().encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return [v.tolist() for v in vectors]


async def embed(texts: list[str]) -> list[list[float]]:
    """Async wrapper: runs CPU-bound encoding in a thread so the event loop
    stays responsive. This is the function the pipeline calls."""
    return await asyncio.to_thread(embed_sync, texts)


async def embed_single(text: str) -> list[float]:
    return (await embed([text]))[0]
```

### 3.10 `app/core/qdrant.py` (fill)

```python
# Qdrant Client Service
# ---------------------
# The ONLY module that talks to Qdrant directly. Features import these
# functions; they never construct clients or filters themselves.
#
# This phase stores dense vectors only. Sparse (BM25) vectors for hybrid
# search belong to the search phase (Part 3) — adding a named sparse vector
# later means recreating the collection, which is trivial while the corpus is
# young. RBAC payload filtering fields are written NOW (org_id, sensitivity,
# role_access) even though nothing filters on them yet: payload is cheap to
# write, but backfilling 10k points later is not.

from datetime import datetime, timezone
from functools import lru_cache

from qdrant_client import QdrantClient, models

from app.core.config import settings

COLLECTION_NAME = "enterprise_embeddings"

# Payload fields indexed for fast filtered search later (Part 3).
_PAYLOAD_INDEX_FIELDS = ("org_id", "document_id", "sensitivity", "role_access")


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    return QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)


def ensure_collection() -> None:
    """Create the collection + payload indexes if they don't exist (idempotent)."""
    client = get_client()
    if client.collection_exists(COLLECTION_NAME):
        return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(
            size=settings.EMBEDDING_DIMENSION,
            distance=models.Distance.COSINE,
        ),
    )
    # KEYWORD index also works for keyword[] fields like role_access.
    for field in _PAYLOAD_INDEX_FIELDS:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )


def store_chunks(
    *,
    doc_id: str,
    org_id: str,
    title: str,
    sensitivity: str,
    role_access: list[str],
    source_type: str,
    chunks: list[str],
    contexts: list[str],
    vectors: list[list[float]],
    point_ids: list,
) -> int:
    """Upsert one point per chunk. `contextualized_content` (the embedded text)
    is exactly context + chunk — search must see what was embedded, never
    something else. Payload keys follow rag-architectures.md Step 2.4."""
    ingested_at = datetime.now(timezone.utc).isoformat()
    points = [
        models.PointStruct(
            id=str(point_id),
            vector=vector,
            payload={
                "document_id": doc_id,
                "org_id": org_id,
                "chunk_index": index,
                "contextualized_content": f"{context}\n\n{chunk}",  # must equal the embedded text
                "raw_content": chunk,
                "context_header": context,
                "title": title,
                "sensitivity": sensitivity,
                "role_access": role_access,
                "source_type": source_type,
                "ingested_at": ingested_at,
            },
        )
        for index, (chunk, context, vector, point_id) in enumerate(
            zip(chunks, contexts, vectors, point_ids)
        )
    ]
    get_client().upsert(collection_name=COLLECTION_NAME, points=points)
    return len(points)


def delete_document_points(doc_id: str) -> None:
    """Remove every point belonging to a document (called before re-upsert so
    re-ingesting is idempotent, and later by the delete endpoint)."""
    get_client().delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=doc_id),
                    )
                ]
            )
        ),
    )
```

### 3.11 `app/features/documents/service.py` (fill — the orchestrator)

```python
# Upload & Ingestion Service
# --------------------------
# Two entry points:
#   save_uploaded_document()  -> validate, stream file to disk, insert metadata row,
#                                optionally run the pipeline inline (process_now=True)
#   ingest_document()         -> parse -> chunk -> contextualize -> embed -> store
#
# NO CELERY IN THIS PHASE: ingest_document() is a plain sync function. The
# upload endpoint runs it via asyncio.to_thread (CPU-bound encoding must not
# block the event loop). When Celery arrives, a task in tasks.py will call this
# exact function — the boundary is already correct, nothing else changes.

import asyncio
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.qdrant import delete_document_points, ensure_collection, store_chunks
from app.features.auth.service import get_or_create_dev_identity
from app.features.documents.chunker import chunk_text, estimate_tokens
from app.features.documents.contextualizer import contextualize_chunks
from app.features.documents.models import Document, DocumentChunk
from app.features.documents.parser import parse_document
from app.features.documents.schemas import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    ROLE_TAGS,
    SENSITIVITY_LEVELS,
    DocumentValidationError,
    UnsupportedFileTypeError,
)

FILE_WRITE_CHUNK = 1024 * 1024  # stream uploads to disk in 1 MB pieces


# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #

def _validate_upload(file: UploadFile) -> None:
    """Extension is the hard rule; content type is checked only when it is a
    known, conflicting value (curl/browsers often send octet-stream)."""
    original_name = file.filename or ""
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"File type '{suffix or 'unknown'}' not allowed. "
            f"Allowed: {sorted(ALLOWED_EXTENSIONS)}"
        )

    mime = (file.content_type or "").lower()
    if mime and mime != "application/octet-stream" and mime not in ALLOWED_MIME_TYPES:
        raise UnsupportedFileTypeError(f"Content type '{mime}' not allowed")


async def save_uploaded_document(
    file: UploadFile,
    org_id: uuid.UUID | None = None,
    uploaded_by: uuid.UUID | None = None,
    title: str | None = None,
    sensitivity: str = "internal",
    role_access_csv: str = "",
    process_now: bool = True,
) -> dict:
    """Validate + persist an upload, then (optionally) run the ingestion pipeline.

    org_id/uploaded_by default to the dev identity when omitted (no auth yet).
    In the auth phase these params are removed and identity comes from the
    authenticated user instead.
    """
    _validate_upload(file)

    if sensitivity not in SENSITIVITY_LEVELS:
        raise DocumentValidationError(
            f"sensitivity must be one of {sorted(SENSITIVITY_LEVELS)}"
        )

    role_access = [r.strip() for r in role_access_csv.split(",") if r.strip()]
    invalid = [r for r in role_access if r not in ROLE_TAGS]
    if invalid:
        raise DocumentValidationError(
            f"Unknown role tags: {invalid}. Allowed: {sorted(ROLE_TAGS)}"
        )

    db = SessionLocal()
    dest: Path | None = None
    try:
        if org_id is None or uploaded_by is None:
            dev_org, dev_user = get_or_create_dev_identity(db)
            org_id = org_id or dev_org.id
            uploaded_by = uploaded_by or dev_user.id

        doc_id = uuid.uuid4()
        original_name = Path(file.filename or "untitled").name
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / f"{doc_id}_{original_name}"

        # Stream to disk in pieces — never hold a 50 MB file fully in memory.
        size = 0
        limit = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        too_big = False
        with dest.open("wb") as out:
            while True:
                piece = await file.read(FILE_WRITE_CHUNK)
                if not piece:
                    break
                size += len(piece)
                if size > limit:
                    too_big = True
                    break
                out.write(piece)

        if too_big or size == 0:
            raise DocumentValidationError(
                f"File exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit"
                if too_big
                else "Uploaded file is empty"
            )

        doc = Document(
            id=doc_id,
            org_id=org_id,
            title=(title or original_name)[:500],
            source_type="upload",
            storage_path=str(dest),
            file_size_bytes=size,
            mime_type=file.content_type,
            uploaded_by=uploaded_by,
            sensitivity=sensitivity,
            role_access=role_access,
            status="uploaded",
        )
        db.add(doc)
        db.commit()
    except Exception:
        db.rollback()
        if dest is not None:
            dest.unlink(missing_ok=True)  # never leave orphan files on failure
        raise
    finally:
        db.close()

    result = {
        "id": str(doc_id),
        "title": (title or original_name)[:500],
        "status": "uploaded",
        "chunk_count": 0,
        "file_size_bytes": size,
        "mime_type": file.content_type,
        "created_at": None,
    }

    if process_now:
        # Sync pipeline, moved off the event loop. Replaces the future
        # Celery dispatch: process_document_task.delay(str(doc_id)).
        result = await asyncio.to_thread(ingest_document, str(doc_id))

    return result


# --------------------------------------------------------------------------- #
# Ingestion pipeline (parse -> chunk -> contextualize -> embed -> store)
# --------------------------------------------------------------------------- #

def ingest_document(doc_id: str) -> dict:
    """Run the full pipeline for an already-uploaded document.

    Idempotent: existing Qdrant points and chunk rows for this document are
    replaced, so re-ingesting is safe.

    Raises ValueError if the document does not exist. On any pipeline error the
    document is marked status='failed' with the reason in metadata['last_error'].
    """
    db = SessionLocal()
    try:
        doc = db.get(Document, uuid.UUID(doc_id))
        if doc is None:
            raise ValueError(f"Document {doc_id} not found")

        doc.status = "processing"
        db.commit()

        try:
            # 1. Parse -----------------------------------------------------
            text = parse_document(doc.storage_path)

            # 2. Chunk -----------------------------------------------------
            chunks = chunk_text(text)
            if not chunks:
                raise DocumentValidationError("No content left after chunking")

            # 3. Contextualize (Contextual RAG) ----------------------------
            contexts = contextualize_chunks(doc.title, text, chunks)
            # Embed exactly what search will retrieve: context + chunk.
            embedded_texts = [
                f"{context}\n\n{chunk}" for context, chunk in zip(contexts, chunks)
            ]

            # 4. Embed -----------------------------------------------------
            # Import here (not module top): this module is imported by the
            # router at startup, and the embedder must stay lazy so a plain
            # upload/health check never loads torch.
            from app.features.search.embedder import embed_sync

            vectors = embed_sync(embedded_texts)

            # 5. Store: Qdrant points + Postgres chunk registry ------------
            ensure_collection()
            delete_document_points(str(doc.id))  # idempotent re-ingest

            point_ids = [uuid.uuid4() for _ in chunks]
            store_chunks(
                doc_id=str(doc.id),
                org_id=str(doc.org_id),
                title=doc.title,
                sensitivity=doc.sensitivity,
                role_access=doc.role_access or [],
                source_type=doc.source_type,
                chunks=chunks,
                contexts=contexts,
                vectors=vectors,
                point_ids=point_ids,
            )

            db.query(DocumentChunk).filter(
                DocumentChunk.document_id == doc.id
            ).delete()
            for index, (chunk, context, point_id) in enumerate(
                zip(chunks, contexts, point_ids)
            ):
                db.add(
                    DocumentChunk(
                        document_id=doc.id,
                        qdrant_point_id=point_id,
                        chunk_index=index,
                        content_preview=chunk[:200],
                        context_header=context,
                        contextualized_content=f"{context}\n\n{chunk}",
                        token_count=estimate_tokens(chunk),
                    )
                )

            doc.chunk_count = len(chunks)
            doc.status = "indexed"
            db.commit()

            return {
                "id": str(doc.id),
                "title": doc.title,
                "status": doc.status,
                "chunk_count": doc.chunk_count,
                "file_size_bytes": doc.file_size_bytes,
                "mime_type": doc.mime_type,
                "created_at": doc.created_at,
            }

        except Exception as exc:
            db.rollback()
            doc = db.get(Document, uuid.UUID(doc_id))
            if doc is not None:
                doc.status = "failed"
                doc.meta = {**(doc.meta or {}), "last_error": str(exc)[:500]}
                db.commit()
            raise

    finally:
        db.close()
```

Why the embedder import sits *inside* `ingest_document`: `service.py` is imported at app startup (via the router), and a top-level `from app.features.search.embedder import ...` would not itself load the model (that's lazy), but keeping the heavy dependency visible only on the pipeline path makes the laziness explicit and the import graph honest.

### 3.12 `app/features/documents/router.py` (edit — replace)

```python
# Document Routes
# ----------------
# Thin HTTP layer: parse forms, map service errors to status codes, return
# schemas. No business logic here — that lives in service.py.
#
# Endpoints in THIS phase:
# - POST /api/v1/documents/upload          multipart upload (+ optional inline processing)
# - POST /api/v1/documents/{id}/process    (re-)run ingestion for an uploaded document
# - GET  /api/v1/documents/{id}/status     processing status for polling
#
# Deliberately NOT here yet (later parts): list & delete — both need RBAC
# semantics from the auth phase to be meaningful.

import asyncio
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.features.documents.schemas import (
    DocumentResponse,
    DocumentStatusResponse,
    DocumentValidationError,
)
from app.features.documents.models import Document
from app.features.documents.service import ingest_document, save_uploaded_document
from app.core.database import get_db
from fastapi import Depends
from sqlalchemy.orm import Session

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    sensitivity: str = Form("internal"),
    role_access: str = Form(""),  # comma-separated tags, e.g. "hr,general"
    org_id: UUID | None = Form(None),      # optional until auth exists (dev seed default)
    uploaded_by: UUID | None = Form(None),  # optional until auth exists
    process_now: bool = Form(True),  # false = upload only, run pipeline via /process
):
    """Upload a document and (by default) run the full ingestion pipeline.

    Set process_now=false to stop after storing the file + metadata; useful
    for testing stages individually or for a future batch-processing UI.
    """
    try:
        return await save_uploaded_document(
            file=file,
            org_id=org_id,
            uploaded_by=uploaded_by,
            title=title,
            sensitivity=sensitivity,
            role_access_csv=role_access,
            process_now=process_now,
        )
    except DocumentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{doc_id}/process", response_model=DocumentResponse)
async def process_document(doc_id: UUID):
    """(Re-)run the ingestion pipeline for a stored document. Idempotent."""
    try:
        # Sync pipeline, off the event loop (embeddings are CPU-bound).
        return await asyncio.to_thread(ingest_document, str(doc_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DocumentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # parser/embedder/qdrant failures
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")


@router.get("/{doc_id}/status", response_model=DocumentStatusResponse)
def get_document_status(doc_id: UUID, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentStatusResponse(
        id=doc.id,
        status=doc.status,
        chunk_count=doc.chunk_count,
        error=(doc.meta or {}).get("last_error"),
    )
```

### 3.13 `app/main.py` (edit — replace lifespan section)

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import check_database_connection, ensure_database, init_db
from app.api import api_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 1. Make sure the database itself exists (dev convenience), then verify connectivity.
    ensure_database()
    check_database_connection()

    # 2. Create tables from ORM models (Alembic migrations arrive in a later phase).
    init_db()

    # 3. Dev-only: seed a default org + user so uploads have valid FK targets
    #    (auth does not exist yet). Removed/replaced in the auth phase.
    if settings.APP_ENV == "development":
        from app.core.database import SessionLocal
        from app.features.auth.service import get_or_create_dev_identity

        db = SessionLocal()
        try:
            get_or_create_dev_identity(db)
        finally:
            db.close()

    yield
    # Shutdown: cleanup resources


app = FastAPI(
    title="Enterprise Knowledge Assistant",
    version="0.1.0",
    description="RAG-based enterprise knowledge search with RBAC",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS.split(","),  # configurable, not hardcoded
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include central API router
app.include_router(api_router)
```

### 3.14 `scripts/test_ingestion.py` (NEW — optional smoke test)

Runs the pipeline end-to-end against real Postgres + Qdrant, **without HTTP and without an API key** (heuristic context path). Tests exactly what this part builds.

```python
# Ingestion smoke test
# --------------------
# Usage:
#   1. docker compose up -d db qdrant
#   2. python scripts/test_ingestion.py
#
# Exercises: upload validation -> disk save -> DB row -> parse -> chunk ->
# contextualize (heuristic, no API key needed) -> embed -> Qdrant upsert ->
# chunk registry. Verifies both stores afterwards.

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # import 'app' from repo root

from starlette.datastructures import UploadFile  # noqa: E402

from app.core.database import SessionLocal, ensure_database, init_db  # noqa: E402
from app.core.qdrant import get_client  # noqa: E402
from app.features.auth.service import get_or_create_dev_identity  # noqa: E402
from app.features.documents.models import Document, DocumentChunk  # noqa: E402
from app.features.documents.service import save_uploaded_document  # noqa: E402

SAMPLE_TEXT = (
    "# Leave Policy\n\n"
    "Employees are entitled to 24 paid leave days per calendar year. "
    "Unused days up to 6 may be carried into the next year. "
    "Sick leave requires notification to the manager before 9 AM. "
) * 30  # repeat so several chunks are produced


def main() -> None:
    ensure_database()
    init_db()

    db = SessionLocal()
    try:
        get_or_create_dev_identity(db)
    finally:
        db.close()

    upload = UploadFile(
        file=io.BytesIO(SAMPLE_TEXT.encode("utf-8")),
        filename="leave-policy.txt",
    )

    result = __import__("asyncio").run(
        save_uploaded_document(file=upload, title="Leave Policy")
    )
    print(f"upload result : status={result['status']} chunks={result['chunk_count']}")

    doc_id = result["id"]
    db = SessionLocal()
    try:
        doc = db.get(Document, __import__("uuid").UUID(doc_id))
        print(f"postgres      : status={doc.status} chunk_count={doc.chunk_count}")
        assert doc.status == "indexed", f"expected 'indexed', got '{doc.status}'"
        rows = db.query(DocumentChunk).filter_by(document_id=doc.id).count()
        assert rows == doc.chunk_count, "chunk rows do not match chunk_count"
    finally:
        db.close()

    points = get_client().count(
        collection_name="enterprise_embeddings", exact=True
    ).count
    print(f"qdrant points : {points} (across all documents)")
    assert points >= doc.chunk_count, "fewer points than expected"

    print("\nOK — ingestion pipeline works end to end.")


if __name__ == "__main__":
    main()
```

---

## 4. Design decisions worth remembering

1. **Pipeline = plain function, not a Celery task (for now).** The whole flow lives in `ingest_document()`. The upload endpoint runs it via `asyncio.to_thread`. When Celery arrives: `tasks.py` gains one 5-line task calling it, and the endpoint swaps `to_thread` for `.delay()`. Nothing else moves. This is why `tasks.py` stays a stub instead of being filled with fake async.
2. **`context + chunk` is the embedded text everywhere.** The embedder sees `f"{context}\n\n{chunk}"`, and Qdrant payload `contextualized_content` stores the identical string. If those ever diverge, search quality bugs become undebuggable — hence the comment in `store_chunks`.
3. **All three texts stored (per rag-architectures.md Step 2.4).** `contextualized_content` (what was embedded) and `raw_content` in the Qdrant payload; `context_header`, `contextualized_content`, and `content_preview` in Postgres. Cheap debugging now, and Part 3 can experiment with BM25 over raw vs contextual text without re-ingesting.
4. **Heuristic fallback is a feature, not a hack.** It makes this part testable with zero API keys and keeps ingestion alive during LLM outages. Setting `GROQ_API_KEY` in `.env` upgrades quality with no code change (Groq is OpenAI-compatible — see Part 3's provider note).
5. **RBAC payload fields written now, filtered later.** `org_id`/`sensitivity`/`role_access` cost nothing per point now; backfilling them after 10k docs would require a full re-embed. Filtering arrives with search (Part 3) once auth exists.
6. **Validation order:** extension (hard rule) → content-type (only when it's a known conflicting value) → size (enforced while streaming, not from headers, which can lie) → sensitivity/role tags → empty text after parsing.
7. **Cleanup guarantees:** failed upload → file deleted; failed pipeline → document marked `failed` with the reason in `metadata.last_error` (visible via `/status`), file kept so you can retry via `/process`.
8. **Re-ingestion is idempotent** by design: `delete_document_points()` before upsert, chunk rows deleted before re-insert. Needed the first time you tweak chunk size or swap the embedding model.

---

## 5. Run & test

**⚠️ Gotcha:** `docker compose up` (everything) will start `celery_worker`, which crash-loops because `app/core/celery.py` is still a stub. Start only what Part 1 needs:

```bash
# 1. Infrastructure (no redis needed yet!)
docker compose up -d db qdrant

# 2. App (first run: pip install -r requirements.txt)
uvicorn app.main:app --reload
# Startup log should show: DB ensured -> tables created -> dev org/user seeded

# 3. Upload + ingest (org_id/uploaded_by omitted -> dev seed used)
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@./uploads/sample.txt" \
  -F "title=Leave Policy" \
  -F "sensitivity=internal"
# -> {"id":"...","status":"indexed","chunk_count":N,...}   (first call downloads the model, ~80MB, once)

# 4. Check status / re-run pipeline
curl http://localhost:8000/api/v1/documents/<DOC_ID>/status
curl -X POST http://localhost:8000/api/v1/documents/<DOC_ID>/process

# 5. Verify the stores directly
curl -s -X POST http://localhost:6333/collections/enterprise_embeddings/points/count \
  -H 'Content-Type: application/json' -d '{"exact": true}'     # -> {"count": N}

docker exec -it <pg-container> psql -U postgres -d ekb \
  -c "select id, title, status, chunk_count from documents;"
# (adapt container name/user to YOUR running Postgres — see commands.txt;
#  make sure .env DATABASE_URL matches those credentials)
```

**Offline smoke test (no HTTP, no API key):**

```bash
docker compose up -d db qdrant
python scripts/test_ingestion.py
```

**Expected result:** `status=indexed`, `chunk_count > 1`, Postgres `document_chunks` rows match `chunk_count`, Qdrant point count ≥ `chunk_count`. To see the contextual-RAG difference, compare `raw_content` vs `contextualized_content` in a Qdrant point payload (`curl http://localhost:6333/collections/enterprise_embeddings/points/<point_id>`).

---

## 6. What changes in later parts (so nothing built now is wasted)

| Later part | Diff to this part |
|---|---|
| **Auth (Phase 1)** | `org_id`/`uploaded_by` Form fields removed from upload; identity comes from the JWT dependency. Dev seed + `process_now` defaults deleted. Alembic introduced. |
| **Workers (Phase 2)** | `tasks.py`: one task wrapping `ingest_document()`; upload swaps `asyncio.to_thread` → `task.delay()`. `core/celery.py` filled. |
| **Search (Phase 3)** | Qdrant collection gains a named sparse vector (recreate collection — cheap); `core/qdrant.py` gains a `search()` with payload filters using the payload fields written today; `search/*` filled. |
| **Storage (Phase 2+)** | `save_uploaded_document`'s disk write moves behind a storage interface (local → S3). Only that function changes. |
