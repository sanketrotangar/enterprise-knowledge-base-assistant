# App startup
uvicorn app.main:app --reload

# Ingest + role-sync worker (separate process; same .env as the API)
python -m app.worker
# one-shot drain for verification:
python -m app.worker --once
