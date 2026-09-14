"""T8S.9/T8S.10/T8S.13 - vectors, Pareto dominance and decision rules."""
import pytest

from sciencemath.evaluation.repro import REQUIRED_REPRO_FIELDS  # noqa: F401
from scripts.t8s_vectors_pareto import (
    PARETO_DIMENSIONS,
    build_vector,
    decide_full_system,
    decide_hybrid,
    dominant_system,
    dominates,
    safety_checks,
)


def _vec(label, **kw):
    base = dict(math=0.8, science=0.8, compositional=0.7, cross_domain=0.7,
                uncertainty=0.6, decomposition=0.6, self_correction=0.1,
                tool_use=0.5, rag_gain=2.0, latency=30.0, peak_vram=2600.0,
                overall=0.8)
    base.update(kw)
    return dict(label=label, **base)


def test_dominance_strict():
    a = _vec("a")
    b = _vec("b", math=0.7, latency=40.0)
    assert dominates(a, b)["result"] == "a"
    assert dominates(b, a)["result"] == "b"


def test_dominance_neither_and_tie():
    a = _vec("a", math=0.9, science=0.5)
    b = _vec("b", math=0.5, science=0.9)
    assert dominates(a, b)["result"] == "neither"
    assert dominates(a, dict(a))["result"] == "tie"


def test_dominance_skips_missing_dimensions():
    a = _vec("a")
    b = {k: v for k, v in _vec("b").items()
         if k not in ("latency", "peak_vram")}
    r = dominates(a, b)
    assert r["result"] == "tie"  # all comparable dimensions equal
    assert set(r["missing_dimensions"]) == {"latency", "peak_vram"}
    # b Pareto-dominated when it only loses (missing dims are skipped)
    a2 = _vec("a", latency=30.0)
    b2 = {k: v for k, v in a2.items() if k != "peak_vram"}
    b2["latency"] = 40.0
    assert dominates(a2, b2)["result"] == "a"


def test_dominant_system_labels():
    a = _vec("A", math=0.9)
    b = _vec("B")
    out = dominant_system(a, b)
    assert out["dominant"] == "Mango-v0.1"


def test_build_vector_provenance_and_raw_dims():
    capacity = {"metrics": {
        "overall": 0.815, "math_macro": 0.862, "science_macro": 0.8,
        "compositional": 0.75, "cross_domain": 0.7, "counterfactual": 0.65,
        "distractor": {"distractor_accuracy": 0.72},
        "uncertainty": {"insufficient_info_f1": 0.66},
        "decomposition": {"repaired_valid_rate": 0.5},
        "self_correction": {"net_benefit": 0.05},
    }}
    t4_notool = {"overall_accuracy": 0.6, "extraction_rate": 0.98,
                 "mean_latency_s": 20.0}
    t4_tool = {"overall_accuracy": 0.7, "mean_latency_s": 30.0,
               "tool_call_rate": 0.8}
    t5r_norag = {"overall_accuracy": 0.5}
    t5r_rag = {"overall_accuracy": 0.55,
               "tool_call_rate": 0.8,
               "citation": {"coverage": {
                   "coverage_rate_all_questions": 0.25},
                   "integrity": {"integrity_ok": True,
                                 "accepted_fabricated": 0}}}
    v = build_vector(label="A", capacity=capacity, t4_notool=t4_notool,
                     t4_tool=t4_tool, t4_router={"invocation_precision": 0.88},
                     t5r_norag=t5r_norag, t5r_rag=t5r_rag,
                     peak_vram_mib=2600.0)
    assert v["overall"] == 0.815 and v["math"] == 0.862
    assert v["tool_use"] == 0.7 and v["tool_routing"] == 0.88
    assert v["rag_gain"] == 5.0
    assert v["citation_integrity"] == 1.0
    assert v["citation_coverage"] == 0.25
    assert v["tool_utilization"] == 0.8  # from t4_tool.tool_call_rate
    assert v["latency"] == 25.0 and v["peak_vram"] == 2600.0
    # raw dimensions must never be merged into a single score
    assert set(PARETO_DIMENSIONS) <= set(v)


def test_safety_checks():
    ok = safety_checks(verifier_selftest={"false_pass_rate": 0.0},
                       t5r_integrity={"integrity_ok": True},
                       self_correction={"overcorrection_rate": 0.1})
    assert all(ok.values())
    bad = safety_checks(verifier_selftest={"false_pass_rate": 0.01},
                        t5r_integrity={"integrity_ok": False},
                        self_correction={"overcorrection_rate": 0.9})
    assert not any(bad.values())


def test_decision_b_rules():
    a = _vec("A")
    safe = {"t4_false_pass_zero": True, "citation_integrity_ok": True,
            "no_overcorrection_explosion": True}
    unsafe = {**safe, "t4_false_pass_zero": False}
    # unsafe system B can never be adopted
    assert decide_full_system(a, _vec("B", overall=0.99), unsafe) == \
        "KEEP_MANGO_V0_1"
    # B dominates -> promotion candidate (not promotion)
    b_dom = _vec("B", overall=0.85, math=0.9, science=0.9,
                 compositional=0.8, cross_domain=0.8, uncertainty=0.7,
                 decomposition=0.7, self_correction=0.2, tool_use=0.6,
                 rag_gain=3.0, latency=25.0, peak_vram=2500.0)
    assert decide_full_system(a, b_dom, safe) == \
        "QWEN3_4B_SYSTEM_PROMOTION_CANDIDATE"
    # strict overall win without dominance -> experimental default
    # (tiny latency loss stays under the 0.02 noise tolerance -> no
    # dominance, but no blocked loss either)
    b_win = _vec("B", overall=0.83, latency=30.01)
    assert decide_full_system(a, b_win, safe) == "USE_QWEN3_4B_EXPERIMENTAL"
    # no overall win -> keep production
    assert decide_full_system(a, _vec("B"), safe) == "KEEP_MANGO_V0_1"


def test_strict_overall_win_tolerance_blocks_pareto_losses():
    a = _vec("A")
    b = _vec("B", overall=0.83, math=0.74)  # math loss > 0.02 tolerance
    assert decide_full_system(a, b, {k: True for k in
                                     ("t4_false_pass_zero",
                                      "citation_integrity_ok",
                                      "no_overcorrection_explosion")}) \
        == "KEEP_MANGO_V0_1"


def test_decision_c_hybrid():
    a = _vec("A", math=0.9, science=0.7)
    b = _vec("B", math=0.7, science=0.9)
    # complementary evidence alone never yields a tested verdict
    assert decide_hybrid(a, b, tested=False) == "NOT_TESTED"
    assert decide_hybrid(a, _vec("B"), tested=False) == "NOT_TESTED"
    # measured hybrid better than best single system
    assert decide_hybrid(a, b, tested=True,
                         hybrid_metrics={"overall": 0.85}) == "PROMISING"
    assert decide_hybrid(a, b, tested=True,
                         hybrid_metrics={"overall": 0.79}) == "REJECTED"
    assert decide_hybrid(a, b, tested=True,
                         hybrid_metrics={}) == "REJECTED"
