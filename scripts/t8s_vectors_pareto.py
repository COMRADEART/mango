"""T8S.9 / T8S.10 / T8S.13 - system capability vectors, Pareto analysis
and the three independent T8S decisions.

Rules:
  - dimensions stay RAW (different evaluation denominators are never merged
    into one fake score); provenance/denominator recorded per dimension
  - Pareto over pre-registered dimensions (latency/VRAM are costs)
  - decisions are deterministic functions of the vectors + safety gates
  - Decision A (T8 model migration) is an INPUT (DO_NOT_MIGRATE), never
    recomputed - T8 is closed.
"""
from __future__ import annotations

# dimension -> direction (True = higher is better)
PARETO_DIMENSIONS = {
    "math": True, "science": True, "compositional": True,
    "cross_domain": True, "uncertainty": True, "decomposition": True,
    "self_correction": True, "tool_use": True, "rag_gain": True,
    "latency": False, "peak_vram": False,
}

SAFETY_GATES = ("t4_false_pass_zero", "citation_integrity_ok",
                "no_overcorrection_explosion")

OVERCORRECTION_EXPLOSION_RATE = 0.75


def dominates(a: dict, b: dict,
              dims: dict[str, bool] | None = None) -> str:
    """Return 'a', 'b', 'neither', or 'tie' for two capability vectors.
    A dominates B iff it is >= on every dimension and > on at least one.
    Missing dimensions are skipped (reported via 'missing' key)."""
    dims = dims or PARETO_DIMENSIONS
    a_wins = b_wins = compared = 0
    missing = []
    for d, higher_better in dims.items():
        va, vb = a.get(d), b.get(d)
        if va is None or vb is None:
            missing.append(d)
            continue
        va, vb = float(va), float(vb)
        if va == vb:
            continue
        a_better = (va > vb) if higher_better else (va < vb)
        if a_better:
            a_wins += 1
        else:
            b_wins += 1
        compared += 1
    out = {"missing_dimensions": missing}
    if not compared:
        out["result"] = "tie"
    elif b_wins == 0:
        out["result"] = "a"
    elif a_wins == 0:
        out["result"] = "b"
    else:
        out["result"] = "neither"
    return out


def dominant_system(vec_a: dict, vec_b: dict,
                    dims: dict[str, bool] | None = None) -> dict:
    r = dominates(vec_a, vec_b, dims)
    r["dominant"] = {"a": "Mango-v0.1", "b": "Qwen3-4B",
                     "neither": None, "tie": None}[r["result"]]
    return r


def build_vector(*, label: str, capacity: dict, t4_notool: dict,
                 t4_tool: dict, t4_router: dict | None,
                 t5r_norag: dict | None, t5r_rag: dict | None,
                 peak_vram_mib: float | None) -> dict:
    """T8S.9 raw capability vector. Every dimension carries provenance
    (which artifact/denominator it came from) - no cross-suite merging."""
    m = capacity.get("metrics", {})
    unc = m.get("uncertainty", {})
    decomp = m.get("decomposition", {})
    sc = m.get("self_correction", {})
    rag_gain = None
    if t5r_norag and t5r_rag and t5r_norag.get("overall_accuracy") \
            is not None and t5r_rag.get("overall_accuracy") is not None:
        rag_gain = round(100 * (t5r_rag["overall_accuracy"]
                                - t5r_norag["overall_accuracy"]), 2)
    citation_coverage = None
    if t5r_rag:
        citation_coverage = ((t5r_rag.get("citation") or {})
                             .get("coverage") or {}).get(
            "coverage_rate_all_questions")
    vector = {
        "label": label,
        "overall": m.get("overall"),
        "math": m.get("math_macro"),
        "science": m.get("science_macro"),
        "compositional": m.get("compositional"),
        "cross_domain": m.get("cross_domain"),
        "counterfactual": m.get("counterfactual"),
        "distractor": (m.get("distractor") or {}).get("distractor_accuracy"),
        "uncertainty": unc.get("insufficient_info_f1"),
        "decomposition": decomp.get("repaired_valid_rate"),
        "self_correction": sc.get("net_benefit"),
        "tool_routing": (t4_router or {}).get("invocation_precision"),
        "tool_use": t4_tool.get("overall_accuracy"),
        "tool_utilization": t4_tool.get("tool_call_rate"),
        "rag_gain": rag_gain,
        "citation_coverage": citation_coverage,
        "citation_integrity": _citation_integrity(t5r_rag),
        "extraction": t4_notool.get("extraction_rate"),
        "latency": _mean_latency(t4_notool, t4_tool),
        "peak_vram": peak_vram_mib,
    }
    return vector


