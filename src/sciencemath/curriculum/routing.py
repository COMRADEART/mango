"""T6.15 — Tool/retrieval routing labels and routing metrics.

Ground-truth labels (recorded per mango-eval-core item at build time):

  NONE         internal reasoning suffices — no tool, no retrieval
  TOOL         needs deterministic math tool
  RETRIEVAL    needs scientific retrieval
  BOTH         needs retrieval AND calculation
  INSUFFICIENT_INFO  correct behavior is uncertainty, not fabrication

The evaluated decision comes from the answering run: which subsystems
were actually invoked and whether the answer signalled insufficiency.

Metrics (T6.15): tool-needed precision/recall, retrieval-needed
precision/recall, BOTH accuracy, unnecessary-subsystem invocation rate.
"""
from __future__ import annotations

LABELS = ("NONE", "TOOL", "RETRIEVAL", "BOTH", "INSUFFICIENT_INFO")


def label_for(*, requires_math_tool: bool, requires_retrieval: bool,
              insufficient_info: bool = False) -> str:
    if insufficient_info:
        return "INSUFFICIENT_INFO"
    if requires_math_tool and requires_retrieval:
        return "BOTH"
    if requires_math_tool:
        return "TOOL"
    if requires_retrieval:
        return "RETRIEVAL"
    return "NONE"


def validate_routing_item(item: dict) -> list[str]:
    errors = []
    for key, typ in (("requires_math_tool", bool),
                     ("requires_retrieval", bool),
                     ("insufficient_info", bool)):
        if key in item and not isinstance(item[key], typ):
            errors.append(f"{key} must be bool")
    label = item.get("routing_label")
    if label is not None and label not in LABELS:
        errors.append(f"routing_label {label!r} not in {LABELS}")
    return errors


def routing_metrics(items: list[dict]) -> dict:
    """items: [{routing_label (ground truth), invoked_tool (bool),
    invoked_retrieval (bool), signalled_insufficient (bool)}] — one record
    per evaluated question."""
    per_label: dict[str, dict[str, int]] = {
        lb: {"n": 0, "tool": 0, "retrieval": 0, "both": 0,
             "insufficient": 0} for lb in LABELS}
    for it in items:
        gt = it.get("routing_label") or label_for(
            requires_math_tool=it.get("requires_math_tool", False),
            requires_retrieval=it.get("requires_retrieval", False),
            insufficient_info=it.get("insufficient_info", False))
        d = per_label[gt]
        d["n"] += 1
        d["tool"] += bool(it.get("invoked_tool"))
        d["retrieval"] += bool(it.get("invoked_retrieval"))
        d["both"] += bool(it.get("invoked_tool")
                          and it.get("invoked_retrieval"))
        d["insufficient"] += bool(it.get("signalled_insufficient"))
    tool_pos = sum(d["n"] for lb, d in per_label.items()
                   if lb in ("TOOL", "BOTH"))
    tool_pred = sum(d["tool"] for lb, d in per_label.items()
                    if lb in ("NONE", "RETRIEVAL", "INSUFFICIENT_INFO"))
    tool_tp = per_label["TOOL"]["tool"] + per_label["BOTH"]["tool"]
    ret_pos = sum(d["n"] for lb, d in per_label.items()
                  if lb in ("RETRIEVAL", "BOTH"))
    ret_pred = sum(d["retrieval"] for lb, d in per_label.items()
                   if lb in ("NONE", "TOOL", "INSUFFICIENT_INFO"))
    ret_tp = per_label["RETRIEVAL"]["retrieval"] + per_label["BOTH"]["retrieval"]
    insuf_n = per_label["INSUFFICIENT_INFO"]["n"]
    insuf_ok = per_label["INSUFFICIENT_INFO"]["insufficient"]
    over_tool = tool_pred
    over_ret = ret_pred
    total = sum(d["n"] for d in per_label.values())
    return {
        "tool_needed_precision": _safe(tool_tp, tool_tp + over_tool),
        "tool_needed_recall": _safe(tool_tp, tool_pos),
        "retrieval_needed_precision": _safe(ret_tp, ret_tp + over_ret),
        "retrieval_needed_recall": _safe(ret_tp, ret_pos),
        "both_accuracy": _safe(per_label["BOTH"]["both"], per_label["BOTH"]["n"]),
        "insufficient_info_rate": _safe(insuf_ok, insuf_n),
        "unnecessary_tool_invocation_rate": _safe(over_tool, total),
        "unnecessary_retrieval_invocation_rate": _safe(over_ret, total),
        "label_counts": {lb: d["n"] for lb, d in per_label.items()},
    }


def _safe(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None