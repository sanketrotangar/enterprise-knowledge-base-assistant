# Enterprise Knowledge Assistant

A multi-tenant knowledge assistant for internal company documents. Managers and
admins upload documents, the system parses, chunks and embeds them in the
background, and every user can ask questions answered only from the documents
their role is allowed to see.

Access is enforced in the database, not in application code: PostgreSQL
row-level security decides which documents and chunks each request may read, so
a forbidden source can never reach the retrieval step or the answer.

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI, SQLAlchemy, Alembic |
| Data | PostgreSQL + pgvector (tenant RLS on every table) |
| Auth | JWT carrying `org_id`, `user_id`, `role` (`user` \| `manager` \| `admin`) |
| Queue | Redis list (`ka:jobs`) consumed by a durable worker with retries |
| Search | Hybrid dense + BM25 retrieval in Postgres, rerank, cited answer |
| UI | React 18, TypeScript, Vite, Tailwind, React Query |

## Status

Beta build in slices — see [`docs/build.md`](docs/build.md) for the plan and
[`DECISIONS.md`](DECISIONS.md) for the rationale behind each choice.
Schema + RLS, JWT auth, document management, the ingest worker and the beta UI
are in place; the ask path proof and eval gate are next.

## Run

```bash
# API
uvicorn app.main:app --reload

# Ingest + role-sync worker (separate process; same .env as the API)
python -m app.worker
# one-shot drain for verification:
python -m app.worker --once
```
