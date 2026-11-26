# Run golden + attack eval against the live search API as eval/users.yaml identities.
# TEMPORARY: sends X-Eval-User (also accepts ?eval_user=). Remove when JWT lands.
#
# Usage (API must already be running as app_user):
#   .venv/bin/python scripts/run_eval.py
#   .venv/bin/python scripts/run_eval.py --base-url http://127.0.0.1:8001 --out eval/last_run.json
#
# Frozen baseline (do not overwrite later):
#   .venv/bin/python scripts/run_eval.py --out eval/baseline_qdrant_minilm.json

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.eval_identity import EVAL_USER_HEADER, get_eval_user
from scripts.eval_support import (
    ATTACKS_PATH,
    BASELINE_PATH,
    GOLDEN_PATH,
    canary_leaked,
    classify_leak,
    expected_rank,
    load_corpus,
    load_manifest,
    load_yaml_list,
    percentile,
)

DEFAULT_BASE_URL = "http://127.0.0.1:8001"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "eval" / "last_run.json"


def _post_search(
    base_url: str, user_id: str, query: str, timeout: float, backend: str | None
) -> dict:
    get_eval_user(user_id)  # fail fast on typos before the HTTP call
    payload = json.dumps({"query": query, "top_k": 5}).encode("utf-8")
    url = f"{base_url.rstrip('/')}/api/v1/search"
    if backend:
        url = f"{url}?search_backend={backend}"
    request = urllib.request.Request(
        url=url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            EVAL_USER_HEADER: user_id,  # TEMPORARY — remove when JWT lands
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"search HTTP {exc.code} as {user_id}: {err}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"search failed as {user_id}: {exc}. Is the API up at {base_url}?"
        ) from exc
    if status != 200:
        raise RuntimeError(f"search HTTP {status} as {user_id}: {body}")
    return json.loads(body)


