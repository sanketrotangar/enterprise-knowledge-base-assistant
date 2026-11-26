# Goal

Company knowledge chatbot that answers ONLY from docs the asker may see,
and proves it with a leak test (0 leaks).

# Why this is different from a normal RAG app

Permissions are enforced by the database (Postgres RLS), not by app code.
A bug in my code cannot leak a document.

# Already built (keep, don't rewrite)

Parser, chunker, contextualizer, hybrid+RRF+rerank flow, Groq answer layer, React UI.

# Decisions

- 2026-10-31 Storage: move retrieval to Postgres (pgvector + tsvector + RLS). Reason: card promises DB-enforced access.
- 2026-10-31 Data loss is OK. No migration of old Qdrant data.
- 2026-10-31 Embedder: switching away from MiniLM (truncates at ~256 tokens, my chunks are longer). Pick winner by golden-set test. Embedding size must be a config value.
- 2026-10-31 Language: English only for now.
- 2026-10-31 Roles: tenant > department > clearance (int). Assumption: one department per user.
- 2026-10-31 RLS on chunks done, 4 tests green. Next: RLS on all tenant tables, runtime connects as app_user only (startup check enforces it).
- 2026-11-01 RLS + WITH CHECK on chunks, documents, search_queries, query_citations. Runtime = app_user, startup check enforces it. Next: RLS on document_chunks, wire app paths through rls_session, then golden set.
- 2026-11-01 document_chunks.tenant_id + ENABLE/FORCE RLS; same on organizations and users. Upload/ingest/status/search/history/query logging all go through rls_session. Qdrant still the search backend. Next: golden set. Remaining tenant tables without RLS: audit_logs, feedback (unused Phase 4).
- 2026-11-01 RLS on all 7 tenant tables, app works as app_user. 11 tests green.
- Rule: any new table with tenant data (audit_logs, feedback, access_requests)
  gets RLS + FORCE + WITH CHECK in the same migration that creates it.
- Rule: when ingest moves to `chunks`, drop `document_chunks`.
- Heads-up: login needs a SECURITY DEFINER lookup because users has RLS.
- Baseline: Qdrant + MiniLM stays until the golden set has a baseline score.
- 2026-11-01 Eval world: eval/corpus (14 docs), users.yaml (5), golden.yaml (30), attacks.yaml (20), seed_eval + run_eval. TEMPORARY X-Eval-User / eval_user header for impersonation; remove when JWT lands. No search/ingest/RLS/UI rewrite.
- 2026-11-01 Eval world built (14 planted docs, 30 golden, 20 attacks).
- Rule: a leak = canary fact of a forbidden doc in answer/sources. Exact match only.
- 2026-11-01 Hardened eval: unique canary per planted doc, 30 filler docs, hit@1+MRR, leak classes.
  Frozen baseline Qdrant+MiniLM in eval/baseline_qdrant_minilm.json — never overwrite.
  golden hit@1=14/15 hit@5=15/15 mrr=0.967 p95_ms=448 attacks leaked=10/20
  (cross_tenant=0 wrong_department=10 above_clearance=0).
- 2026-11-01 Baseline Qdrant+MiniLM: hit@1 14/15, MRR 0.967, leaked 10/20
  (all wrong_department, 0 cross_tenant). above_clearance 0 is accidental
  (Qdrant over-blocks restricted for everyone).
- Rule: eval must include positive cases (authorized user gets the restricted doc).
- Next: Postgres retrieval on chunks, compare against baseline, then embedders.
- 2026-11-01 Postgres hybrid on `chunks` (vector+tsvector RRF, RLS only). SEARCH_BACKEND=qdrant|postgres.
  Same 33-row golden: postgres hit@1=17/18 hit@5=18/18 mrr=0.972 leaked=0/20.
  Qdrant on that set: hit@1=14/18 hit@5=15/18 mrr=0.806 leaked=10/20 (wrong_department).
  Frozen baseline file untouched. Authorized hr-comp now retrieves exec salary.
- 2026-11-01 Postgres RLS backend: attacks leaked 0/20 (Qdrant 10/20),
  hit@1 17/18, MRR 0.972, p95 410ms. Authorized hr-comp reaches salary sheet.
- Claim to use: equal retrieval quality, access enforced by the DB. Not "better retrieval".
- Next: harder attacks, history per-user scoping check, then embedder comparison, then delete Qdrant.
- 2026-11-01 Harder attacks (30) + SEARCH_BACKEND default postgres. Ingest writes `chunks` only (Qdrant code kept).
  postgres v2: hit@1=17/18 hit@5=18/18 mrr=0.972 leaked=0/30. Existence probes do not retrieve the salary sheet.
