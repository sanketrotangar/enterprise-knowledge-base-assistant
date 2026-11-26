# Enterprise Knowledge Assistant — Context for Claude

Use this file as the starting brief. It describes **what is already built**, **what is still planned**, and the **conventions you must follow**. Do not re-implement working slices. Prefer extending existing functions over rewriting them.

Longer specs (implementation paste-docs, not always in sync with code):

- `md-files/plan.md` — original one-page product pitch
- `md-files/technical-analysis.md` — original HLD, schema, and Phase 1–5 task list
- `md-files/document-ingestion-part1.md` — Part 1 ingestion spec (implemented)
- `md-files/search-retrieval-part3.md` — Part 3 retrieval spec (implemented)
- `md-files/understanding.md` — request-lifecycle walkthrough of the running system
- `frontend/README.md` — frontend API coverage map

---

## 1. Product

Employees cannot find internal knowledge that already exists in PDFs and docs.

The product is an **enterprise RAG assistant**:

1. Upload PDFs / TXT / MD
2. Parse → chunk → **contextualize** → embed (dense + BM25 sparse)
3. Hybrid search in Qdrant, RBAC-filtered
4. Cross-encoder rerank
5. LLM answer with `[n]` citations
6. Later: real auth, feedback, admin, async workers

Core user question the system is built around: *“Where is the leave policy?”*

---

## 2. Status snapshot (2026-10-31)

| Slice | Status | Notes |
|---|---|---|
| FastAPI app skeleton + feature folders | **Done** | Vertical slices under `app/features/` |
| Postgres schema (orgs, users, docs, chunks, queries, citations) | **Done** | Created via `Base.metadata.create_all` on startup — **no Alembic yet** |
| Dev identity seed | **Done** | Default org `default` + user `dev@local` (role `admin`) |
| Document upload + ingestion (Part 1) | **Done** | Sync pipeline in a thread, not Celery |
| Contextual RAG | **Done** | Groq LLM context, heuristic fallback |
| Hybrid search + rerank + cited answers (Part 3) | **Done** | Combines original analysis Phases 3 and 4 answer-gen |
| Query + citation logging | **Done** | `search_queries` / `query_citations` |
| Search history API + UI | **Done** | Latest 20 globally (not per-user) |
| React + Vite admin UI | **Done** | Dashboard, Documents, Search, History |
| JWT auth / login / register | **Not built** | Models exist; router is empty |
| HTTP RBAC / JWT middleware | **Not built** | Qdrant payload filter **is** built; identity still comes from the dev seed |
| Celery workers | **Not built** | `tasks.py` / `celery.py` are comment stubs |
| Redis cache | **Not built** | `cache.py` is a comment stub |
| Feedback API | **Not built** | Model is comments only; router empty |
| Admin APIs | **Not built** | Router empty |
| Audit logging | **Not built** | Model is comments only |
| Rate limiting | **Not built** | Described in `security.py` comments only |
| List / delete documents | **Not built** | Needs auth to be meaningful |
| Real `/health/detailed` | **Not built** | Values are **hardcoded** in `app/api.py` |
| S3 / Google Drive / Notion / DOCX | **Not built** | `source_type` column already allows them |
| Streaming answers / document viewer | **Not built** | |

**Part numbering in this repo is not sequential.** Implementation docs are **Part 1** (ingest) then **Part 3** (search). Original `technical-analysis.md` uses **Phase 1–5**. When someone says “Phase 4” they usually mean **feedback**. When they say “auth phase” they mean JWT + replacing the dev seed.

---

## 3. Architecture as built

```
Browser (React + Vite, :5173)
    │  /api and /health proxied to FastAPI in vite.config.ts
    ▼
FastAPI (app/main.py)  — CORS, lifespan, routers via app/api.py
    │
    ├─ PostgreSQL     metadata, chunk registry, query log
    ├─ Qdrant         named vectors: dense (384, Cosine) + sparse (BM25/IDF)
    ├─ Groq           contextualizer + answer LLM (OpenAI-compatible client)
    └─ Local disk     uploads/  (MVP storage)

Redis + Celery are in docker-compose and .env but NOT used by app code yet.
```

**Two stores on purpose**

- Postgres = source of truth for documents and the chunk registry (`document_chunks.qdrant_point_id`)
- Qdrant = vectors + search payload (text + RBAC fields)

Deleting/re-indexing a document deletes Qdrant points by `document_id` then re-upserts.

### Ingestion pipeline (live)

```
POST /api/v1/documents/upload
  → validate (ext + mime + size streamed in 1MB chunks)
  → save file to disk
  → insert documents row (status=uploaded)
  → ingest_document() in asyncio.to_thread:
        parse → chunk → contextualize → embed dense+sparse
        → Qdrant upsert + document_chunks rows
        → status=indexed | failed
GET /api/v1/documents/{id}/status   (frontend polls this)
POST /api/v1/documents/{id}/process (re-ingest, idempotent)
```

### Search pipeline (live)

