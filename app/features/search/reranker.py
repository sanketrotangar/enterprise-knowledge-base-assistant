# Cross-Encoder Reranker
# ----------------------
# Stage-2 precision: the hybrid retrieval (Stage 1) is fast but approximate;
# a cross-encoder reads (query, chunk) PAIRS and scores true relevance, which
# reordering top-20 -> top-5 dramatically improves (learning-guide/06 §6).
#
# Separated from service.py because it owns a SECOND model with its own lazy
# lifecycle and its own failure mode — same reasoning that split
# contextualizer.py from chunker.py in Part 1.
#
# Fallback: any reranker failure (model missing, OOM, scoring error) degrades
# to the Stage-1 hybrid order instead of failing the request. Search returns
# *something* useful while the root cause is investigated.

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Model card: cross-encoder/ms-marco-MiniLM-L-12-v2 (same MiniLM family as
# the embedder, 12-layer, trained on MS MARCO passage ranking).
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-12-v2"

# Where the hybrid-order fallback score should sit. Real cross-encoder scores
# for relevant pairs are typically > 0; a small negative keeps fallback
# candidates ordered by their RRF score but below genuinely reranked ones.
_FALLBACK_SCORE = -1.0

_model: Any = None


def get_model():
    """Get the reranker model singleton, loading it if not yet loaded."""
    global _model
    if _model is None:
        from sentence_transformers import CrossEncoder

        logger.info("Loading reranker model '%s'...", RERANKER_MODEL_NAME)
        _model = CrossEncoder(RERANKER_MODEL_NAME)
        logger.info("Reranker model '%s' loaded successfully.", RERANKER_MODEL_NAME)
    return _model


def warmup() -> None:
    """Explicit warmup called at server startup to preload weights and warm up compute graph."""
    try:
        model = get_model()
        model.predict([("warmup query", "warmup document")], show_progress_bar=False)
        logger.info("Reranker model '%s' warmup complete.", RERANKER_MODEL_NAME)
    except Exception as exc:
        logger.warning("Reranker warmup failed (search will degrade to hybrid order): %s", exc)


def rerank_sync(
    query: str, documents: list[str], top_k: int | None = None
) -> list[tuple[int, float]]:
    """Score (query, doc) pairs; return [(original_index, score)] best-first.

    Blocking; runs on a worker thread via rerank(). `top_k=None` keeps all.
    On any model failure, returns the ORIGINAL order with a sentinel score so
    the pipeline degrades to hybrid ranking instead of erroring out.
    """
    if not documents:
        return []
    if top_k is None:
        top_k = len(documents)

    try:
        model = get_model()
        pairs = [(query, doc) for doc in documents]
        scores = model.predict(pairs, show_progress_bar=False)
        ranked = sorted(
            ((i, float(s)) for i, s in enumerate(scores)),
            key=lambda x: x[1],
            reverse=True,
        )
        return ranked[:top_k]
    except Exception:
        # Degrade to Stage-1 order (hybrid RRF) rather than failing the request.
        return [(i, _FALLBACK_SCORE) for i in range(min(top_k, len(documents)))]


async def rerank(
    query: str, documents: list[str], top_k: int | None = None
) -> list[tuple[int, float]]:
    """Async wrapper — CPU-bound batch scoring must not block the event loop."""
    if not documents:
        return []
    return await asyncio.to_thread(rerank_sync, query, documents, top_k)
