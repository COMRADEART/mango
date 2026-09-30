"""T32 paired analysis (DEV_PROTOCOL §7): 2x2 tables, McNemar exact test,
effect size, per benchmark — no pooling across benchmarks.

Joins item ids across:
  * the FROZEN T31 scored rows (base arm + adapter arm), and
  * the fresh T32 arm rows (sciencemath.t32.final_eval),

each compared pairwise with identical members and prompts, and writes
evaluations/t32/paired/T32_PAIRED_ANALYSIS.json plus per-benchmark csv
deltas. McNemar's exact test uses the binomial tail of the discordant
pairs (exact two-sided binomial; no large-sample approximation).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, "src")

ROOT = Path(".")
T31 = ROOT / "evaluations" / "t31" / "scored"
FINAL = ROOT / "evaluations" / "t32" / "final"
OUT = ROOT / "evaluations" / "t32" / "paired"
BENCHMARKS_ALL = ("gsm8k", "math500", "arc_easy", "arc_challenge", "sciq")


def correct_map(path: Path) -> dict[str, dict]:
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            out[r["item_id"]] = r
    return out


def _mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact binomial McNemar p-value for discordant counts b, c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) * (0.5 ** n)
    return min(1.0, 2.0 * tail)


def _cohens_g(b: int, c: int) -> float:
    """Effect size (odds ratio equivalent for the discordant cells)."""
    n = b + c
    if n == 0:
        return 0.0
    if min(b, c) == 0:
        return float("inf") if max(b, c) > 0 else 0.0
    return (max(b, c) - min(b, c)) / (max(b, c) + min(b, c))


def paired_table(frozen_arm: str, fresh_arm: str, benchmark: str,
                 frozen_rows: dict[str, dict],
                 fresh_rows: dict[str, dict]) -> dict:
    ids = sorted(set(frozen_rows) & set(fresh_rows))
    only_frozen = len(set(frozen_rows) - set(fresh_rows))
    only_fresh = len(set(fresh_rows) - set(frozen_rows))
    both = only_a = only_b = neither = 0
    for iid in ids:
        a = frozen_rows[iid].get("content_valid") is True
        b_ = fresh_rows[iid].get("content_valid") is True
        if a and b_:
            both += 1
        elif a:
            only_a += 1
        elif b_:
            only_b += 1
        else:
            neither += 1
    disc_b, disc_c = only_a, only_b   # frozen-correct/fresh-wrong, fresh-correct/frozen-wrong
    p = _mcnemar_exact(disc_b, disc_c)
    g = _cohens_g(disc_b, disc_c)
    n = len(ids)
    return {
        "benchmark": benchmark,
        "frozen_arm": frozen_arm, "fresh_arm": fresh_arm,
        "n_shared": n, "n_only_frozen_rows": only_frozen,
        "n_only_fresh_rows": only_fresh,
        "accuracy_frozen": round(
            (both + only_a) / n, 4) if n else None,
        "accuracy_fresh": round((both + only_b) / n, 4) if n else None,
        "delta_pp": (round(100.0 * ((both + only_b) / n
                                    - (both + only_a) / n), 2)
                     if n else None),
        "table": {"both_correct": both,
                  f"{frozen_arm}_correct_only": only_a,
                  f"{fresh_arm}_correct_only": only_b,
                  "neither_correct": neither},
        "discordant": {"frozen_only_correct": disc_b,
                       "fresh_only_correct": disc_c},
        "mcnemar_exact_p": p, "effect_size_g": (
            None if math.isinf(g) else round(g, 4)),
        "membership_and_prompts_identical": (
            only_frozen == 0 and only_fresh == 0),
    }


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else None
    if not label:
        # default: the t32 arm directory name
        fresh_dirs = [p for p in FINAL.iterdir() if p.is_dir()]
        if len(fresh_dirs) != 1:
            raise SystemExit(f"pass the fresh arm name (dirs={fresh_dirs})")
        label = fresh_dirs[0].name
    OUT.mkdir(parents=True, exist_ok=True)

    report = {"schema_version": "t32-paired-v1",
              "artifact": "T32_PAIRED_ANALYSIS",
              "fresh_arm": label,
              "note": ("base and T30 adapter columns reuse the FROZEN T31 "
                       "scored rows (identical membership and prompts); "
                       "the T32 arm was generated fresh under the identical "
                       "frozen config; McNemar exact = two-sided binomial "
                       "on the discordant pairs; no pooling across "
                       "benchmarks"),
              "benchmarks": {}}

    for b in BENCHMARKS_ALL:
        base_rows = correct_map(T31 / "base" / f"{b}.jsonl")
        t30_rows = correct_map(T31 / "adapter" / f"{b}.jsonl")
        t32_rows = correct_map(FINAL / label / f"{b}.jsonl")
        report["benchmarks"][b] = {
            "base_vs_" + label: paired_table("base", label, b, base_rows,
                                             t32_rows),
            "t30_vs_" + label: paired_table("t30", label, b, t30_rows,
                                            t32_rows),
        }

    path = OUT / "T32_PAIRED_ANALYSIS.json"
    path.write_text(json.dumps(report, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    summary = {}
    for b, v in report["benchmarks"].items():
        summary[b] = {k:
                      {"delta_pp": x["delta_pp"],
                       "p": x["mcnemar_exact_p"],
                       "identical": x["membership_and_prompts_identical"]}
                      for k, x in v.items()}
    print(json.dumps(summary, indent=2))
    print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())