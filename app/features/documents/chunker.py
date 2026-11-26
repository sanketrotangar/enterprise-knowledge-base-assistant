# Text Chunker Service
# ---------------------
# Splits extracted text into manageable chunks for embedding
#
# Responsibilities:
# - Split text into fixed-size chunks (512 tokens)
# - Add overlap between chunks (50 tokens) for context continuity
# - Preserve sentence boundaries when possible
# - Track chunk index for source citation
#
# Key functions:
# - chunk_text(text, chunk_size=512, overlap=50) -> list[str]
#   - Returns list of text chunks
#   - Each chunk is approximately chunk_size tokens
#   - Adjacent chunks overlap by overlap tokens
#
# Chunking strategy:
# - Fixed-size with overlap (deterministic, no LLM dependency)
# - Word-level splitting (not character-level)
# - Preserves natural break points when possible
#
# Why chunking?
# - Embedding models have token limits (512 for MiniLM)
# - Smaller chunks = more precise search results
# - Overlap ensures no information lost at boundaries



# Text Chunker Service
# ---------------------
# Fixed-size, word-based chunking with overlap and sentence-boundary snapping.
# Deterministic and dependency-free (this module intentionally never touches
# the network or the LLM — see contextualizer.py for why that's separate).
#
# Why words, not exact tokens: MiniLM's limit is 512 tokens, and English text
# averages ~1.3 tokens/word, so 320 words ≈ 420 tokens sits safely under the
# cap without shipping a tokenizer dependency just for counting.
# Why overlap: a fact split across a boundary lives fully in at least one chunk.

CHUNK_SIZE_WORDS = 320   # ≈ 420 tokens, safely under MiniLM's 512-token limit
CHUNK_OVERLAP_WORDS = 40
_SENTENCE_CUT_ZONE = 0.8  # only shorten a window if a sentence ends in its last 20%
_SENTENCE_ENDINGS = (".", "!", "?")
_AVERAGE_TOKENS_PER_WORD = 1.3


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE_WORDS,
    overlap: int = CHUNK_OVERLAP_WORDS,
) -> list[str]:
    """Split text into overlapping word-window chunks.

    Each chunk is at most `chunk_size` words; when a sentence boundary appears
    near the end of a window, the window is shortened to end there. Adjacent
    chunks overlap by `overlap` words.
    """
    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        window = words[start:end]

        # Prefer cutting at a sentence boundary (only shortens the window).
        if end < len(words):
            cut = _last_sentence_end(window)
            if cut is not None:
                end = start + cut
                window = words[start:end]

        chunks.append(" ".join(window).strip())
        if end >= len(words):
            break
        start = max(end - overlap, start + 1)  # +1 guarantees forward progress

    return [c for c in chunks if c]


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token) stored on each chunk row."""
    return max(1, len(text) // 4)


def _last_sentence_end(window: list[str]) -> int | None:
    """Index just past the last sentence-ending word in the tail of `window`."""
    zone = int(len(window) * _SENTENCE_CUT_ZONE)
    for i in range(len(window) - 1, zone - 1, -1):
        if window[i].endswith(_SENTENCE_ENDINGS):
            return i + 1
    return None
