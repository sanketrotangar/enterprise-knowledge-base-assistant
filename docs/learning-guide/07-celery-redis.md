# 07 — Celery + Redis: Background Tasks

> **Why learn this?** Document processing (parsing PDFs, generating embeddings, indexing) takes 10-60 seconds per document. We can't block the API for that long. Celery + Redis lets us run these heavy tasks in the background while the API stays responsive.
>
> **Scope of learning:** Task definition, message broker basics, retry logic, monitoring. Skip distributed task routing, custom schedulers, canvas workflows.

---

## The Problem

```
❌ WITHOUT Celery (Synchronous):
─────────────────────────────────

User uploads PDF
    │
    ├──▶ API receives upload (0.1 sec)
    ├──▶ Parse PDF (2-5 sec)          ← User is waiting!
    ├──▶ Chunk text (1 sec)           ← User is waiting!
    ├──▶ Generate embeddings (5-10 sec) ← User is waiting!
    ├──▶ Index in Qdrant (1 sec)      ← User is waiting!
    │
    └──▶ Response sent (10-20 sec total) 😢

User sees: "Please wait..." for 20 seconds


✅ WITH Celery (Asynchronous):
──────────────────────────────

User uploads PDF
    │
    ├──▶ API receives upload (0.1 sec)
    ├──▶ Save file to disk (0.5 sec)
    ├──▶ Send task to Celery (0.01 sec)
    │
    └──▶ Response sent immediately! 🚀
         "Document uploaded, processing..."

Background (Celery worker):
    │
    ├──▶ Parse PDF (2-5 sec)
    ├──▶ Chunk text (1 sec)
    ├──▶ Generate embeddings (5-10 sec)
    ├──▶ Index in Qdrant (1 sec)
    │
    └──▶ Update document status: "indexed" ✅
```

---

## 1. Redis as Message Broker

### What Is a Message Broker?

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Producer   │────▶│   Broker    │────▶│  Consumer   │
│  (FastAPI)   │     │   (Redis)   │     │  (Celery)   │
│              │     │             │     │             │
│ "Process     │     │ [queue:     │     │ "I'll pick  │
│  this doc"   │     │  task-1,    │     │  up task-1  │
│              │     │  task-2,    │     │  and run it"│
│              │     │  task-3]"   │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
```

### Redis Basics

```bash
# Start Redis
docker run -p 6379:6379 redis:alpine

# Or with Docker Compose
docker-compose up redis
```

### Redis as Cache

```python
import redis

# Connect
r = redis.Redis(host="localhost", port=6379, db=0)

# Set a value (with expiry)
r.setex("user:123:name", 300, "Alice")  # Expires in 5 minutes

# Get a value
name = r.get("user:123:name")  # b"Alice"

# Delete
r.delete("user:123:name")

# Check if key exists
r.exists("user:123:name")  # 0 or 1
```

### Redis as Queue

```python
import redis
import json

r = redis.Redis(host="localhost", port=6379, db=1)

# Push a task to the queue
task = {
    "task_id": "abc-123",
    "doc_id": "doc-456",
    "org_id": "org-789",
}
r.lpush("document_processing_queue", json.dumps(task))

# Pop a task (blocking)
task_json = r.brpop("document_processing_queue")
task = json.loads(task_json)
```

---

## 2. Celery Fundamentals

### What Is Celery?

Celery is a distributed task queue. It:
1. Receives tasks from FastAPI
2. Queues them in Redis
3. Workers pick up tasks and execute them
4. Returns results (optional)

### Setup

```bash
pip install celery[redis]
```

### Basic Celery App

```python
# app/workers/celery_app.py

from celery import Celery

# Create Celery app
celery_app = Celery(
    "enterprise_knowledge_assistant",
    broker="redis://localhost:6379/1",      # Where to queue tasks
    backend="redis://localhost:6379/2",     # Where to store results
)

# Configure
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,          # 5 min hard limit
    task_soft_time_limit=240,     # 4 min soft limit (raises warning)
    worker_prefetch_multiplier=1, # Pick up one task at a time
)
```

### Defining Tasks

```python
# app/workers/tasks.py

