"""T8S.2-T8S.13 finalize - recomputes all T8S metrics from saved run
records, stamps reproducibility metadata (T8S.16), builds capability
vectors (T8S.9), Pareto analysis (T8S.10) and the three decisions
(T8S.13). Pure analysis: no model is loaded here.

Outputs (evaluations/t8s/):
  t4_head_to_head.json  t5r_head_to_head.json
  selfcorrection_uncertainty.json  system_capability_vectors.json
  pareto_analysis.json  DECISIONS.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

RUNS = REPO / "evaluations" / "t8s" / "runs"
OUT = REPO / "evaluations" / "t8s"

SYSTEMS = {
    "A": {"label": "Mango-v0.1", "dir": "mango-v0.1",
          "model": "Qwen/Qwen3-1.7B",
          "adapter": "training/adapters/sciencemath-v0.1-t3"},
    "B": {"label": "Qwen3-4B experimental", "dir": "qwen3-4b-system",
          "model": "Qwen/Qwen3-4B-Instruct-2507", "adapter": None},
}


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in
            p.read_text(encoding="utf-8").splitlines() if l.strip()]


def read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


# -- T8S.7 self-correction (Groups 1+2) ---------------------------------------
def selfcorrection_metrics(sc_rows: list[dict]) -> dict:
    """Group 1 = initially wrong + FAIL_WITH_RESULT (valid corrective
    evidence). Group 2 = initially correct + FAIL_ONLY probe (false FAIL
    feedback). Blind agreement and ignored evidence reported separately."""
    g1 = [r for r in sc_rows if not r["initially_correct"]]
    g2 = [r for r in sc_rows if r["initially_correct"]]
    g1_fixed = sum(1 for r in g1 if r["revised_correct"])
    g1_ignored = sum(1 for r in g1 if not r["changed"]
                     and not r["revised_correct"])
    g1_degraded = sum(1 for r in g1 if r["changed"]
                      and not r["revised_correct"])
    g1_still_wrong = sum(1 for r in g1 if not r["revised_correct"])
    g2_preserved = sum(1 for r in g2 if r["revised_correct"])
    g2_over = sum(1 for r in g2 if not r["revised_correct"])
    g2_changed = sum(1 for r in g2 if r["changed"])
    g2_blind = sum(1 for r in g2 if r["changed"] and not r["revised_correct"])
    out = {
        "group1_wrong_with_valid_evidence": {
            "n": len(g1),
            "correction_success": round(g1_fixed / len(g1), 4)
            if g1 else None,
            "ignored_valid_evidence": round(g1_ignored / len(g1), 4)
            if g1 else None,
            "unchanged_wrong": round(g1_ignored / len(g1), 4)
            if g1 else None,
            "degraded_further": round(g1_degraded / len(g1), 4)
            if g1 else None,
            "still_wrong": round(g1_still_wrong / len(g1), 4)
            if g1 else None,
        },
        "group2_correct_with_false_fail": {
            "n": len(g2),
            "correct_answer_preservation": round(g2_preserved / len(g2), 4)
            if g2 else None,
            "overcorrection": round(g2_over / len(g2), 4) if g2 else None,
            "blind_agreement_with_false_feedback": round(
                g2_blind / len(g2), 4) if g2 else None,
            "changed_answer_rate": round(g2_changed / len(g2), 4)
            if g2 else None,
        },
        "net_self_correction": round(
            (g1_fixed - g2_over) / max(1, len(g1)), 4) if g1 else None,
    }
    return out


# -- T8S.8 uncertainty (recomputed from capacity predictions) -----------------
def uncertainty_metrics(preds: list[dict]) -> dict:
    """Same frozen formulas as the T8 capacity runner, recomputed here
    independently from the per-question records."""
    uncertain = [p for p in preds if p["dimension"] == "uncertainty"]
    answerable = [p for p in preds if p["dimension"] != "uncertainty"]
    tp = sum(1 for p in uncertain if p["uncertainty_signaled"]
             and not p["hallucinated"])
    fn = sum(1 for p in uncertain if not p["uncertainty_signaled"])
    fp = sum(1 for p in answerable if p["uncertainty_signaled"])
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * prec * rec / (prec + rec)) if prec and rec else None
    halluc = sum(1 for p in uncertain if p["hallucinated"])
    return {
        "n_uncertainty_questions": len(uncertain),
        "precision": round(prec, 4) if prec is not None else None,
        "recall": round(rec, 4) if rec is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "hallucinated_answer_rate": round(halluc / len(uncertain), 4)
        if uncertain else None,
        "false_uncertainty_rate": round(fp / len(answerable), 4)
        if answerable else None,
    }


# -- reproducibility stamps (T8S.16) ------------------------------------------
def stamp_repro() -> list[str]:
    """Write repro_metadata.json into every T8S run dir and validate.
    Future-run rule: fail loudly when required metadata is missing."""
    from sciencemath.evaluation.repro import (ReproducibilityError,
                                              enrich_manifest)
    problems = []
    for sys_key, spec in SYSTEMS.items():
        d = RUNS / spec["dir"]
        if not d.exists():
            problems.append(f"missing run dir: {d}")
            continue
        sources = []
        t4 = d / "t4_arm_summary.json"
        if t4.exists():
            sources.append((t4, read_json(t4)))
        cap = d / "model" / "summary.json"
        if cap.exists():
            sources.append((cap, read_json(cap)))
        for path, summary in sources:
            generation = summary.get("generation") or {}
            try:
                meta = enrich_manifest(
                    {"run_artifact": str(path.relative_to(REPO)),
                     "adapter": spec["adapter"]},
                    model_id=summary.get("model") or spec["model"],
                    generation=generation, repo=REPO,
                    require_revision=True)
                (path.parent / "repro_metadata.json").write_text(
                    json.dumps(meta, indent=2, ensure_ascii=False),
                    encoding="utf-8")
            except ReproducibilityError as exc:
                problems.append(f"{path.parent.name}: {exc}")
    return problems



def _router_metrics(run_dir: str) -> dict | None:
    p = RUNS / run_dir / "t4_arm_summary.json"
    if not p.exists():
        return None
    return read_json(p).get("router_metrics")

def _system_metrics(sys_key: str) -> dict:
    from t8s_metrics import t4_arm_metrics, t5r_variant_metrics
    from sciencemath.tools.benchmark import load_suite
    suite_rows = load_suite(REPO / "evaluations" / "tool-suite" / "v1")
    spec = SYSTEMS[sys_key]
    d = RUNS / spec["dir"]
    out: dict = {"system": spec["label"], "dir": spec["dir"]}
    nt = d / "t4_notool" / "predictions.jsonl"
    tl = d / "t4_tool" / "predictions.jsonl"
    out["t4_notool"] = (t4_arm_metrics(nt, arm="no_tool",
                                       suite_rows=suite_rows)
                        if nt.exists() else {"arm": "no_tool", "n": 0})
    out["t4_tool"] = (t4_arm_metrics(tl, arm="tool",
                                     suite_rows=suite_rows)
                      if tl.exists() else {"arm": "tool", "n": 0})
    t5r_dir = d / "t5r"
    if (t5r_dir / "NORAG" / "predictions.jsonl").exists():
        out["t5r_norag"] = t5r_variant_metrics(
            t5r_dir / "NORAG" / "predictions.jsonl", variant="NORAG")
        out["t5r_rag"] = t5r_variant_metrics(
            t5r_dir / "G" / "predictions.jsonl", variant="G")
    cap = d / "model" / "summary.json"
    if cap.exists():
        out["capacity"] = read_json(cap)
    sc = d / "model" / "self_correction.jsonl"
    if sc.exists():
        out["selfcorrection"] = selfcorrection_metrics(read_jsonl(sc))
    preds = d / "model" / "predictions.jsonl"
    if preds.exists():
        out["uncertainty"] = uncertainty_metrics(read_jsonl(preds))
    return out


def main() -> int:
    A = _system_metrics("A")
    B = _system_metrics("B")

    # ---- T8S.2/T8S.3: matched T4 head-to-head ----
    t4_verifier = {s: read_json(RUNS / SYSTEMS[s]["dir"] /
                                "t4_arm_summary.json")["verifier_selftest"]
                   for s in SYSTEMS if (RUNS / SYSTEMS[s]["dir"] /
                                        "t4_arm_summary.json").exists()}
    critical_answer = None
    if A.get("t4_tool", {}).get("overall_accuracy") is not None \
            and B.get("t4_tool", {}).get("overall_accuracy") is not None:
        a2 = A["t4_tool"]["overall_accuracy"]
        b2 = B["t4_tool"]["overall_accuracy"]
        gain_b = B["t4_tool"].get("overall_accuracy", 0) - \
            B["t4_notool"].get("overall_accuracy", 0)
        gain_a = A["t4_tool"].get("overall_accuracy", 0) - \
            A["t4_notool"].get("overall_accuracy", 0)
        tool_gain_b = B["t4_tool"].get("overall_accuracy", 0) - \
            B["t4_notool"].get("overall_accuracy", 0)
        critical_answer = {
            "question": "Does T4 compensate for Qwen3-4B model-only math "
                        "regression enough to make the 4B complete system "
                        "better than Mango-v0.1?",
            "mango_v0_1_tool_accuracy": a2,
            "qwen3_4b_tool_accuracy": b2,
            "tool_gain_pp_mango": round(100 * gain_a, 2),
            "tool_gain_pp_qwen3_4b": round(100 * gain_b, 2),
            "complete_system_better": bool(b2 > a2),
            "math_recovery": {
                "question": "Does the frozen T4 layer recover enough of "
                            "Qwen3-4B's math deficit that the complete 4B "
                            "system meets or exceeds complete Mango-v0.1 "
                            "on the matched T4 arm?",
                "denominators_note": "T8 capacity math (131-q suite, "
                                     "model-only) and T8S T4 accuracy "
                                     "(150-q tool suite) are DIFFERENT "
                                     "denominators and are never combined",
                "answered_from": "T8S matched T4 arm only",
            },
        }
    t4_h2h = {
        "systems": {"A": A["t4_notool"] | {"label": A["system"],
                                           "tool_arm": A["t4_tool"]},
                    "B": B["t4_notool"] | {"label": B["system"],
                                           "tool_arm": B["t4_tool"]}},
        "verifier_safety": t4_verifier,
        "critical_t4_system_question": critical_answer,
    }
    (OUT / "t4_head_to_head.json").write_text(
        json.dumps(t4_h2h, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- T8S.4/T8S.5: matched T5R head-to-head ----
    t5r_h2h = {"A": {k: A[k] for k in ("t5r_norag", "t5r_rag")
                     if k in A},
               "B": {k: B[k] for k in ("t5r_norag", "t5r_rag")
                     if k in B}}
    (OUT / "t5r_head_to_head.json").write_text(
        json.dumps(t5r_h2h, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- T8S.7/T8S.8: self-correction + uncertainty ----
    sc_unc = {"A": {k: A[k] for k in ("selfcorrection", "uncertainty")
                    if k in A},
              "B": {k: B[k] for k in ("selfcorrection", "uncertainty")
                    if k in B}}
    (OUT / "selfcorrection_uncertainty.json").write_text(
        json.dumps(sc_unc, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- T8S.16 stamps (fail loudly) ----
    repro_problems = stamp_repro()

    # ---- T8S.9: capability vectors ----
    from t8s_vectors_pareto import (build_vector, decide_full_system,
                                    decide_hybrid, dominant_system,
                                    safety_checks)
    def _peak(m: dict, sys_key: str) -> float | None:
        vals = []
        s = read_json(RUNS / SYSTEMS[sys_key]["dir"] / "t4_arm_summary.json") \
            if (RUNS / SYSTEMS[sys_key]["dir"] / "t4_arm_summary.json").exists() \
            else {}
        if s.get("peak_vram_mib") is not None:
            vals.append(s["peak_vram_mib"])
        hw = (m.get("capacity") or {}).get("hardware") or {}
        if hw.get("peak_reserved_mib"):
            vals.append(hw["peak_reserved_mib"])
        return max(vals) if vals else None

    vec_a = build_vector(
        label="Mango-v0.1", capacity=A.get("capacity") or {"metrics": {}},
        t4_notool=A["t4_notool"], t4_tool=A["t4_tool"],
        t4_router=_router_metrics("mango-v0.1"),
        t5r_norag=A.get("t5r_norag"), t5r_rag=A.get("t5r_rag"),
        peak_vram_mib=_peak(A, "A"))
    vec_b = build_vector(
        label="Qwen3-4B", capacity=B.get("capacity") or {"metrics": {}},
        t4_notool=B["t4_notool"], t4_tool=B["t4_tool"],
        t4_router=_router_metrics("qwen3-4b-system"),
        t5r_norag=B.get("t5r_norag"), t5r_rag=B.get("t5r_rag"),
        peak_vram_mib=_peak(B, "B"))
    vectors = {
        "milestone": "T8S", "step": "T8S.9",
        "dimension_note": "raw dimensions; different evaluation "
                          "denominators are NOT merged into one score; "
                          "provenance: overall/math/science/compositional/"
                          "cross_domain/counterfactual/distractor/"
                          "uncertainty/decomposition/self_correction from "
                          "mango-capacity-eval-v1; tool_routing/tool_use/"
                          "extraction/latency/peak_vram from mango-tool-"
                          "eval-v1; rag_gain/citation_integrity from "
                          "mango-rag-eval-v1",
        "Mango-v0.1": vec_a,
        "Qwen3-4B": vec_b,
    }
    (OUT / "system_capability_vectors.json").write_text(
        json.dumps(vectors, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- T8S.10: Pareto ----
    pareto = {"milestone": "T8S", "step": "T8S.10",
              "dimensions": {"higher_is_better": ["math", "science",
                              "compositional", "cross_domain", "uncertainty",
                              "decomposition", "self_correction", "tool_use",
                              "rag_gain"],
                             "lower_is_better": ["latency", "peak_vram"]},
              "dominance": dominant_system(vec_a, vec_b)}
    (OUT / "pareto_analysis.json").write_text(
        json.dumps(pareto, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- T8S.13: decisions ----
    safety_b = safety_checks(
        verifier_selftest=t4_verifier.get("B"),
        t5r_integrity=(B.get("t5r_rag") or {}).get("citation_integrity"),
        self_correction={"overcorrection_rate":
                         ((B.get("selfcorrection") or {})
                          .get("group2_correct_with_false_fail") or {})
                         .get("overcorrection")})
    dec_b = decide_full_system(vec_a, vec_b, safety_b)
    hybrid_metrics = None
    decisions = {
        "milestone": "T8S", "step": "T8S.13",
        "decision_a_t8_model_migration": {
            "decision": "DO_NOT_MIGRATE",
            "note": "historical T8 decision is an input here, never "
                    "recomputed; T8 remains closed",
        },
        "decision_b_full_system_default": {
            "decision": dec_b,
            "rule": "unsafe->KEEP; B dominates->PROMOTION_CANDIDATE; "
                    "strict overall win without dominance->EXPERIMENTAL; "
                    "else KEEP",
            "safety_checks_b": safety_b,
        },
        "decision_c_hybrid": {
            "decision": decide_hybrid(vec_a, vec_b, tested=False),
            "note": "hybrid arm runs only if A and B show clearly "
                    "complementary strengths; experimental only",
        },
        "reproducibility_stamp_problems": repro_problems,
    }
    (OUT / "DECISIONS.json").write_text(
        json.dumps(decisions, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(json.dumps({"decision_b": dec_b, "dominance": pareto["dominance"],
                      "repro_problems": repro_problems}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
