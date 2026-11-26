# 03 — PostgreSQL + SQLAlchemy: Data Storage

> **Why learn this?** PostgreSQL stores all our metadata — users, documents, roles, permissions, search history, feedback. SQLAlchemy is how Python talks to PostgreSQL. Without this, we have nowhere to persist data.
>
> **Scope of learning:** SQL basics, table design, queries, SQLAlchemy models, relationships, migrations. Skip advanced PostgreSQL features (window functions, CTEs, PL/pgSQL) — we don't need them yet.

---

## The Big Picture

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│   FastAPI        │         │   SQLAlchemy     │         │   PostgreSQL    │
│   (API)          │───────▶│   (ORM)          │───────▶│   (Database)    │
│                  │         │                  │         │                  │
│ Gets HTTP request│         │ Translates Python│         │ Stores data      │
│ Calls service    │         │ to SQL queries   │         │ Returns results  │
└─────────────────┘         └─────────────────┘         └─────────────────┘

You write:          SQLAlchemy converts to:      PostgreSQL runs:
db.query(User)      SELECT * FROM users          Actually executes query
                    WHERE id = '123'
```

---

## 1. PostgreSQL Fundamentals

### What Is a Database?

Think of it as a collection of spreadsheets:

```
┌─────────────────────────────────────────────────────┐
│                    DATABASE                         │
│  "enterprise_knowledge_base"                        │
│                                                     │
│  ┌─────────────────┐    ┌─────────────────┐        │
│  │    users         │    │   documents     │        │
│  │                  │    │                 │        │
│  │ id | name | role │    │ id | title | ...│        │
│  │----|------|------│    │----|-------|----│        │
│  │ 1  | Alice| admin│    │ 1  | Leave |    │        │
│  │ 2  | Bob  | emp  │    │ 2  | VPN   |    │        │
│  └─────────────────┘    └─────────────────┘        │
│                                                     │
│  ┌─────────────────┐    ┌─────────────────┐        │
│  │  search_queries  │    │    feedback     │        │
│  │                  │    │                 │        │
│  │ id | query | ... │    │ id | rating | ..│        │
│  └─────────────────┘    └─────────────────┘        │
└─────────────────────────────────────────────────────┘
```

### SQL Basics

```sql
-- CREATE a table
CREATE TABLE users (
    id    UUID PRIMARY KEY,
    name  VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    role  VARCHAR(50) DEFAULT 'employee'
);

-- INSERT data
INSERT INTO users (id, name, email, role)
VALUES ('123e4567-e89b-12d3-a456-426614174000', 'Alice', 'alice@company.com', 'admin');

-- SELECT data
SELECT * FROM users WHERE role = 'admin';

-- UPDATE data
UPDATE users SET role = 'manager' WHERE name = 'Alice';

-- DELETE data
DELETE FROM users WHERE name = 'Bob';
```

### Key Concepts

```sql
-- PRIMARY KEY: Unique identifier for each row
id UUID PRIMARY KEY DEFAULT gen_random_uuid()

-- FOREIGN KEY: References another table's primary key
org_id UUID REFERENCES organizations(id) ON DELETE CASCADE

-- NOT NULL: Must have a value
name VARCHAR(255) NOT NULL

-- UNIQUE: No duplicates allowed
email VARCHAR(255) UNIQUE NOT NULL

-- DEFAULT: Auto-set if not provided
role VARCHAR(50) DEFAULT 'employee'
status VARCHAR(50) DEFAULT 'uploaded'

-- INDEX: Speeds up searches
CREATE INDEX idx_users_email ON users(email);
```

---

## 2. SQLAlchemy Models — Python Representation of Tables

### Basic Model

```python
from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

# This Python class = a PostgreSQL table
class User:
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    role = Column(String(50), default="employee")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

### With SQLAlchemy 2.0 (Modern Style)

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from datetime import datetime
from uuid import UUID, uuid4

# Base class for all models
class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    role: Mapped[str] = mapped_column(String(50), default="employee")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### All Our Models

```python
# Organization
class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    settings: Mapped[dict] = mapped_column(JSONB, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

# Document
class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    title: Mapped[str] = mapped_column(String(500))
    source_type: Mapped[str] = mapped_column(String(50), default="upload")
    storage_path: Mapped[str] = mapped_column(String(1000))
    uploaded_by: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    sensitivity: Mapped[str] = mapped_column(String(50), default="internal")
    role_access: Mapped[list] = mapped_column(ARRAY(String), default=[])
    status: Mapped[str] = mapped_column(String(50), default="uploaded")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

# Search Query
class SearchQuery(Base):
    __tablename__ = "search_queries"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    query_text: Mapped[str] = mapped_column(Text)
    results_count: Mapped[int] = mapped_column(Integer, default=0)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

# Feedback
class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    query_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("search_queries.id"))
    user_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    rating: Mapped[str] = mapped_column(String(20))  # 'useful', 'not_useful', 'partial'
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

---

## 3. Relationships

### Visual

```
organizations
    │
    │ 1:N (one org has many users)
    │
    ▼
users ─────────────────────────────────┐
    │                                  │
    │ 1:N (one user uploads many docs) │ 1:N (one user submits many feedbacks)
    │                                  │
    ▼                                  ▼
documents ────────────────┐    search_queries
    │                      │         │
    │ 1:N                  │         │ 1:N
    │                      │         │
    ▼                      ▼         ▼
document_chunks    query_citations   feedback
```

### Defining Relationships

```python
from sqlalchemy.orm import relationship

