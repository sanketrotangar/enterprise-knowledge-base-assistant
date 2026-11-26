# LLM Answer Generation
# ---------------------
# Final pipeline stage: synthesize a grounded answer from the reranked chunks
# with numbered citations [1]..[n] that map to the `sources` array the UI
# renders. OpenAI-compatible API via the already-declared `openai` package.
#
# Two graceful degradations (search must answer with CHUNKS even without an
# LLM — that is the retrieval system's core promise):
#   - no GROQ_API_KEY -> extractive fallback: top chunk + citation pointers
#   - LLM error/timeout -> same extractive fallback
# Both keep the HTTP contract intact; the UI renders whatever `answer` says.

from app.core.config import settings

_ANSWER_SYSTEM_PROMPT = (
    "You are a knowledge assistant for enterprise documents. Answer the user's "
    "question using ONLY the provided context chunks. Cite sources inline in "
    "square-bracket [number] format matching the given chunk numbers. If the "
    "context does not contain the answer, say you could not find it in the "
    "knowledge base. Be concise (max ~150 words)."
)

_MAX_CONTEXT_CHARS = 6000  # ~1500 tokens of context, bounded for speed/cost
_MAX_ANSWER_TOKENS = 1500  # accommodates reasoning models + full answer without cutoff
_TIMEOUT_SECONDS = 30.0


def build_prompt(query: str, contexts: list[str]) -> list[dict]:
    """Chat messages with numbered context chunks (1-indexed to match the
    [n] citations the model is asked to emit and the UI's source list)."""
    per_chunk = max(_MAX_CONTEXT_CHARS // max(len(contexts), 1), 200)
    blocks = "\n\n".join(
        f"[{i + 1}] {context[:per_chunk]}" for i, context in enumerate(contexts)
    )
    return [
        {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Context:\n{blocks}\n\nQuestion: {query}\n\nAnswer:",
        },
    ]


def generate_answer(query: str, contexts: list[str]) -> str:
    """Generate a cited answer. Blocking (runs via to_thread in service).

    Falls back to an extractive answer when no API key is configured or the
    call fails — retrieval itself remains useful without the LLM.
    """
    if not contexts:
        return "No relevant information was found in the knowledge base for this query."

    if not settings.GROQ_API_KEY:
        return _extractive_answer(query, contexts)

    try:
        from openai import OpenAI  # lazy: only on the answer path

        # Groq speaks the OpenAI chat-completions dialect; only the endpoint
        # (base_url) and key change — same client, same response shape.
        client = OpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url=settings.GROQ_BASE_URL,
            timeout=_TIMEOUT_SECONDS,
        )
        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            temperature=0.3,
            max_tokens=_MAX_ANSWER_TOKENS,
            messages=build_prompt(query, contexts),
        )
        content = (response.choices[0].message.content or "").strip()
        return content or _extractive_answer(query, contexts)
    except Exception:
        # LLM outage must not fail a search that already has good chunks.
        return _extractive_answer(query, contexts)


def _extractive_answer(query: str, contexts: list[str]) -> str:
    """No-LLM fallback: point the user at the best-matching chunk(s)."""
    top = contexts[0].replace("\n", " ").strip()
    if len(top) > 400:
        top = top[:400].rstrip() + "…"
    more = (
        f" {len(contexts) - 1} more related chunk(s) available below."
        if len(contexts) > 1
        else ""
    )
    return (
        f"LLM answer generation is not configured, showing the most relevant "
        f"chunk for \"{query}\":\n\n{top}{more}"
    )
