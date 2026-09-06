"""T8.29 — capacity-study unit tests (license gates, capability vectors,
Pareto selection, subtest scorers, migration/promotion rules, SFT
answer/work agreement, identity detection, hardware profiles).

All tests are deterministic and GPU-free.
"""
import json

import pytest

from sciencemath.evaluation.capacity import (
    CAPACITY_DIMENSIONS,
    detect_adapter_identity,
    detect_model_identity,
    dominates,
    hardware_profile,
    license_gate,
    migration_decision,
    pareto_front,
    pareto_rank,
    promotion_check,
    score_decomposition,
    score_distractor,
    score_self_correction,
    score_uncertainty,
    sft_answer_work_agreement,
    validate_candidate_manifest,
    validate_capability_vector,
)

# ---------------------------------------------------------------- license gate
def base_entry(**kw):
    e = {"model_id": "x/y", "revision": "main", "params_b": 3.8,
         "license": "mit", "license_verified": True,
         "allows_training_use": True, "context_length": 128000,
         "checked_on": "2026-09-04"}
    e.update(kw)
    return e


def test_permissive_verified_license_approved():
    status, _ = license_gate(base_entry())
    assert status == "APPROVED"


def test_unverified_license_denied_by_default():
    status, reason = license_gate(base_entry(license_verified=False))
    assert status == "REVIEW_REQUIRED"
    assert "not verified" in reason


def test_custom_license_requires_review():
    status, _ = license_gate(base_entry(license="gemma"))
    assert status == "REVIEW_REQUIRED"


def test_training_use_denied_blocks():
    status, _ = license_gate(base_entry(allows_training_use=False))
    assert status == "BLOCKED"


def test_permissive_but_unconfirmed_training_use():
    status, _ = license_gate(base_entry(allows_training_use=None))
    assert status == "REVIEW_REQUIRED"


def test_manifest_requires_control_and_three_candidates():
    entries = [base_entry(model_id=f"m/{i}") for i in range(3)]
    errs = validate_candidate_manifest(entries)
    assert any("Qwen/Qwen3-1.7B" in e for e in errs)
    entries.append(base_entry(model_id="Qwen/Qwen3-1.7B"))
    errs = validate_candidate_manifest(entries)
    assert not any("Qwen/Qwen3-1.7B" in e for e in errs)


def test_manifest_duplicate_ids_flagged():
    entries = [base_entry(model_id="m/1") for _ in range(4)]
    entries.append(base_entry(model_id="Qwen/Qwen3-1.7B"))
    errs = validate_candidate_manifest(entries)
    assert any("duplicate" in e for e in errs)


# --------------------------------------------------------- capability vector
def test_full_vector_valid():
    vec = {d: 0.5 for d in CAPACITY_DIMENSIONS}
    vec["retrieval_routing"] = None
    assert validate_capability_vector(vec) == []


def test_vector_missing_dimension_flagged():
    vec = {d: 0.5 for d in CAPACITY_DIMENSIONS[:-1]}
    errs = validate_capability_vector(vec)
    assert len(errs) == 1 and "missing" in errs[0]


def test_vector_out_of_range_flagged():
    vec = {d: 0.5 for d in CAPACITY_DIMENSIONS}
    vec["overall"] = 1.5
    assert any("out of" in e for e in validate_capability_vector(vec))


def test_vector_negative_self_correction_is_valid():
    """Net self-correction benefit ranges [-1,1]; a negative value must NOT
    disqualify a capability vector from Pareto comparison (T8.13)."""
    vec = {d: 0.5 for d in CAPACITY_DIMENSIONS}
    vec["self_correction"] = -0.2273
    assert validate_capability_vector(vec) == []
    vec["self_correction"] = -1.5
    assert any("out of" in e for e in validate_capability_vector(vec))


# ------------------------------------------------------------------ Pareto
def vec(**kw):
    base = {"overall": 0.5, "math_macro": 0.5, "science_macro": 0.5,
            "cross_domain": 0.5, "compositional": 0.5, "counterfactual": 0.5,
            "distractor": 0.5, "uncertainty": 0.5, "decomposition": 0.5,
            "self_correction": 0.5, "tool_routing": 0.5,
            "retrieval_routing": None, "extraction": 0.9}
    base.update(kw)
    return base


