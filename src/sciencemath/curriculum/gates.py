"""T6.10 / T6.11 / T6.12 — Regression gates, promotion, Pareto view.

The gate thresholds are DECLARED IN ADVANCE in configs/curriculum.yaml and
frozen before any curriculum training runs (T6.11). evaluate_gates()
compares a candidate checkpoint against its parent on the same frozen
suite and returns KEEP / REJECT with the violated gates named.

No single aggregate score may hide a serious regression: every tracked
dimension is gated separately, and the material-regression rule uses
absolute percentage points.

Pareto view (T6.12): a checkpoint capability vector is (math_macro,
science_macro, cross_domain_macro, generalization_macro, tool_routing,
retrieval_routing, extraction, overall). A dominates B iff >= on all
dimensions and > on at least one. Promoted checkpoint = best balanced
tradeoff, never automatic replacement of an older checkpoint.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# The tracked gate dimensions (must all be present in configs/curriculum.yaml)
GATE_DIMENSIONS = (
    "overall", "math_macro", "science_macro", "cross_domain",
    "compositional", "tool_routing", "retrieval_routing", "extraction",
    "uncertainty",
)


def load_gates(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8")) \
        if path.suffix == ".json" else _read_yaml(path)
    return _validate_gates(cfg)


def _read_yaml(path: Path) -> dict:
    from sciencemath.utils.io_utils import load_yaml
    return load_yaml(path)


def _validate_gates(cfg: dict) -> dict:
    gates = cfg.get("regression_gates", cfg)
    errors = [d for d in GATE_DIMENSIONS if d not in gates]
    if errors:
        raise ValueError(f"curriculum gate config missing dimensions: "
                         f"{errors} (gates must be fully pre-declared)")
    return gates


def pp_drop(baseline: float | None, candidate: float | None) -> float | None:
    """Absolute percentage-point drop (positive = candidate is worse)."""
    if baseline is None or candidate is None:
        return None
    return round((baseline - candidate) * 100.0, 2)


def evaluate_gates(gates: dict, baseline: dict, candidate: dict,
                   *, level: int, checkpoint: str, parent: str) -> dict:
    """baseline/candidate: metric dicts keyed by GATE_DIMENSIONS names
    (fractions in 0..1). Returns {decision: KEEP|REJECT, violated: [...],
    drops: {...}}."""
    drops: dict[str, float | None] = {}
    violated: list[str] = []
    for dim in GATE_DIMENSIONS:
        d = pp_drop(baseline.get(dim), candidate.get(dim))
        drops[dim] = d
        threshold = float(gates[dim])
        if d is not None and d > threshold:
            violated.append(dim)
    decision = "REJECT" if violated else "KEEP"
    return {
        "checkpoint": checkpoint,
        "parent": parent,
        "level": level,
        "decision": decision,
        "violated_gates": violated,
        "drops_pp": drops,
        "gate_thresholds_pp": {dim: float(gates[dim])
                               for dim in GATE_DIMENSIONS},
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def append_promotion_log(log_path: Path, entry: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        f.flush()


def promotion_entry(gate_result: dict, *, metrics: dict,
                    capability_vector: dict, notes: str = "") -> dict:
    entry = {
        "record_type": "promotion_decision",
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "checkpoint": gate_result["checkpoint"],
        "parent": gate_result["parent"],
        "level": gate_result["level"],
        "decision": gate_result["decision"],
        "violated_gates": gate_result["violated_gates"],
        "drops_pp": gate_result["drops_pp"],
        "capability_vector": capability_vector,
        "metrics": metrics,
        "notes": notes,
    }
    return entry


def validate_promotion_log(path: Path) -> list[str]:
    errors = []
    if not path.exists():
        return ["promotion log missing (decisions must be recorded)"]
    last_by_checkpoint: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        for f in ("checkpoint", "parent", "decision", "decided_at"):
            if f not in rec:
                errors.append(f"entry missing {f}")
        if rec.get("decision") not in ("KEEP", "REJECT"):
            errors.append(f"invalid decision {rec.get('decision')!r}")
        cp = rec.get("checkpoint")
        if cp in last_by_checkpoint and last_by_checkpoint[cp] == "KEEP" \
                and rec.get("decision") == "KEEP":
            errors.append(f"checkpoint {cp}: multiple KEEP entries — "
                          "never silently overwrite a promoted checkpoint")
        last_by_checkpoint[cp] = rec.get("decision")
    return errors


# ---------------------------------------------------------------------------
# T6.12 Pareto checkpointing
# ---------------------------------------------------------------------------

PARETO_DIMENSIONS = ("math_macro", "science_macro", "cross_domain_macro",
                     "generalization_macro", "tool_routing",
                     "retrieval_routing", "extraction", "overall")


def capability_vector(metrics: dict) -> dict:
    return {dim: metrics.get(dim) for dim in PARETO_DIMENSIONS}


def dominates(a: dict, b: dict) -> bool:
    """a dominates b: >= on every dimension (None-treated-as-missing skips
    the dimension) and > on at least one comparable dimension."""
    strictly_greater = False
    for dim in PARETO_DIMENSIONS:
        va, vb = a.get(dim), b.get(dim)
        if va is None or vb is None:
            continue
        if va < vb:
            return False
        if va > vb:
            strictly_greater = True
    return strictly_greater


def pareto_front(vectors: dict[str, dict]) -> list[str]:
    """vectors: {checkpoint_id: capability_vector}. Returns the
    non-dominated checkpoint ids (sorted)."""
    ids = list(vectors)
    front = []
    for cid in ids:
        dominated = any(dominates(vectors[o], vectors[cid])
                        for o in ids if o != cid)
        if not dominated:
            front.append(cid)
    return sorted(front)


def balanced_best(vectors: dict[str, dict]) -> str | None:
    """The best *balanced* tradeoff: highest minimum across dimensions
    (None counts as 0), tie-broken by mean. Returns checkpoint id."""
    def score(vec: dict) -> tuple[float, float]:
        vals = [v if v is not None else 0.0 for v in vec.values()]
        return (min(vals) if vals else 0.0,
                sum(vals) / len(vals) if vals else 0.0)
    if not vectors:
        return None
    return max(vectors, key=lambda cid: score(vectors[cid]))