class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))

    # Relationship: one user belongs to one org
    organization: Mapped["Organization"] = relationship(back_populates="users")

    # Relationship: one user uploads many documents
    documents: Mapped[list["Document"]] = relationship(back_populates="uploader")

class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    uploaded_by: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    # Relationship: one document belongs to one uploader
    uploader: Mapped["User"] = relationship(back_populates="documents")

    # Relationship: one document has many chunks
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")
```

### Querying Relationships

```python
from sqlalchemy.orm import Session, selectinload

# Get user with their documents (lazy loading)
user = db.query(User).filter(User.id == user_id).first()
print(user.documents)  # Triggers a separate query!

# Get user with documents in ONE query (eager loading)
user = (
    db.query(User)
    .options(selectinload(User.documents))
    .filter(User.id == user_id)
    .first()
)
print(user.documents)  # No extra query!
```

---

## 4. CRUD Operations

### Create

```python
from sqlalchemy.orm import Session

def create_user(db: Session, name: str, email: str, role: str = "employee") -> User:
    user = User(name=name, email=email, role=role)
    db.add(user)          # Add to session
    db.commit()           # Save to database
    db.refresh(user)      # Reload with generated ID
    return user
```

### Read

```python
# Get one user
user = db.query(User).filter(User.id == user_id).first()

# Get all users in an org
users = db.query(User).filter(User.org_id == org_id).all()

# Get with filters and sorting
users = (
    db.query(User)
    .filter(User.org_id == org_id, User.is_active == True)
    .order_by(User.created_at.desc())
    .limit(20)
    .all()
)

# Count users
count = db.query(User).filter(User.org_id == org_id).count()

# Get or raise 404
from fastapi import HTTPException

user = db.query(User).filter(User.id == user_id).first()
if not user:
    raise HTTPException(status_code=404, detail="User not found")
```

### Update

```python
# Update a user
user = db.query(User).filter(User.id == user_id).first()
user.role = "manager"       # Modify the field
db.commit()                 # Save changes

# Bulk update
db.query(User).filter(User.org_id == org_id).update({"is_active": False})
db.commit()
```

### Delete

```python
# Delete a user
user = db.query(User).filter(User.id == user_id).first()
db.delete(user)
db.commit()

# Delete with filter
db.query(User).filter(User.is_active == False).delete()
db.commit()
```

---

## 5. Sessions and Connection Management

### How It Works

```
FastAPI Request
    │
    ▼
get_db() dependency
    │
    ├── Creates SessionLocal()
    │
    ├── Passes session to route handler
    │
    ├── Route handler uses session
    │
    └── Session.close() (cleanup)
```

### Implementation

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Create engine (connection pool)
DATABASE_URL = "postgresql+psycopg://user:pass@localhost:5432/ekb"
engine = create_engine(DATABASE_URL)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Dependency for FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Usage in routes
@app.get("/api/v1/users")
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return {"users": users}
```

---

## 6. Migrations with Alembic

### Why Migrations

When you change your models (add a column, create a table), Alembic generates the SQL to update the database.

```bash
# Install
pip install alembic

# Initialize
alembic init alembic

# Create a migration after model changes
alembic revision --autogenerate -m "add users table"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

### What Alembic Generates

```python
# alembic/versions/abc123_add_users_table.py

def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )

def downgrade():
    op.drop_table('users')
```

---

## 7. Indexing — Making Queries Fast

### When to Add Indexes

```sql
-- ❌ WITHOUT INDEX: Full table scan (slow for large tables)
SELECT * FROM documents WHERE org_id = 'abc-123';
-- Scans ALL rows to find matches

-- ✅ WITH INDEX: Direct lookup (fast!)
CREATE INDEX idx_documents_org ON documents(org_id);
-- Jumps directly to matching rows
```

### Index Strategy

```sql
-- Single column index (for WHERE clauses)
CREATE INDEX idx_documents_org ON documents(org_id);
CREATE INDEX idx_documents_status ON documents(status);

-- Composite index (for multiple WHERE conditions)
-- Columns ordered by: equality first, then range/sort
CREATE INDEX idx_documents_org_status ON documents(org_id, status);

-- For sorting
CREATE INDEX idx_queries_org_time ON search_queries(org_id, created_at DESC);

-- Partial index (for specific conditions)
CREATE INDEX idx_active_users ON users(org_id) WHERE is_active = true;
```

---

## Try It Yourself

### Exercise 1: Create a Model
Create a `DocumentChunk` model with:
- id (UUID, primary key)
- document_id (UUID, foreign key to documents)
- content (Text)
- chunk_index (Integer)
- created_at (DateTime)

### Exercise 2: CRUD Operations
Write functions to:
- Create a document chunk
- Get all chunks for a document
- Delete all chunks when a document is deleted

### Exercise 3: Relationship Query
Write a query that fetches a document with all its chunks in a single query (use `selectinload`).

---

## Common Pitfalls

| Mistake | Why It's Bad | Fix |
|---------|-------------|-----|
| N+1 queries | 100 users = 100 queries! | Use `selectinload` for relationships |
| Not using indexes | Slow queries on large tables | Add indexes for WHERE/ORDER BY columns |
| Committing too often | Slows down bulk operations | Batch commits for bulk inserts |
| Not closing sessions | Connection pool exhaustion | Always use `Depends(get_db)` |
| Using raw SQL with f-strings | SQL injection | Use parameterized queries |
| Missing `db.refresh()` | Stale data after insert | Refresh to get generated fields |

---

*Continue to [04-qdrant.md](04-qdrant.md) →*