def test_pareto_dominance_strict():
    a = vec(overall=0.6, math_macro=0.7)
    b = vec()
    assert dominates(a, b)
    assert not dominates(b, a)


def test_pareto_front_prefers_balance():
    """A math-only monster must not beat a balanced candidate on the front."""
    balanced = {k: 0.55 for k in CAPACITY_DIMENSIONS}
    balanced["extraction"] = 0.9
    math_monster = {k: 0.1 for k in CAPACITY_DIMENSIONS}
    math_monster["math_macro"] = 0.95
    front = pareto_front({"balanced": balanced, "monster": math_monster})
    assert front == ["balanced", "monster"]   # neither dominates the other


def test_pareto_rank_strips_fronts():
    a = vec(overall=0.9)
    b = vec()
    c = vec(overall=0.1, math_macro=0.1, science_macro=0.1)
    assert pareto_rank({"a": a, "b": b, "c": c}) == ["a", "b", "c"]


# --------------------------------------------------------------- subtests
def test_uncertainty_scores():
    unc = [{"uncertainty_signaled": True, "hallucinated": False},
           {"uncertainty_signaled": False, "hallucinated": True}]
    ans = [{"uncertainty_signaled": False}, {"uncertainty_signaled": True},
           {"uncertainty_signaled": False}]
    m = score_uncertainty(unc, ans)
    assert m["insufficient_info_precision"] == pytest.approx(1 / 2)
    assert m["insufficient_info_recall"] == pytest.approx(1 / 2)
    assert m["false_uncertainty_count"] == 1
    assert m["hallucinated_answer_rate"] == pytest.approx(1 / 2)


def test_distractor_delta():
    m = score_distractor(0.8, 0.6)
    assert m["robustness_delta"] == pytest.approx(-0.2)
    assert m["robustness_ratio"] == pytest.approx(0.75)


def test_self_correction_counts():
    recs = [
        {"initially_correct": False, "revised_correct": True},
        {"initially_correct": False, "revised_correct": False},
        {"initially_correct": True, "revised_correct": True},
        {"initially_correct": True, "revised_correct": False},
    ]
    m = score_self_correction(recs)
    assert m["corrected_wrong"] == 1
    assert m["preserved_correct"] == 1
    assert m["overcorrections"] == 1
    assert m["net_benefit"] == pytest.approx(0.0)


def test_decomposition_raw_vs_repaired_kept_apart():
    recs = [{"raw_valid": False, "repaired_valid": True,
             "semantic_ok": True, "executable_ok": True},
            {"raw_valid": True, "repaired_valid": True,
             "semantic_ok": False, "executable_ok": True}]
    m = score_decomposition(recs, spontaneous_count=3, main_count=10)
    assert m["raw_valid_rate"] == pytest.approx(0.5)
    assert m["repaired_valid_rate"] == pytest.approx(1.0)
    assert m["unnecessary_plan_rate"] == pytest.approx(0.3)


# ------------------------------------------------------ migration decision
def improving_candidate(**over):
    v = {d: 0.5 for d in CAPACITY_DIMENSIONS}
    v["extraction"] = 0.9
    v.update({"compositional": 0.7, "cross_domain": 0.7,
              "counterfactual": 0.7, "decomposition": 0.8,
              "uncertainty": 0.7, "overall": 0.6})
    v.update(over)
    return v


def control(**over):
    v = {d: 0.5 for d in CAPACITY_DIMENSIONS}
    v["extraction"] = 0.9
    v.update(over)
    return v


def test_migration_approved_on_balanced_win():
    dec, _ = migration_decision(improving_candidate(), control())
    assert dec == "MIGRATE"


def test_migration_blocked_on_math_regression():
    dec, _ = migration_decision(improving_candidate(math_macro=0.2),
                                control())
    assert dec == "DO_NOT_MIGRATE"


def test_migration_conditional_on_license():
    dec, _ = migration_decision(improving_candidate(), control(),
                                license_status="REVIEW_REQUIRED")
    assert dec == "CONDITIONAL"


def test_migration_conditional_on_vram():
    dec, _ = migration_decision(improving_candidate(), control(),
                                fits_vram=False)
    assert dec == "CONDITIONAL"


