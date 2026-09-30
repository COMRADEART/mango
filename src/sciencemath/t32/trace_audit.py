"""T32 Phase 10: qualitative trace audit on deterministic samples.

Samples a deterministic head (sorted by item_id) of each math benchmark's
rows across the three arms (base / T30 frozen rows + fresh T32 rows), and
renders a side-by-side markdown audit file with the raw generation of each
arm, the extracted answer, the gold, and the per-arm correctness. This is a
QUALITATIVE artifact for the report; no selection decision reads it.

Usage: PYTHONPATH=src python -m sciencemath.t32.trace_audit --arm-label t32-A
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, "src")

ROOT = Path(".")
T31 = ROOT / "evaluations" / "t31" / "scored"
FINAL = ROOT / "evaluations" / "t32" / "final"
OUT = ROOT / "evaluations" / "t32" / "final"
BENCHMARKS_ALL = ("gsm8k", "math500")
N_PER_BENCH = 8


def read_rows(path: Path) -> dict[str, dict]:
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out[r["item_id"]] = r
    return out


def items_map(benchmark: str) -> dict[str, dict]:
    from sciencemath.comparability.loaders import load_benchmark
    return {it.item_id: it for it in load_benchmark(benchmark)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm-label", required=True)
    ap.add_argument("--per-bench", type=int, default=N_PER_BENCH)
    ap.add_argument("--benchmarks", default=",".join(BENCHMARKS_ALL))
    args = ap.parse_args()

    t32 = read_rows(FINAL / args.arm_label)
    lines = [
        "# T32 Phase 10 — qualitative trace audit",
        "",
        f"Fresh arm: `{args.arm_label}`; frozen arms: `base`, `adapter "
        f"(T30)`; samples are the sorted head of item_id per benchmark "
        f"(deterministic; no model-dependent selection).",
        "",
    ]
    for b in [s for s in args.benchmarks.split(",") if s]:
        base = read_rows(T31 / "base" / f"{b}.jsonl")
        t30 = read_rows(T31 / "adapter" / f"{b}.jsonl")
        shared = sorted(set(base) & set(t30) & set(t32))
        items = items_map(b)
        picked = shared[: args.per_bench]
        lines += [f"## {b} — {len(picked)} sampled of {len(shared)} rows",
                  ""]
        for iid in picked:
            it = items[iid]
            gold = it.gold if isinstance(it.gold, str) else it.gold
            lines += [f"### `{iid}` — gold: {gold}", "",
                      f"**question:** {it.question}", ""]
            for label, row in (("base", base[iid]), ("t30", t30[iid]),
                               (args.arm_label, t32[iid])):
                ok = "PASS" if row.get("content_valid") is True else "FAIL"
                trunc = row.get("finish_reason") != "stop"
                lines += [
                    f"**{label}** [{ok}"
                    + (", TRUNCATED" if trunc else "")
                    + f", {row.get('output_tokens')} tok] "
                    f"extracted: {row.get('extracted_answer')!r}",
                    "", "```text",
                    (row.get("raw_generation") or "")[:2000],
                    "```", ""]
    path = OUT / f"T32_TRACE_AUDIT_{args.arm_label}.md"
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())