from app.workers.celery_app import celery_app

@celery_app.task(bind=True, max_retries=3)
def process_document(self, doc_id: str, org_id: str):
    """
    Process an uploaded document:
    1. Parse PDF
    2. Chunk text
    3. Generate embeddings
    4. Index in Qdrant
    """
    try:
        # Update status: processing
        update_doc_status(doc_id, "processing")

        # Step 1: Parse
        text = parse_document(doc_id)

        # Step 2: Chunk
        chunks = chunk_text(text)

        # Step 3: Embed
        embeddings = generate_embeddings(chunks)

        # Step 4: Index
        index_in_qdrant(doc_id, org_id, chunks, embeddings)

        # Update status: indexed
        update_doc_status(doc_id, "indexed")

        return {"status": "success", "doc_id": doc_id}

    except Exception as exc:
        # Retry on failure (up to 3 times)
        self.retry(exc=exc, countdown=60)  # Wait 60 sec before retry
```

### Calling Tasks from FastAPI

```python
# app/routes/upload.py

from fastapi import APIRouter, UploadFile, File, Form
from app.workers.tasks import process_document

router = APIRouter()

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    org_id: UUID = Form(...),
    uploaded_by: UUID = Form(...),
):
    # Step 1: Save file
    doc_id = await save_file(file, org_id, uploaded_by)

    # Step 2: Send to background worker (non-blocking!)
    process_document.delay(
        doc_id=str(doc_id),
        org_id=str(org_id),
    )

    # Step 3: Return immediately
    return {
        "id": str(doc_id),
        "status": "processing",
        "message": "Document is being processed in the background"
    }
```

---

## 3. Task States & Status Tracking

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  RECEIVED   │────▶│  STARTED    │────▶│  SUCCESS    │
│  (queued)   │     │  (running)  │     │  (done)     │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  FAILURE    │
                    │  (error)    │
                    └─────────────┘
```

### Tracking Task Progress

```python
@celery_app.task(bind=True)
def process_document(self, doc_id: str):
    # Update state at each step
    self.update_state(
        state="PROGRESS",
        meta={"current": 1, "total": 4, "step": "parsing"}
    )
    text = parse_document(doc_id)

    self.update_state(
        state="PROGRESS",
        meta={"current": 2, "total": 4, "step": "chunking"}
    )
    chunks = chunk_text(text)

    self.update_state(
        state="PROGRESS",
        meta={"current": 3, "total": 4, "step": "embedding"}
    )
    embeddings = generate_embeddings(chunks)

    self.update_state(
        state="PROGRESS",
        meta={"current": 4, "total": 4, "step": "indexing"}
    )
    index_in_qdrant(doc_id, chunks, embeddings)

    return {"status": "indexed", "chunk_count": len(chunks)}
```

### Checking Task Status from API

```python
from celery.result import AsyncResult

@router.get("/documents/{doc_id}/status")
async def get_processing_status(doc_id: UUID):
    # Get task result (stored in Redis)
    result = AsyncResult(str(doc_id))

    if result.state == "PENDING":
        return {"status": "queued"}
    elif result.state == "PROGRESS":
        return {
            "status": "processing",
            "progress": result.info
        }
    elif result.state == "SUCCESS":
        return {"status": "indexed", "result": result.result}
    elif result.state == "FAILURE":
        return {"status": "failed", "error": str(result.info)}
```

---

## 4. Retry Logic

### Why Retry?

```
Document processing can fail due to:
- Network timeout (Qdrant temporarily unavailable)
- Memory spike (embedding model loaded)
- Disk I/O error (file write failed)

Retry = try again automatically
```

### Retry Strategies

```python
@celery_app.task(
    bind=True,
    max_retries=3,              # Try up to 3 times
    default_retry_delay=60,     # Wait 60 sec between retries
    autoretry_for=(ConnectionError, TimeoutError),  # Auto-retry on these
    retry_backoff=True,         # Exponential backoff (60, 120, 240 sec)
    retry_jitter=True,          # Add random jitter to avoid thundering herd
)
def process_document(self, doc_id: str):
    try:
        # ... processing logic ...
        pass
    except Exception as exc:
        # Manual retry
        raise self.retry(exc=exc, countdown=60)
```

