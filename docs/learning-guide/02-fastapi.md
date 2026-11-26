# 02 — FastAPI: Building the API Layer

> **Why learn this?** FastAPI is the backbone of our system. Every user request — uploading documents, searching, getting answers — goes through FastAPI. It handles HTTP requests, validates input, and connects to our services.
>
> **Scope of learning:** Routes, request/response handling, dependency injection, middleware. Skip auto-generated docs (just know it exists), WebSocket, background tasks (we use Celery instead).

---

## What FastAPI Does

```
User's Browser/App
        │
        │ HTTP Request (POST /search)
        ▼
┌─────────────────────────────────────────┐
│              FastAPI                     │
│                                         │
│  1. Route matching     ──▶ /search      │
│  2. Input validation   ──▶ Pydantic     │
│  3. Auth check         ──▶ JWT verify   │
│  4. Business logic     ──▶ Services     │
│  5. Response building  ──▶ JSON         │
│                                         │
└─────────────────────────────────────────┘
        │
        │ HTTP Response
        ▼
User sees results
```

---

## 1. Your First FastAPI App

### Minimal Example

```python
from fastapi import FastAPI

# Create the app
app = FastAPI(title="Enterprise Knowledge Assistant")

# Define a route
@app.get("/")
def root():
    return {"message": "Hello, World!"}

# Run with: uvicorn main:app --reload
```

### What Happens

```
1. You run: uvicorn main:app --reload
2. Uvicorn starts a web server on port 8000
3. When you visit http://localhost:8000/
4. FastAPI sees GET / matches the root() function
5. Returns {"message": "Hello, World!"} as JSON
```

---

## 2. Routes — The Building Blocks

### Route Types

```python
from fastapi import FastAPI

app = FastAPI()

# GET — Read data (no side effects)
@app.get("/api/v1/documents")
def list_documents():
    return {"documents": []}

# POST — Create new data
@app.post("/api/v1/documents")
def create_document():
    return {"id": "new-doc-id", "status": "created"}

# PUT — Replace entire resource
@app.put("/api/v1/documents/{doc_id}")
def replace_document(doc_id: str):
    return {"id": doc_id, "status": "replaced"}

# PATCH — Partial update
@app.patch("/api/v1/documents/{doc_id}")
def update_document(doc_id: str):
    return {"id": doc_id, "status": "updated"}

# DELETE — Remove resource
@app.delete("/api/v1/documents/{doc_id}")
def delete_document(doc_id: str):
    return {"status": "deleted"}
```

### Path Parameters

```python
from uuid import UUID

# {doc_id} is a path parameter — part of the URL
@app.get("/api/v1/documents/{doc_id}")
def get_document(doc_id: UUID):  # FastAPI auto-converts to UUID
    return {"id": doc_id, "title": "Leave Policy"}

# Multiple path parameters
@app.get("/api/v1/organizations/{org_id}/documents/{doc_id}")
def get_org_document(org_id: UUID, doc_id: UUID):
    return {"org_id": org_id, "doc_id": doc_id}
```

### Query Parameters

```python
# ?page=1&limit=20 are query parameters
@app.get("/api/v1/documents")
def list_documents(
    page: int = 1,          # Default value of 1
    limit: int = 20,        # Default value of 20
    status: str | None = None,  # Optional
):
    return {"page": page, "limit": limit, "status": status}

# GET /api/v1/documents?page=2&limit=10&status=indexed
# Returns: {"page": 2, "limit": 10, "status": "indexed"}
```

---

## 3. Request Bodies — Receiving Data

### With Pydantic

```python
from pydantic import BaseModel, Field

# Define the expected request body
class SearchQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict | None = None

# FastAPI validates the body automatically
@app.post("/api/v1/search")
def search(query: SearchQuery):
    # query is already validated!
    # query.query = "What is the leave policy?"
    # query.top_k = 5
    return {"results": [], "query": query.query}

# Client sends:
# POST /api/v1/search
# {
#     "query": "What is the leave policy?",
#     "top_k": 5
# }
```

