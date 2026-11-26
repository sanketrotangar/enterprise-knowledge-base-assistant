# 01 — Python Fundamentals for This Project

> **Why learn this?** Everything in this project is written in Python. You need to be comfortable with the patterns used throughout the codebase — not every Python feature, just the ones that matter here.
>
> **Scope of learning:** Type hints, async/await, Pydantic models, file handling, context managers. Skip advanced OOP, decorators, metaclasses — you won't need them.

---

## What You Need to Know (and What You Can Skip)

```
✅ LEARN THIS                    ❌ SKIP THIS (for now)
─────────────────────            ─────────────────────
Type hints (str, int, UUID)      Decorators (@property)
Async/await                      Metaclasses
Pydantic models                  Context managers (advanced)
File I/O                         Generators
List comprehensions              Unit testing
f-strings                        Design patterns
Virtual environments             C extensions
```

---

## 1. Type Hints — The Language of This Project

Every file in our project uses type hints. They tell Python (and other developers) what type each variable should be.

### Why It Matters Here

```python
# Without type hints — what does this function expect? 🤷
def process_document(file, org_id, user_id):
    ...

# With type hints — crystal clear 🎯
def process_document(file: UploadFile, org_id: UUID, user_id: UUID) -> dict:
    ...
```

### Types You'll See Everywhere

```python
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel

# Primitive types
name: str = "Alice"
age: int = 30
is_active: bool = True
score: float = 0.95

# UUID — used for every ID in our database
user_id: UUID = UUID("123e4567-e89b-12d3-a456-426614174000")

# Optional — when something can be None
middle_name: str | None = None  # Python 3.10+
# OR
from typing import Optional
middle_name: Optional[str] = None

# List — a list of things
tags: list[str] = ["hr", "policy"]
scores: list[float] = [0.9, 0.8, 0.7]

# Dict — key-value pairs
metadata: dict[str, str] = {"author": "HR", "version": "2.0"}

# Union — can be one of several types
status: str | int = "active"  # Could be str or int

# Callable — a function passed as argument
transform: callable = lambda x: x.upper()
```

### The Real Project Example

Look at this actual code from `app/routes/upload.py`:

```python
from uuid import UUID
from fastapi import APIRouter, UploadFile, File, Form

router = APIRouter()

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),      # The uploaded file
    org_id: UUID = Form(...),          # Which organization
    uploaded_by: UUID = Form(...),     # Who uploaded it
):
    # Everything has a type — you know exactly what comes in and out
    return await save_uploaded_document(
        file=file,
        org_id=org_id,
        uploaded_by=uploaded_by,
    )
```

---

## 2. Async/Await — Why Our API Is Fast

### The Problem

```
Synchronous (slow):
  Request 1 ──▶ [Processing: 2 sec] ──▶ Response
  Request 2 ──▶ [Waiting...] ──▶ [Processing: 2 sec] ──▶ Response
  Request 3 ──▶ [Waiting...] ──▶ [Waiting...] ──▶ [Processing: 2 sec] ──▶ Response
  Total: 6 seconds for 3 requests 😢

Asynchronous (fast):
  Request 1 ──▶ [Processing: 2 sec] ──▶ Response
  Request 2 ──▶ [Processing: 2 sec] ──▶ Response  (starts immediately!)
  Request 3 ──▶ [Processing: 2 sec] ──▶ Response  (starts immediately!)
  Total: 2 seconds for 3 requests 🚀
```

### How It Works

```python
# Synchronous — blocks while waiting
import time

def fetch_data():
    time.sleep(2)  # Blocks everything for 2 seconds
    return {"data": "result"}

# Asynchronous — yields control while waiting
import asyncio

async def fetch_data():
    await asyncio.sleep(2)  # Other tasks run during this 2 seconds
    return {"data": "result"}
```

### In Our Project

```python
# app/routes/upload.py
from fastapi import APIRouter

router = APIRouter()

@router.post("/upload")
async def upload_document(file: UploadFile, org_id: UUID, uploaded_by: UUID):
    # 'async' means this endpoint can handle other requests
    # while waiting for file I/O or database operations
    return await save_uploaded_document(file=file, org_id=org_id, uploaded_by=uploaded_by)
```

### Key Rule

```python
# ✅ DO: Use async for I/O operations (database, file, network)
async def get_user(user_id: UUID) -> User:
    result = await db.execute(query)  # Database I/O
    return result.fetchone()

# ❌ DON'T: Use async for CPU-heavy work (it blocks the event loop)
async def embed_text(text: str) -> list[float]:
    # This blocks! Use sync version in a thread pool instead
    return model.encode(text)

# ✅ DO: Run CPU-heavy work in a thread pool
import asyncio
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

def embed_sync(text: str) -> list[float]:
    return model.encode(text).tolist()

async def embed_text(text: str) -> list[float]:
    return await asyncio.to_thread(embed_sync, text)
```

---

## 3. Pydantic — Data Validation (Used Everywhere)

### What Is Pydantic?

Pydantic validates data at runtime. If someone sends wrong data, Pydantic catches it *before* your code runs.

### Why It Matters Here

```python
from pydantic import BaseModel, EmailStr

# Define what a user SHOULD look like
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    role: str  # "admin" | "manager" | "employee"

# Pydantic validates automatically
user = UserCreate(name="Alice", email="alice@company.com", role="admin")
# ✅ Works

user = UserCreate(name="Alice", email="not-an-email", role="admin")
# ❌ ValidationError: value is not a valid email
```

### Real Project Example

