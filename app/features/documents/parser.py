# Document Parser Service
# ------------------------
# Extracts text content from uploaded documents
#
# Responsibilities:
# - Parse PDF files (using pypdf)
# - Parse plain text files
# - Handle encoding issues gracefully
# - Extract metadata (page count, etc.)
#
# Key functions:
# - parse_document(file_path) -> str: Extract text from file
# - parse_pdf(file_path) -> str: PDF-specific parsing
# - parse_text(file_path) -> str: Plain text parsing
#
# Supported formats:
# - application/pdf (pypdf)
# - text/plain (direct read)
# - text/markdown (direct read)
#
# Error handling:
# - Corrupted files → raise ParseError
# - Empty documents → raise EmptyDocumentError
# - Unsupported format → raise UnsupportedFormatError



# Document Parser Service
# -----------------------
# Extracts raw text from stored files. Pure function of (file_path) -> text:
# no DB, no Qdrant, no network. That makes it trivially testable and lets the
# ingestion pipeline treat "get text" as a black box.
#
# Why pypdf and not unstructured/pymupdf: pypdf is already in requirements.txt,
# pure-Python (no system deps in Docker), and good enough for policy-style
# PDFs. Swap the implementation here later without touching the pipeline.

from pathlib import Path


class ParseError(Exception):
    """Raised when a file cannot be parsed."""


class UnsupportedFormatError(ParseError):
    """Raised for file types outside the allowlist."""


class EmptyDocumentError(ParseError):
    """Raised when a parsed document contains no extractable text."""


def parse_document(file_path: str | Path) -> str:
    """Extract text from a stored document. Raises a ParseError subclass on failure."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        text = _parse_pdf(path)
    elif suffix in {".txt", ".md"}:
        text = _parse_text(path)
    else:
        raise UnsupportedFormatError(f"Unsupported file type: '{suffix}'")

    if not text.strip():
        raise EmptyDocumentError("Document contains no extractable text")

    return text


def _parse_pdf(path: Path) -> str:
    # Imported lazily: pypdf (+ its deps) is only needed when a PDF is parsed.
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        # Join pages with a blank line so page boundaries don't glue sentences together.
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except ParseError:
        raise
    except Exception as exc:  # pypdf raises many unrelated exception types
        raise ParseError(f"Failed to parse PDF '{path.name}': {exc}") from exc


def _parse_text(path: Path) -> str:
    try:
        # errors="replace": never fail ingestion over one bad byte in a text file.
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ParseError(f"Failed to read text file '{path.name}': {exc}") from exc