def _citation_integrity(t5r_rag: dict | None) -> float | None:
    if t5r_rag is None:
        return None
    integ = ((t5r_rag.get("citation") or {}).get("integrity")
             or t5r_rag.get("citation_integrity") or {})
    if not integ:
        return None
    return 1.0 if integ.get("integrity_ok") else 0.0


def _mean_latency(t4_notool: dict, t4_tool: dict) -> float | None:
    vals = [t4_notool.get("mean_latency_s"),
            t4_tool.get("mean_latency_s")]
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def safety_checks(*, verifier_selftest: dict, t5r_integrity: dict | None,
                  self_correction: dict) -> dict:
    """T8S.3/T8S.5/T8S.7 gates that gate any promotion decision."""
    over = (self_correction or {}).get("overcorrection_rate")
    return {
        "t4_false_pass_zero": (
            (verifier_selftest or {}).get("false_pass_rate") == 0.0),
        "citation_integrity_ok": bool(
            t5r_integrity is None or t5r_integrity.get("integrity_ok")),
        "no_overcorrection_explosion": not (
            over is not None and over >= OVERCORRECTION_EXPLOSION_RATE),
    }


def decide_full_system(vec_a: dict, vec_b: dict, safety_b: dict) -> str:
    """Pre-registered decision rule (Decision B, full-system default).
    Promotion of weights is NEVER an outcome of T8S."""
    if not all(safety_b.values()):
        return "KEEP_MANGO_V0_1"
    d = dominates(vec_a, vec_b)  # result 'b' means B dominates A
    if d["result"] == "b":
        return "QWEN3_4B_SYSTEM_PROMOTION_CANDIDATE"
    # no dominance: adopt as experimental default only on a strict overall
    # win with no Pareto loss on any safety-relevant dimension
    if _strict_overall_win(vec_b, vec_a):
        return "USE_QWEN3_4B_EXPERIMENTAL"
    return "KEEP_MANGO_V0_1"


def _strict_overall_win(b: dict, a: dict) -> bool:
    """B overall strictly above A on the matched capacity denominator AND
    not worse on any Pareto dimension by more than 0.02 (tolerance for
    sampling noise on sampled capacity arms)."""
    if b.get("overall") is None or a.get("overall") is None:
        return False
    if float(b["overall"]) <= float(a["overall"]):
        return False
    for d, higher_better in PARETO_DIMENSIONS.items():
        vb, va = b.get(d), a.get(d)
        if vb is None or va is None:
            continue
        diff = (float(va) - float(vb)) if higher_better \
            else (float(vb) - float(va))
        if diff > 0.02:
            return False
    return True


def decide_hybrid(vec_a: dict, vec_b: dict, *, tested: bool,
                  hybrid_metrics: dict | None = None) -> str:
    """T8S.11/T8S.13 Decision C. NOT_TESTED unless complementarity is
    demonstrated; PROMISING/REJECTED only from a measured experiment."""
    if not tested:
        # even clear complementarity does NOT authorise a verdict without
        # a measured hybrid arm - hybrid stays NOT_TESTED
        return "NOT_TESTED"
    # measured hybrid arm: better than the best single system?
    best_single = max(float(vec_a.get("overall") or 0),
                      float(vec_b.get("overall") or 0))
    h = (hybrid_metrics or {}).get("overall")
    if h is None:
        return "REJECTED"
    return "PROMISING" if float(h) > best_single else "REJECTED"
