"""T8 — capacity-study scoring, gating, and selection logic.

Pure, deterministic functions used by the T8 runner/build scripts and
covered directly by tests/test_t8_capacity.py:

  license_gate / validate_candidate_manifest   (T8.3)
  validate_capability_vector                   (T8.12)
  pareto_front / pareto_rank                   (T8.13)
  score_uncertainty / score_distractor /
  score_self_correction / score_decomposition  (T8.8-T8.11)
  migration_decision                           (T8.18)
  promotion_check                              (T8.25)
  sft_answer_work_agreement                    (T8.21)
  detect_model_identity / detect_adapter_identity (T8.29)
  hardware_profile                             (T8.26)
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

CAPACITY_DIMENSIONS = (
    "overall", "math_macro", "science_macro", "cross_domain",
    "compositional", "counterfactual", "distractor", "uncertainty",
    "decomposition", "self_correction", "tool_routing",
    "retrieval_routing", "extraction",
)

LICENSE_STATUSES = ("APPROVED", "REVIEW_REQUIRED", "BLOCKED")

# permissive licenses that clear the training-base gate outright
PERMISSIVE = {"apache-2.0", "mit", "bsd-3-clause", "bsd-2-clause",
              "cc0-1.0", "cc-by-4.0"}


# -- T8.3 license gate --------------------------------------------------------
def license_gate(entry: dict) -> tuple[str, str]:
    """Deny-by-default candidate gate. Returns (status, reason)."""
    lic = (entry.get("license") or "").strip().lower()
    if not entry.get("license_verified"):
        return ("REVIEW_REQUIRED",
                f"license {lic or '<missing>'!r} not verified against the "
                "live model card")
    if entry.get("license_status") == "BLOCKED":
        return ("BLOCKED", "recorded as blocked during verification")
    if lic in PERMISSIVE:
        if entry.get("allows_training_use") is False:
            return ("BLOCKED", f"license {lic} but training use denied")
        if entry.get("allows_training_use") is None:
            return ("REVIEW_REQUIRED",
                    "permissive license but training-use right unconfirmed")
        return ("APPROVED", f"{lic}: training + redistribution verified")
    return ("REVIEW_REQUIRED",
            f"custom/nonstandard license {lic!r} requires explicit review")


def validate_candidate_manifest(entries: list[dict]) -> list[str]:
    errors: list[str] = []
    ids = [e.get("model_id") for e in entries]
    if len(ids) != len(set(ids)):
        errors.append("duplicate model_id entries")
    if len(entries) < 4:
        errors.append("manifest must contain >= 4 candidates "
                      "(control + >= 3 serious candidates)")
    if "Qwen/Qwen3-1.7B" not in ids:
        errors.append("control candidate Qwen/Qwen3-1.7B missing")
    for e in entries:
        mid = e.get("model_id", "?")
        for f in ("model_id", "revision", "params_b", "license",
                  "license_verified", "context_length", "checked_on"):
            if f not in e:
                errors.append(f"{mid}: missing manifest field {f}")
        status, _ = license_gate(e)
        if status not in LICENSE_STATUSES:
            errors.append(f"{mid}: invalid gate status {status!r}")
    return errors


# -- T8.12 capability vector --------------------------------------------------
# self_correction is a NET benefit (corrected-minus-overcorrected)/n_wrong,
# so it legitimately ranges [-1, +1]; every other dimension is a rate in
# [0, 1].
SIGNED_DIMENSIONS = ("self_correction",)


def validate_capability_vector(vec: dict) -> list[str]:
    errors = []
    for d in CAPACITY_DIMENSIONS:
        if d not in vec:
            errors.append(f"missing dimension {d}")
            continue
        v = vec[d]
        if v is None:
            continue
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            errors.append(f"{d} must be numeric or null")
        elif d in SIGNED_DIMENSIONS and not (-1.0 <= float(v) <= 1.0):
            errors.append(f"{d} out of [-1,1]: {v}")
        elif d not in SIGNED_DIMENSIONS and not (0.0 <= float(v) <= 1.0):
            errors.append(f"{d} out of [0,1]: {v}")
    return errors


# -- T8.13 Pareto -------------------------------------------------------------
def _dims(vec: dict) -> list[float]:
    return [float(vec.get(d) or 0.0) for d in CAPACITY_DIMENSIONS]


def dominates(a: dict, b: dict) -> bool:
    """a dominates b: a >= b on every dimension and > on at least one."""
    da, db = _dims(a), _dims(b)
    return all(x >= y for x, y in zip(da, db)) and any(
        x > y for x, y in zip(da, db))


def pareto_front(vectors: dict[str, dict]) -> list[str]:
    """Labels on the Pareto front (no other candidate dominates them)."""
    front = []
    for label, vec in vectors.items():
        if any(dominates(other, vec) for other in vectors.values()
               if other is not vec):
            continue
        front.append(label)
    return sorted(front)


def pareto_rank(vectors: dict[str, dict]) -> list[str]:
    """Repeatedly strip the front; deterministic order."""
    remaining = dict(vectors)
    order: list[str] = []
    while remaining:
        front = pareto_front(remaining)
        if not front:  # safety (mutual domination)
            front = sorted(remaining)
        order.extend(front)
        for f in front:
            remaining.pop(f)
    return order


# -- T8.9 uncertainty ---------------------------------------------------------
def score_uncertainty(uncertain_preds: list[dict],
                      answerable_preds: list[dict]) -> dict:
    tp = sum(1 for p in uncertain_preds
             if p["uncertainty_signaled"] and not p["hallucinated"])
    fn = sum(1 for p in uncertain_preds if not p["uncertainty_signaled"])
    fp = sum(1 for p in answerable_preds if p["uncertainty_signaled"])
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * prec * rec / (prec + rec)) if prec and rec else None
    halluc = sum(1 for p in uncertain_preds if p["hallucinated"])
    return {
        "insufficient_info_precision": prec,
        "insufficient_info_recall": rec,
        "insufficient_info_f1": f1,
        "false_uncertainty_count": fp,
        "false_uncertainty_rate": fp / len(answerable_preds)
        if answerable_preds else None,
        "hallucinated_answer_rate": halluc / len(uncertain_preds)
        if uncertain_preds else None,
    }


# -- T8.10 distractor ---------------------------------------------------------
def score_distractor(clean_acc: float | None,
                     loaded_acc: float | None) -> dict:
    delta = ratio = None
    if clean_acc is not None and loaded_acc is not None:
        delta = loaded_acc - clean_acc
        ratio = loaded_acc / clean_acc if clean_acc > 0 else None
    return {"clean_accuracy": clean_acc, "distractor_accuracy": loaded_acc,
            "robustness_delta": delta, "robustness_ratio": ratio}


# -- T8.11 self-correction ----------------------------------------------------
def score_self_correction(records: list[dict]) -> dict:
    corrected = sum(1 for r in records if not r["initially_correct"]
                    and r["revised_correct"])
    preserved = sum(1 for r in records if r["initially_correct"]
                    and r["revised_correct"])
    over = sum(1 for r in records if r["initially_correct"]
               and not r["revised_correct"])
    still = sum(1 for r in records if not r["initially_correct"]
                and not r["revised_correct"])
    n_wrong = max(1, sum(1 for r in records if not r["initially_correct"]))
    return {"corrected_wrong": corrected, "still_wrong": still,
            "preserved_correct": preserved, "overcorrections": over,
            "n_wrong_probed": n_wrong,
            "n_correct_probed": sum(1 for r in records
                                    if r["initially_correct"]),
            "net_benefit": (corrected - over) / n_wrong}


# -- T8.8 decomposition -------------------------------------------------------
def score_decomposition(plan_records: list[dict],
                        spontaneous_count: int = 0,
                        main_count: int = 0) -> dict:
    n = max(1, len(plan_records))
    return {
        "subset": len(plan_records),
        "raw_valid_rate": sum(1 for r in plan_records
                              if r["raw_valid"]) / n,
        "repaired_valid_rate": sum(1 for r in plan_records
                                   if r["repaired_valid"]) / n,
        "semantic_valid_rate": sum(1 for r in plan_records
                                   if r["semantic_ok"]) / n,
        "executable_rate": sum(1 for r in plan_records
                               if r["executable_ok"]) / n,
        "unnecessary_plan_rate": (spontaneous_count / main_count
                                  if main_count else 0.0),
    }


# -- T8.18 migration decision --------------------------------------------------
# pre-registered T8.14 win condition: improvement on several capacity-limited
# dimensions without major math/science regression
CAPACITY_DIMS = ("compositional", "cross_domain", "counterfactual",
                 "decomposition", "uncertainty", "distractor",
                 "self_correction")
GUARD_DIMS = ("math_macro", "science_macro")
REGRESSION_TOLERANCE = 0.05       # ≤5 pp drop counts as "no major regression"
WIN_DIMS_REQUIRED = 3
MIN_OVERALL_GAIN = 0.03


def _pair_metrics(cand: dict, control: dict) -> dict:
    gains = {d: (cand.get(d) or 0.0) - (control.get(d) or 0.0)
             for d in CAPACITY_DIMS}
    guards = {d: (cand.get(d) or 0.0) - (control.get(d) or 0.0)
              for d in GUARD_DIMS}
    wins = sum(1 for v in gains.values() if v > 0.02)
    return {"dimension_gains": gains, "guard_deltas": guards,
            "capacity_wins": wins,
            "overall_delta": ((cand.get("overall") or 0.0)
                              - (control.get("overall") or 0.0))}


def migration_decision(cand: dict, control: dict, *,
                       license_status: str = "APPROVED",
                       fits_vram: bool = True,
                       training_feasible: bool | None = None) -> tuple[str, str]:
    """MIGRATE / DO_NOT_MIGRATE / CONDITIONAL per T8.14/T8.18."""
    m = _pair_metrics(cand, control)
    reason = (f"overall delta {m['overall_delta']:+.3f}, "
              f"{m['capacity_wins']} capacity dimensions improved")
    if license_status == "BLOCKED":
        return "DO_NOT_MIGRATE", f"license BLOCKED; {reason}"
    if not fits_vram:
        return "CONDITIONAL", f"does not fit local VRAM; {reason}"
    if any(v < -REGRESSION_TOLERANCE for v in m["guard_deltas"].values()):
        return "DO_NOT_MIGRATE", (
            f"major math/science regression "
            f"{ {k: round(v, 3) for k, v in m['guard_deltas'].items()} }; "
            f"{reason}")
    if (m["capacity_wins"] >= WIN_DIMS_REQUIRED
            and m["overall_delta"] >= MIN_OVERALL_GAIN):
        if license_status != "APPROVED":
            return ("CONDITIONAL",
                    f"capacity win holds but license {license_status}; "
                    f"{reason}")
        if training_feasible is False:
            return ("CONDITIONAL",
                    f"capacity win holds but local QLoRA infeasible — "
                    f"needs approved alternate training environment; {reason}")
        return "MIGRATE", f"capacity win condition met; {reason}"
    return "DO_NOT_MIGRATE", (
        f"insufficient balanced improvement "
        f"({m['capacity_wins']}<{WIN_DIMS_REQUIRED} dims or overall delta "
        f"{m['overall_delta']:+.3f}<{MIN_OVERALL_GAIN:+.3f}); {reason}")


# -- T8.25 promotion gates ------------------------------------------------------
PRESERVE_DIMS = ("math_macro", "science_macro")
IMPROVE_DIMS = ("compositional", "cross_domain", "decomposition",
                "distractor", "uncertainty", "self_correction")
MIN_IMPROVE = 3


def promotion_check(v02: dict, v01: dict, *, t4_false_pass: int,
                    t5_fabricated: int) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if t4_false_pass != 0:
        reasons.append(f"T4 false-PASS safety violated ({t4_false_pass})")
    if t5_fabricated != 0:
        reasons.append(f"T5R citation integrity violated "
                       f"({t5_fabricated} fabricated)")
    for d in PRESERVE_DIMS:
        if (v02.get(d) or 0.0) < (v01.get(d) or 0.0) - REGRESSION_TOLERANCE:
            reasons.append(f"{d} regressed beyond tolerance")
    improved = sum(1 for d in IMPROVE_DIMS
                   if (v02.get(d) or 0.0) > (v01.get(d) or 0.0) + 0.02)
    if improved < MIN_IMPROVE:
        reasons.append(f"only {improved} weak dimensions improved "
                       f"(need {MIN_IMPROVE})")
    return (not reasons), reasons


# -- T8.21 SFT answer/work agreement --------------------------------------------
_BOXED = re.compile(r"\\boxed\{([^{}]+)\}")
_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")
_NUMBER_WORDS = re.compile(
    r"(?:final answer|answer)(?:\s+is|\s*[:=])\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE)
_EQUALITY = re.compile(r"=\s*(-?\d+(?:\.\d+)?)(?!\d)")


def sft_answer_work_agreement(example: dict) -> list[str]:
    """Detect 'reasoning answer != final answer' for quantitative examples
    (the T6 defect that must never repeat). Checks (a) prose 'answer is X'
    statements and (b) the LAST shown-work equality result — both must
    agree with the boxed final answer."""
    errors: list[str] = []
    work = example.get("response") or example.get("completion") or ""
    if not work.strip():
        return ["empty response"]
    boxed = _BOXED.findall(work)
    if not boxed:
        errors.append("no \\boxed{} final answer found in response")
        return errors
    final = boxed[-1].strip()
    if not _NUM.match(final):
        return errors          # non-numeric finals are not checkable here
    fv = float(final)
    stripped = _BOXED.sub("", work)
    checks: list[tuple[str, float]] = []
    m_last = _NUMBER_WORDS.search(stripped)
    if m_last:
        checks.append(("prose answer", float(m_last.group(1))))
    eqs = _EQUALITY.findall(stripped)
    if eqs:
        checks.append(("last shown-work result", float(eqs[-1])))
    for label, val in checks:
        if not math.isclose(val, fv, rel_tol=1e-9, abs_tol=1e-9):
            errors.append(
                f"{label} {val} disagrees with boxed {final}")
    return errors


# -- T8.29 identity detection ----------------------------------------------------
def detect_model_identity(config_path: str | Path,
                          declared_model_id: str,
                          expected_fingerprint: str | None = None
                          ) -> tuple[bool, str]:
    """Verify a loaded/local model's config actually belongs to the declared
    base (guards against silently evaluating the wrong model)."""
    try:
        cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, f"config unreadable: {exc}"
    for key in ("model_type", "hidden_size", "num_hidden_layers"):
        if key not in cfg:
            return False, f"config missing {key}"
    # deterministic fingerprints recorded per candidate in the manifest
    fp = hashlib_fingerprint(cfg)
    if expected_fingerprint and fp != expected_fingerprint:
        return False, (f"identity mismatch for {declared_model_id}: "
                       f"fp={fp} expected={expected_fingerprint}")
    return True, (f"model_type={cfg['model_type']} "
                  f"hidden={cfg['hidden_size']} "
                  f"layers={cfg['num_hidden_layers']} fp={fp}")


def hashlib_fingerprint(cfg: dict) -> str:
    import hashlib
    blob = json.dumps({k: cfg.get(k) for k in
                       ("model_type", "hidden_size", "num_hidden_layers",
                        "num_attention_heads", "vocab_size")},
                      sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def detect_adapter_identity(adapter_dir: str | Path) -> tuple[bool, str]:
    """Check an adapter directory declares its base model and carries
    weights — Mango adapter identity check."""
    d = Path(adapter_dir)
    cfg_p = d / "adapter_config.json"
    w_p = d / "adapter_model.safetensors"
    if not cfg_p.exists():
        return False, "adapter_config.json missing"
    try:
        cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, f"adapter_config unreadable: {exc}"
    base = cfg.get("base_model_name_or_path")
    if not base:
        return False, "base_model_name_or_path missing"
    if not w_p.exists():
        return False, "adapter weights missing"
    return True, f"base={base} weights=present"


# -- T8.26 hardware profile ------------------------------------------------------
def hardware_profile(load_vram_bytes: int | None, peak_vram_bytes: int | None,
                     total_vram_bytes: int, *, cpu_offload: bool,
                     tokens_per_s: float | None = None,
                     disk_size_gb: float | None = None) -> dict:
    """Record a per-candidate hardware profile and flag VRAM overrun."""
    total = float(total_vram_bytes)
    peak = float(peak_vram_bytes or 0)
    headroom = total - peak
    return {
        "load_vram_mib": round(load_vram_bytes / 2**20, 1)
        if load_vram_bytes else None,
        "peak_vram_mib": round(peak / 2**20, 1) if peak_vram_bytes else None,
        "total_vram_mib": round(total / 2**20, 1),
        "headroom_mib": round(headroom / 2**20, 1),
        "fits_target_vram": headroom >= 0,
        "cpu_offload": cpu_offload,
        "tokens_per_s": tokens_per_s,
        "disk_size_gb": disk_size_gb,
        "capability_per_gb_vram": None,   # filled by selection script
        "capability_per_second": None,
    }