```python
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

# What we send BACK to the client
class DocumentResponse(BaseModel):
    id: UUID
    title: str
    status: str
    created_at: datetime

# What we accept FROM the client
class SearchQuery(BaseModel):
    query: str
    top_k: int = 5  # Default value
    filters: dict | None = None
```

### Common Pydantic Patterns

```python
from pydantic import BaseModel, Field

class DocumentUpload(BaseModel):
    # Field() adds validation rules
    title: str = Field(..., min_length=1, max_length=500)
    sensitivity: str = Field(default="internal", pattern="^(public|internal|confidential|restricted)$")
    role_access: list[str] = Field(default_factory=list)

    # Validators for custom logic
    @classmethod
    def validate_title(cls, v: str) -> str:
        if v.strip() == "":
            raise ValueError("Title cannot be empty")
        return v.strip()
```

---

## 4. File I/O — Handling Uploads

### Basic File Operations

```python
from pathlib import Path

# Create a directory
upload_dir = Path("uploads")
upload_dir.mkdir(exist_ok=True)  # Create if doesn't exist

# Write to a file
file_path = upload_dir / "document.pdf"
file_path.write_bytes(pdf_content)

# Read from a file
content = file_path.read_text()

# Check if file exists
if file_path.exists():
    print(f"File size: {file_path.stat().st_size} bytes")
```

### Async File Upload (FastAPI)

```python
from fastapi import UploadFile, File
from pathlib import Path

async def save_upload(file: UploadFile) -> Path:
    """Save uploaded file to disk in chunks."""
    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)

    file_path = upload_dir / file.filename

    # Read in chunks (don't load entire file into memory!)
    with file_path.open("wb") as buffer:
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            buffer.write(chunk)

    return file_path
```

---

## 5. Context Managers — Clean Resource Management

### What They Are

Context managers ensure resources are properly opened and closed, even if errors occur.

```python
# ❌ Bad — file might not close on error
file = open("data.txt", "r")
data = file.read()
file.close()  # Might not reach here!

# ✅ Good — guaranteed cleanup
with open("data.txt", "r") as file:
    data = file.read()
# File is automatically closed, even if an error occurred
```

### Database Connections

```python
from sqlalchemy import create_engine, text

engine = create_engine("postgresql://user:pass@localhost/db")

# Context manager ensures connection is closed
with engine.connect() as conn:
    result = conn.execute(text("SELECT * FROM users"))
    users = result.fetchall()
# Connection is automatically returned to the pool
```

---

## 6. Data Structures You'll Use

### Dictionaries

```python
# Creating
user = {
    "id": "123e4567-e89b-12d3-a456-426614174000",
    "name": "Alice",
    "role": "admin",
    "department": "engineering"
}

# Accessing
name = user["name"]  # "Alice"
role = user.get("role", "employee")  # "admin" (with default)

# Updating
user["role"] = "manager"

# Merging (Python 3.9+)
defaults = {"is_active": True, "theme": "light"}
config = {**defaults, **user}  # Merge dicts
```

### List Comprehensions

```python
# Transform a list
documents = ["doc1.pdf", "doc2.pdf", "doc3.pdf"]
pdf_files = [d for d in documents if d.endswith(".pdf")]

# Transform with function
chunk_sizes = [len(chunk) for chunk in chunks]

# Filter
active_users = [u for u in users if u.is_active]
```

### f-strings

```python
name = "Alice"
doc_count = 42

# Basic
message = f"Hello, {name}!"

# Expressions
greeting = f"Welcome, {name.upper()}!"

# Formatting
print(f"Documents: {doc_count:,}")  # "Documents: 42"

# Multi-line
query = f"""
SELECT * FROM documents
WHERE org_id = '{org_id}'
AND status = 'indexed'
"""
# ⚠️ Don't use f-strings for SQL — use parameterized queries!
```

---

## 7. Common Patterns in Our Project

### UUID Generation

```python
from uuid import UUID, uuid4

# Generate a new UUID
doc_id = uuid4()  # UUID('a1b2c3d4-e5f6-7890-abcd-ef1234567890')

# Parse a UUID from string
user_id = UUID("123e4567-e89b-12d3-a456-426614174000")
```

### Dataclass-like Patterns

```python
from dataclasses import dataclass

@dataclass
class SearchResult:
    id: str
    content: str
    score: float
    source: str

result = SearchResult(
    id="chunk-123",
    content="The leave policy states...",
    score=0.95,
    source="leave-policy.pdf"
)
```

---

## Try It Yourself

### Exercise 1: Type Hints
Create a function that takes a list of documents (dicts with "title" and "size" keys) and returns only documents larger than 1MB.

### Exercise 2: Async
Write two async functions — one that simulates a database query (sleep 1 sec) and one that simulates an API call (sleep 2 sec). Run them both concurrently and verify they complete in ~2 seconds, not 3.

### Exercise 3: Pydantic
Create a `DocumentMetadata` Pydantic model with fields for title, file_size, mime_type, and uploaded_by. Add validation that title is 1-500 chars and mime_type is one of: "application/pdf", "text/plain", "text/markdown".

---

## Common Pitfalls

| Mistake | Why It's Bad | Fix |
|---------|-------------|-----|
| Forgetting `await` | Function runs but result is a coroutine, not actual data | Always `await` async functions |
| Using mutable defaults | `def f(x=[])` — shared across all calls! | Use `None` default, create inside function |
| Not closing files | Resource leak, locked files | Use `with` statement |
| f-strings in SQL | SQL injection vulnerability | Use parameterized queries |
| Ignoring type hints | Harder to debug, no IDE support | Always add types |
| `import *` | Namespace pollution, unclear dependencies | Import specific names |

---

*Continue to [02-fastapi.md](02-fastapi.md) →*
