"""T14.6 — necessity router metrics (do not collapse to one accuracy)."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_items(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def pr(tp: int, fp: int, fn: int) -> tuple[float | None, float | None]:
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    return prec, rec


def evaluate(items: list[dict]) -> dict:
    from sciencemath.scicomp.router import (
        COMPUTE_HELPFUL, COMPUTE_REQUIRED, INSUFFICIENT_INFORMATION,
        NO_COMPUTE, auto_routes_scicomp, compute_necessity, route,
        route_precedence)

    labels = (COMPUTE_REQUIRED, COMPUTE_HELPFUL, NO_COMPUTE,
              INSUFFICIENT_INFORMATION)
    gold_pred = []
    unnecessary = missed = wrong_op = route_conflict = 0
    rows = []
    for it in items:
        out = compute_necessity(it["question"])
        pred = out["necessity"]
        gold = it["gold_necessity"]
        gold_pred.append((gold, pred))
        routed = route(it["question"])["route"]
        prec = route_precedence(it["question"])
        if auto_routes_scicomp(pred) and gold in (NO_COMPUTE, INSUFFICIENT_INFORMATION):
            unnecessary += 1
        if gold == COMPUTE_REQUIRED and not auto_routes_scicomp(pred):
            missed += 1
        exp_op = it.get("expected_operation")
        if exp_op and gold == COMPUTE_REQUIRED and pred == COMPUTE_REQUIRED:
            # operation expected if known: compare scicomp category vs
            # presence of a compute route, not the exact solver name.
            if routed == "NO_COMPUTE":
                wrong_op += 1
        if (prec["primary"] == "SCICOMP" and pred == NO_COMPUTE) or (
                prec["primary"] == "MATH_T4" and pred == COMPUTE_REQUIRED
                and it.get("gold_primary_skill") == "MATH_T4"):
            route_conflict += 1
        rows.append({
            "eval_id": it["eval_id"], "gold": gold, "pred": pred,
            "split": it.get("split"), "reason": out.get("reason"),
            "preferred_skill": out.get("preferred_skill"),
            "precedence": prec["primary"],
        })

    per = {}
    for lab in labels:
        tp = sum(1 for g, p in gold_pred if g == lab and p == lab)
        fp = sum(1 for g, p in gold_pred if g != lab and p == lab)
        fn = sum(1 for g, p in gold_pred if g == lab and p != lab)
        prec, rec = pr(tp, fp, fn)
        per[lab] = {"tp": tp, "fp": fp, "fn": fn, "precision": prec,
                    "recall": rec}
    n = len(items)
    return {
        "n": n,
        "per_label": per,
        "COMPUTE_REQUIRED_precision": per[COMPUTE_REQUIRED]["precision"],
        "COMPUTE_REQUIRED_recall": per[COMPUTE_REQUIRED]["recall"],
        "NO_COMPUTE_precision": per[NO_COMPUTE]["precision"],
        "NO_COMPUTE_recall": per[NO_COMPUTE]["recall"],
        "INSUFFICIENT_INFORMATION_precision":
            per[INSUFFICIENT_INFORMATION]["precision"],
        "INSUFFICIENT_INFORMATION_recall":
            per[INSUFFICIENT_INFORMATION]["recall"],
        "unnecessary_compute_rate": unnecessary / n if n else None,
        "missed_compute_rate": missed / n if n else None,
        "wrong_operation_rate": wrong_op / n if n else None,
        "route_conflict_rate": route_conflict / n if n else None,
        "confusion": dict(Counter(f"{g}->{p}" for g, p in gold_pred)),
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["development", "final", "all"],
                    default="development")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    suite = ROOT / "evaluations/t14/suites/necessity/v1"
    if args.split == "all":
        path = suite / "questions.jsonl"
    elif args.split == "final":
        path = suite / "final.jsonl"
        pinned = (suite / "final_checksum.txt").read_text(encoding="utf-8").strip()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != pinned:
            raise SystemExit(f"final split checksum mismatch {digest} != {pinned}")
    else:
        path = suite / "development.jsonl"
    items = load_items(path)
    metrics = evaluate(items)
    metrics["split"] = args.split
    metrics["suite_path"] = str(path.relative_to(ROOT))
    metrics["suite_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    rows = metrics.pop("rows")
    out_dir = Path(args.out) if args.out else (
        ROOT / "evaluations/t14/necessity" / args.split)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    with open(out_dir / "predictions.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in metrics.items() if k != "confusion"},
                     indent=2))
    print("confusion", metrics["confusion"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
