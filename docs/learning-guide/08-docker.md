# 08 — Docker: Packaging & Deployment

> **Why learn this?** Our system has 5+ services (FastAPI, PostgreSQL, Qdrant, Redis, Celery). Docker lets us package each service into a container and run them all together with one command. No "works on my machine" problems.
>
> **Scope of learning:** Dockerfile basics, Docker Compose, multi-service setup. Skip Docker Swarm, Kubernetes, advanced networking.

---

## The Problem Docker Solves

```
❌ WITHOUT Docker:
──────────────────

Developer A: "Install Python 3.11, PostgreSQL 15, Redis 7, Qdrant..."
Developer B: "I have Python 3.10, PostgreSQL 12..."
Developer C: "I'm on Windows, nothing works..."

Result: 2 days setting up environment 😢


✅ WITH Docker:
────────────────

Developer A: "docker-compose up"
Developer B: "docker-compose up"
Developer C: "docker-compose up"

Result: Everything works in 2 minutes 🚀
```

---

## 1. Docker Fundamentals

### What Is a Container?

```
┌─────────────────────────────────────────┐
│              CONTAINER                   │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │  Your App Code                    │  │
│  ├───────────────────────────────────┤  │
│  │  Dependencies (pip, npm, etc.)    │  │
│  ├───────────────────────────────────┤  │
│  │  Runtime (Python, Node, etc.)     │  │
│  ├───────────────────────────────────┤  │
│  │  OS (Linux)                       │  │
│  └───────────────────────────────────┘  │
│                                         │
│  Isolated from other containers         │
│  Can be started/stopped in seconds     │
│  Identical on any machine              │
└─────────────────────────────────────────┘
```

### Docker vs Virtual Machine

```
Virtual Machine:                    Docker Container:
┌─────────────────┐                ┌─────────────────┐
│     App A       │                │     App A       │
├─────────────────┤                ├─────────────────┤
│   Libraries     │                │   Libraries     │
├─────────────────┤                └─────────────────┘
│     OS          │                ┌─────────────────┐
│  (full copy)    │                │     App B       │
├─────────────────┤                ├─────────────────┤
│  Hypervisor     │                │   Libraries     │
├─────────────────┤                └─────────────────┘
│  Host OS        │                ┌─────────────────┐
└─────────────────┘                │     App C       │
                                   ├─────────────────┤
Heavy (GBs)                        │   Libraries     │
Slow startup (minutes)             └─────────────────┘
                                   ─────────────────
                                   Docker Engine
                                   ─────────────────
                                   Host OS

                                   Lightweight (MBs)
                                   Fast startup (seconds)
```

---

## 2. Dockerfile — Building an Image

### What Is a Dockerfile?

A Dockerfile is a recipe for building a Docker image:

```dockerfile
# Dockerfile

# Step 1: Start with Python base image
FROM python:3.11-slim

# Step 2: Set working directory
WORKDIR /app

# Step 3: Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Step 4: Copy requirements file
COPY requirements.txt .

# Step 5: Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Step 6: Copy application code
COPY . .

# Step 7: Expose port
EXPOSE 8000

# Step 8: Run the app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Building & Running

```bash
# Build the image
docker build -t enterprise-knowledge-assistant .

# Run the container
docker run -p 8000:8000 enterprise-knowledge-assistant

# Access at http://localhost:8000
```

---

## 3. Docker Compose — Multi-Service Setup

### What Is Docker Compose?

Docker Compose lets you define and run multiple containers together:

```yaml
# docker-compose.yml

version: "3.8"

services:
  # Our FastAPI application
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/ekb
      - REDIS_URL=redis://redis:6379/0
      - QDRANT_URL=http://qdrant:6333
    depends_on:
      - db
      - redis
      - qdrant

  # PostgreSQL database
  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_DB=ekb
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  # Redis (cache + message broker)
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  # Qdrant (vector database)
  qdrant:
    image: qdrant/qdrant
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage

  # Celery worker (background tasks)
  celery_worker:
    build: .
    command: celery -A app.workers.celery_app worker --loglevel=info
    environment:
      - DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/ekb
      - REDIS_URL=redis://redis:6379/0
      - QDRANT_URL=http://qdrant:6333
    depends_on:
      - db
      - redis
      - qdrant

volumes:
  postgres_data:
  qdrant_data:
```

### Commands

```bash
# Start all services
docker-compose up

# Start in background (detached)
docker-compose up -d

# Stop all services
docker-compose down

# View logs
docker-compose logs -f api

# Rebuild after code changes
docker-compose up --build

# View running containers
docker-compose ps

# Execute command in running container
docker-compose exec api bash
docker-compose exec db psql -U postgres
```

---

## 4. Our Complete Docker Setup

### Project Structure

```
enterprise-knowledge-assistant/
├── Dockerfile                 # API + Worker image
├── docker-compose.yml         # All services
├── requirements.txt           # Python dependencies
├── .env                       # Environment variables (NOT in git!)
├── .env.example               # Template (in git)
├── .dockerignore              # Files to exclude from build
├── app/
│   ├── main.py
│   └── ...
└── uploads/                   # Document storage
```

### Dockerfile (Multi-Stage)

```dockerfile
# Dockerfile

# Build stage
FROM python:3.11-slim AS builder

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p /app/uploads

# Expose port
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### .dockerignore

```
# .dockerignore
__pycache__
*.pyc
.env
.git
.vscode
uploads/
*.md
.dockerignore
Dockerfile
docker-compose.yml
```

### .env.example

