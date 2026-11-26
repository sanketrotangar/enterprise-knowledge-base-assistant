# 10 — Putting It All Together: System Integration

> **Why learn this?** You've learned each piece in isolation. Now it's time to understand how they connect. This is where you see the complete picture — from user request to response, from document upload to searchable index.
>
> **Scope of learning:** Complete request flows, data flow diagrams, debugging strategies, and how to run the whole system. This is your system architecture reference.

---

## The Complete Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ENTERPRISE KNOWLEDGE ASSISTANT                   │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                        CLIENT LAYER                                │  │
│  │  ┌────────────────────────────────────────────────────────────┐   │  │
│  │  │  Frontend (React/Next.js)                                   │   │  │
│  │  │  - Chat interface                                           │   │  │
│  │  │  - Document upload                                          │   │  │
│  │  │  - Feedback widget                                          │   │  │
│  │  └────────────────────────────────────────────────────────────┘   │  │
│  └───────────────────────────┬───────────────────────────────────────┘  │
│                               │ HTTPS                                    │
│                               ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                        API LAYER (FastAPI)                         │  │
│  │                                                                     │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │  │
│  │  │  /auth      │  │  /documents │  │  /search    │               │  │
│  │  │  login      │  │  upload     │  │  query      │               │  │
│  │  │  register   │  │  list       │  │  history    │               │  │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘               │  │
│  │         │                 │                 │                       │  │
│  │  ┌──────▼─────────────────▼─────────────────▼────────────────┐   │  │
│  │  │              MIDDLEWARE                                     │   │  │
│  │  │  1. JWT Authentication                                     │   │  │
│  │  │  2. RBAC Authorization                                     │   │  │
│  │  │  3. Rate Limiting                                          │   │  │
│  │  │  4. CORS                                                   │   │  │
│  │  └────────────────────────────┬──────────────────────────────┘   │  │
│  └───────────────────────────────┼──────────────────────────────────┘  │
│                                   │                                      │
│        ┌──────────────────────────┼──────────────────────────┐         │
│        │                          │                          │         │
│        ▼                          ▼                          ▼         │
│  ┌──────────────┐        ┌──────────────┐        ┌──────────────┐    │
│  │  PostgreSQL  │        │    Qdrant    │        │    Redis     │    │
│  │              │        │              │        │              │    │
│  │  users       │        │  embeddings  │        │  cache       │    │
│  │  documents   │        │  vectors     │        │  rate limits │    │
│  │  queries     │        │  metadata    │        │  sessions    │    │
│  │  feedback    │        │              │        │              │    │
│  │  audit_logs  │        │              │        │              │    │
│  └──────┬───────┘        └──────┬───────┘        └──────────────┘    │
│         │                       │                                     │
│         │                       │                                     │
│         └───────────┬───────────┘                                     │
│                     │                                                 │
│                     ▼                                                 │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                    CELERY WORKERS                                │ │
│  │                                                                   │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │ │
│  │  │  Parser     │  │  Chunker    │  │  Embedder   │             │ │
│  │  │  (pypdf)    │  │  (512 tok)  │  │  (MiniLM)   │             │ │
│  │  └─────────────┘  └─────────────┘  └─────────────┘             │ │
│  │                                                                   │ │
│  │  ┌─────────────┐  ┌─────────────┐                               │ │
│  │  │  Qdrant     │  │  Reranker   │                               │ │
│  │  │  Indexer    │  │  (BERT)     │                               │ │
│  │  └─────────────┘  └─────────────┘                               │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Complete Request Flow: Document Upload