def test_migration_refused_without_capacity_wins():
    dec, _ = migration_decision(control(), control())
    assert dec == "DO_NOT_MIGRATE"


# ----------------------------------------------------------- promotion gates
def test_promotion_passes_on_strong_v02():
    ok, reasons = promotion_check(improving_candidate(), control(),
                                  t4_false_pass=0, t5_fabricated=0)
    assert ok, reasons


def test_promotion_fails_on_t4_false_pass():
    ok, reasons = promotion_check(improving_candidate(), control(),
                                  t4_false_pass=1, t5_fabricated=0)
    assert not ok and any("false-PASS" in r for r in reasons)


def test_promotion_fails_on_fabricated_citations():
    ok, reasons = promotion_check(improving_candidate(), control(),
                                  t4_false_pass=0, t5_fabricated=2)
    assert not ok and any("citation" in r for r in reasons)


def test_promotion_fails_without_weak_dim_improvements():
    ok, reasons = promotion_check(control(), control(), t4_false_pass=0,
                                  t5_fabricated=0)
    assert not ok and any("weak dimensions" in r for r in reasons)


# ------------------------------------------------- SFT answer/work agreement
def test_agreement_ok():
    ex = {"response": "We compute 12*15=180, so the final answer is 180. "
                      "\\boxed{180}"}
    assert sft_answer_work_agreement(ex) == []


def test_agreement_flags_prose_boxed_mismatch():
    ex = {"response": "Compute: 12*15=181. \\boxed{180}"}
    errs = sft_answer_work_agreement(ex)
    assert errs and "disagrees" in errs[0]


def test_agreement_flags_missing_boxed():
    ex = {"response": "The answer is 42."}
    errs = sft_answer_work_agreement(ex)
    assert any("boxed" in e for e in errs)


# -------------------------------------------------------- identity detection
def test_model_identity_ok(tmp_path):
    cfg = {"model_type": "qwen3", "hidden_size": 2048,
           "num_hidden_layers": 28, "num_attention_heads": 16,
           "vocab_size": 151936}
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    ok, desc = detect_model_identity(p, "Qwen/Qwen3-1.7B")
    assert ok and "qwen3" in desc
    ok2, _ = detect_model_identity(p, "Qwen/Qwen3-1.7B",
                                   expected_fingerprint=desc.split("fp=")[1])
    assert ok2


def test_model_identity_mismatch_detected(tmp_path):
    cfg = {"model_type": "qwen3", "hidden_size": 2048,
           "num_hidden_layers": 28, "num_attention_heads": 16,
           "vocab_size": 151936}
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    ok, desc = detect_model_identity(p, "some/other",
                                     expected_fingerprint="deadbeef0000")
    assert not ok and "mismatch" in desc


def test_adapter_identity(tmp_path):
    (tmp_path / "adapter_config.json").write_text(
        json.dumps({"base_model_name_or_path": "Qwen/Qwen3-1.7B"}),
        encoding="utf-8")
    (tmp_path / "adapter_model.safetensors").write_bytes(b"stub")
    ok, desc = detect_adapter_identity(tmp_path)
    assert ok and "Qwen/Qwen3-1.7B" in desc


def test_adapter_identity_missing_weights(tmp_path):
    (tmp_path / "adapter_config.json").write_text(
        json.dumps({"base_model_name_or_path": "Qwen/Qwen3-1.7B"}),
        encoding="utf-8")
    ok, desc = detect_adapter_identity(tmp_path)
    assert not ok and "weights" in desc


# --------------------------------------------------------- hardware profile
def test_hardware_profile_fits():
    p = hardware_profile(3_700_000_000, 4_500_000_000, 6 * 1024**3,
                         cpu_offload=False, tokens_per_s=12.5,
                         disk_size_gb=7.5)
    assert p["fits_target_vram"] is True
    assert p["cpu_offload"] is False
    assert p["headroom_mib"] > 0


def test_hardware_profile_overrun():
    p = hardware_profile(5_900_000_000, 7_200_000_000, 6 * 1024**3,
                         cpu_offload=True)
    assert p["fits_target_vram"] is False
    assert p["cpu_offload"] is True