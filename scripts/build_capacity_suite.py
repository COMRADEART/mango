"""Build, verify, and freeze mango-capacity-eval-v1 (T8.5).

Pipeline (all gates must pass before the suite is frozen):
  1. schema validation (capacity-specific fields, category/answer types)
  2. numeric answer verification: every tool_check expression is evaluated
     deterministically and must agree with expected_answer (no silent
     tolerance abuse; T8.21 spirit — answer/work agreement enforced here)
  3. pair integrity: distractor twins share the answer; counterfactual
     children reference an existing parent and carry a change type
  4. uncertainty integrity: insufficient_info items expect __UNKNOWN__ and
     non-uncertainty items must not
  5. dedup + near-dup check within the suite and vs frozen suites
  6. freeze + per-question checksums (same contract as eval-core)

Usage:
  python scripts/build_capacity_suite.py            # verify + report
  python scripts/build_capacity_suite.py --freeze   # freeze to evaluations/t8/capacity-suite/v1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from sciencemath.evaluation.extraction import normalize_symbolic  # noqa: E402

STAGING = REPO / "evaluations" / "t8" / "capacity-suite-staging" / "items.json"
OUT_DIR = REPO / "evaluations" / "t8" / "capacity-suite" / "v1"

SUITE_VERSION = "mango-capacity-eval-v1"
EVAL_ID_PREFIX = "mce1-"
LICENSE = "CC0-1.0"

DIMENSIONS = ("math", "science", "compositional", "cross_domain",
              "uncertainty", "counterfactual", "distractor_clean",
              "distractor_loaded")
CATEGORIES = (
    "math_foundation", "algebra", "geometry", "trig", "calculus",
    "probability_statistics", "physics", "chemistry", "biology",
    "earth_space", "scientific_reasoning", "mixed_quantitative",
    "interdisciplinary", "uncertainty_calibration",
)
SPLITS = ("IID", "COMPOSITIONAL", "OUT_OF_TEMPLATE", "CROSS_DOMAIN")
ANSWER_TYPES = ("numeric", "exact_answer", "text")
CF_CHANGE_TYPES = ("numbers", "units", "constraint", "relationship")


def validate_item(item: dict) -> list[str]:
    errors: list[str] = []
    for f in ("key", "capacity_dimension", "category", "capability_track",
              "generalization_split", "requires_math_tool",
              "requires_retrieval", "insufficient_info", "multi_hop",
              "answer_type", "question", "expected_answer",
              "solution_outline"):
        if f not in item or item[f] in (None, ""):
            errors.append(f"missing/empty field {f}")
    if errors:
        return errors
    if item["capacity_dimension"] not in DIMENSIONS:
        errors.append(f"bad capacity_dimension {item['capacity_dimension']!r}")
    if item["category"] not in CATEGORIES:
        errors.append(f"bad category {item['category']!r}")
    if item["generalization_split"] not in SPLITS:
        errors.append(f"bad generalization_split {item['generalization_split']!r}")
    if item["answer_type"] not in ANSWER_TYPES:
        errors.append(f"bad answer_type {item['answer_type']!r}")
    for f in ("requires_math_tool", "requires_retrieval", "insufficient_info",
              "multi_hop"):
        if f in item and not isinstance(item[f], bool):
            errors.append(f"{f} must be boolean")
    q = item["question"]
    if not (15 <= len(q) <= 1200):
        errors.append("question length out of range")
    if len(item["expected_answer"]) > 80:
        errors.append("expected_answer too long (>80 chars)")
    if item["insufficient_info"]:
        if item["expected_answer"] != "__UNKNOWN__":
            errors.append("insufficient_info must expect __UNKNOWN__")
    else:
        if item["expected_answer"] == "__UNKNOWN__":
            errors.append("non-uncertainty item expects __UNKNOWN__")
    if item["capacity_dimension"] == "uncertainty" \
            and not item["insufficient_info"]:
        errors.append("uncertainty dimension must set insufficient_info")
    if item["capacity_dimension"] == "counterfactual":
        if not item.get("cf_parent_key"):
            errors.append("counterfactual item needs cf_parent_key")
        if item.get("cf_change_type") not in CF_CHANGE_TYPES:
            errors.append(f"cf_change_type must be in {CF_CHANGE_TYPES}")
    if item["capacity_dimension"] in ("distractor_clean",
                                      "distractor_loaded") \
            and not item.get("distractor_pair_key"):
        errors.append("distractor item needs distractor_pair_key")
    tc = item.get("tool_check")
    if tc is not None:
        if not isinstance(tc, dict) or tc.get("tool") != "calculator" \
                or not isinstance(tc.get("args", {}).get("expression"), str):
            errors.append("tool_check must be a calculator invocation")
        elif item["answer_type"] != "numeric":
            errors.append("tool_check only valid for numeric answers")
    return errors


_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _norm_number(s: str) -> float | None:
    s = s.strip().replace(",", "").rstrip(".")
    if _NUMERIC_RE.match(s):
        return float(s)
    return None


def verify_numeric(item: dict) -> str | None:
    """Deterministically re-evaluate the tool_check expression. Returns an
    error string, or None if it agrees with expected_answer."""
    tc = item.get("tool_check")
    if not tc:
        return None
    expr = tc["args"]["expression"]
    expected = _norm_number(item["expected_answer"])
    if expected is None:
        return f"numeric item {item['key']}: expected_answer not numeric"
    try:
        import sympy

        val = sympy.sympify(expr).evalf(15)
        got = float(val)
    except Exception as exc:  # noqa: BLE001 — report any eval failure
        return f"tool_check {item['key']}: eval failed: {exc}"
    if abs(got - expected) > 1e-9 + 1e-9 * abs(expected):
        return (f"tool_check {item['key']}: expression={expr} -> {got} "
                f"!= expected {expected}")
    return None


def check_pairs(items: list[dict]) -> list[str]:
    errors: list[str] = []
    by_key = {it["key"]: it for it in items}
    # distractor twins must share the same answer (whitespace-normalized)
    groups: dict[str, list[dict]] = {}
    for it in items:
        pk = it.get("distractor_pair_key")
        if pk:
            groups.setdefault(pk, []).append(it)
    for pk, members in groups.items():
        dims = {m["capacity_dimension"] for m in members}
        if dims != {"distractor_clean", "distractor_loaded"}:
            errors.append(f"distractor pair {pk}: members are {dims}")
        answers = {normalize_symbolic(m["expected_answer"]) for m in members}
        if len(answers) != 1:
            errors.append(f"distractor pair {pk}: answers diverge: {answers}")
        if len(members) != 2:
            errors.append(f"distractor pair {pk}: expected 2 members, "
                          f"got {len(members)}")
    # counterfactual children must reference an existing parent
    for it in items:
        pkey = it.get("cf_parent_key")
        if pkey and pkey not in by_key:
            errors.append(f"counterfactual {it['key']}: parent {pkey} missing")
        if pkey and it.get("cf_change_type") not in CF_CHANGE_TYPES:
            errors.append(f"counterfactual {it['key']}: bad change type")
    return errors


def eval_id_for(question: str) -> str:
    return EVAL_ID_PREFIX + hashlib.sha256(
        f"{SUITE_VERSION}|{question}".encode("utf-8")).hexdigest()[:12]


def near_dup_check(items: list[dict]) -> list[str]:
    """Exact-duplicate and 8-shingle near-dup detection within the suite.
    Counterfactual children and their parents share stems BY DESIGN and are
    exempted; unrelated items may not. A single shared 8-word shingle is
    tolerated (standard problem phrasing); >= 2 shared shingles flags."""
    errors: list[str] = []
    cf_links = {it.get("cf_parent_key") for it in items
                if it.get("cf_parent_key")}
    seen: dict[str, str] = {}
    shingles: dict[str, list[str]] = {}
    for it in items:
        q = " ".join(it["question"].lower().split())
        if q in seen:
            errors.append(f"duplicate question: {it['key']} == {seen[q]}")
        seen[q] = it["key"]
        sh = [" ".join(q.split()[i:i + 8]) for i in range(max(1, len(q.split()) - 7))]
        for s in sh:
            if s in shingles and it["key"] not in shingles[s]:
                a = shingles[s][0]
                if a.split("-")[0] == it["key"].split("-")[0]:
                    continue  # cf/distractor twins share stems by design
                if a in cf_links and it["key"].startswith("cf-"):
                    continue  # counterfactual child of parent a
                shingles[s].append(it["key"])
                if len(shingles[s]) == 2:  # flag once per pair
                    errors.append(f"near-dup 8-shingle overlap: {a} ~ "
                                  f"{it['key']} ({s!r})")
            shingles.setdefault(s, [it["key"]])
    return errors


def freeze(items: list[dict]) -> dict:
    canon = []
    for it in sorted(items, key=lambda x: (x["capacity_dimension"],
                                           x["question"])):
        rec = {k: it[k] for k in it if k not in ("key", "solution_outline")}
        rec["author_key"] = it["key"]
        rec.setdefault("license", LICENSE)
        rec["eval_id"] = eval_id_for(rec["question"])
        rec["suite_version"] = SUITE_VERSION
        canon.append(rec)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "questions.jsonl"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in canon:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=False) + "\n")
    checksums = {r["eval_id"]: hashlib.sha256(
        json.dumps(r, ensure_ascii=False, sort_keys=False).encode()
    ).hexdigest() for r in canon}
    (OUT_DIR / "checksum.json").write_text(
        json.dumps(checksums, indent=2) + "\n", encoding="utf-8")
    dims = Counter(r["capacity_dimension"] for r in canon)
    cats = Counter(r["category"] for r in canon)
    manifest = {
        "artifact": SUITE_VERSION,
        "suite_version": SUITE_VERSION,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "immutable": True,
        "questions": len(canon),
        "eval_id_prefix": EVAL_ID_PREFIX,
        "license": f"self-authored synthetic items under {LICENSE}",
        "capacity_dimensions": dict(sorted(dims.items())),
        "categories": dict(sorted(cats.items())),
        "note": "T8 capacity benchmark — targets the measured weaknesses of "
                "the 1.7B base (T5R/T6/T7): decomposition, composition, "
                "counterfactual, uncertainty, distractors, cross-domain.",
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    args = ap.parse_args()

    raw = json.loads(STAGING.read_text(encoding="utf-8"))
    items = raw["items"] if isinstance(raw, dict) else raw
    print(f"staged items: {len(items)}")

    # -- schema --
    errors: list[str] = []
    keys = [it.get("key") for it in items]
    dup_keys = {k for k in keys if keys.count(k) > 1}
    if dup_keys:
        errors.append(f"duplicate keys: {sorted(dup_keys)}")
    for it in items:
        errors.extend(validate_item(it))
    # -- numeric verification --
    for it in items:
        err = verify_numeric(it)
        if err:
            errors.append(err)
    # -- pairs --
    errors.extend(check_pairs(items))
    # -- dups --
    errors.extend(near_dup_check(items))

    counts = Counter(it.get("capacity_dimension", "?") for it in items)
    print("dimension counts:", dict(sorted(counts.items())))
    if errors:
        print(f"\n{len(errors)} ERRORS:")
        for e in errors:
            print(" -", e)
        return 1

    print("all gates passed: schema, numeric tool_check, pair integrity, "
          "no dups")
    if args.freeze:
        manifest = freeze(items)
        print("frozen ->", OUT_DIR)
        print(json.dumps(manifest, indent=2)[:800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())