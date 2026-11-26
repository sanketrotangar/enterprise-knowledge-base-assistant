"""Shared helpers for seed_eval.py and run_eval.py. Not part of the app."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO_ROOT / "eval" / "corpus"
FILLER_DIR = REPO_ROOT / "eval" / "corpus_filler"
GOLDEN_PATH = REPO_ROOT / "eval" / "golden.yaml"
ATTACKS_PATH = REPO_ROOT / "eval" / "attacks.yaml"
MANIFEST_PATH = REPO_ROOT / "eval" / "seed_manifest.json"
BASELINE_PATH = REPO_ROOT / "eval" / "baseline_qdrant_minilm.json"

FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)

CLEARANCE_TO_SENSITIVITY = {
    0: "public",
    1: "internal",
    2: "confidential",
    3: "restricted",
}

# Document.sensitivity maps to DB clearance 1-4. Seed SET LOCAL must be >= that.
SEED_CLEARANCE = 4

LEAK_CLASSES = ("cross_tenant", "wrong_department", "above_clearance")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    match = FRONTMATTER.match(text)
    if not match:
        raise ValueError("document is missing YAML frontmatter")
    meta = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).lstrip()
    if not body.strip():
        raise ValueError("document body is empty")
    return meta, body


def _load_dir(directory: Path, *, require_canary: bool, min_words: int, max_words: int) -> list[dict]:
    docs: list[dict] = []
    paths = sorted(directory.glob("*.md"))
    if not paths:
        raise FileNotFoundError(f"no markdown files in {directory}")
    seen: set[str] = set()
    for path in paths:
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        doc_id = str(meta.get("id") or path.stem)
        if doc_id in seen:
            raise ValueError(f"duplicate corpus id {doc_id!r}")
        seen.add(doc_id)
        words = len(body.split())
        if not (min_words <= words <= max_words):
            raise ValueError(f"{path.name}: body is {words} words (need {min_words}-{max_words})")
        clearance = int(meta["clearance"])
        if clearance not in CLEARANCE_TO_SENSITIVITY:
            raise ValueError(f"{path.name}: clearance must be 0-3")
        canary = str(meta["canary"]).strip() if meta.get("canary") else ""
        if require_canary:
            if not canary:
                raise ValueError(f"{path.name}: planted doc needs a canary")
            if canary not in body:
                raise ValueError(f"{path.name}: canary is not in the body")
        docs.append(
            {
                "id": doc_id,
                "path": path,
                "title": str(meta.get("title") or doc_id),
                "tenant": str(meta["tenant"]),
                "department": str(meta["department"]),
                "clearance": clearance,
                "doc_family": str(meta.get("doc_family") or ""),
                "version": int(meta.get("version") or 1),
                "canary": canary,
                "filler": bool(meta.get("filler")),
                "body": body,
                "word_count": words,
            }
        )
    return docs


def load_corpus() -> list[dict]:
    """Planted eval docs (with canaries)."""
    docs = _load_dir(CORPUS_DIR, require_canary=True, min_words=400, max_words=900)
    canaries = [d["canary"] for d in docs]
    if len(set(canaries)) != len(canaries):
        raise ValueError("planted canaries are not unique")
    return docs


def load_filler() -> list[dict]:
    return _load_dir(FILLER_DIR, require_canary=False, min_words=400, max_words=700)


def load_seed_docs() -> list[dict]:
    planted = load_corpus()
    filler = load_filler()
    ids = [d["id"] for d in planted + filler]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate ids across corpus and filler")
    planted_canaries = [d["canary"] for d in planted]
    for doc in filler:
        for canary in planted_canaries:
            if canary and canary in doc["body"]:
                raise ValueError(f"filler {doc['id']} contains planted canary")
    return planted + filler


def load_yaml_list(path: Path) -> list[dict]:
    rows = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(rows, list):
        raise ValueError(f"{path} must be a list")
    return rows


def load_manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        return {"docs": {}}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def write_manifest(payload: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _source_matches_expected(source: dict, expected_doc: str, expected: dict) -> bool:
    expected_id = str(expected.get("document_id") or "")
    expected_title = str(expected.get("title") or "").lower()
    if expected_id and str(source.get("document_id") or "") == expected_id:
        return True
    title = str(source.get("document_title") or "").lower()
    if expected_title and expected_title == title:
        return True
    slug = expected_doc.lower()
    if slug in title.replace(" ", "-") or slug in title:
        return True
    return False


def expected_rank(
    sources: list[dict], expected_doc: str, manifest_docs: dict, k: int = 5
) -> int | None:
    expected = manifest_docs.get(expected_doc) or {}
    for index, source in enumerate(sources[:k], start=1):
        if _source_matches_expected(source, expected_doc, expected):
            return index
    return None


def hit_at_k(sources: list[dict], expected_doc: str, manifest_docs: dict, k: int = 5) -> bool:
    return expected_rank(sources, expected_doc, manifest_docs, k=k) is not None


def canary_leaked(canary: str, *, answer: str, sources: list[dict]) -> bool:
    """Exact substring only. No fuzzy / n-gram / title overlap."""
    if not canary:
        raise ValueError("forbidden doc has no canary")
    if canary in (answer or ""):
        return True
    for source in sources:
        if canary in str(source.get("content") or ""):
            return True
    return False


def classify_leak(*, user_tenant: str, user_department: str, user_clearance: int, doc: dict) -> str:
    """tenant > department > clearance. First failing layer wins."""
    if user_tenant != doc["tenant"]:
        return "cross_tenant"
    if doc["department"] != "general" and user_department != doc["department"]:
        return "wrong_department"
    if user_clearance < int(doc["clearance"]):
        return "above_clearance"
    return "unexpected"


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (p / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    weight = rank - lo
    return float(ordered[lo] * (1.0 - weight) + ordered[hi] * weight)
