# 09 — Authentication + RBAC: Securing the System

> **Why learn this?** Our system contains sensitive company documents. Without authentication, anyone can access everything. Without RBAC, an intern can see HR confidential policies. This section ensures the right people see the right documents.
>
> **Scope of learning:** JWT tokens, password hashing, role-based access control, middleware. Skip OAuth2/SAML (use email/password for MVP), MFA, advanced audit logging.

---

## The Security Model

```
┌─────────────────────────────────────────────────────────────┐
│                    SECURITY LAYERS                           │
│                                                             │
│  Layer 1: Authentication                                    │
│  "Who are you?"                                             │
│  ├── Email + password                                       │
│  ├── Password hashed with bcrypt                            │
│  └── Returns JWT token                                      │
│                                                             │
│  Layer 2: Authorization (RBAC)                              │
│  "What can you do?"                                         │
│  ├── Role: admin, manager, employee, intern                 │
│  ├── Department: hr, engineering, finance                   │
│  └── Sensitivity: public, internal, confidential            │
│                                                             │
│  Layer 3: Access Control                                    │
│  "Which documents can you see?"                             │
│  ├── Org isolation (org A can't see org B's docs)          │
│  ├── Role-based (interns can't see confidential docs)       │
│  └── Hierarchy (employees can't see manager-only docs)      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Password Hashing

### Why Hash Passwords?

```
❌ NEVER store plain text passwords:

Database: "alice@company.com : password123"
  → If database is leaked, all passwords exposed!

✅ ALWAYS store hashed passwords:

Database: "alice@company.com : $2b$12$LJ3m4..."
  → Even if leaked, passwords are unreadable!
```

### How Hashing Works

```
Password: "password123"
    │
    ▼
