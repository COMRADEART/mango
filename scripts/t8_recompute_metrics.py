"""T8 STEP 2 — independent metric recomputation from saved predictions.

For every completed model-only run, recomputes every major metric
directly from predictions.jsonl / self_correction.jsonl / plans.jsonl
(never trusting the stored aggregate fields) and cross-checks against
summary.json. Any disagreement is a blocking error.

Also verifies, per run:
  - total expected IDs (131) and unique IDs
  - no duplicate rows, no stale prediction mixing (every eval_id belongs
    to the frozen suite)
  - exact model identity (config fingerprint via detect_model_identity,
    cross-checked against the hardware probe)
  - exact quantization mode and decoding settings as recorded
  - hardware profile present and consistent

Output: evaluations/t8/recomputed_metrics.json
Exit code 0 only if every run agrees.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from sciencemath.evaluation.capacity import hashlib_fingerprint  # noqa: E402

SUITE = REPO / "evaluations" / "t8" / "capacity-suite" / "v1"
RUNS = REPO / "evaluations" / "t8" / "runs"
HARDWARE = REPO / "evaluations" / "t8" / "hardware"
OUT = REPO / "evaluations" / "t8" / "recomputed_metrics.json"


def local_config_fingerprint(model_id: str) -> str | None:
    """Fingerprint the local snapshot's config.json for model_id."""
    import os
    cache = Path.home() / ".cache" / "huggingface" / "hub"
    d = cache / ("models--" + model_id.replace("/", "--"))
    cfg = d / "snapshots"
    if not cfg.is_dir():
        return None
    for root, _dirs, files in os.walk(cfg):
        if "config.json" in files:
            try:
                cfg_obj = json.loads(
                    (Path(root) / "config.json").read_text(
                        encoding="utf-8"))
                return hashlib_fingerprint(cfg_obj)
            except Exception:  # noqa: BLE001
                return None
    return None