```
User uploads "leave-policy.pdf"
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 1: API Receives Request                                │
│                                                             │
│ FastAPI endpoint: POST /api/v1/documents/upload             │
│ - Validates JWT token (authentication)                      │
│ - Checks RBAC (is user admin/manager?)                      │
│ - Receives file + metadata                                  │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 2: Save File + Create Database Record                   │
│                                                             │
│ PostgreSQL:                                                 │
│   INSERT INTO documents (                                   │
│     id, org_id, title, storage_path,                        │
│     uploaded_by, sensitivity, status                        │
│   ) VALUES (                                                │
│     'doc-123', 'org-456', 'leave-policy.pdf',              │
│     '/uploads/doc-123_leave-policy.pdf',                    │
│     'user-789', 'internal', 'uploaded'                     │
│   );                                                        │
│                                                             │
│ Status: "uploaded"                                          │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 3: Send to Background Worker                           │
│                                                             │
│ Celery: process_document_task.delay("doc-123", "org-456")   │
│                                                             │
│ API returns immediately:                                    │
│ {                                                           │
│   "id": "doc-123",                                          │
│   "status": "processing",                                   │
│   "message": "Document is being processed"                  │
│ }                                                           │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 4: Celery Worker Processes Document                     │
│                                                             │
│ 4a. Parse PDF                                               │
│     └── pypdf extracts text from PDF                        │
│     └── "The leave policy states that employees..."         │
│                                                             │
│ 4b. Chunk Text                                              │
│     └── Split into 512-token chunks with 50-token overlap   │
│     └── [chunk_1, chunk_2, chunk_3, ..., chunk_15]          │
│                                                             │
│ 4c. Generate Embeddings                                     │
│     └── sentence-transformers encodes each chunk            │
│     └── [[0.23, -0.45, ...], [0.12, 0.67, ...], ...]       │
│                                                             │
│ 4d. Index in Qdrant                                         │
│     └── Store vectors + metadata                            │
│     └── 15 points added to collection                      │
│                                                             │
│ 4e. Update Status                                           │
│     └── UPDATE documents SET status = 'indexed'             │
│     └── UPDATE documents SET chunk_count = 15               │
│                                                             │
│ Status: "indexed" ✅                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Complete Request Flow: Search

```
User searches: "How much paid time off do I get?"
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 1: API Receives Request                                │
│                                                             │
│ FastAPI endpoint: POST /api/v1/search                       │
│ - Validates JWT token                                       │
│ - Extracts user info:                                       │
│   { user_id: "user-789", org_id: "org-456",                │
│     role: "employee", department: "engineering" }           │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 2: Check Cache                                         │
│                                                             │
│ Redis: GET search:org-456:abc123hash                        │
│ - Cache hit? Return cached results                          │
│ - Cache miss? Continue to Step 3                            │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 3: Embed Query                                         │
│                                                             │
│ sentence-transformers:                                      │
│ "How much paid time off do I get?"                          │
│     │                                                       │
│     ▼                                                       │
│ [0.25, -0.42, 0.71, 0.15, -0.85, ...] (384 dimensions)    │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 4: Hybrid Search in Qdrant                             │
│                                                             │
│ 4a. Vector Search (semantic)                                │
│     └── Find 20 most similar vectors                        │
│     └── Results: [doc_1 (0.92), doc_3 (0.88), ...]         │
│                                                             │
│ 4b. BM25 Search (keyword)                                   │
│     └── Find 20 documents with matching keywords            │
│     └── Results: [doc_1 (0.85), doc_5 (0.72), ...]         │
│                                                             │
│ 4c. Reciprocal Rank Fusion (RRF)                            │
│     └── Combine rankings                                    │
│     └── Fused results: [doc_1 (0.032), doc_3 (0.031), ...] │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 5: RBAC Filtering                                      │
│                                                             │
│ Filter results by user's access:                            │
│ - org_id must match "org-456"                               │
│ - sensitivity must be ≤ "internal" (employee level)         │
│ - role_access must include "engineering" or "general"        │
│                                                             │
│ Before: 20 results                                          │
│ After: 8 results (12 filtered out)                          │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 6: Cross-Encoder Reranking                             │
│                                                             │
│ ms-marco-MiniLM-L-12-v2:                                    │
│ - Score each of 8 results against query                     │
│ - Sort by reranker score                                    │
│ - Return top 5                                              │
│                                                             │
│ Results:                                                    │
│ 1. "Annual leave policy: 20 days..." (score: 0.95)         │
│ 2. "Vacation entitlements by level..." (score: 0.91)       │
│ 3. "How to apply for leave..." (score: 0.87)               │
│ 4. "Company holidays 2024..." (score: 0.82)                │
│ 5. "Parental leave policy..." (score: 0.78)                │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 7: LLM Answer Generation                               │
│                                                             │
│ Prompt:                                                     │
│ "Based on the following context, answer the user's question │
│  and cite sources:                                          │
│                                                              │
│  Context:                                                    │
│  1. Annual leave policy: 20 days per year... (doc-1)       │
│  2. Vacation entitlements by level... (doc-3)               │
│  ..."                                                       │
│                                                              │
│ Answer: "According to the leave policy, employees are       │
│ entitled to 20 days of annual leave per year. This can be   │
│ found in the Leave Policy document [1]."                    │
│                                                              │
│ Sources:                                                    │
│ [1] Leave Policy 2024 (doc-1)                               │
│ [2] Vacation Entitlements (doc-3)                           │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 8: Log Query + Cache Results                           │
│                                                             │
│ PostgreSQL:                                                 │
│   INSERT INTO search_queries (user_id, org_id, query_text,  │
│     results_count, answer_text)                             │
│   VALUES (...)                                              │
│                                                             │
│ Redis:                                                      │
│   SET search:org-456:abc123hash {results} EX 300             │
│   (cache for 5 minutes)                                     │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 9: Return Response                                     │
│                                                             │
│ {                                                           │
│   "answer": "According to the leave policy...",             │
│   "sources": [                                              │
│     {"title": "Leave Policy 2024", "doc_id": "doc-1"},     │
│     {"title": "Vacation Entitlements", "doc_id": "doc-3"}  │
│   ],                                                        │
│   "query_id": "query-abc-123"                               │
│ }                                                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      DATA FLOW                                   │
│                                                                 │
│  UPLOAD FLOW:                                                   │
│  ──────────────                                                 │
│  User → FastAPI → PostgreSQL (metadata)                         │
│         │                                                       │
│         └──→ Celery → Parser → Chunker → Embedder              │
│                            │              │                      │
│                            │              ▼                      │
│                            │         Qdrant (vectors)           │
│                            │                                    │
│                            └──→ PostgreSQL (update status)       │
│                                                                 │
│  SEARCH FLOW:                                                   │
│  ──────────────                                                 │
│  User → FastAPI → Redis (check cache)                           │
│         │                                                       │
│         └──→ Embedder → Qdrant (hybrid search)                  │
│                   │           │                                  │
│                   │           └──→ Filter (RBAC)                │
│                   │                     │                       │
│                   │                     └──→ Reranker           │
│                   │                                │            │
│                   │                                └──→ LLM     │
│                   │                                      │       │
│                   │                                      ▼       │
│                   │                                PostgreSQL    │
│                   │                                (log query)   │
│                   │                                             │
│                   └──→ Redis (cache results)                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Service Dependencies