- Gap (not fixed): search_queries / query_citations RLS is tenant-only. intern-hr SELECT sees other same-tenant users' rows. Cross-tenant still 0.

# Tradeoffs I accepted

- Postgres keyword search is weaker than my custom BM25. Reranker should cover it. Check on golden set.
- Vector index + RLS can return fewer than k rows. Use pgvector iterative scan or exact scan at this scale.

# Not doing (until the goal is proven)

Rate limiting, S3 (disk first), Drive/Notion, streaming, DOCX.
(Durable job queue + Redis/worker for ingest is in target — see 2026-11-11.)

# Target architecture locks (2026-11-11) — beta design

- Auth: JWT carrying org_id, user_id, role.
- Roles (beta): user / manager / admin.
- Multi-org: many orgs; each user belongs to one org.
- Files: disk now; metadata in DB; S3 later behind same File Store interface.
- Upload: manager/admin only. Accept → disk + DB pending → durable queue job per doc (parse/chunk/embed).
- Delete / set doc roles: manager/admin only. user: list / preview / ask only (no upload, no delete).
- Durability: multi-upload = N independent jobs; one doc failing does not drop others; disk + DB outlive queue message; re-enqueue by doc_id.
- Ingest outcomes: transient error → retry; document error → failed (file kept); Redis+worker (or equivalent) allowed.
- Access: option B — DB enforces (RLS); chunks inherit parent doc org + allowed roles.
- Ask empty hits: safe reply “not found in docs you can access”; no existence leak; sources when hits exist.
- 2026-11-11 History: **not in beta**. Sources only in ask response. Chat/search history later if needed. (Supersedes earlier B1 persist.)
- Schema: A1 document_role_access; C2 hard delete; D org_id on chunks + chunk_role_access copied at ingest.
- Tables (target): organizations, users, documents, document_role_access, chunks, chunk_role_access.
- Role change: API updates document_role_access, returns; worker job `sync_chunk_roles(doc_id)` re-copies to chunk_role_access (UI not blocked).
- UI: old frontend chrome is not locked; slice 6 may redesign. Keep roles/JWT/docs/ask aligned to plan.
- 2026-11-12 UI foundation: use-case CSS tokens (`canvas`/`panel`/`ink`/`action`/`status-*`/`metric-*`); shadcn-style shared UI + framer-motion; reuse components (project rule 10); dashboard bento with live health + placeholders (`—`) for unwired metrics.
- Parked in `temp/`: feedback, audit, admin stub, search history. Do not import from temp/.
- Diagrams: 01–03 under docs/diagrams/. Build: docs/build.md.
- 2026-11-11 Slice 0 frozen. Agent rules in `.cursor/rules/project.mdc`.

- 2026-11-12 Slice 1: Postgres in Docker (`pgvector/pgvector:pg15`, host `:5436`, db `ekb`). `.env` points at Docker. Host `:5434` was down / unused.
- Migration `20261112_0004`: `document_role_access` + `chunk_role_access` (with `org_id` denorm), roles remapped to user|manager|admin, RLS select vs write split (ingest can INSERT before role rows exist).
- Migration `20261112_0005`: physical schema aligned to `docs/diagrams/03-schema.drawio` — drop department/clearance/legacy cols; rename filename/disk_path; chunks.org_id + chunk_index; drop search_queries/query_citations/document_chunks; keep org_id on *_role_access for RLS.
- Session locals: `app.org_id` + `app.role` (+ `app.tenant_id` mirror kept harmless).
- Seed: `scripts/seed_beta_org.py` — one org + user/manager/admin (+ dev@local).
- Ingest now writes `document_role_access` + `chunk_role_access`; doc status = pending|ready|failed.

