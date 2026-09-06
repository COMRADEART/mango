"""T6.29 — tests for the T6 curriculum systems.

Covers: capability taxonomy/matrix, curriculum levels, generators +
verification gates, replay selection, gates/promotion/Pareto,
decomposition, routing metrics, counterfactuals, failure memory,
eval-core schema/freeze/contamination. GPU and model loads are NOT
required.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from sciencemath.curriculum.capabilities import (
    FAMILIES, family_of, family_macro, new_matrix, track_ids, track_spec,
    update_track, validate_matrix,
)
from sciencemath.curriculum.levels import LEVELS, validate_level_def
from sciencemath.curriculum.generators import (
    generate_stage_examples, verified_records, cross_check_with_tools,
)
from sciencemath.curriculum.replay import select_replay
from sciencemath.curriculum.gates import (
    GATE_DIMENSIONS, evaluate_gates, pp_drop, dominates, pareto_front,
    balanced_best, capability_vector, validate_promotion_log,
    append_promotion_log, promotion_entry, load_gates,
)
from sciencemath.curriculum.decomposition import (
    validate_plan, parse_plan_from_output, routing_label_from_plan,
)
from sciencemath.curriculum.routing import routing_metrics, label_for
from sciencemath.curriculum.counterfactual import (
    KINDS, apply_perturbation, expected_behavior, validate_spec,
)
from sciencemath.curriculum.failure_memory import (
    ERROR_TYPES, classify_error_type, make_record, append_failures,
    validate_record, summarize,
)
from sciencemath.curriculum.eval_core import (
    CORE_CATEGORIES, eval_id_for, routing_label, validate_item,
    contamination_check, freeze_suite, verify_frozen,
)


# ---------------------------------------------------------------- T6.1
def test_taxonomy_complete_and_consistent():
    ids = track_ids()
    assert len(ids) == len(set(ids))
    assert len(ids) == 81
    for tid in ids:
        spec = track_spec(tid)
        lo, hi = spec["difficulty_range"]
        assert 1 <= lo <= hi <= 5
        assert family_of(tid) in FAMILIES
        assert family_macro(family_of(tid)) in (
            "math_macro", "science_macro", "cross_domain_macro")


def test_matrix_roundtrip():
    m = new_matrix()
    errs = validate_matrix(m)
    assert errs == []
    update_track(m, "math_arithmetic", checkpoint="ck0", score=0.9)
    assert m["tracks"]["math_arithmetic"]["status"] == "acquired"
    assert m["tracks"]["math_arithmetic"]["best_checkpoint"] == "ck0"


# ---------------------------------------------------------------- T6.5
@pytest.mark.parametrize("level", sorted(LEVELS))
def test_level_defs_valid(level):
    assert validate_level_def(level) == []


def test_tracks_covered_monotonic():
    from sciencemath.curriculum.levels import tracks_covered_through
    s1 = tracks_covered_through(1)
    s2 = tracks_covered_through(2)
    assert s1 < s2


# ---------------------------------------------------------------- T6.6/T6.7
def test_generators_verified_and_cross_checked():
    recs, _ = generate_stage_examples(
        level=1, tracks={"math_arithmetic": 10, "math_fractions": 10,
                         "math_percentages": 10, "phys_mechanics": 10},
        seed=99)
    assert len(recs) == 40
    kept, vstats = verified_records(recs)
    assert vstats["unknown"] == 0 and vstats["failed"] == 0
    kept2, cstats = cross_check_with_tools(kept)
    assert cstats["dropped"] == 0
    from sciencemath.curriculum.generators import mark_verified
    for r in mark_verified(kept2):
        assert r["verification_state"] == "PASS"
        assert 1 <= r["difficulty"] <= 2          # L1 range
        assert r["license"] == "CC0-1.0"
        assert r["target_response"].startswith("Answer: \\boxed{")
        assert r["curriculum_level"] == 1


def test_generator_determinism():
    a, _ = generate_stage_examples(level=1, tracks={"math_ratios": 8},
                                   seed=7)
    b, _ = generate_stage_examples(level=1, tracks={"math_ratios": 8},
                                   seed=7)
    assert [r["question"] for r in a] == [r["question"] for r in b]


# ---------------------------------------------------------------- T6.9
def test_replay_selection_stratified_and_deterministic():
    pool = []
    for i in range(60):
        pool.append({"question": f"q {i} unique text {i}",
                     "target_response": "Answer: \\boxed{1}",
                     "family": "mathematics" if i % 2 else "chemistry",
                     "verification_state": "PASS", "subject": "x"})
    sel1, rep1 = select_replay(pool, fraction=0.2, target_size=10, seed=3)
    sel2, rep2 = select_replay(pool, fraction=0.2, target_size=10, seed=3)
    assert [r["question"] for r in sel1] == [r["question"] for r in sel2]
    assert len(sel1) == 10
    assert "composition" in rep1 or "by_macro" in rep1 or rep1


def test_replay_excludes_stage_questions():
    pool = [{"question": f"shared question {i}", "target_response": "x",
             "family": "physics", "verification_state": "PASS"}
            for i in range(10)]
    sel, _ = select_replay(pool, fraction=0.5, target_size=5,
                           exclude_questions={"shared question 0",
                                              "shared question 1"})
    assert all(r["question"] not in ("shared question 0",
                                     "shared question 1") for r in sel)


# ---------------------------------------------------------------- T6.10-12
def _gates():
    return {d: 5.0 for d in GATE_DIMENSIONS}


def test_gate_keep_and_reject():
    base = {d: 0.5 for d in GATE_DIMENSIONS}
    cand = {d: 0.5 for d in GATE_DIMENSIONS}
    cand["science_macro"] = 0.42          # 8 pp drop > 5 pp threshold
    r = evaluate_gates(_gates(), base, cand, level=1, checkpoint="c",
                       parent="p")
    assert r["decision"] == "REJECT"
    assert r["violated_gates"] == ["science_macro"]
    cand["science_macro"] = 0.47          # 3 pp drop: within gate
    r = evaluate_gates(_gates(), base, cand, level=1, checkpoint="c",
                       parent="p")
    assert r["decision"] == "KEEP"


def test_pp_drop_none_safe():
    assert pp_drop(None, 0.5) is None and pp_drop(0.5, None) is None


def test_pareto_and_promotion_log(tmp_path):
    a = capability_vector({"math_macro": 0.5, "science_macro": 0.5})
    b = capability_vector({"math_macro": 0.6, "science_macro": 0.6})
    assert dominates(b, a) and not dominates(a, b)
    front = pareto_front({"x": a, "y": b})
    assert front == ["y"]
    assert balanced_best({"x": a, "y": b}) == "y"

    log = tmp_path / "promotion_log.jsonl"
    r = evaluate_gates(_gates(), {d: 0.5 for d in GATE_DIMENSIONS},
                       {d: 0.5 for d in GATE_DIMENSIONS}, level=1,
                       checkpoint="ck1", parent="base")
    append_promotion_log(log, promotion_entry(r, metrics={},
                                             capability_vector={}))
    append_promotion_log(log, promotion_entry(r, metrics={},
                                              capability_vector={}))
    errs = validate_promotion_log(log)
    assert any("multiple KEEP" in e for e in errs)


# ---------------------------------------------------------------- T6.14
PLAN = {
    "problem_type": "mixed",
    "subproblems": [
        {"id": 1, "goal": "find the formula", "needs_math_tool": False,
         "needs_retrieval": True},
        {"id": 2, "goal": "compute the value", "needs_math_tool": True,
         "needs_retrieval": False},
    ],
}


def test_plan_validation_and_routing():
    assert validate_plan(PLAN) == []
    bad = dict(PLAN, problem_type="vibes")
    assert validate_plan(bad)
    assert routing_label_from_plan(PLAN) == "BOTH"
    math_only = {"problem_type": "math", "subproblems": [
        {"id": 1, "goal": "compute", "needs_math_tool": True,
         "needs_retrieval": False}]}
    assert routing_label_from_plan(math_only) == "TOOL"
    # no hidden chain-of-thought: long goals rejected
    long_goal = json.loads(json.dumps(math_only))
    long_goal["subproblems"][0]["goal"] = "x" * 500
    assert any("too long" in e for e in validate_plan(long_goal))


def test_parse_plan_from_output():
    raw = ('Here is the plan:\n{"problem_type": "math", "subproblems": '
           '[{"id": 1, "goal": "compute", "needs_math_tool": true, '
           '"needs_retrieval": false}]}\nAnswer: \\boxed{7}')
    plan = parse_plan_from_output(raw)
    assert plan and validate_plan(plan) == []


# ---------------------------------------------------------------- T6.15
def test_routing_metrics():
    items = [
        {"routing_label": "TOOL", "invoked_tool": True,
         "invoked_retrieval": False},
        {"routing_label": "TOOL", "invoked_tool": False,
         "invoked_retrieval": False},
        {"routing_label": "NONE", "invoked_tool": False,
         "invoked_retrieval": False},
        {"routing_label": "NONE", "invoked_tool": True,
         "invoked_retrieval": False},   # unnecessary tool invocation
        {"routing_label": "RETRIEVAL", "invoked_retrieval": True,
         "invoked_tool": False},
        {"routing_label": "RETRIEVAL", "invoked_retrieval": False,
         "invoked_tool": False},
        {"routing_label": "BOTH", "invoked_tool": True,
         "invoked_retrieval": True},
        {"routing_label": "BOTH", "invoked_tool": False,
         "invoked_retrieval": False},
    ]
    m = routing_metrics(items)
    # semantics: precision = tp / invocations of that kind;
    # recall = tp / items needing that capability
    assert m["tool_needed_precision"] == pytest.approx(2 / 3, abs=1e-3)
    assert m["tool_needed_recall"] == pytest.approx(0.5, abs=1e-3)
    assert m["retrieval_needed_precision"] == pytest.approx(1.0, abs=1e-3)
    assert m["retrieval_needed_recall"] == pytest.approx(0.5, abs=1e-3)
    assert m["both_accuracy"] == 0.5
    assert m["unnecessary_tool_invocation_rate"] == 0.125
    assert label_for(requires_math_tool=True, requires_retrieval=False) \
        == "TOOL"
    assert label_for(requires_math_tool=False, requires_retrieval=False,
                     insufficient_info=True) == "INSUFFICIENT_INFO"


# ---------------------------------------------------------------- T6.17
def test_counterfactual_kinds():
    q = "A train travels 120 km in 2 hours. What is its average speed?"
    specs = [
        {"kind": "change_value", "find": "120", "replace": "150"},
        {"kind": "reverse_relation", "find": "120 km in 2 hours",
         "replace": "2 hours in 120 km trips"},
        {"kind": "alter_unit", "find": "km", "replace": "miles"},
        {"kind": "add_distractor",
         "distractor_sentence": "The conductor likes tea."},
        {"kind": "remove_fact", "sentence_contains": "120 km"},
        {"kind": "swap_variables", "find": "120", "replace": "2"},
    ]
    for spec in specs:
        assert validate_spec(spec) == []
        new_q, applied = apply_perturbation(q, spec)
        if spec["kind"] in ("remove_fact",):
            assert applied and "120" not in new_q
        elif spec["kind"] == "add_distractor":
            assert applied and "conductor" in new_q
        elif spec["kind"] == "swap_variables":
            assert applied and "2 hours" not in new_q.replace("150", "")
        else:
            assert applied
    assert expected_behavior("add_distractor") == "ANSWER_UNCHANGED"
    assert expected_behavior("change_value") == "ANSWER_CHANGES"
    assert expected_behavior("remove_fact") == "ANSWER_INSUFFICIENT"
    with pytest.raises(ValueError):
        expected_behavior("nonsense")


# ---------------------------------------------------------------- T6.19
def test_failure_memory_classification_and_log(tmp_path):
    assert classify_error_type({"failure": "EXTRACTION_FAILURE"}) == \
        "EXTRACTION_ERROR"
    assert classify_error_type({"routing_label": "TOOL",
                                "correct": False}) == "TOOL_ROUTING_ERROR"
    assert classify_error_type({"routing_label": "INSUFFICIENT_INFO",
                                "correct": False}) == "OVERCONFIDENCE"
    assert classify_error_type({"correct": False}) == "CONCEPT_ERROR"
    rec = make_record(
        problem_id="mec1-abc", suite="mango-eval-core-v1",
        domain="physics", capability_track="phys_mechanics",
        tool_needed=False, retrieval_needed=False,
        expected_answer="42", actual_wrong_answer="40",
        checkpoint="test", run_record={"raw_model_output": "40"},
        verification_evidence="test-run predictions row")
    assert validate_record(rec) == []
    path = tmp_path / "failures.jsonl"
    assert append_failures(path, [rec]) == 1
    s = summarize(path)
    assert s["total_failures"] == 1
    assert set(ERROR_TYPES) >= {
        "CONCEPT_ERROR", "ALGEBRA_ERROR", "ARITHMETIC_ERROR",
        "TOOL_ROUTING_ERROR", "RETRIEVAL_ROUTING_ERROR", "EVIDENCE_MISUSE",
        "UNIT_ERROR", "EXTRACTION_ERROR", "MULTI_HOP_FAILURE",
        "UNSUPPORTED_CLAIM", "OVERCONFIDENCE"}


# ---------------------------------------------------------------- T6.17
def test_counterfactual_eval_scoring():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "run_counterfactual_eval",
        REPO / "scripts" / "run_counterfactual_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def variant(eid, parent, kind, behavior, expected):
        return {"eval_id": eid,
                "counterfactual": {"parent_eval_id": parent, "kind": kind,
                                   "expected_behavior": behavior},
                "expected_answer": expected}

    variants = [
        variant("v1", "p1", "change_value", "ANSWER_CHANGES", "23.08"),
        variant("v2", "p2", "add_distractor", "ANSWER_UNCHANGED", "24"),
        variant("v3", "p3", "remove_fact", "ANSWER_INSUFFICIENT", "24"),
    ]
    preds = {
        "v1": {"extracted_answer": "23.08", "raw_model_output": "x"},
        "v2": {"extracted_answer": "24", "raw_model_output": "x"},
        "v3": {"extracted_answer": None,
               "raw_model_output": "I don't have enough information"},
    }
    parent_ans = {"p1": "24", "p2": "24", "p3": "24"}
    scored = mod.score_variants(variants, preds, parent_ans)
    assert [s["behavior_passed"] for s in scored] == [True, True, True]
    # change_value without a parent answer on record -> cannot confirm
    scored2 = mod.score_variants(variants[:1], preds, {})
    assert scored2[0]["behavior_passed"] is False
    # ANSWER_INSUFFICIENT with a invented answer -> fails
    preds["v3"]["extracted_answer"] = "42"
    scored3 = mod.score_variants(variants[2:], preds, parent_ans)
    assert scored3[0]["behavior_passed"] is False


# ---------------------------------------------------------------- T6.2/3
def _item(**over):
    base = {
        "category": "algebra", "capability_track": "math_linear_equations",
        "generalization_split": "IID", "requires_math_tool": True,
        "requires_retrieval": False, "insufficient_info": False,
        "multi_hop": False, "answer_type": "numeric",
        "question": "Solve for x: 2x + 3 = 11 in one unknown.",
        "expected_answer": "4", "license": "CC0-1.0",
    }
    base.update(over)
    return base


def test_eval_core_item_schema():
    tracks = {"math_linear_equations": {"family": "mathematics"}}
    assert validate_item(_item(), tracks) == []
    assert validate_item(_item(category="nope"), tracks)
    assert validate_item(_item(capability_track="nope"), tracks)
    ins = _item(insufficient_info=True, expected_answer="__UNKNOWN__")
    assert validate_item(ins, tracks) == []
    bad_ins = _item(insufficient_info=True, expected_answer="4")
    assert validate_item(bad_ins, tracks)
    assert routing_label(_item()) == "TOOL"
    assert routing_label(_item(requires_retrieval=True)) == "BOTH"
    assert eval_id_for("q1") != eval_id_for("q2")


def test_contamination_check_flags_overlap():
    ref = ["A warehouse receives 386 crates and each crate holds 47 "
           "bottles. How many bottles arrive in total?"]
    items = [_item(question="A warehouse receives 386 crates and each "
                   "crate holds 47 bottles. How many bottles arrive in "
                   "total?")]
    flagged = contamination_check(items, ref)
    assert flagged and flagged[0]["overlap"] >= 0.5
    assert contamination_check(
        [_item(question="Completely different text about planetary "
                       "orbits and Kepler's third law of motion.")],
        ref) == []


def test_freeze_and_verify_roundtrip(tmp_path):
    items = [_item(), _item(question="Another distinct question about "
                            "circle areas with radius seven units.",
                            capability_track="geometry_area_volume",
                            requires_math_tool=False)]
    freeze = freeze_suite(items, tmp_path / "s")
    assert freeze["questions"] == 2
    v = verify_frozen(tmp_path / "s")
    assert v["ok"] and v["checked"] == 2
    # tamper -> verification fails
    p = tmp_path / "s" / "questions.jsonl"
    lines = p.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("4", "5", 1)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not verify_frozen(tmp_path / "s")["ok"]


def test_frozen_suites_exist_and_verify():
    for rel in ("evaluations/eval-core/v1",
                "evaluations/t6/counterfactual/v1"):
        d = REPO / rel
        assert (d / "questions.jsonl").exists(), rel
        assert (d / "checksum.json").exists(), rel
        v = verify_frozen(d)
        assert v["ok"], (rel, v)


def test_curriculum_gates_config_declares_all_dimensions():
    gates = load_gates(REPO / "configs" / "curriculum.yaml")
    for d in GATE_DIMENSIONS:
        assert d in gates
        assert 0 < float(gates[d]) <= 25


def test_stage_corpus_frozen_and_checksummed():
    d = REPO / "training" / "curriculum" / "mango-sft-v2" / "level1"
    assert (d / "train.jsonl").exists()
    assert (d / "checksums.json").exists()
    cs = json.loads((d / "checksums.json").read_text(encoding="utf-8"))
    import hashlib
    for name, digest in cs.items():
        f = d / name
        assert f.exists(), name
        assert hashlib.sha256(f.read_bytes()).hexdigest() == digest, name


def test_frozen_v1_corpus_untouched():
    cs = json.loads((REPO / "training" / "datasets" / "sciencemath-sft-v1"
                     / "checksums.json").read_text(encoding="utf-8"))
    import hashlib
    for name, digest in cs.items():
        f = REPO / "training" / "datasets" / "sciencemath-sft-v1" / name
        assert f.exists(), name
        assert hashlib.sha256(f.read_bytes()).hexdigest() == digest, name