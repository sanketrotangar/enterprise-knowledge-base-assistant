# Build plan — Knowledge Assistant (Beta)

Source of truth for **what to build in order**.  
Architecture diagrams: `docs/diagrams/01–03`. Decisions log: `DECISIONS.md`.

## Status (update every slice)

| Checkpoint | Status |
|------------|--------|
| 0 Freeze | done |
| 1 Schema + RLS | done (aligned to 03-schema) |
| 2 JWT | done |
| 3 Disk + docs API | done |
| 4 Ingest + role-sync workers | done |
| 5 Ask + sources | not started |
| 6 Beta UI | built (review pending) |
| 7 Eval gate | not started |

**Current slice:** 5 — Ask path (retrieval + answer + sources)  
**Done:** Slice 1 on Docker Postgres (`localhost:5436` / `ekb` / `app_user`), schema aligned to `03-schema.drawio` (migration `0005`). Slice 2 JWT login + route protection + JWT→RLS mapping (migration `0006`). Slice 3 disk file store + upload/list/preview/delete/set-roles API with queued (non-inline) ingestion. Slice 4 durable Redis worker (migration `0007` for the worker's scoped chunk-id helpers) with retries, crash recovery and role-sync.  
Do not start slice N+1 until slice N proof passes.

**Phase 1 (this plan):** e2e beta — login, upload/manage, ask + sources, DB-enforced access.  
**Phase 2 (later):** polish, metrics, optimize/scale — not more feature surface.

---

## Locked inputs (do not re-litigate while building)

- Multi-org; roles: `user` | `manager` | `admin`
- JWT: `org_id`, `user_id`, `role`
- Files on disk; metadata in DB; S3 later
- Upload / delete / set roles: manager/admin only
- User: list / preview / ask only
- Durable queue for parse → chunk → embed (1 job per doc)
- Role changes on a doc: API updates `document_role_access` quickly, then **worker** re-copies to `chunk_role_access` (UI not blocked)
- Access: option B (Postgres RLS)
- Hard delete (cascade DB + wipe disk)
- Empty ask: safe “not found in docs you can access” + no existence leak
- Show sources in the ask **response** only (no search/chat history in beta)
- UI/UX may be redesigned in slice 6 — old chrome is not locked
- Parked out of live tree: `temp/` (feedback, audit, admin stub, history)

---

## Slice 0 — Freeze checklist

**Do**
- [x] Agree diagrams 01, 02, 03 match this plan
- [x] Agree this `build.md` is the build order

**Proof:** reviewed and approved 2026-11-11. Agent rules refreshed in `.cursor/rules/project.mdc`.

---

## Slice 1 — Schema + RLS skeleton

**Do**
- Alembic migration for: `organizations`, `users`, `documents`, `document_role_access`, `chunks`, `chunk_role_access`
  (no `search_queries` / `query_citations` in target beta)
- RLS + FORCE + WITH CHECK on every tenant table
- Runtime DB role = non-superuser (no BYPASSRLS)
- Every DB session: transaction + `SET LOCAL` org / user / role (clearance N/A in beta role model)

**Proof**
- Migration applies clean on empty DB
- As `user` role: cannot SELECT another org’s rows
- As `user` role: cannot SELECT chunks whose `chunk_role_access` does not include `user`
- Manager/admin policies match write rules (upload/delete later wired in API)

---

## Slice 2 — Auth (JWT)

**Do**
- Login endpoint → JWT with `org_id`, `user_id`, `role`
- Protect API routes with JWT
- Map JWT → RLS session vars on each request

**Proof**
- Wrong/missing token → 401
- Token for org A never reads org B data (RLS test)
- Remove any temporary eval impersonation header from **product** paths when JWT is live (eval harness may stay separate)

---

## Slice 3 — Disk file store + Doc management API

**Do**
- File store interface (disk implementation now)
- Manager/admin: upload accept → write disk + `documents` row `pending` + `document_role_access` rows → enqueue ingest job → return `doc_id` immediately
- Multi-file upload = N independent docs/jobs
- List / preview (role-filtered via RLS)
- Delete: manager/admin → hard delete DB cascade + disk file
- Set roles: manager/admin → update `document_role_access` → enqueue **role-sync** worker job → return immediately

**Proof**
- `user` gets 403 on upload / delete / set roles
- Preview only for docs their role may see
- After delete, file gone from disk and no orphan chunks
- Set-roles API returns before chunk re-copy finishes; worker eventually makes `chunk_role_access` match

---

## Slice 4 — Ingest worker (queue)

**Do**
- Durable queue (Redis + worker or equivalent)
- Job types: `ingest(doc_id)`, `sync_chunk_roles(doc_id)`
- Ingest: parse → chunk → embed → write `chunks` + `chunk_role_access` → `ready` / `failed`
- Transient errors → retry; document errors → `failed` (file kept); other docs unaffected
- Re-enqueue by `doc_id` if queue message lost (disk + DB still there)

**Proof**
- Two docs uploaded; one corrupt → one `ready`, one `failed`; good file still on disk
- Kill worker mid-job → re-enqueue → reaches `ready` or clean `failed`
- `sync_chunk_roles` after role change: old role loses retrieval; new role gains it (RLS/eval)

---

## Slice 5 — Ask path (retrieve + answer + sources)

**Do**
- Ask API: JWT → RLS session → retrieve under RLS only → LLM on allowed chunks only
- Response: answer + sources (no history tables)
- No hits → safe empty reply, no sources, no existence leak

**Proof**
- Leak/attack suite: 0 leaks (forbidden canary never in answer/sources)
- Authorized role gets the restricted doc when allowed
- Citations reference only chunks the caller can see
- Cross-org ask returns nothing from other orgs

---

## Slice 6 — Beta UI e2e (redesign allowed)

**Do**
- Design UI/UX for this product (do not preserve old layout as a constraint)
- Login
- Manager/admin: upload, list, preview, delete, set roles (status: pending/ready/failed)
- User: list/preview allowed docs, ask + see sources
- Show ingest/role-sync as async status (not a blocking spinner for the whole pipeline)
- No history / feedback / audit screens unless re-added to the plan

**Proof**
- Manual script: two orgs, three roles, upload → ready → ask with sources → role change → ask changes → delete
- No UI path that waits on full embed before acknowledging upload

---

## Slice 7 — Eval gate (ship bar for beta)

**Do**
- Golden retrieval + attack/leak suite against this architecture
- Document claim: “answers only from docs the asker may see; DB-enforced; sources shown”

**Proof**
- Freeze an eval JSON run as beta baseline
- Leak count = 0 on attack set
- Hit metrics recorded (optimize in phase 2, don’t block beta if leak=0 and e2e works)

---

## Explicitly not in this build plan (phase 2 / later)

- S3 migration (keep File Store interface ready)
- Department/clearance model (replaced by role for beta target)
- Extra product features beyond locked list
- Premature scaling work (caching layers, etc.) unless a slice’s proof requires it

---

## Worker job summary

| Job | Trigger | Result |
|-----|---------|--------|
| `ingest` | upload accepted | chunks + chunk_role_access; status ready/failed |
| `sync_chunk_roles` | set doc roles API | chunk_role_access rewritten to match document_role_access |

UI never blocks on either job finishing.

### Running the worker

```bash
.venv/bin/python -m app.worker                 # long-running consumer
.venv/bin/python -m app.worker --once          # drain available jobs and exit
.venv/bin/python -m app.worker --max-attempts 5 --retry-base-seconds 10
```

- One process is the supported deployment. Handlers are idempotent, so duplicate
  delivery is safe, but orphan recovery assumes it is not stealing a live worker's job.
- Retries use `ka:jobs:delayed` (5s, 10s, … capped at 60s); after the attempt cap an
  ingest job is marked `failed` with the error and the file is kept.
- A document deleted before its job runs is dropped cleanly (no rows to update).
- Lost queue message: `POST /api/v1/documents/{id}/process` re-enqueues by `doc_id`
  because disk + DB are the source of truth.

---

## Progress log

| Slice | Status | Notes |
|-------|--------|-------|
| 0 Freeze | done | diagrams + plan + agent rules locked |
| 0b Park pass | done | history/feedback/audit/admin → temp/; ask returns sources only |
| 1 Schema + RLS | done | Docker pgvector; 0004 role RLS + 0005 align to 03-schema; seed; 5 RLS tests green |
| 2 Auth JWT | done | login + `/auth/me`; Bearer-protected docs/search; JWT→RLS (org/user/role); 0006 SECURITY DEFINER lookup + password hashes; 11 tests green (6 new) |
| 3 Disk + docs API | done | FileStore (disk); multi-upload → pending + `ka:jobs`; list/preview RLS-filtered; hard delete wipes disk; set-roles async (worker sync handler); 7 new tests, 18 total green |
| 4 Ingest worker | done | `app/worker.py` consumes `ka:jobs` via a Redis list; claimed jobs sit in `ka:jobs:processing` and are requeued on start (crash recovery); transient failures retry via `ka:jobs:delayed` (2× backoff, 3 attempts), document failures mark `failed` and keep the file. Migration `0007` adds org+document-scoped SECURITY DEFINER helpers for chunk ids and chunk deletion, needed because RLS hides chunks the worker role no longer holds. 12 new tests. |
| 5 Ask path | not started | |
| 6 Beta UI | built (review pending) | JWT login + route guard; live docs list/preview/multi-upload/roles/delete/retry; ask + sources; pending polls; `npm run build` green. Manual two-org proof script not run yet; no seed data added. |
| 7 Eval gate | not started | |