- 2026-11-25 Slice 2 done: `POST /api/v1/auth/login` (email + password) → JWT (`sub`, `org_id`, `role`, 24h) and `GET /api/v1/auth/me`.
  bcrypt directly (passlib 1.7.4 is incompatible with bcrypt 5; dropped passlib from requirements).
  Login lookup is a SECURITY DEFINER function `login_lookup_user` (migration `0006`) because users has FORCE RLS and the org is unknown pre-login; EXECUTE granted to app_user only, search_path pinned.
  Also in `0006`: unique index on (org_id, lower(email)) + email lookup index (login assumes one user per org+email).
  Product paths (documents, search, pg_retrieve, auth/me) take the JWT principal and SET LOCAL app.org_id / app.user_id / app.role per transaction. Form-supplied `org_id`/`uploaded_by` were removed.
  Temporary X-Eval-User middleware is no longer installed. `scripts/run_eval.py` now gets 401 until Slice 7 mints eval JWTs.
  Seed script writes real bcrypt hashes (default password `password123`).
  Proof: 6 new tests (login claims, 401 missing/malformed/expired/wrong password, org A token 404 on org B doc, token principal sees only its org's rows); 11 total green.

- 2026-11-26 Slice 3 done: disk File Store + document management API.
  `app/core/file_store.py` — `FileStore` protocol + `DiskFileStore` under `UPLOAD_DIR`; `documents.disk_path` stores the store reference (absolute path for disk). Keys are server-generated `{org_id}/{doc_id}{suffix}`, never client filenames. S3 can replace the implementation later.
  Upload (`POST /documents/upload`, manager/admin) accepts 1..N files, writes disk + `documents` pending + `document_role_access`, then publishes one `ingest` job per doc and returns immediately. No inline ingest and no `process_now` on product paths. Legacy single `file` field still accepted.
  `app/core/jobs.py` publishes JSON jobs to the Redis list `ka:jobs` at `CELERY_BROKER_URL` (list payload = type + document_id + org_id); Slice 4 consumes it. Enqueue is best-effort after commit — disk + DB row are the source of truth, and `POST /documents/{id}/process` re-enqueues by id.
  List is RLS-filtered; preview returns metadata + 5000-char excerpt and 404s when the caller's role cannot see the doc (no existence leak). Delete is manager/admin, hard-deletes the row (chunks + role rows cascade) then removes the disk file.
  Set roles (manager/admin) rewrites `document_role_access` and returns after enqueue; `sync_chunk_roles(doc_id)` is the worker entry point that re-copies to `chunk_role_access`.
  Role gating: new `require_manager_or_admin` dependency returns 403; `documents` RLS write policy already enforces manager/admin and user-scoped reads.
  Set-roles with `[]` removes every role row (manager/admin still see the doc via RLS); an empty `role_access` on upload keeps the legacy all-roles default.
  Proof: 7 tests (`tests/test_documents_api.py`) — 403s for user upload/delete/set-roles; multi-file pending + 2 jobs; role-filtered list/preview (404 hidden); delete removes file/chunks/role rows; set-roles returns before sync then converges via `sync_chunk_roles`; empty roles stay manager/admin-only; reprocess enqueues. 18 total green.

- 2026-11-26 Slice 4 done: durable Redis worker (`app/worker.py` + `app/core/worker.py`).
  Queue: `ka:jobs` (RPUSH, claimed with BLMOVE) → `ka:jobs:processing` while in flight →
  `ka:jobs:delayed` ZSET for retries. On start the worker requeues orphans left in
  `processing` (killed mid-job); handlers are idempotent, so duplicate delivery is safe.
  Retry policy: transient (DB/model/IO) → 3 attempts, 5s/10s backoff (cap 60s), then
  `failed` + error recorded; permanent (parse/empty/no content/missing row) → `failed`
  immediately, file kept; unknown/malformed payloads are dropped and logged.
  `app/features/documents/tasks.py` maps payload → service and runs with a system
  `admin` principal for the job's org (RLS allows chunk writes only to manager/admin;
  `app.user_id` is unused by policies, so the worker uses the nil UUID).
  Migration `0007`: SECURITY DEFINER `list_document_chunk_ids(doc)` +
  `delete_document_chunks(doc)`, scoped to `app.org_id`, EXECUTE to app_user only.
  Reason: `chunks_select` requires a matching `chunk_role_access` row, and Postgres also
  applies SELECT policies to rows scanned by `DELETE ... WHERE`; once a doc's roles
  exclude admin, a plain select/delete by the worker silently matches nothing, which
  broke role sync and duplicated chunks on re-ingest. Functions return ids/count only.
  Also fixed: ORM chunk INSERT must not rely on the `created_at` server default —
  `INSERT ... RETURNING` is checked against the SELECT policy before role rows exist,
  so chunk id + created_at are set client-side.
  Proof: 12 new tests (ready + idempotent replay, corrupt PDF failed while the other doc
  stays ready and both files remain, transient error stays pending then retries,
  role sync flips user/manager chunk visibility, re-ingest after restriction replaces
  chunks without duplicates, orphan requeue, retry→exhaustion, malformed/unknown jobs).
  30 total green. No seed data added.

# Now working on

Slice 5 — Ask path (retrieve + answer + sources over the now-ready chunks).
Embedder bakeoff / delete Qdrant remain later.
Eval world (Slice 7) still maps old dept/clearance YAML → needs rebuild for beta roles and JWT.