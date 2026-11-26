# Enterprise Knowledge Assistant — Learning Guide (0 to Hero)

> **For:** Intern (learning from scratch) + Tech Lead (reference & parallel work)
> **Goal:** Go from zero understanding to building the complete RAG system
> **Approach:** Each section has a "Why learn this?" and "What you'll learn" so you always know the point

---

## The Big Picture: What Are We Building?

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│   EMPLOYEE                                                         │
│   asks "Where is the leave policy?"                                │
│        │                                                           │
│        ▼                                                           │
│   ┌─────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    │
│   │ FastAPI  │───▶│ Qdrant   │───▶│ Reranker │───▶│ LLM      │    │
│   │ (API)    │    │ (Search) │    │ (Rank)   │    │ (Answer) │    │
│   └────┬─────┘    └──────────┘    └──────────┘    └──────────┘    │
│        │                                                           │
│   ┌────▼─────┐    ┌──────────┐    ┌──────────┐                   │
│   │PostgreSQL│    │ Redis    │    │ Celery   │                   │
│   │ (Data)   │    │ (Cache)  │    │ (Worker) │                   │
│   └──────────┘    └──────────┘    └──────────┘                   │
│                                                                     │
│   ┌──────────┐    ┌──────────┐                                    │
│   │ Docker   │    │ JWT/RBAC │                                    │
│   │ (Deploy) │    │ (Security│                                    │
│   └──────────┘    └──────────┘                                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Learning Roadmap

**Follow this order.** Each section builds on the previous ones.

```
Week 1: Foundation
│
├─ [01] Python Basics ──────────────── "I need to write Python code"
│        │
├─ [02] FastAPI ────────────────────── "I need to build HTTP APIs"
│        │
└─ [03] PostgreSQL + SQLAlchemy ────── "I need to store and query data"
         │
Week 2: AI/Search Layer
         │
├─ [04] Qdrant (Vector Database) ───── "I need to store and search embeddings"
│        │
├─ [05] Sentence-Transformers ──────── "I need to convert text to vectors"
│        │
└─ [06] Hybrid Search (BM25 + Vector) "I need to combine keyword + semantic search"
         │
Week 3: Infrastructure
         │
├─ [07] Celery + Redis ─────────────── "I need to run background tasks"
│        │
├─ [08] Docker ─────────────────────── "I need to package and deploy"
│        │
└─ [09] Authentication + RBAC ──────── "I need to secure the system"
         │
Week 4: Integration
         │
└─ [10] Putting It All Together ────── "I need to wire everything"
```

---

## Quick Reference: What Each Stack Does

| # | Stack | One-Line Purpose | Files |
|---|-------|-----------------|-------|
| 01 | **Python** | Language we write everything in | [→](01-python.md) |
| 02 | **FastAPI** | Builds the HTTP API endpoints | [→](02-fastapi.md) |
| 03 | **PostgreSQL + SQLAlchemy** | Stores users, documents, metadata | [→](03-postgresql-sqlalchemy.md) |
| 04 | **Qdrant** | Stores document embeddings, does vector search | [→](04-qdrant.md) |
| 05 | **Sentence-Transformers** | Converts text into numerical vectors | [→](05-sentence-transformers.md) |
| 06 | **Hybrid Search** | Combines keyword + semantic search | [→](06-hybrid-search.md) |
| 07 | **Celery + Redis** | Runs heavy tasks in background | [→](07-celery-redis.md) |
| 08 | **Docker** | Packages everything for deployment | [→](08-docker.md) |
| 09 | **Auth + RBAC** | Secures who can see what | [→](09-auth-rbac.md) |
| 10 | **Integration** | Wires everything together | [→](10-integration.md) |

---

## Prerequisites Checklist

Before starting, make sure you have:

- [ ] A computer with Python 3.11+ installed
- [ ] Docker Desktop installed
- [ ] A code editor (VS Code recommended)
- [ ] Basic terminal/command line knowledge
- [ ] Git installed

---

## How to Use This Guide

### For the Intern
1. Start at [01-python.md](01-python.md) and work through each section in order
2. **Run every code example** — don't just read, type it out
3. After each section, try the "Try It Yourself" exercises
4. Use the project's actual code as reference once you've learned the basics

### For the Tech Lead
1. Skim each section to understand what the intern will learn
2. Use the diagrams for architecture discussions
3. Reference the "Common Pitfalls" boxes for code review guidance
4. The [10-integration.md](10-integration.md) section is your system design reference

---

## Learning Principles

> **"I hear and I forget. I see and I remember. I do and I understand."**

1. **Learn by building** — Every concept is shown in project context
2. **Understand the WHY** — Each section starts with the reason
3. **Visual first** — Diagrams before code, always
4. **Progressive complexity** — Simple examples → real project code
5. **Mistakes are teachers** — Common pitfalls are highlighted

---

*Continue to [01-python.md](01-python.md) →*