### Dead Letter Queue (DLQ)

```python
# When all retries fail, send to DLQ for manual inspection
@celery_app.task(bind=True, max_retries=3)
def process_document(self, doc_id: str):
    try:
        # ... processing ...
        pass
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            # All retries exhausted — send to DLQ
            send_to_dlq(doc_id, str(exc))
            update_doc_status(doc_id, "failed")
            return {"status": "failed", "error": str(exc)}
        else:
            raise self.retry(exc=exc, countdown=60)
```

---

## 5. Running Celery Workers

### Start a Worker

```bash
# Basic worker
celery -A app.workers.celery_app worker --loglevel=info

# With concurrency (4 threads)
celery -A app.workers.celery_app worker --loglevel=info --concurrency=4

# With specific queue
celery -A app.workers.celery_app worker -Q document_processing --loglevel=info
```

### Multiple Workers

```bash
# Worker 1: Document processing (CPU-heavy)
celery -A app.workers.celery_app worker -Q document_processing -c 2

# Worker 2: Light tasks (notifications, logging)
celery -A app.workers.celery_app worker -Q notifications -c 4
```

### Monitor with Flower

```bash
pip install flower
celery -A app.workers.celery_app flower

# Access at http://localhost:5555
```

---

## 6. Complete Worker Setup

### Project Structure

```
app/
├── workers/
│   ├── __init__.py
│   ├── celery_app.py       # Celery configuration
│   └── tasks.py            # Task definitions
```

### celery_app.py

```python
from celery import Celery

celery_app = Celery(
    "enterprise_knowledge_assistant",
    broker="redis://localhost:6379/1",
    backend="redis://localhost:6379/2",
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=240,
    worker_prefetch_multiplier=1,
    task_acks_late=True,  # Ack after execution, not before
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.workers"])
```

### tasks.py

```python
from app.workers.celery_app import celery_app
from app.services.parser import parse_document
from app.services.chunker import chunk_text
from app.services.embedder import embedding_service
from app.services.qdrant_client import qdrant_service
from app.database import SessionLocal

@celery_app.task(bind=True, max_retries=3)
def process_document_task(self, doc_id: str, org_id: str):
    """Full document processing pipeline."""
    db = SessionLocal()
    try:
        # Update status
        doc = db.query(Document).filter(Document.id == doc_id).first()
        doc.status = "processing"
        db.commit()

        # Step 1: Parse
        text = parse_document(doc.storage_path)

        # Step 2: Chunk
        chunks = chunk_text(text, chunk_size=512, overlap=50)

        # Step 3: Embed
        embeddings = embedding_service.embed_sync(chunks)

        # Step 4: Index in Qdrant
        qdrant_service.store_chunks(
            doc_id=doc_id,
            org_id=org_id,
            chunks=chunks,
            embeddings=embeddings,
            sensitivity=doc.sensitivity,
            role_access=doc.role_access,
        )

        # Update status
        doc.status = "indexed"
        doc.chunk_count = len(chunks)
        db.commit()

        return {"status": "success", "chunks": len(chunks)}

    except Exception as exc:
        db.rollback()
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.status = "failed"
            db.commit()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
```

---

## 7. Redis for Caching

### Caching Search Results

```python
import redis
import json
from hashlib import md5

r = redis.Redis(host="localhost", port=6379, db=0)
CACHE_TTL = 300  # 5 minutes

def get_cached_search(query: str, org_id: str) -> dict | None:
    """Get cached search results."""
    cache_key = f"search:{org_id}:{md5(query.encode()).hexdigest()}"
    cached = r.get(cache_key)
    if cached:
        return json.loads(cached)
    return None

def set_cached_search(query: str, org_id: str, results: dict):
    """Cache search results."""
    cache_key = f"search:{org_id}:{md5(query.encode()).hexdigest()}"
    r.setex(cache_key, CACHE_TTL, json.dumps(results))

def invalidate_doc_cache(doc_id: str):
    """Invalidate cache when document is updated."""
    # Delete all cache keys matching this document
    pattern = f"search:*:*"
    for key in r.scan_iter(match=pattern):
        cached = json.loads(r.get(key))
        if cached.get("doc_id") == doc_id:
            r.delete(key)
```