### Complex Request Body

```python
class DocumentUploadRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    sensitivity: str = Field(
        default="internal",
        pattern="^(public|internal|confidential|restricted)$"
    )
    role_access: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

@app.post("/api/v1/documents")
def upload_document(body: DocumentUploadRequest):
    # All fields are validated and typed
    print(body.title)          # str
    print(body.sensitivity)    # str
    print(body.role_access)    # list[str]
    print(body.metadata)       # dict
    return {"status": "uploaded"}
```

---

## 4. Response Models — What We Send Back

### Why Use Them

```python
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID

# Define what the response looks like
class DocumentResponse(BaseModel):
    id: UUID
    title: str
    status: str
    created_at: datetime
    chunk_count: int

# FastAPI documents this in /docs
@app.get("/api/v1/documents/{doc_id}", response_model=DocumentResponse)
def get_document(doc_id: UUID):
    # Even if you return extra fields, they're stripped
    return {
        "id": doc_id,
        "title": "Leave Policy",
        "status": "indexed",
        "created_at": "2024-01-15T10:30:00Z",
        "chunk_count": 42,
        "internal_field": "this is removed from response"  # Stripped!
    }
```

### Error Responses

```python
from fastapi import HTTPException

@app.get("/api/v1/documents/{doc_id}")
def get_document(doc_id: UUID):
    doc = find_document(doc_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Document {doc_id} not found"
                }
            }
        )
    return doc
```

---

## 5. File Uploads — Critical for Our Project

### Basic File Upload

```python
from fastapi import UploadFile, File, Form

@app.post("/api/v1/documents/upload")
async def upload_document(
    file: UploadFile = File(...),           # The actual file
    org_id: UUID = Form(...),               # Form field
    uploaded_by: UUID = Form(...),          # Form field
):
    # file.filename = "leave-policy.pdf"
    # file.content_type = "application/pdf"
    # file.size (use await file.read() to get content)

    return {
        "filename": file.filename,
        "content_type": file.content_type,
        "status": "uploading"
    }
```

### Saving the File

```python
from pathlib import Path
from fastapi import UploadFile, File, Form
from uuid import uuid4

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

@app.post("/api/v1/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    org_id: UUID = Form(...),
    uploaded_by: UUID = Form(...),
):
    # Generate unique filename
    doc_id = uuid4()
    original_name = Path(file.filename or "upload").name
    file_path = UPLOAD_DIR / f"{doc_id}_{original_name}"

    # Save in chunks (don't load entire file into memory!)
    with file_path.open("wb") as buffer:
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            buffer.write(chunk)

    return {
        "id": str(doc_id),
        "filename": original_name,
        "size": file_path.stat().st_size
    }
```

---

## 6. Dependency Injection — Sharing Resources

### What It Is

FastAPI can automatically provide dependencies (like database connections) to your route functions.

```python
from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

app = FastAPI()

# Define a dependency
def get_db():
    db = SessionLocal()
    try:
        yield db          # This is a generator — provides the connection
    finally:
        db.close()        # Cleanup when done

# Use it in a route
@app.get("/api/v1/documents")
def list_documents(db: Session = Depends(get_db)):
    # db is automatically provided by FastAPI
    # FastAPI calls get_db() before your function
    # And ensures db.close() runs after
    documents = db.query(Document).all()
    return {"documents": documents}
```

### Why This Is Powerful

```python
# The SAME route works with different dependencies:
# - In production: uses real database
# - In tests: uses test database
# - In development: uses local database

# Just swap the dependency!
def get_test_db():
    return testing_db_session

# In tests:
app.dependency_overrides[get_db] = get_test_db
```

---

## 7. Routers — Organizing Code

### Why Routers

Instead of one giant `main.py`, split into separate files:

