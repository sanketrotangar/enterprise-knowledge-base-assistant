# Embedding Service
# ------------------
# Converts text chunks into vector embeddings
#
# Responsibilities:
# - Load and manage sentence-transformers model
# - Encode text chunks into 384-dimensional vectors (by the model we are currently using)
# - Support batch processing for efficiency
# - Run CPU-bound work in thread pool (async compatible)
#
# Key functions:
# - embed(texts) -> list[list[float]]: Async batch embedding
# - embed_single(text) -> list[float]: Async single embedding
# - embed_sync(texts) -> list[list[float]]: Sync batch embedding
#
# Model:
# - all-MiniLM-L6-v2 (384 dimensions, 80MB)
# - Lazy-loaded on first use
# - CPU-optimized
#
# Performance:
# - Batch encoding for multiple chunks
# - asyncio.to_thread() for async compatibility
# - Model loaded once, reused across requests



# Embedding Service
# -----------------
# Single home for the embedding model so ingestion (chunk indexing) and search
# (query embedding) can never drift apart on model name or dimension.
#
# Lazy loading on purpose: importing sentence-transformers pulls in torch
# (~seconds + RAM). Uploads with process_now=False never pay that cost, and
# the model is loaded exactly once per process.

import asyncio
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_model: Any = None


def get_model():
    """Get the embedding model singleton, loading it if not yet loaded."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model '%s'...", settings.EMBEDDING_MODEL)
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
        logger.info("Embedding model '%s' loaded successfully.", settings.EMBEDDING_MODEL)
    return _model


def warmup() -> None:
    """Explicit warmup called at server startup to preload weights and warm up PyTorch."""
    model = get_model()
    # Run a quick dummy inference so PyTorch internals/CUDA/threadpool are initialized
    model.encode(["warmup query"], show_progress_bar=False)
    logger.info("Embedding model '%s' warmup complete.", settings.EMBEDDING_MODEL)


def embed_sync(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Batch-encode texts (blocking). Used directly by workers/threads."""
    if not texts:
        return []
    vectors = get_model().encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return [v.tolist() for v in vectors]


async def embed(texts: list[str]) -> list[list[float]]:
    """Async wrapper: runs CPU-bound encoding in a thread so the event loop
    stays responsive. This is the function the pipeline calls."""
    return await asyncio.to_thread(embed_sync, texts)


async def embed_single(text: str) -> list[float]:
    return (await embed([text]))[0]