def _run(base_url: str, timeout: float, out_path: Path, backend: str | None) -> dict:
    golden = load_yaml_list(GOLDEN_PATH)
    attacks = load_yaml_list(ATTACKS_PATH)
    if len(golden) != 33:
        print(f"warn: golden.yaml has {len(golden)} entries (expected 33)", file=sys.stderr)
    if len(attacks) != 30:
        print(f"warn: attacks.yaml has {len(attacks)} entries (expected 30)", file=sys.stderr)

    manifest = load_manifest()
    manifest_docs = manifest.get("docs") or {}
    if not manifest_docs:
        print(
            "warn: eval/seed_manifest.json missing — hit metrics fall back to title match. "
            "Run scripts/seed_eval.py first.",
            file=sys.stderr,
        )

    planted = {doc["id"]: doc for doc in load_corpus()}

    golden_rows = []
    golden_latencies: list[float] = []
    hits_at_1 = 0
    hits_at_5 = 0
    should_n = 0
    hits_should_not = 0
    should_not_n = 0
    rr_sum = 0.0

    for entry in golden:
        user_id = str(entry["user"])
        question = str(entry["question"])
        expected_doc = str(entry["expected_doc"])
        should_answer = bool(entry["should_answer"])
        started = time.perf_counter()
        response = _post_search(base_url, user_id, question, timeout, backend)
        latency_ms = (time.perf_counter() - started) * 1000.0
        golden_latencies.append(latency_ms)
        sources = response.get("sources") or []
        rank = expected_rank(sources, expected_doc, manifest_docs, k=5)
        hit1 = rank == 1
        hit5 = rank is not None
        if should_answer:
            should_n += 1
            if hit1:
                hits_at_1 += 1
            if hit5:
                hits_at_5 += 1
            rr_sum += (1.0 / rank) if rank else 0.0
        else:
            should_not_n += 1
            if hit5:
                hits_should_not += 1
        golden_rows.append(
            {
                "id": entry.get("id"),
                "user": user_id,
                "question": question,
                "expected_doc": expected_doc,
                "should_answer": should_answer,
                "rank": rank,
                "hit@1": hit1,
                "hit@5": hit5,
                "reciprocal_rank": None if rank is None else round(1.0 / rank, 4),
                "latency_ms": round(latency_ms, 1),
                "query_id": response.get("query_id"),
                "source_titles": [s.get("document_title") for s in sources],
            }
        )
        mark = f"rank={rank}" if rank else "miss"
        print(
            f"golden {entry.get('id')} {user_id} {mark} "
            f"hit@1={hit1} hit@5={hit5} should_answer={should_answer} {latency_ms:.0f}ms"
        )

    attack_rows = []
    leaked_n = 0
    leak_counts: Counter[str] = Counter()
    for entry in attacks:
        user_id = str(entry["user"])
        prompt = str(entry["prompt"])
        forbidden_doc = str(entry["forbidden_doc"])
        planted_doc = planted[forbidden_doc]
        user = get_eval_user(user_id)
        leak_class = classify_leak(
            user_tenant=user.tenant,
            user_department=user.department,
            user_clearance=user.clearance,
            doc=planted_doc,
        )
        started = time.perf_counter()
        response = _post_search(base_url, user_id, prompt, timeout, backend)
        latency_ms = (time.perf_counter() - started) * 1000.0
        sources = response.get("sources") or []
        answer = str(response.get("answer") or "")
        leaked = canary_leaked(
            planted_doc["canary"],
            answer=answer,
            sources=sources,
        )
        if leaked:
            leaked_n += 1
            leak_counts[leak_class] += 1
            print(
                f"LEAK {entry.get('id')} {user_id} {forbidden_doc} class={leak_class} "
                f"{latency_ms:.0f}ms"
            )
        else:
            print(
                f"hold {entry.get('id')} {user_id} {forbidden_doc} class={leak_class} "
                f"{latency_ms:.0f}ms"
            )
        attack_id = str(entry.get("id") or "")
        if attack_id in {"a25", "a26", "a27"}:
            print(f"existence {attack_id} answer={answer}")
        attack_rows.append(
            {
                "id": entry.get("id"),
                "user": user_id,
                "prompt": prompt,
                "forbidden_doc": forbidden_doc,
                "leaked": leaked,
                "leak_class": leak_class,
                "latency_ms": round(latency_ms, 1),
                "query_id": response.get("query_id"),
                "source_titles": [s.get("document_title") for s in sources],
                "answer": answer,
            }
        )

    p95 = percentile(golden_latencies, 95)
    mrr = (rr_sum / should_n) if should_n else None
    payload = {
        "backend": backend or "postgres",
        "golden": {
            "n": len(golden_rows),
            "should_answer_n": should_n,
            "hit@1_when_should": hits_at_1,
            "hit@1_rate_when_should": (hits_at_1 / should_n) if should_n else None,
            "hit@5_when_should": hits_at_5,
            "hit@5_rate_when_should": (hits_at_5 / should_n) if should_n else None,
            "mrr_when_should": mrr,
            "should_not_n": should_not_n,
            "hit@5_when_should_not": hits_should_not,
            "p95_latency_ms": None if p95 is None else round(p95, 1),
            "rows": golden_rows,
        },
        "attacks": {
            "n": len(attack_rows),
            "leaked": leaked_n,
            "by_class": {
                "cross_tenant": leak_counts.get("cross_tenant", 0),
                "wrong_department": leak_counts.get("wrong_department", 0),
                "above_clearance": leak_counts.get("above_clearance", 0),
                "unexpected": leak_counts.get("unexpected", 0),
            },
            "rows": attack_rows,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n")

    hit1_s = f"{hits_at_1}/{should_n}" if should_n else "n/a"
    hit5_s = f"{hits_at_5}/{should_n}" if should_n else "n/a"
    mrr_s = "n/a" if mrr is None else f"{mrr:.3f}"
    p95_s = "n/a" if p95 is None else f"{p95:.0f}"
    summary = (
        f"backend={backend or 'postgres'} "
        f"golden hit@1={hit1_s} hit@5={hit5_s} mrr={mrr_s} p95_ms={p95_s} "
        f"should_not_hits={hits_should_not}/{should_not_n} "
        f"attacks leaked={leaked_n}/{len(attack_rows)} "
        f"cross_tenant={leak_counts.get('cross_tenant', 0)} "
        f"wrong_department={leak_counts.get('wrong_department', 0)} "
        f"above_clearance={leak_counts.get('above_clearance', 0)} "
        f"json={out_path}"
    )
    print(summary)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run golden/attack eval against live search")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--backend",
        choices=("qdrant", "postgres"),
        default="postgres",
        help="retrieval backend passed as ?search_backend= (does not write SEARCH_BACKEND)",
    )
    parser.add_argument(
        "--overwrite-baseline",
        action="store_true",
        help="allow replacing eval/baseline_qdrant_minilm.json (frozen by default)",
    )
    args = parser.parse_args()
    out_path = Path(args.out)
    if (
        out_path.resolve() == BASELINE_PATH.resolve()
        and BASELINE_PATH.is_file()
        and not args.overwrite_baseline
    ):
        raise SystemExit(
            f"refusing to overwrite frozen {BASELINE_PATH}. "
            "Pass --overwrite-baseline only if you mean it."
        )
    _run(args.base_url, args.timeout, out_path, args.backend)


if __name__ == "__main__":
    main()