```
app/
├── main.py              # App entry point
├── routes/
│   ├── __init__.py
│   ├── auth.py          # /api/v1/auth/*
│   ├── documents.py     # /api/v1/documents/*
│   ├── search.py        # /api/v1/search/*
│   └── feedback.py      # /api/v1/feedback/*
```

### Creating a Router

```python
# app/routes/search.py
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/api/v1/search", tags=["search"])

@router.post("/")
def search_documents(query: SearchQuery):
    return {"results": []}

@router.get("/history")
def search_history():
    return {"history": []}
```

### Connecting to Main App

```python
# app/main.py
from fastapi import FastAPI
from app.routes import auth, documents, search, feedback

app = FastAPI(title="Enterprise Knowledge Assistant")

# Include all routers
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(feedback.router)
```

---

## 8. Middleware — Cross-Cutting Concerns

### What Middleware Does

Middleware runs before/after every request:

```
Request → [Middleware 1] → [Middleware 2] → [Route Handler] → Response
          ↑                              ↑
          └── Logs, Auth, CORS, etc. ────┘
```

### CORS Middleware

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Custom Middleware

```python
import time
from fastapi import Request

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()

    # Process the request
    response = await call_next(request)

    # Add timing header
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)

    return response
```

---

## 9. Real Project Structure

```
app/
├── main.py                 # App creation, lifespan, router includes
├── config/
│   └── settings.py         # Environment variables
├── database.py             # Database engine + connection check
├── models/                 # SQLAlchemy models
│   ├── __init__.py
│   ├── user.py
│   ├── document.py
│   └── feedback.py
├── schemas/                # Pydantic request/response models
│   ├── __init__.py
│   ├── auth.py
│   ├── document.py
│   └── search.py
├── routes/                 # API endpoints
│   ├── __init__.py
│   ├── auth.py
│   ├── documents.py
│   ├── search.py
│   └── feedback.py
├── services/               # Business logic
│   ├── __init__.py
│   ├── auth.py
│   ├── upload.py
│   ├── search.py
│   └── llm.py
├── middleware/              # Cross-cutting concerns
│   ├── __init__.py
│   ├── auth.py
│   └── rate_limit.py
└── workers/                # Celery background tasks
    ├── __init__.py
    └── document_processor.py
```

---

## 10. Running the App

```bash
# Install dependencies
pip install fastapi uvicorn[standard]

# Development mode (auto-reload on code changes)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Production mode
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

# Access the app
# API: http://localhost:8000
# Docs: http://localhost:8000/docs  (auto-generated!)
# Health: http://localhost:8000/health
```

---

## Try It Yourself

### Exercise 1: Create a CRUD API
Build a simple API for "tasks" with:
- `POST /tasks` — Create a task
- `GET /tasks` — List all tasks
- `GET /tasks/{id}` — Get one task
- `DELETE /tasks/{id}` — Delete a task

### Exercise 2: File Upload
Create an endpoint that accepts a PDF file upload, saves it to disk, and returns the file metadata.

### Exercise 3: Error Handling
Add proper error handling to your CRUD API — return 404 when task not found, 422 for validation errors.

---

## Common Pitfalls

| Mistake | Why It's Bad | Fix |
|---------|-------------|-----|
| Forgetting `async` on I/O routes | Blocks the event loop, slows everything | Use `async def` for database/file operations |
| Using `def` instead of `async def` | Runs in thread pool, not event loop | Use `def` only for CPU-bound work |
| Not validating input | Security risk, crashes from bad data | Use Pydantic models |
| Returning raw dicts | No documentation, no validation | Use `response_model` |
| Hardcoding config | Can't change between environments | Use `pydantic-settings` |
| Not using dependency injection | Hard to test, tight coupling | Use `Depends()` |

---

*Continue to [03-postgresql-sqlalchemy.md](03-postgresql-sqlalchemy.md) →*
