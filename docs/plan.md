# Real-world problem
In many companies, new employees repeatedly ask:
“Where is the leave policy?”
“How do I configure VPN?”
“What is the reimbursement process?”
“Where is the API documentation?”

Information exists in PDFs, Google Docs, and Notion, but is hard to find.

# What you build

Upload PDFs/docs
Chunk + embed
Hybrid search (BM25 + vector)
Reranking
Role-based access (HR docs vs Engineering docs vs Hierarchy like manager vs intern vs junior developer)
Source citations
Feedback system (“Was this answer useful?”)

# Tech
Backend: FastAPI + PostgreSQL 
AI: Qdrant, sentence-transformers, cross-encoder reranker 
Infra: Docker, Redis, background workers