```
┌─────────────────────────────────────────────────────────────┐
│              SERVICE STARTUP ORDER                           │
│                                                             │
│  1. PostgreSQL (must start first)                           │
│     └── No dependencies                                    │
│                                                             │
│  2. Redis (can start in parallel with PostgreSQL)           │
│     └── No dependencies                                    │
│                                                             │
│  3. Qdrant (can start in parallel)                          │
│     └── No dependencies                                    │
│                                                             │
│  4. FastAPI (depends on PostgreSQL, Redis, Qdrant)          │
│     └── Waits for: db, redis, qdrant healthy               │
│                                                             │
│  5. Celery Worker (depends on PostgreSQL, Redis, Qdrant)    │
│     └── Waits for: db, redis, qdrant healthy               │
│                                                             │
│  docker-compose handles this automatically!                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Running the Complete System

### First Time Setup

```bash
# 1. Clone the repository
git clone <repo-url>
cd enterprise-knowledge-assistant

# 2. Create .env file
cp .env.example .env
# Edit .env with your settings

# 3. Start everything
docker-compose up -d

# 4. Check services are running
docker-compose ps

# 5. Run database migrations
docker-compose exec api alembic upgrade head

# 6. Access the API
# API: http://localhost:8000
# Docs: http://localhost:8000/docs
# Qdrant: http://localhost:6333/dashboard
```

### Development Workflow

```bash
# Start with hot reload
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

# View logs
docker-compose logs -f api

# Run a specific service
docker-compose up api redis db

# Shell into a container
docker-compose exec api bash

# Run tests
docker-compose exec api pytest
```

---

## 6. Debugging Guide

### Common Issues

```
ISSUE: API returns 500 Internal Server Error
├── Check logs: docker-compose logs api
├── Common causes:
│   ├── Database connection failed
│   ├── Qdrant not reachable
│   └── Missing environment variables
└── Fix: Check .env file, ensure all services are running

ISSUE: Document stuck in "processing" status
├── Check Celery worker: docker-compose logs celery_worker
├── Common causes:
│   ├── Worker crashed (memory issue)
│   ├── PDF parsing failed
│   └── Embedding model not loaded
└── Fix: Restart worker, check PDF format

ISSUE: Search returns no results
├── Check Qdrant: http://localhost:6333/dashboard
├── Common causes:
│   ├── Documents not indexed yet
│   ├── RBAC filter too restrictive
│   └── Embedding model mismatch
└── Fix: Verify document status, check filters

ISSUE: Authentication fails
├── Check JWT token: decode at jwt.io
├── Common causes:
│   ├── Token expired
│   ├── Wrong SECRET_KEY
│   └── User not found in database
└── Fix: Re-login, check SECRET_KEY in .env
```

### Health Check Endpoints

```bash
# API health
curl http://localhost:8000/health

# PostgreSQL
docker-compose exec db psql -U postgres -c "SELECT 1"

# Redis
docker-compose exec redis redis-cli ping

