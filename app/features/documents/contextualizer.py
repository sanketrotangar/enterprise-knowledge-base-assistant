# Contextualizer — Contextual Chunk Enrichment (Contextual RAG)
# -------------------------------------------------------------
# Naive chunks lose context ("This applies to them" — who?). Per the
# contextual-retrieval approach (rag-architectures.md §3), we prepend a short
# blurb to every chunk that situates it within the document, and embed
# context + chunk together. All three texts are stored (Postgres columns
# context_header / contextualized_content + Qdrant payload keys) so search can
# use either representation later.
#
# Two strategies, chosen automatically:
#   1. LLM (Groq)    — used when GROQ_API_KEY is set; best quality. Groq speaks
#      the OpenAI API dialect, so the `openai` package works with a base_url.
#   2. Heuristic     — deterministic fallback (title + neighbor hints); used
#      when no API key is set OR the LLM call fails. This keeps ingestion
#      working (and testable) fully offline, and makes LLM outages non-fatal.
#
# Why a separate file: chunker.py must stay pure/deterministic; this module
# has network I/O, a prompt, and a fallback path — different failure modes,
# different tests.

from app.core.config import settings

# Only send the head of the document to the LLM: enough to situate typical
# policy docs, keeps per-chunk cost bounded for large files.
_MAX_DOC_CHARS_FOR_LLM = 8000
_MAX_CONTEXT_TOKENS = 120


def contextualize_chunks(title: str, full_text: str, chunks: list[str]) -> list[str]:
    """Return one context blurb per chunk (same order/length as `chunks`).

    Thin orchestrator over the spec's generate_chunk_context() (Step 2.1):
    batched here so a document is contextualized in one call, with a
    deterministic fallback when no API key is set or the LLM fails.
    """
    if not chunks:
        return []
    if settings.GROQ_API_KEY:
        try:
            return _llm_contexts(title, full_text, chunks)
        except Exception:
            pass  # ingestion must not die on an LLM outage — fall back below
    return _heuristic_contexts(title, chunks)


# --------------------------------------------------------------------------- #
# Strategy 1: LLM-generated context (rag-architectures.md Step 2.1)
# --------------------------------------------------------------------------- #

_LLM_SYSTEM_PROMPT = (
    "You write concise situating context for document chunks in a search index. "
    "Given a document and one chunk from it, reply with 2-3 sentences that place "
    "the chunk in context: what document it is from, what section/topic it covers, "
    "and what it applies to. Reply with the context ONLY — no preamble, no quotes."
)


def _llm_contexts(title: str, full_text: str, chunks: list[str]) -> list[str]:
    from openai import OpenAI  # lazy import: only when a key is configured

    # Groq hosts the same chat-completions API shape; only the endpoint moves.
    client = OpenAI(
        api_key=settings.GROQ_API_KEY, base_url=settings.GROQ_BASE_URL
    )
    doc_excerpt = full_text[:_MAX_DOC_CHARS_FOR_LLM]

    contexts: list[str] = []
    for chunk in chunks:
        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            temperature=0,
            max_tokens=_MAX_CONTEXT_TOKENS,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"<document>\n<title>{title}</title>\n{doc_excerpt}\n</document>\n"
                        f"Here is the chunk:\n<chunk>\n{chunk}\n</chunk>"
                    ),
                },
            ],
        )
        contexts.append(response.choices[0].message.content.strip())
    return contexts


# --------------------------------------------------------------------------- #
# Strategy 2: deterministic heuristic fallback
# --------------------------------------------------------------------------- #

_NEIGHBOR_WORDS = 12


def _heuristic_contexts(title: str, chunks: list[str]) -> list[str]:
    contexts: list[str] = []
    for i, chunk in enumerate(chunks):
        parts = [f"[Document: {title}]"]
        if i > 0:
            tail = " ".join(chunks[i - 1].split()[-_NEIGHBOR_WORDS:])
            parts.append(f"Continues from: ...{tail}")
        if i < len(chunks) - 1:
            head = " ".join(chunks[i + 1].split()[:_NEIGHBOR_WORDS])
            parts.append(f"Leads into: {head}...")
        contexts.append(" ".join(parts))
    return contexts