```bash
# .env.example (commit this to git)
DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/ekb
REDIS_URL=redis://redis:6379/0
QDRANT_URL=http://qdrant:6333
SECRET_KEY=change-me-in-production
OPENAI_API_KEY=your-api-key-here
```

---

## 5. Data Persistence

### Volumes

```
Without volumes:              With volumes:
┌──────────────┐             ┌──────────────┐
│  Container   │             │  Container   │
│              │             │              │
│  /var/lib/   │             │  /var/lib/   │
│  postgres/   │             │  postgres/   │
│              │             │      │       │
│  [DATA]      │             │      ▼       │
└──────────────┘             │  [VOLUME]    │
      │                      │  (persists)  │
      ▼                      └──────────────┘
  Container deleted                │
  = Data gone!                     ▼
                             Volume stays!
                             Container deleted
                             = Data safe!
```

### Our Volumes

```yaml
volumes:
  postgres_data:    # PostgreSQL data
  qdrant_data:      # Qdrant vectors
```

---

## 6. Networking

### How Containers Communicate

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Network                            │
│                                                             │
│  ┌─────────┐     ┌─────────┐     ┌─────────┐              │
│  │   api   │────▶│   db    │     │  redis  │              │
│  │ :8000   │     │ :5432   │     │ :6379   │              │
│  └─────────┘     └─────────┘     └─────────┘              │
│       │                                 │                   │
│       │            ┌─────────┐          │                   │
│       └───────────▶│ qdrant  │◀─────────┘                   │
│                    │ :6333   │                              │
│                    └─────────┘                              │
│                                                             │
│  Containers reference each other by SERVICE NAME            │
│  "db" not "localhost"                                      │
│  "redis" not "localhost"                                   │
└─────────────────────────────────────────────────────────────┘
```

### Environment Variables

```yaml
# In docker-compose.yml
services:
  api:
    environment:
      - DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/ekb
                                    ^^                                    ^^
                                    │                                     │
                              Service name                          Database name
                              (from docker-compose)
```

---

## 7. Common Docker Commands

### Essential Commands

```bash
# Build
docker build -t myapp .                    # Build image
docker-compose build                       # Build all services

# Run
docker-compose up                          # Start all
docker-compose up -d                       # Start in background
docker-compose up --build                  # Rebuild and start
docker-compose up api                      # Start only API

# Stop
docker-compose down                        # Stop all
docker-compose down -v                     # Stop and delete volumes

# Logs
docker-compose logs                        # All logs
docker-compose logs -f api                 # Follow API logs
docker-compose logs --tail=100 api         # Last 100 lines

# Execute
docker-compose exec api bash               # Shell into API container
docker-compose exec db psql -U postgres    # Connect to PostgreSQL

# Clean up
docker system prune                        # Remove unused containers/images
docker volume prune                        # Remove unused volumes
```

---

## 8. Development vs Production

### Development (with hot reload)

```yaml
# docker-compose.dev.yml
services:
  api:
    build: .
    volumes:
      - .:/app                    # Mount code for hot reload
    command: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    environment:
      - APP_ENV=development
      - DEBUG=true
```

### Production

```yaml
# docker-compose.prod.yml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - APP_ENV=production
      - DEBUG=false
    deploy:
      replicas: 3                 # 3 instances
      resources:
        limits:
          cpus: "2"
          memory: 4G
    restart: unless-stopped
```

---

## Visual Summary

```
┌─────────────────────────────────────────────────────────────┐
│                 DOCKER COMPOSE SETUP                        │
│                                                             │
│  docker-compose up                                         │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │     api      │  │ celery      │  │   flower    │        │
│  │  (FastAPI)   │  │  (worker)   │  │ (monitor)   │        │
│  │   :8000      │  │             │  │   :5555     │        │
│  └──────┬───────┘  └──────┬──────┘  └─────────────┘        │
│         │                 │                                 │
│         └────────┬────────┘                                 │
│                  │                                          │
│  ┌───────────────┼───────────────┐                         │
│  │               │               │                         │
│  ▼               ▼               ▼                         │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐                   │
│  │   db    │  │  redis  │  │ qdrant  │                   │
│  │ (Postgres)│  │ (Cache) │  │ (Vector)│                   │
│  │  :5432  │  │  :6379  │  │  :6333  │                   │
│  └─────────┘  └─────────┘  └─────────┘                   │
│                                                             │
│  All managed by Docker Compose                              │
│  One command to start/stop everything                       │
│  Identical on any machine                                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Try It Yourself

### Exercise 1: Basic Dockerfile
1. Create a simple Python app (e.g., "Hello, World!")
2. Write a Dockerfile for it
3. Build and run the container

### Exercise 2: Docker Compose
1. Create a docker-compose.yml with:
   - Your FastAPI app
   - PostgreSQL
   - Redis
2. Start all services with `docker-compose up`
3. Verify all services are running

### Exercise 3: Multi-Container
1. Add Celery worker to your docker-compose
2. Verify the worker connects to Redis
3. Send a task and see it processed

---

## Common Pitfalls

| Mistake | Why It's Bad | Fix |
|---------|-------------|-----|
| Using `localhost` in containers | Can't reach other services | Use service names (db, redis) |
| Not using volumes | Data lost on restart | Define volumes for persistent data |
| Hardcoding secrets in Dockerfile | Security risk | Use .env files or secrets |
| Not using .dockerignore | Large images, slow builds | Exclude unnecessary files |
| Running as root | Security risk | Use `USER` directive in Dockerfile |
| No health checks | Can't detect unhealthy services | Add `healthcheck` in docker-compose |

---

*Continue to [09-auth-rbac.md](09-auth-rbac.md) →*