```
POST /api/v1/search {query, top_k}
  → resolve dev identity (org/user/role)
  → embed query (same MiniLM as ingestion)
  → Qdrant hybrid: dense + BM25 sparse, RRF fusion, RBAC filter, top 20
  → cross-encoder rerank → top_k (default 5)
  → Groq cited answer (extractive fallback if no key / LLM error)
  → log search_queries + query_citations
  → {query_id, answer, sources[], response_time_ms}
```

---

## 4. Tech stack

| Layer | Choice |
|---|---|
| API | FastAPI + Uvicorn, Python 3.11 (project `.venv`) |
| DB | PostgreSQL + SQLAlchemy 2 + psycopg |
| Vectors | Qdrant collection `enterprise_embeddings` |
| Embeddings | `sentence-transformers` `all-MiniLM-L6-v2` (384-d) |
| Sparse | Custom BM25 encoder in `app/features/search/sparse.py` |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-12-v2` |
| LLM | Groq via `openai` package (`GROQ_BASE_URL`, `GROQ_MODEL`) |
| Frontend | React 18 + TypeScript + Vite + Tailwind + React Query + React Router |
| Infra (declared) | Docker Compose: api, db, redis, qdrant; celery worker is **commented out** |

LLM is **Groq, not OpenAI**. Original analysis mentioned OpenAI; code uses `GROQ_API_KEY` / `GROQ_MODEL` / `GROQ_BASE_URL`.

---

## 5. Repo layout and ownership rules

Feature-based (vertical slices). **Routers are thin** (HTTP + status codes). **Services own logic**. Features never construct a raw Qdrant client — all Qdrant I/O goes through `app/core/qdrant.py`.

```
app/
  main.py                 FastAPI app + lifespan (DB, seed, model warmup)
  api.py                  /health + /api/v1/* aggregation
  core/                   config, database, qdrant, cache(stub), celery(stub), security(stub)
  features/
    auth/                 Organization + User models; dev seed; empty router
    documents/            upload, parse, chunk, contextualize, ingest
    search/               embedder, sparse, reranker, llm, search service
    feedback/             comments + empty router
    admin/                comments + empty router
    audit/                comments only
frontend/                 Vite app; API clients already exist for unimplemented endpoints
md-files/                 specs and this handoff
uploads/                  local file storage
.venv/                    Python 3.11 env — use `.venv/bin/python -m uvicorn`, not system uvicorn
```

**Stubs are intentional.** Many files still start with a long comment describing the *future* API, then (sometimes) real code below. Empty routers (`auth`, `feedback`, `admin`) are mounted but have no routes.

### Important code facts

- `Document.meta` maps to DB column `metadata` (SQLAlchemy reserved name).
- Chunking is **word-based**, not token-based: 320 words, 40-word overlap, snap to sentence end (`chunker.py`).
- Contextualizer is a **separate module** from the chunker (chunker must stay pure/offline).
- All three texts are stored: raw chunk, `context_header`, `contextualized_content`. Embeddings are of **contextualized** text.
- Search schemas are **locked to** `frontend/src/types/api.ts`. Do not rename fields.
- Identity today: `get_or_create_dev_identity()`. Auth phase **replaces** this; do not grow more Form fields for `org_id` / `uploaded_by`.
- When Celery lands, `tasks.py` should wrap `ingest_document()` — do not move the pipeline into the task file.
- When Redis cache lands, wrap `search()` — do not fold cache into Qdrant/rerank internals.
- Qdrant named-vector layout is fixed at collection create. Changing it requires delete + re-ingest.
- `create_all` never ALTERs existing columns. If you change a column type, migrate the DB or you get `DatatypeMismatch` at insert.

---

## 6. Live vs planned APIs

### Live

| Method | Path | Behavior |
|---|---|---|
| GET | `/health` | `{"status":"healthy"}` |
| GET | `/health/detailed` | **Hardcoded** service statuses — not real probes |
| POST | `/api/v1/documents/upload` | Multipart; optional `process_now` |
| POST | `/api/v1/documents/{id}/process` | Re-run ingestion |
| GET | `/api/v1/documents/{id}/status` | Poll processing |
| POST | `/api/v1/search` | Hybrid search + rerank + answer |
| GET | `/api/v1/search/history` | Latest 20 logged queries |

Upload form fields today: `file`, `title`, `sensitivity` (`public|internal|confidential|restricted`), `role_access` (csv of `hr|engineering|finance|general`), optional `org_id` / `uploaded_by` (dev only), `process_now`.

Allowed files: `.pdf`, `.txt`, `.md`.

### Planned (routers exist, no handlers)

```
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
GET    /api/v1/auth/me

GET    /api/v1/documents
GET    /api/v1/documents/:id
DELETE /api/v1/documents/:id

POST   /api/v1/feedback
GET    /api/v1/feedback/summary

GET    /api/v1/admin/documents
GET    /api/v1/admin/users
PATCH  /api/v1/admin/users/:id/role
GET    /api/v1/admin/audit-logs
```

Frontend **clients** for these already live under `frontend/src/api/`. Unbuilt admin pages show a Coming Soon screen. Search/History/Documents/Dashboard are live.

---

## 7. Data model (what exists in Postgres)

Implemented ORM:

- `organizations`, `users` — schema only; password_hash default is `"dev-only-not-a-real-hash"`
- `documents` — metadata, sensitivity, role_access[], status (`uploaded|processing|indexed|failed`)
- `document_chunks` — qdrant_point_id, content_preview, context_header, contextualized_content
- `search_queries`, `query_citations`

Not created yet (comment-only models): `feedback`, `audit_logs`.

Qdrant payload per point includes: `document_id`, `title`, `org_id`, `sensitivity`, `role_access`, `chunk_index`, `raw_content`, `contextualized_content`, `context_header`, `__sparse_unavailable__`.

RBAC filter (already in `build_rbac_filter`): same org AND (not restricted OR role_access matches user tags / `general`). Nested `should` is required — a top-level `should` plus `must` would leak restricted docs.

---

## 8. Frontend

- App: `frontend/` — light-mode teal admin shell
- Routes live: `/` dashboard, `/documents`, `/search`, `/history`
- Coming soon: `/admin/users`, `/admin/audit-logs`, `/admin/feedback`
- Mock mode: `npm run dev:mock` (`VITE_MOCK_MODE=true`)
- Dev proxy: Vite `:5173` → FastAPI `:8000` for `/api` and `/health`
- If the API is not on 8000, set `VITE_API_BASE_URL` (CORS must include the UI origin)

UI rule already in the frontend README: features whose backend has not landed show Coming Soon — no fake live data outside mock mode.

---

## 9. What to build next (planned work)

Suggested order, matching existing seams in the code:

### Next up (highest leverage)

1. **Auth (JWT)** — register, login, refresh, `/me`. Replace `get_or_create_dev_identity` with a FastAPI dependency. Fill `app/core/security.py` and `app/features/auth/*`. Remove `org_id` / `uploaded_by` form fields from upload.
2. **Wire RBAC to HTTP** — upload restricted to admin/manager; search history scoped to the current user; Qdrant filter already takes `org_id` / `role` / `role_access`.
3. **Document list + delete** — `GET /documents`, `DELETE /documents/{id}` (delete Postgres row + Qdrant points).
4. **Feedback (Phase 4)** — `POST /feedback` against `search_queries.id`; unique (query_id, user_id); then summary for admin.

### After that

5. **Celery** — `process_document_task` calls `ingest_document()`; upload uses `task.delay()` instead of `asyncio.to_thread`. Uncomment worker in `docker-compose.yml`.
6. **Redis cache** — wrap search results (`search:{org_id}:{hash(query)}`, ~5 min TTL); invalidate on re-ingest/delete.
7. **Admin + audit** — users, roles, document inventory, audit_logs for sensitive actions.
8. **Rate limiting** — Redis-backed; analysis suggests 100/15m general, 10/15m auth, 50/15m search.
9. **Alembic** — once auth schema settles. Stop relying on `create_all`.
10. **Real health checks** — actually ping Postgres / Redis / Qdrant / Celery.
11. **Storage interface** — local disk → S3 without rewriting ingest.
12. **Sources beyond upload** — Google Drive, Notion, URL (`source_type` already on documents).
13. **DOCX parsing**, streaming answers, in-app document viewer.

Original analysis Phase 5 also includes input sanitization, unified error envelope (`{error:{code,message,details}}`), and production Docker. Dockerfile exists; local dev is venv + existing Postgres/Qdrant/Redis containers, not `docker compose up` of the whole stack.

---

## 10. How to run locally

**Do not use system `uvicorn`.** It is Python 3.12 without project deps. Use the venv:

```bash
# infra (names/ports on this machine as of Oct 2026)
# Postgres: projects-postgres on localhost:5434
# Redis:    kb-redis on 6379
# Qdrant:   kb-qdrant on 6333
# DATABASE_URL is in .env — do not commit or paste secrets.

.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# If 8000 is taken (another project), use 8001 and point the UI at it.

cd frontend && npm run dev   # http://localhost:5173
```

Startup lifespan: ensure DB exists → connect → `create_all` → seed dev identity → warmup embedder + reranker (HuggingFace download on first run).

First upload downloads MiniLM (~80MB) once.

---

## 11. Conventions for any new work

- Match existing comment style and thin-router / fat-service split.
- Do not add features “just in case” (YAGNI is explicit in `notes.md`).
- Prefer graceful fallback over failing the user path (LLM outage → heuristic context / extractive answer; reranker fail → keep hybrid order).
- Tenant isolation is `org_id` everywhere. Never search without an org filter once auth exists.
- Tests/smoke: `app/scripts/test-ingestion.py` exists; Part 3 mentioned `scripts/test_search.py` and `scripts/reindex_all.py` — confirm on disk before assuming they shipped.
- Frontend types in `frontend/src/types/api.ts` may still say search is unimplemented — **that comment is stale**. Backend search is live.

---

## 12. One-line summary for a new session

> RAG knowledge assistant: Part 1 ingest (contextual chunks into Postgres + Qdrant) and Part 3 hybrid search + rerank + Groq answers are live, with a Vite admin UI. Auth, Celery, Redis cache, feedback, admin, and audit are the remaining work. Extend the existing pipeline; do not rebuild it.