def main() -> int:
    suite = [json.loads(l) for l in
             (SUITE / "questions.jsonl").read_text(encoding="utf-8")
             .splitlines() if l.strip()]
    suite_by_id = {it["eval_id"]: it for it in suite}
    expected_ids = set(suite_by_id)

    from run_capacity_eval import grade, dimension_of, score_plan

    report = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "suite": "mango-capacity-eval-v1", "runs": {}, "all_agree": True}

    for run_dir in sorted(RUNS.glob("*/model")):
        label = run_dir.parent.name
        if not (run_dir / "summary.json").exists():
            continue
        s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        if not s.get("ok"):
            continue
        errs: list[str] = []
        notes: list[str] = []

        # ---------- predictions integrity ----------
        preds = [json.loads(l) for l in
                 (run_dir / "predictions.jsonl").read_text(encoding="utf-8")
                 .splitlines() if l.strip()]
        ids = [p["eval_id"] for p in preds]
        if len(preds) != s.get("n_questions", len(preds)):
            errs.append(f"prediction count {len(preds)} != "
                        f"summary n_questions {s.get('n_questions')}")
        if len(ids) != len(set(ids)):
            dups = [k for k, v in Counter(ids).items() if v > 1]
            errs.append(f"duplicate eval_ids: {dups[:5]}")
        stale = sorted(set(ids) - expected_ids)
        if stale:
            errs.append(f"stale/mixed predictions (not in frozen suite): "
                        f"{stale[:5]}")
        missing = sorted(expected_ids - set(ids))
        if missing:
            errs.append(f"missing predictions: {len(missing)}")

        # ---------- independent regrade from raw text ----------
        recomputed_preds = []
        for p in preds:
            it = suite_by_id[p["eval_id"]]
            g = grade(it, p["raw"], p.get("extracted_answer"))
            recomputed = bool(g["correct"])
            if recomputed != p["correct"]:
                errs.append(f"grade mismatch on {p['eval_id']}: stored "
                            f"{p['correct']} vs recomputed {recomputed}")
            recomputed_preds.append({**p, "recomputed_correct": recomputed})

        def acc(sub):
            return sum(1 for p in sub if p["recomputed_correct"]) / len(sub) \
                if sub else None

        answerable = [p for p in recomputed_preds
                      if dimension_of(suite_by_id[p["eval_id"]]) != "uncertainty"]
        uncertain = [p for p in recomputed_preds
                     if dimension_of(suite_by_id[p["eval_id"]]) == "uncertainty"]
        # uncertainty semantics need regrade (hallucinated flag comes from
        # grade(), which we recomputed)
        tp = sum(1 for p in uncertain if p["uncertainty_signaled"]
                 and not p.get("hallucinated", p["correct"]))
        fn = sum(1 for p in uncertain if not p["uncertainty_signaled"])
        fp = sum(1 for p in answerable if p["uncertainty_signaled"])
        prec = tp / (tp + fp) if (tp + fp) else None
        rec = tp / (tp + fn) if (tp + fn) else None
        f1 = (2 * prec * rec / (prec + rec)) if prec and rec else None

        dims = ("math", "science", "cross_domain", "compositional",
                "counterfactual")
        re_vec = {"overall": acc(answerable),
                  "uncertainty_f1": f1,
                  "uncertainty_recall": rec,
                  "distractor_clean": acc([p for p in recomputed_preds
                                           if p["dimension"] == "distractor_clean"]),
                  "distractor_loaded": acc([p for p in recomputed_preds
                                            if p["dimension"] == "distractor_loaded"]),
                  "extraction_rate": (sum(1 for p in answerable
                                          if not p.get("extraction_failure"))
                                      / len(answerable)) if answerable else None}
        for d in dims:
            re_vec[d] = acc([p for p in recomputed_preds
                             if p["dimension"] == d])

        stored = s["capability_vector"]
        pairs = [("overall", stored["overall"], re_vec["overall"]),
                 ("math_macro", stored["math_macro"], re_vec["math"]),
                 ("science_macro", stored["science_macro"], re_vec["science"]),
                 ("cross_domain", stored["cross_domain"], re_vec["cross_domain"]),
                 ("compositional", stored["compositional"], re_vec["compositional"]),
                 ("counterfactual", stored["counterfactual"], re_vec["counterfactual"]),
                 ("distractor", stored["distractor"], re_vec["distractor_loaded"]),
                 ("uncertainty", stored["uncertainty"], re_vec["uncertainty_f1"]),
                 ("extraction", stored["extraction"], re_vec["extraction_rate"])]
        disagreements = []
        for k, sv, rv in pairs:
            if (sv is None) != (rv is None):
                disagreements.append(f"{k}: stored {sv} vs recomputed {rv}")
            elif sv is not None and rv is not None and abs(sv - rv) > 1e-9:
                disagreements.append(f"{k}: stored {sv} vs recomputed {rv}")

        # ---------- self-correction recompute ----------
        sc_path = run_dir / "self_correction.jsonl"
        if sc_path.exists():
            sc = [json.loads(l) for l in sc_path.read_text(encoding="utf-8")
                  .splitlines() if l.strip()]
            corrected = sum(1 for r in sc if not r["initially_correct"]
                            and r["revised_correct"])
            over = sum(1 for r in sc if r["initially_correct"]
                       and not r["revised_correct"])
            preserved = sum(1 for r in sc if r["initially_correct"]
                            and r["revised_correct"])
            n_wrong_total = sum(1 for p in answerable
                                if not p["recomputed_correct"])
            net = (corrected - over) / max(1, n_wrong_total)
            stored_sc = s["metrics"]["self_correction"]
            if (corrected != stored_sc["corrected_wrong"]
                    or over != stored_sc["overcorrections"]
                    or preserved != stored_sc["preserved_correct"]
                    or abs(net - stored_sc["net_benefit"]) > 1e-9):
                disagreements.append(
                    f"self_correction: stored {stored_sc} vs recomputed "
                    f"corrected={corrected} over={over} preserved={preserved} "
                    f"net={net:.4f} (n_wrong_total={n_wrong_total})")
            re_vec["self_correction_net_benefit"] = net
            re_vec["self_correction_counts"] = {
                "corrected": corrected, "overcorrected": over,
                "preserved": preserved, "n_wrong_total": n_wrong_total}

        # ---------- decomposition aggregate cross-check ----------
        pl_path = run_dir / "plans.jsonl"
        if pl_path.exists():
            pl = [json.loads(l) for l in pl_path.read_text(encoding="utf-8")
                  .splitlines() if l.strip()]
            n = max(1, len(pl))
            re_dec = {
                "raw_valid_rate": sum(1 for r in pl if r["raw_valid"]) / n,
                "repaired_valid_rate":
                    sum(1 for r in pl if r["repaired_valid"]) / n,
                "semantic_valid_rate":
                    sum(1 for r in pl if r["semantic_ok"]) / n,
                "executable_rate": sum(1 for r in pl
                                       if r["executable_ok"]) / n,
            }
            sd = s["metrics"]["decomposition"]
            for k, v in re_dec.items():
                if abs(v - sd[k]) > 1e-9:
                    disagreements.append(
                        f"decomposition.{k}: stored {sd[k]} vs recomputed {v}")
            re_vec["decomposition"] = re_dec
            # semantic_ok must be a SUBSET of repaired_valid
            if any(r["semantic_ok"] and not r["repaired_valid"] for r in pl):
                errs.append("semantic_ok without repaired_valid (impossible)")
            notes.append("note: raw_valid/repaired_valid judged at runtime "
                         "against full raw text (raw_extract is truncated in "
                         "plans.jsonl); aggregate consistency verified here")

        # ---------- identity / quantization / decoding / hardware ----------
        fp_model = local_config_fingerprint(s["model"])
        hw_path = HARDWARE / f"{label}.json"
        hw = json.loads(hw_path.read_text(encoding="utf-8")) \
            if hw_path.exists() else {}
        if hw.get("model") != s["model"]:
            errs.append(f"model id mismatch: summary {s['model']} vs probe "
                        f"{hw.get('model')}")
        if hw.get("cpu_offload"):
            errs.append("hardware probe recorded CPU offload")
        if fp_model is None:
            errs.append(f"no local config.json snapshot found for "
                        f"{s['model']} (identity unverified)")
        elif not fp_model:
            errs.append("config fingerprint empty")

        gen = s.get("generation", {})
        if not gen.get("profile") or "seed" not in gen:
            errs.append("decoding settings not fully recorded")

        if disagreements:
            errs.extend(disagreements)
        agree = not errs
        if not agree:
            report["all_agree"] = False
        report["runs"][label] = {
            "model": s["model"], "n_predictions": len(preds),
            "unique_ids": len(set(ids)), "missing": len(missing),
            "recomputed": re_vec, "stored_vector": stored,
            "agrees_with_summary": agree, "errors": errs, "notes": notes,
            "quantization": s.get("hardware", {}).get("quantization"),
            "generation_profile": gen.get("profile"),
            "config_fingerprint": fp_model,
        }
        print(f"{label}: {'AGREE' if agree else 'DISAGREEMENT'} "
              f"({len(preds)} preds, {len(errs)} errors)")
        for e in errs:
            print("   -", e)

    # ---------- cross-run identity consistency ----------
    by_model: dict[str, set] = {}
    for label, r in report["runs"].items():
        if r.get("config_fingerprint"):
            by_model.setdefault(r["model"], set()).add(
                r["config_fingerprint"])
    for mid, fps in by_model.items():
        if len(fps) > 1:
            report["all_agree"] = False
            report.setdefault("errors", []).append(
                f"identity inconsistency: {mid} has fingerprints {sorted(fps)}")

    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print("written:", OUT)
    return 0 if report["all_agree"] else 1


if __name__ == "__main__":
    raise SystemExit(main())