# Qdrant
curl http://localhost:6333/healthz

# Celery
docker-compose exec celery_worker celery -A app.workers.celery_app inspect ping
```

---

## 7. Project File Structure

```
enterprise-knowledge-assistant/
│
├── docker-compose.yml          # All services
├── docker-compose.dev.yml      # Development overrides
├── Dockerfile                  # API + Worker image
├── requirements.txt            # Python dependencies
├── .env.example                # Environment template
├── .gitignore
│
├── alembic/                    # Database migrations
│   ├── versions/
│   └── alembic.ini
│
├── app/
│   ├── main.py                 # FastAPI app entry point
│   ├── database.py             # Database engine
│   │
│   ├── config/
│   │   └── settings.py         # Environment variables
│   │
│   ├── models/                 # SQLAlchemy models
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── document.py
│   │   ├── search_query.py
│   │   └── feedback.py
│   │
│   ├── schemas/                # Pydantic schemas
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── document.py
│   │   └── search.py
│   │
│   ├── routes/                 # API endpoints
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── documents.py
│   │   ├── search.py
│   │   └── feedback.py
│   │
│   ├── services/               # Business logic
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── upload.py
│   │   ├── parser.py
│   │   ├── chunker.py
│   │   ├── embedder.py
│   │   ├── qdrant_client.py
│   │   ├── search.py
│   │   ├── reranker.py
│   │   ├── llm.py
│   │   └── cache.py
│   │
│   ├── middleware/              # Cross-cutting concerns
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── rbac.py
│   │   └── rate_limit.py
│   │
│   └── workers/                # Celery tasks
│       ├── __init__.py
│       ├── celery_app.py
│       └── tasks.py
│
├── uploads/                    # Document storage
│
├── md-files/                   # Documentation
│   ├── plan.md
│   ├── technical-analysis.md
│   └── learning-guide/
│       ├── 00-index.md
│       ├── 01-python.md
│       ├── ...
│       └── 10-integration.md
│
└── tests/                      # Test files
    ├── __init__.py
    ├── test_auth.py
    ├── test_documents.py
    └── test_search.py
```

---

## 8. Key Takeaways

### Architecture Principles

```
1. SEPARATION OF CONCERNS
   ├── API layer (FastAPI) handles HTTP
   ├── Service layer handles business logic
   ├── Data layer (PostgreSQL, Qdrant) handles storage
   └── Worker layer (Celery) handles async processing

2. ASYNC EVERYTHING
   ├── File uploads → background processing
   ├── Search → async with caching
   └── Embeddings → batch processing

3. SECURITY BY DEFAULT
   ├── Authentication on every endpoint
   ├── RBAC filtering on every query
   ├── Input validation at boundaries
   └── No secrets in code

4. OBSERVABILITY
   ├── Health check endpoints
   ├── Structured logging
   ├── Audit trails
   └── Metrics collection
```

### Performance Optimization

```
1. CACHING
   ├── Cache search results (5 min TTL)
   ├── Cache user sessions
   └── Invalidate on document update

2. BATCHING
   ├── Batch embeddings (not one-by-one)
   ├── Batch database inserts
   └── Batch Qdrant upserts

3. INDEXING
   ├── PostgreSQL indexes on frequently queried columns
   ├── Qdrant payload indexes for filtering
   └── Composite indexes for complex queries

4. CONNECTION POOLING
   ├── PostgreSQL connection pool
   ├── Redis connection pool
   └── Qdrant connection reuse
```

---

## 9. Next Steps

### For the Intern

1. ✅ Complete all learning guide exercises
2. 🔨 Build the auth system (T1-T4)
3. 🔨 Build the document upload pipeline (T5-T11)
4. 🔨 Build the search system (T12-T16)
5. 🔨 Build the answer generation (T17-T20)
6. 🔨 Add security polish (T21-T25)

### For the Tech Lead

1. 📋 Review the [technical-analysis.md](../technical-analysis.md)
2. 🏗️ Set up CI/CD pipeline
3. 📊 Add monitoring (Prometheus + Grafana)
4. 🔒 Security audit
5. 📈 Load testing
6. 🚀 Production deployment

---

## Congratulations! 🎉

You now understand the complete system architecture. Every component, every data flow, every security layer.

**Remember:**
- Start small, iterate fast
- Test everything
- Document as you go
- Ask questions when unsure

**The journey of a thousand miles begins with a single step.**

You've taken that step. Now go build something amazing! 🚀

---

*This concludes the Enterprise Knowledge Assistant Learning Guide.*

*For implementation details, see [technical-analysis.md](../technical-analysis.md)*
*For task breakdown, see [plan.md](../plan.md)*