┌─────────────────────────────┐
│  bcrypt (hashing algorithm) │
│                             │
│  Input: password123         │
│  Salt:  (random, unique)    │
│  Cost:  12 rounds           │
│                             │
│  Output: $2b$12$LJ3m4...   │
│  (one-way, can't reverse!)  │
└─────────────────────────────┘
```

### Implementation

```python
from passlib.context import CryptContext

# Create hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash a password for storage."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)

# Usage
hashed = hash_password("password123")
print(hashed)  # "$2b$12$LJ3m4K..."

# Later, verify login
is_valid = verify_password("password123", hashed)
print(is_valid)  # True

is_valid = verify_password("wrongpassword", hashed)
print(is_valid)  # False
```

---

## 2. JWT Tokens

### What Is JWT?

JWT (JSON Web Token) is a way to prove identity without storing sessions on the server.

```
┌─────────────────────────────────────────────────────────────┐
│                      JWT TOKEN                               │
│                                                             │
│  Header.Payload.Signature                                   │
│                                                             │
│  Header:                                                    │
│  {                                                          │
│    "alg": "HS256",                                          │
│    "typ": "JWT"                                             │
│  }                                                          │
│                                                             │
│  Payload:                                                   │
│  {                                                          │
│    "sub": "user-123",        ← User ID                     │
│    "org_id": "org-456",      ← Organization                │
│    "role": "admin",          ← Role                        │
│    "exp": 1704067200,        ← Expiration (24h)            │
│    "iat": 1703980800         ← Issued at                   │
│  }                                                          │
│                                                             │
│  Signature:                                                 │
│  HMAC-SHA256(header + payload, SECRET_KEY)                  │
│  (ensures token hasn't been tampered with)                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Why JWT?

```
Session-based (traditional):         JWT (stateless):
┌─────────────┐                     ┌─────────────┐
│   Client    │                     │   Client    │
└──────┬──────┘                     └──────┬──────┘
       │                                    │
       │ "login: alice / pass123"           │ "login: alice / pass123"
       ▼                                    ▼
┌─────────────┐                     ┌─────────────┐
│   Server    │                     │   Server    │
│             │                     │             │
│ Store       │                     │ Generate    │
│ session in  │                     │ JWT token   │
│ database    │                     │ (no storage)│
│             │                     │             │
│ Return      │                     │ Return      │
│ session ID  │                     │ JWT token   │
└─────────────┘                     └─────────────┘

Each request:                       Each request:
  Send session ID                     Send JWT token
  Server looks up session            Server verifies signature
  (database query)                    (no database needed!)
```

### Implementation

```python
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Configuration
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Security scheme
security = HTTPBearer()

def create_access_token(data: dict) -> str:
    """Create a JWT token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    """Decode and verify a JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

# Dependency to get current user
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Extract and verify user from JWT token."""
    token = credentials.credentials
    payload = decode_token(token)

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    return {
        "user_id": user_id,
        "org_id": payload.get("org_id"),
        "role": payload.get("role"),
    }
```

### Login Endpoint

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

class LoginRequest(BaseModel):
    email: str
    password: str

@router.post("/login")
def login(request: LoginRequest):
    # Find user
    user = db.query(User).filter(User.email == request.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Verify password
    if not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Create JWT token
    token = create_access_token({
        "sub": str(user.id),
        "org_id": str(user.org_id),
        "role": user.role,
    })

    return {"access_token": token, "token_type": "bearer"}
```

### Protected Endpoint

```python
@router.get("/api/v1/me")
def get_current_user_info(
    user: dict = Depends(get_current_user),  # Requires valid JWT
):
    return {
        "user_id": user["user_id"],
        "org_id": user["org_id"],
        "role": user["role"],
    }
```

---

## 3. Role-Based Access Control (RBAC)

### Role Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                    ROLE HIERARCHY                            │
│                                                             │
│  ┌─────────────┐                                           │
│  │    ADMIN     │  ← Full access to everything              │
│  └──────┬──────┘                                           │
│         │                                                   │
│  ┌──────▼──────┐                                           │
│  │   MANAGER   │  ← Access to team docs + org docs          │
│  └──────┬──────┘                                           │
│         │                                                   │
│  ┌──────▼──────┐                                           │
│  │  EMPLOYEE   │  ← Access to org docs + role-specific      │
│  └──────┬──────┘                                           │
│         │                                                   │
│  ┌──────▼──────┐                                           │
│  │   INTERN    │  ← Access to public/general docs only      │
│  └─────────────┘                                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Sensitivity Levels

```
┌─────────────────────────────────────────────────────────────┐
│                 DOCUMENT SENSITIVITY                         │
│                                                             │
│  PUBLIC                                                     │
│  ├── Everyone in the organization can see                   │
│  ├── Example: Company newsletter, office hours              │
│  └── Everyone: admin, manager, employee, intern             │
│                                                             │
│  INTERNAL                                                   │
│  ├── All employees (not interns)                            │
│  ├── Example: Company policies, procedures                  │
│  └── admin, manager, employee                               │
│                                                             │
│  CONFIDENTIAL                                               │
│  ├── Managers and above only                                │
│  ├── Example: Salary info, performance reviews              │
│  └── admin, manager                                         │
│                                                             │
│  RESTRICTED                                                 │
│  ├── Admin only                                             │
│  ├── Example: Legal documents, board minutes                │
│  └── admin only                                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### RBAC Middleware

```python
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse

# Role hierarchy (higher number = more access)
ROLE_HIERARCHY = {
    "intern": 1,
    "employee": 2,
    "manager": 3,
    "admin": 4,
}

# Sensitivity → minimum role required
SENSITIVITY_LEVELS = {
    "public": 1,        # intern can access
    "internal": 2,      # employee can access
    "confidential": 3,  # manager can access
    "restricted": 4,    # admin can access
}

def check_document_access(
    user_role: str,
    document_sensitivity: str,
    document_role_access: list[str],
    user_department: str,
) -> bool:
    """Check if user can access a document."""
    user_level = ROLE_HIERARCHY.get(user_role, 0)
    required_level = SENSITIVITY_LEVELS.get(document_sensitivity, 4)

    # Check sensitivity level
    if user_level < required_level:
        return False

    # Check role access (if document is restricted to specific roles)
    if document_role_access:  # Non-empty list
        if user_department not in document_role_access:
            return False

    return True

# Middleware
async def rbac_middleware(request: Request, call_next):
    # Skip auth for public endpoints
    if request.url.path in ["/health", "/api/v1/auth/login", "/api/v1/auth/register"]:
        return await call_next(request)

    # Get user from JWT
    user = request.state.user  # Set by auth middleware
    if not user:
        return JSONResponse(
            status_code=401,
            content={"error": "Not authenticated"}
        )

    # For document-specific routes, check access
    if "/documents/" in request.url.path:
        doc_id = request.path_params.get("doc_id")
        if doc_id:
            doc = get_document(doc_id)
            if not check_document_access(
                user_role=user["role"],
                document_sensitivity=doc.sensitivity,
                document_role_access=doc.role_access,
                user_department=user.get("department"),
            ):
                return JSONResponse(
                    status_code=403,
                    content={"error": "Insufficient permissions"}
                )

    return await call_next(request)
```

---

## 4. Access Control in Search

### Filtering Search Results by RBAC

```python
# In search service
async def search(
    query: str,
    user: dict,  # From JWT
) -> list[dict]:
    # Build filter based on user's role and department
    org_id = user["org_id"]
    user_role = user["role"]
    department = user.get("department", "")

    # Get allowed sensitivity levels
    user_level = ROLE_HIERARCHY.get(user_role, 0)
    allowed_sensitivity = [
        s for s, level in SENSITIVITY_LEVELS.items()
        if level <= user_level
    ]

    # Build Qdrant filter
    search_filter = Filter(
        must=[
            # Must be from user's org
            FieldCondition(key="org_id", match=MatchValue(value=org_id)),
            # Must be accessible sensitivity level
            FieldCondition(key="sensitivity", match=MatchAny(any=allowed_sensitivity)),
        ]
    )

    # If not admin/manager, also check role_access
    if user_level < 3:  # Not manager or above
        search_filter.must.append(
            FieldCondition(
                key="role_access",
                match=MatchAny(any=[department, "general"])  # User's dept or general
            )
        )

    # Execute search with filter
    results = qdrant_client.search(
        collection_name="enterprise_embeddings",
        query_vector=query_embedding,
        query_filter=search_filter,
        limit=10,
    )

    return results
```

---

## 5. Complete Auth Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    AUTH FLOW                                  │
│                                                             │
│  1. LOGIN                                                   │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐           │
│  │  Client   │────▶│  API     │────▶│  DB      │           │
│  │           │     │  /login  │     │          │           │
│  │ email +   │     │          │     │ Verify   │           │
│  │ password  │     │          │     │ password │           │
│  │           │◀────│          │◀────│          │           │
│  │           │     │          │     │          │           │
│  │ JWT token │     │ Generate │     │          │           │
│  │           │     │ JWT      │     │          │           │
│  └──────────┘     └──────────┘     └──────────┘           │
│                                                             │
│  2. AUTHENTICATED REQUEST                                   │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐           │
│  │  Client   │────▶│  API     │────▶│  Qdrant  │           │
│  │           │     │  /search │     │          │           │
│  │ JWT token │     │          │     │ Search   │           │
│  │ in header │     │ Verify   │     │ with     │           │
│  │           │     │ JWT +    │     │ RBAC     │           │
│  │           │     │ RBAC     │     │ filter   │           │
│  │           │◀────│ check    │◀────│          │           │
│  │           │     │          │     │          │           │
│  │ Results   │     │ Filter   │     │          │           │
│  │ (filtered)│     │ by role  │     │          │           │
│  └──────────┘     └──────────┘     └──────────┘           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Registration Endpoint

```python
from pydantic import BaseModel, EmailStr, Field

class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8)
    org_slug: str  # Organization to join

@router.post("/register")
def register(request: RegisterRequest):
    # Check if user already exists
    existing = db.query(User).filter(User.email == request.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    # Find organization
    org = db.query(Organization).filter(Organization.slug == request.org_slug).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Create user
    user = User(
        name=request.name,
        email=request.email,
        password_hash=hash_password(request.password),
        org_id=org.id,
        role="employee",  # Default role
    )
    db.add(user)
    db.commit()

    # Generate JWT
    token = create_access_token({
        "sub": str(user.id),
        "org_id": str(org.id),
        "role": user.role,
    })

    return {"access_token": token, "token_type": "bearer"}
```

---

## 7. Security Best Practices

### Always Use HTTPS

```
❌ HTTP: Passwords sent in plain text
✅ HTTPS: Passwords encrypted in transit
```

### Rate Limiting on Auth Endpoints

```python
from app.middleware.rate_limit import is_rate_limited

@router.post("/login")
def login(request: LoginRequest):
    # Rate limit: 5 attempts per 15 minutes per IP
    if is_rate_limited(f"login:{request.ip}", limit=5, window=900):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later."
        )
    # ... rest of login logic
```

### Token Expiry

```python
# Short-lived tokens (24 hours)
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

# Refresh token flow (for production)
REFRESH_TOKEN_EXPIRE_DAYS = 30
```

---

## Try It Yourself

### Exercise 1: Password Hashing
1. Hash 3 different passwords with bcrypt
2. Verify each password against its hash
3. Try verifying wrong passwords — what happens?

### Exercise 2: JWT Flow
1. Create a JWT token with user data
2. Decode it and extract user info
3. Try decoding with wrong secret — what happens?

### Exercise 3: RBAC Check
1. Create a function that checks document access
2. Test with different roles (admin, manager, employee, intern)
3. Test with different sensitivity levels

---

## Common Pitfalls

| Mistake | Why It's Bad | Fix |
|---------|-------------|-----|
| Storing passwords in plain text | Security catastrophe | Use bcrypt hashing |
| Not verifying JWT signature | Anyone can forge tokens | Always verify with `jwt.decode()` |
| No token expiry | Stolen tokens work forever | Set `exp` claim |
| Hardcoding secrets | Exposed in version control | Use environment variables |
| No rate limiting on login | Brute force attacks | Add rate limiter |
| Logging sensitive data | Security/compliance risk | Never log passwords/tokens |

---

*Continue to [10-integration.md](10-integration.md) →*