### Rate Limiting with Redis

```python
import redis
import time

r = redis.Redis(host="localhost", port=6379, db=0)

def is_rate_limited(user_id: str, limit: int = 100, window: int = 60) -> bool:
    """Check if user has exceeded rate limit."""
    key = f"rate_limit:{user_id}"

    # Get current count
    current = r.get(key)

    if current is None:
        # First request in window
        r.setex(key, window, 1)
        return False

    if int(current) >= limit:
        return True

    # Increment counter
    r.incr(key)
    return False
```

---

## Visual Summary

```
┌─────────────────────────────────────────────────────────────┐
│                    CELERY + REDIS ARCHITECTURE               │
│                                                             │
│  ┌─────────────┐                                           │
│  │  FastAPI     │                                           │
│  │  (Producer)  │                                           │
│  └──────┬──────┘                                           │
│         │                                                   │
│         │ task.delay(doc_id, org_id)                        │
│         ▼                                                   │
│  ┌─────────────────────────────────────┐                   │
│  │           Redis (Broker)             │                   │
│  │                                      │                   │
│  │  Queue: document_processing          │                   │
│  │  ┌─────────┬─────────┬─────────┐   │                   │
│  │  │ Task 1  │ Task 2  │ Task 3  │   │                   │
│  │  └─────────┴─────────┴─────────┘   │                   │
│  └──────────────────┬──────────────────┘                   │
│                     │                                       │
│         ┌───────────┼───────────┐                          │
│         ▼           ▼           ▼                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                   │
│  │ Worker 1 │ │ Worker 2 │ │ Worker 3 │                   │
│  │          │ │          │ │          │                   │
│  │ Parse    │ │ Parse    │ │ Parse    │                   │
│  │ Chunk    │ │ Chunk    │ │ Chunk    │                   │
│  │ Embed    │ │ Embed    │ │ Embed    │                   │
│  │ Index    │ │ Index    │ │ Index    │                   │
│  └──────────┘ └──────────┘ └──────────┘                   │
│                     │                                       │
│                     ▼                                       │
│  ┌─────────────────────────────────────┐                   │
│  │           Redis (Backend)            │                   │
│  │                                      │                   │
│  │  Results: {doc_id: "indexed"}        │                   │
│  │  Cache: {query_hash: results}        │                   │
│  └─────────────────────────────────────┘                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Try It Yourself

### Exercise 1: Basic Task
1. Create a Celery app with Redis broker
2. Define a task that takes 10 seconds (use `time.sleep`)
3. Call the task with `.delay()`
4. Check the task status

### Exercise 2: Retry Logic
1. Create a task that fails randomly (50% chance)
2. Add retry logic with exponential backoff
3. Run it 10 times — how many eventually succeed?

### Exercise 3: Caching
1. Implement a simple cache with Redis
2. Cache a slow function's results
3. Verify the second call is instant

---

## Common Pitfalls

| Mistake | Why It's Bad | Fix |
|---------|-------------|-----|
| Not using `.delay()` | Blocks the API | Always use `.delay()` for background tasks |
| No retry logic | Permanent failure on transient errors | Add `max_retries` and `autoretry_for` |
| Not closing DB sessions | Connection leak in workers | Use `try/finally` to close sessions |
| Prefetch too high | Worker overloaded, unfair scheduling | Set `worker_prefetch_multiplier=1` |
| No task timeout | Worker hangs forever | Set `task_time_limit` |
| Storing secrets in tasks | Security risk | Use environment variables |

---

*Continue to [08-docker.md](08-docker.md) →*
