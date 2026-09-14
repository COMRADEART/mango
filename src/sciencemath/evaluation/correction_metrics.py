"""Deterministic T9 correction metrics; no model judging."""
from __future__ import annotations

from math import sqrt


def correction_metrics(rows: list[dict]) -> dict:
    true_rows = [r for r in rows if r["case_class"] == "TRUE_FAIL"]
    false_rows = [r for r in rows if r["case_class"] == "FALSE_FAIL"]
    corrected = sum(r.get("initial_correct") is False and r.get("final_correct") is True
                    for r in true_rows)
    preserved = sum(r.get("initial_correct") is True and r.get("final_correct") is True
                    for r in false_rows)
    over = sum(r.get("initial_correct") is True and r.get("final_correct") is False
               for r in false_rows)
    under = sum(r.get("initial_correct") is False and r.get("final_correct") is False
                for r in true_rows)
    blind = sum(bool(r.get("changed")) and r.get("feedback_trust") == "UNVERIFIED"
                for r in rows)
    return {
        "true_correction": corrected / len(true_rows) if true_rows else None,
        "false_feedback_preservation": preserved / len(false_rows) if false_rows else None,
        "overcorrection": over / len(false_rows) if false_rows else None,
        "under_correction": under / len(true_rows) if true_rows else None,
        "blind_agreement": blind / len(rows) if rows else None,
        "net_correction_benefit": corrected - over,
        "counts": {"corrected_wrong": corrected, "preserved_correct": preserved,
                   "destroyed_correct": over, "still_wrong": under,
                   "blind_agreement": blind},
    }


def wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total <= 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [max(0.0, centre - half), min(1.0, centre + half)]


# --------------------------------------------------------------- T10 v2 ----

CITATION_TOKENS = ("wiki", "wikipedia", "reference", "source", "citation")


def _part_value(answer: str, part: str) -> str:
    """Extract '(a) ...' style component values from a multi-part answer.

    A part label is a single letter in parens PRECEDED BY WHITESPACE, so a
    value like 'cos(x)' is not truncated at its own '(x)'."""
    import re
    m = re.search(rf"\({part}\)\s*(.+?)(?=\s+\([a-z]\)\s|\s+\([a-z]\)$|$)",
                  answer or "", re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _citation_ok(value: str) -> bool:
    v = (value or "").lower()
    if "citation_missing" in v or "citation_ok" in v:
        return "citation_ok" in v
    return any(t in v for t in CITATION_TOKENS) or len(v.split()) >= 4


def _part_matches(expected: str, actual: str) -> bool:
    from sciencemath.evaluation.extraction import answers_match
    if expected == "CITATION_OK":
        return _citation_ok(actual)
    return answers_match(expected, actual)


def correction_metrics_v2(rows: list[dict]) -> dict:
    """T10 correction metrics: v1 semantics plus partial-fail handling,
    ambiguous preservation, repair-method attribution, attempt stats."""
    base = correction_metrics(rows)
    partial = [r for r in rows if r["case_class"] == "PARTIAL_FAIL"]
    amb = [r for r in rows if r["case_class"] == "AMBIGUOUS"]
    true_rows = [r for r in rows if r["case_class"] == "TRUE_FAIL"]

    def parts_of(row: dict) -> tuple[int, int]:
        protected = row.get("protected") or {}
        fixed = preserved = 0
        for part, spec in protected.items():
            expected = str(spec.get("expected", ""))
            actual = _part_value(row.get("final_answer", ""), part)
            ok = _part_matches(expected, actual)
            if part == row.get("failed_part"):
                fixed += 1 if ok else 0
            else:
                preserved += 1 if ok else 0
        return fixed, preserved

    repaired = collateral = 0
    for row in partial:
        fixed, preserved = parts_of(row)
        row["_failed_fixed"] = bool(fixed)
        n_protected = len(row.get("protected", {})) - (1 if row.get("failed_part")
                                                       in (row.get("protected") or {}) else 0)
        row["_protected_preserved"] = preserved == n_protected
        if fixed and row["_protected_preserved"]:
            repaired += 1
        if not row["_protected_preserved"]:
            collateral += 1
    ambiguous_preserved = sum(not r.get("changed") for r in amb)
    attempts = [r.get("repair_attempts", 0) for r in rows]
    methods: dict[str, int] = {}
    for r in rows:
        m = r.get("repair_method") or "NO_REPAIR"
        methods[m] = methods.get(m, 0) + 1
    att1 = [r for r in true_rows + partial
            if (r.get("repair_attempts") or 0) >= 1]
    att1_ok = sum(r.get("final_correct") or r.get("_failed_fixed", False)
                  for r in att1)
    att2 = [r for r in true_rows + partial
            if (r.get("repair_attempts") or 0) >= 2]
    att2_ok = sum(1 for r in att2 if r.get("final_correct")
                  or r.get("_failed_fixed", False))
    n_true = len(true_rows)
    n_false = len([r for r in rows if r["case_class"] == "FALSE_FAIL"])
    return {
        **base,
        "partial_fail_repair_rate": repaired / len(partial) if partial else None,
        "collateral_change_rate": collateral / len(partial) if partial else None,
        "ambiguous_preservation": (ambiguous_preserved / len(amb))
                                  if amb else None,
        "repair_methods": methods,
        "first_attempt": {"used": len(att1),
                          "success_rate": att1_ok / len(att1) if att1 else None},
        "second_attempt": {"used": len(att2),
                           "incremental_gain": (att2_ok - att1_ok) / n_true
                                               if att2 and n_true else None},
        "counts_v2": {"partial_repaired": repaired,
                      "partial_collateral": collateral,
                      "ambiguous_preserved": ambiguous_preserved,
                      "ambiguous_total": len(amb)},
    }
