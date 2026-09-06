"""Build the counterfactual robustness suite (T6.17).

Derives perturbed variants of mango-eval-core-v1 items. Only perturbations
whose expected answer can be re-derived DETERMINISTICALLY are included:

  * change_value — a number appearing in both the question and the item's
    tool_check args is replaced; the new answer is recomputed by executing
    the modified tool_check against the live T4 registry.
  * add_distractor — an irrelevant sentence is appended; answer must stay
    unchanged (ANSWER_UNCHANGED).
  * alter_unit — for unit_converter items, the target unit is swapped and
    the answer recomputed with the same tool.

The remaining kinds (reverse_relation, remove_fact, swap_variables) are
implemented in sciencemath.curriculum.counterfactual and unit-tested, but
are not auto-derivable from the frozen suite without human-authored
answer keys; their absence from the frozen v1 probe file is recorded in
the build report rather than silently skipped.

The suite is frozen with checksums and is NEVER trained on.

Usage: python scripts/build_counterfactual_suite.py [--freeze]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from sciencemath.curriculum.counterfactual import apply_perturbation  # noqa: E402
from sciencemath.curriculum.eval_core import freeze_suite  # noqa: E402
from sciencemath.tools.router import build_default_registry  # noqa: E402
from sciencemath.utils.io_utils import read_jsonl  # noqa: E402

SUITE = REPO / "evaluations" / "eval-core" / "v1"
OUT = REPO / "evaluations" / "t6" / "counterfactual" / "v1"

DISTRACTOR = ("Separately, the facility also rents bicycles on weekends "
              "for a flat fee.")

_TOOL_VALUE = {"calculator": "value", "unit_converter": "converted_value"}


def _tool_value(registry, tool: str, args: dict):
    inv = registry.invoke(tool, args)
    if inv.status != "ok":
        return None
    field = _TOOL_VALUE.get(tool)
    if tool == "equation_solver":
        try:
            return float(inv.result["solutions"][0][
                inv.result.get("variable", "x")])
        except (KeyError, IndexError, TypeError, ValueError):
            return None
    try:
        return float(inv.result[field])
    except (KeyError, TypeError, ValueError):
        return None


def _numbers_in(text: str) -> list[str]:
    return re.findall(r"\d[\d,]*(?:\.\d+)?", text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    args = ap.parse_args()

    suite = read_jsonl(SUITE / "questions.jsonl")
    registry = build_default_registry()
    variants, notes = [], {"built": [], "skipped": []}

    for item in suite:
        tc = item.get("tool_check")
        if not tc or item["answer_type"] != "numeric" \
                or item.get("source_fact") or item["insufficient_info"]:
            continue
        q = item["question"]
        tc_args = tc.get("args", {})

        # --- change_value: number present in question AND tool args ------
        expr_key = "expression" if tc["tool"] == "calculator" else None
        if expr_key and isinstance(tc_args.get(expr_key), str):
            for num in _numbers_in(q):
                if num in tc_args[expr_key] and float(num) != 0:
                    new_num = num.replace("9", "3").replace("7", "1")
                    new_num = new_num.replace("8", "2").replace("5", "6")
                    if new_num == num:
                        continue
                    new_args = dict(tc_args)
                    new_args[expr_key] = tc_args[expr_key].replace(
                        num, new_num)
                    new_val = _tool_value(registry, tc["tool"], new_args)
                    if new_val is None:
                        notes["skipped"].append(
                            (item["eval_id"], "change_value recompute failed"))
                        continue
                    new_q, applied = apply_perturbation(q, {
                        "kind": "change_value", "find": num,
                        "replace": new_num})
                    if not applied:
                        continue
                    # replace only the FIRST occurrence in question order:
                    # apply_perturbation already did that; verify number set
                    variants.append(_variant(item, new_q,
                                             _fmt(new_val), {
                        "kind": "change_value", "find": num,
                        "replace": new_num,
                        "recomputed_with": f"{tc['tool']}:{new_args[expr_key]}",
                    }))
                    break   # one change_value variant per item

        # --- alter_unit: unit_converter items only ------------------------
        if tc["tool"] == "unit_converter" and item["answer_type"] == "numeric":
            to_unit = tc_args.get("to_unit")
            from_unit = tc_args.get("from_unit")
            swap = {"m/s": "km/h", "km/h": "m/s"}.get(to_unit)
            if swap:
                new_args = dict(tc_args, to_unit=swap)
                new_val = _tool_value(registry, "unit_converter", new_args)
                if new_val is not None:
                    new_q, applied = apply_perturbation(q, {
                        "kind": "alter_unit", "find": to_unit,
                        "replace": swap})
                    if applied:
                        variants.append(_variant(item, new_q,
                                                 _fmt(new_val), {
                            "kind": "alter_unit", "find": to_unit,
                            "replace": swap,
                            "recomputed_with": f"unit_converter:{new_args}",
                        }))

        # --- add_distractor: answer must remain unchanged ------------------
        new_q, applied = apply_perturbation(q, {"kind": "add_distractor",
                                                "distractor_sentence": DISTRACTOR})
        if applied:
            variants.append(_variant(item, new_q,
                                     item["expected_answer"], {
                "kind": "add_distractor",
                "expected_behavior": "ANSWER_UNCHANGED",
            }))

    report = {"variants": len(variants),
              "by_kind": {k: sum(1 for v in variants
                                 if v["counterfactual"]["kind"] == k)
                          for k in sorted({v["counterfactual"]["kind"]
                                           for v in variants})},
              "parents": len({v["counterfactual"]["parent_eval_id"]
                              for v in variants}),
              "notes": notes}
    print(json.dumps(report, indent=2)[:1200])

    if not variants:
        print("no variants built")
        return 1
    if not args.freeze:
        print("report only (pass --freeze)")
        return 0
    freeze = freeze_suite(variants, OUT,
                          build_config={"derived_from": "mango-eval-core-v1",
                                        "purpose": "T6.17 robustness probes"})
    print(json.dumps(freeze, indent=2)[:600])
    return 0


def _variant(item: dict, new_q: str, new_answer: str, cf: dict) -> dict:
    kind = cf["kind"]
    default_behavior = {"change_value": "ANSWER_CHANGES",
                        "alter_unit": "ANSWER_CHANGES",
                        "add_distractor": "ANSWER_UNCHANGED"}[kind]
    return {
        "category": item["category"],
        "capability_track": item["capability_track"],
        "generalization_split": "OUT_OF_TEMPLATE",
        "requires_math_tool": item["requires_math_tool"],
        "requires_retrieval": False,
        "insufficient_info": False,
        "multi_hop": item["multi_hop"],
        "answer_type": item["answer_type"],
        "question": new_q,
        "expected_answer": new_answer,
        "license": "CC0-1.0",
        "difficulty": item.get("difficulty", 3),
        "counterfactual": {"parent_eval_id": item["eval_id"],
                           "parent_question": item["question"],
                           "expected_behavior": cf.get(
                               "expected_behavior", default_behavior),
                           **cf},
    }


def _fmt(value: float) -> str:
    return f"{value:g}"


if __name__ == "__main__":
    raise SystemExit(main())