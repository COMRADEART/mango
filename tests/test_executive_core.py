"""T7 executive core tests — state machine, classification, planning,
execution, verification, uncertainty, correction, checkpointing, and
the runner loop on FAKE model/registry/retriever (CPU, no GPU, no
network)."""
from __future__ import annotations

import json

import time

import pytest

from sciencemath.executive import state as st
from sciencemath.executive import budgets as bmod
from sciencemath.executive import classify as cls_mod
from sciencemath.executive import understand as und
from sciencemath.executive import plan as plan_mod
from sciencemath.executive import verify as ver
from sciencemath.executive import uncertainty as unc
from sciencemath.executive import correction as corr
from sciencemath.executive import replan as rp
from sciencemath.executive import checkpoint as ckpt
from sciencemath.executive.runner import (ExecContext, run_executive,
                                          _execute_plan)


# ---- state machine ----------------------------------------------------------
def test_valid_transitions_accepted():
    st.transition({"status": st.RECEIVED, "transitions": []},
                  st.CLASSIFYING)
    st.transition({"status": st.VERIFYING, "transitions": []},
                  st.SYNTHESIZING)
    st.transition({"status": st.REPLANNING, "transitions": []},
                  st.STALLED)


def test_invalid_transition_fails_closed():
    with pytest.raises(st.TransitionError):
        st.transition({"status": st.RECEIVED, "transitions": []},
                      st.SYNTHESIZING)
    with pytest.raises(st.TransitionError):
        st.transition({"status": st.COMPLETE, "transitions": []},
                      st.PLANNING)
    with pytest.raises(st.TransitionError):
        st.transition({"status": "BOGUS", "transitions": []},
                      st.PLANNING)


def test_terminal_states_have_no_outgoing():
    for terminal in st.TERMINAL_STATES:
        assert st.STATE_TRANSITIONS[terminal] == frozenset()


def test_all_stop_reasons_map_to_terminal_states():
    for reason in st.STOP_REASONS:
        assert st.REASON_TO_STATE[reason] in st.TERMINAL_STATES


def test_run_state_roundtrip_and_schema_rejection():
    r = st.new_run("q1", "what?")
    r.problem_type = "MATH"
    d = r.to_dict()
    r2 = st.RunState.from_dict(d)
    assert r2.problem_type == "MATH" and r2.run_id == "q1"
    d["schema_version"] = "0.0.1"
    with pytest.raises(ValueError):
        st.RunState.from_dict(d)


# ---- budgets ----------------------------------------------------------------
def test_budget_exceeded_priority_and_none():
    b = bmod.Budgets()
    usage = bmod.default_usage()
    assert bmod.exceeded(usage, b) is None
    # caps are totals: reaching the cap IS exhaustion (no off-by-one)
    usage["model_calls"] = b.max_model_calls
    assert bmod.exceeded(usage, b) == "max_model_calls"
    usage = bmod.default_usage()
    usage["retrievals"] = b.max_retrievals
    assert bmod.exceeded(usage, b) == "max_retrievals"
    usage = bmod.default_usage()
    usage["elapsed_s"] = b.max_total_seconds
    assert bmod.exceeded(usage, b) == "max_total_seconds"
    # a cap of 0 means zero calls allowed
    b0 = bmod.Budgets(max_model_calls=0)
    assert bmod.exceeded(bmod.default_usage(), b0) == "max_model_calls"


# ---- classification ---------------------------------------------------------
def test_classification_deterministic():
    q = "A car travels 100 m/s for 20 s. Calculate the total distance."
    c1 = cls_mod.classify_problem(q)
    c2 = cls_mod.classify_problem(q)
    assert c1 == c2
    assert c1["problem_type"] in cls_mod.PROBLEM_TYPES
    assert c1["complexity"] in cls_mod.COMPLEXITIES
    assert c1["resources"] in cls_mod.RESOURCES


def test_classification_complexity_buckets():
    assert cls_mod.classify_complexity(
        "Why does ice float?") == "OPEN_ENDED"
    assert cls_mod.classify_complexity(
        "If each student gets 3 books and there are 20 students, what is "
        "the total?") == "MULTI_STEP"
    assert cls_mod.classify_complexity(
        "What is 4 + 6?") == "SIMPLE"


def test_classification_resources():
    assert cls_mod.classify_resources("What is 12 * 8?") == "MATH_TOOL"
    assert cls_mod.classify_resources(
        "What is the chemical symbol for gold?") == "RETRIEVAL"
    assert cls_mod.classify_resources("What color is the sky?") == "NONE"
    assert cls_mod.classify_resources(
        "Who discovered penicillin and in what year?") == "RETRIEVAL"


def test_fast_path_eligibility():
    assert cls_mod.fast_path_eligible({"complexity": "SIMPLE",
                                       "resources": "NONE",
                                       "problem_type": "MATH"})
    assert not cls_mod.fast_path_eligible({"complexity": "SIMPLE",
                                           "resources": "MATH_TOOL",
                                           "problem_type": "MATH"})
    assert not cls_mod.fast_path_eligible({"complexity": "MULTI_STEP",
                                           "resources": "NONE",
                                           "problem_type": "MATH"})


# ---- understanding + distractors ---------------------------------------------
def test_understanding_extraction():
    u = und.extract_understanding(
        "A train moves at 30 m/s for 60 s. Calculate the total distance.")
    assert "30 m/s" in u.knowns or "60 s" in u.knowns
    assert u.question_target


def test_distractor_labels_and_filter():
    q = ("A ball is thrown at 10 m/s. Calculate the kinetic energy if "
         "its mass is 2 kg. The Eiffel Tower is in Paris. Bananas are "
         "yellow fruit.")
    labels = und.label_facts(q)
    by = {l.text: l.label for l in labels}
    assert by["Bananas are yellow fruit."] == "IRRELEVANT"
    kept = und.filter_context(list(by), labels)
    assert "Bananas are yellow fruit." in kept["excluded"]
    assert any("kinetic energy" in s for s in kept["included"])


def test_conflict_detection():
    # genuine contradiction: same entity, same unit, explicit same-entity
    # cue, different values
    conflicts = und.extract_conflicts(
        "q?", ["The car moves at 20 m/s.",
               "Later, the same car is stated to move at 30 m/s."])
    assert conflicts and conflicts[0]["unit"] == "m/s"
    assert len(conflicts[0]["values"]) == 2


def test_conflict_detection_negative_multi_value():
    # two DIFFERENT objects sharing a unit is not a conflict
    conflicts = und.extract_conflicts(
        "q?", ["A train travels at 30 m/s for 60 s.",
               "A car travels at 20 m/s.",
               "What is the difference in their speeds?"])
    assert not any(c["unit"] == "m/s" for c in conflicts)


# ---- plan schema ---------------------------------------------------------------
GOOD_PLAN = {"steps": [
    {"id": "s1", "action": "RETRIEVE", "description": "find facts",
     "depends_on": [], "input": "photosynthesis"},
    {"id": "s2", "action": "SYNTHESIZE", "description": "combine",
     "depends_on": ["s1"], "input": ""},
]}


def test_valid_plan_passes():
    v = plan_mod.validate_plan(GOOD_PLAN)
    assert v.ok, v.errors


@pytest.mark.parametrize("plan,needle", [
    ({"steps": [{"id": "s1", "action": "REASON", "description": "x",
                 "depends_on": []},
                {"id": "s1", "action": "SYNTHESIZE",
                 "description": "y", "depends_on": ["s1"]}]},
     "duplicate"),
    ({"steps": [{"id": "s1", "action": "HACK", "description": "x",
                 "depends_on": []},
                {"id": "s2", "action": "SYNTHESIZE",
                 "description": "y", "depends_on": ["s1"]}]},
     "action"),
    ({"steps": [{"id": "s1", "action": "REASON", "description": "x",
                 "depends_on": ["s2"]},
                {"id": "s2", "action": "SYNTHESIZE",
                 "description": "y", "depends_on": ["s1"]}]},
     "earlier"),
    ({"steps": [{"id": "s1", "action": "REASON", "description": "x",
                 "depends_on": []}]},
     "SYNTHESIZE"),
    ({"steps": [{"id": "s1", "action": "REASON", "description": "x",
                 "depends_on": []},
                {"id": "s2", "action": "SYNTHESIZE",
                 "description": "y", "depends_on": ["s1"]},
                {"id": "s3", "action": "SYNTHESIZE",
                 "description": "z", "depends_on": []}]},
     "one SYNTHESIZE"),
])
def test_invalid_plans_fail(plan, needle):
    v = plan_mod.validate_plan(plan)
    assert not v.ok
    assert any(needle.lower() in e.lower() for e in v.errors)
    assert v.feedback  # structured feedback for the retry


def test_plan_too_many_steps():
    steps = [{"id": f"s{i}", "action": "REASON", "description": "d",
              "depends_on": []} for i in range(1, 7)]
    steps.append({"id": "s7", "action": "SYNTHESIZE",
                  "description": "d", "depends_on": []})
    v = plan_mod.validate_plan({"steps": steps})
    assert not v.ok
    assert any("too many steps" in e for e in v.errors)


def test_parse_model_plan():
    assert plan_mod.parse_model_plan('{"steps": []}') == {"steps": []}
    assert plan_mod.parse_model_plan(
        'Sure!\n```json\n{"steps": []}\n```') == {"steps": []}
    assert plan_mod.parse_model_plan(
        'junk before {"steps": [{"id": "s1", "action": "REASON", '
        '"description": "d", "depends_on": []}]} trailing') is not None
    assert plan_mod.parse_model_plan("no json here") is None
    assert plan_mod.parse_model_plan('{"steps": [') is None
    # braces inside string literals must not break the object matcher
    assert plan_mod.parse_model_plan(
        'junk {"steps": [{"id": "s1", "action": "REASON", '
        '"description": "handle a } brace", "depends_on": []}]} tail'
    ) is not None


def test_fallback_plan_valid_by_construction():
    c = {"problem_type": "MIXED", "resources": "BOTH"}
    u = {"question_target": "total distance", "knowns": ["30 m/s"],
         "unknowns": [], "expression": "30*60"}
    p = plan_mod.fallback_plan(c, u)
    assert plan_mod.validate_plan(p).ok
    assert p["source"] == "deterministic_fallback"
    assert plan_mod.plan_fingerprint(p) == plan_mod.plan_fingerprint(p)


def test_fallback_plan_math_without_expression():
    """No expression -> no MATH_TOOL step (a prose placeholder would
    deterministically fail in the calculator) and ids stay unique."""
    c = {"problem_type": "MATH", "resources": "MATH_TOOL"}
    p = plan_mod.fallback_plan(c, {"question_target": "x", "knowns": [],
                                   "unknowns": [], "expression": ""})
    v = plan_mod.validate_plan(p)
    assert v.ok, v.errors
    actions = [s["action"] for s in p["steps"]]
    assert "MATH_TOOL" not in actions
    assert actions[-1] == "SYNTHESIZE"
    ids = [s["id"] for s in p["steps"]]
    assert len(ids) == len(set(ids))


# ---- verification --------------------------------------------------------------
def test_citation_verification_fail_closed():
    chunks = [{"source_id": "w", "chunk_id": "c1", "text": "x"}]
    ok = ver.verify_citations("Sky is blue [c1]", chunks)
    assert ok["ok"] and ok["valid_refs"] == ["c1"]
    bad = ver.verify_citations("Sky is blue [cX]", chunks)
    assert not bad["ok"] and bad["invalid_refs"] == ["cX"]


def test_citation_prose_is_not_a_citation():
    # prose colons and numbers must not be read as chunk references
    chunks = [{"source_id": "w", "chunk_id": "c1", "text": "x"}]
    r = ver.verify_citations("The ratio is 12:30 and it is 3:2 times.", [])
    assert r["ok"] and r["invalid_refs"] == []
    r2 = ver.verify_citations("The ratio is 12:30.", chunks)
    assert r2["ok"] and r2["valid_refs"] == [] and r2["invalid_refs"] == []


def test_verify_final_tool_match():
    v = ver.verify_final("42", "Answer: 42", [42], [])
    assert v["verdict"] == "VERIFIED"
    v = ver.verify_final("41", "Answer: 41", [42], [])
    assert v["verdict"] == "FAILED"
    v = ver.verify_final(None, "", [], [])
    assert v["verdict"] == "UNKNOWN"


def test_verify_final_retrieval_without_citations_is_unknown():
    # retrieval-backed answer with NO citations: unverified, not failed
    chunks = [{"source_id": "w", "chunk_id": "c1", "text": "sky"}]
    v = ver.verify_final("blue", "The sky is blue because ...", [], chunks)
    assert v["verdict"] == "UNKNOWN"
    v = ver.verify_final("blue", "The sky is blue [c1].", [], chunks)
    assert v["verdict"] == "VERIFIED"
    v = ver.verify_final("blue", "The sky is blue [cX].", [], chunks)
    assert v["verdict"] == "FAILED"  # fabricated chunk reference


# ---- uncertainty ----------------------------------------------------------------
def test_uncertainty_mapping_priority():
    assert unc.decide_status({"contradictions": True}) == \
        "CONFLICTING_EVIDENCE"
    assert unc.decide_status({"empty_retrieval": True,
                              "good_retrieval": False}) == \
        "INSUFFICIENT_INFORMATION"
    assert unc.decide_status({"verification_verdict": "VERIFIED"}) == \
        "VERIFIED"
    assert unc.decide_status({"good_retrieval": True,
                              "tool_ok": True}) == "STRONGLY_SUPPORTED"
    assert unc.decide_status({}) == "UNCERTAIN"
    assert unc.decide_status({"text_insufficient": True}) == \
        "INSUFFICIENT_INFORMATION"


def test_decline_not_triggered_by_single_empty_retrieval():
    # one empty retrieval must not discard a verified, tool-backed answer
    signals = {"empty_retrieval": True, "good_retrieval": True,
               "tool_ok": True}
    assert not unc.answer_should_decline("VERIFIED", signals)


def test_decline_answer_uses_frozen_insufficiency_sentence():
    a = unc.decline_answer("INSUFFICIENT_INFORMATION")
    from sciencemath.evaluation.extraction import signals_uncertainty
    assert signals_uncertainty(a)
    assert signals_uncertainty(unc.decline_answer("CONFLICTING_EVIDENCE"))


def test_all_statuses_in_closed_set():
    for s in unc.EVIDENCE_STATUSES_ALL if hasattr(
            unc, "EVIDENCE_STATUSES_ALL") else st.EVIDENCE_STATUSES:
        assert s in st.EVIDENCE_STATUSES


# ---- correction -----------------------------------------------------------------
def test_correction_gate_requires_external_evidence():
    ok, _ = corr.correction_eligible({}, {"verdict": "FAILED",
                                          "contradicting_evidence": "42"},
                                     0)
    assert ok
    ok, why = corr.correction_eligible({}, {"verdict": "VERIFIED"}, 0)
    assert not ok
    ok, why = corr.correction_eligible({}, {"verdict": "FAILED"}, 1)
    assert not ok and "budget" in why
    ok, why = corr.correction_eligible({}, {"verdict": "FAILED",
                                            "contradicting_evidence": None},
                                       0)
    assert not ok and "external" in why  # specific reason given


def test_parse_correction_overcorrection_protection():
    out = corr.parse_correction("Unchanged: evidence supports my answer",
                                "42")
    assert out["unchanged"] and out["answer"] == "42"
    out = corr.parse_correction("Because the tool says 40.\nAnswer: 40",
                                "42")
    assert not out["unchanged"] and out["answer"] == "40"


# ---- checkpoint -------------------------------------------------------------------
def test_checkpoint_atomic_save_load_resume(tmp_path):
    cp = ckpt.RunCheckpointer(tmp_path)
    state = {"run_id": "r1", "status": "EXECUTING",
             "completed_steps": ["s1"], "observations": []}
    p = cp.save(state, {"nodes": [], "edges": []})
    assert p.exists()
    loaded = cp.load("r1")
    assert loaded["state"]["completed_steps"] == ["s1"]
    assert cp.completed_step_ids("r1") == {"s1"}
    assert cp.completed_step_ids("missing") == set()


def test_signature_stable():
    s = {"id": "s1", "action": "MATH_TOOL", "input": "2+2"}
    assert ckpt.signature_of_step(s) == ckpt.signature_of_step(dict(s))


def test_replan_triggers_and_stall():
    state = {"replans": 0, "conflicts": [], "observations": []}
    tr, why = rp.detect_trigger(
        state, {"verdict": "FAILED", "failed_steps": []})
    assert tr == "VERIFICATION_FAILED"
    tr, _ = rp.detect_trigger(
        {"conflicts": [{"unit": "m/s"}], "observations": []},
        {"verdict": "VERIFIED", "failed_steps": []})
    assert tr == "CONTRADICTION"
    tr, _ = rp.detect_trigger(
        {"conflicts": [], "observations": [
            {"action": "RETRIEVE", "status": "FAILED"}]},
        {"verdict": "VERIFIED", "failed_steps": []})
    assert tr == "RETRIEVAL_INSUFFICIENT"
    ok, trigger, _ = rp.should_replan({"replans": 2}, {}, bmod.Budgets())
    assert not ok


def test_loop_stall_after_repeated_identical_plan():
    plan = {"steps": GOOD_PLAN["steps"]}
    s1 = {"failure_fingerprints": []}
    assert rp.register_failure(s1, plan, "r1") == ""
    assert rp.register_failure(s1, plan, "r2") == "STALLED"


# ---- fake model / registry / retriever ----------------------------------------
class FakeTok:
    pad_token_id = 0
    eos_token_id = 1

    def __init__(self, responder):
        self.responder = responder
        self.last_prompt = ""
        self.calls = 0

    def apply_chat_template(self, messages, **kw):
        return "User: " + messages[0]["content"] + "\nAssistant:"

    def __call__(self, text, return_tensors="pt", truncation=False,
                 max_length=None):
        import torch
        self.last_prompt = text
        self.calls += 1
        ids = torch.arange(16).reshape(1, 16)
        return {"input_ids": ids,
                "attention_mask": torch.ones_like(ids)}

    def decode(self, ids, skip_special_tokens=True):
        return self.responder(self.last_prompt)


class FakeModel:
    device = "cpu"

    def __init__(self, tok):
        self.tok = tok

    def generate(self, **kw):
        import torch
        base = kw["input_ids"]
        extra = torch.tensor([[7, 7, 7]])
        return torch.cat([base, extra], dim=1)


PLAN_JSON = json.dumps({"steps": [
    {"id": "s1", "action": "RETRIEVE", "description": "find facts",
     "depends_on": [], "input": "why is the sky blue"},
    {"id": "s2", "action": "SYNTHESIZE", "description": "combine",
     "depends_on": ["s1"], "input": ""},
]})


def default_responder(prompt):
    if "JSON execution plan" in prompt or "previous plan was invalid" \
            in prompt.lower():
        return PLAN_JSON
    if "Combine the step results" in prompt:
        return ("The sky is blue due to Rayleigh scattering [w:c1].\n"
                "Answer: Rayleigh scattering")
    if "FAILED verification" in prompt:
        return "The evidence supports 42.\nAnswer: 42"
    return "Step: compute.\nAnswer: 42"


class FakeRegistry:
    def __init__(self, value=42, error=None):
        self.value = value
        self.error = error
        self.calls = []

    def invoke(self, name, arguments):
        from types import SimpleNamespace
        self.calls.append((name, arguments))
        if self.error:
            return SimpleNamespace(status="error", error=self.error,
                                   result=None)
        return SimpleNamespace(status="ok", error=None,
                               result=self.value)


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.queries = []

    def search(self, query, k=3):
        self.queries.append(query)
        return self.hits


def make_ctx(tok, registry=None, retriever=None, features=None,
             tmp=None):
    return ExecContext(
        model=FakeModel(tok), tokenizer=tok,
        registry=registry or FakeRegistry(),
        retriever=retriever or FakeRetriever([]),
        generation={"seed": 42, "max_new_tokens": 64},
        features=dict(features) if features else None,
        checkpointer=ckpt.RunCheckpointer(tmp) if tmp else None,
    )


# ---- runner end-to-end ------------------------------------------------------
def test_runner_fast_path_simple_question(tmp_path):
    tok = FakeTok(default_responder)
    res = run_executive("What color is the sky?", "q_fast", ctx=make_ctx(
        tok, features={"fast_path": True}, tmp=tmp_path))
    assert res["fast_path"] is True
    assert res["final_answer"] == "42"
    assert res["termination_reason"] == "SOLVED_UNVERIFIED"
    # fast path must not have planned
    assert res["steps_executed"] == 0


def test_runner_fast_path_bypass_off(tmp_path):
    tok = FakeTok(default_responder)
    res = run_executive("What color is the sky?", "q_nofast", ctx=make_ctx(
        tok, features={"fast_path": False, "replanning": False},
        tmp=tmp_path))
    assert res["fast_path"] is False
    assert res["plan_source"] == "model"
    assert res["first_attempt_plan_valid"] is True


def test_runner_full_loop_with_evidence(tmp_path):
    hits = [{"source_id": "w", "chunk_id": "c1",
             "text": "Rayleigh scattering makes the sky blue."}]
    tok = FakeTok(default_responder)
    res = run_executive(
        "Why is the sky blue according to Rayleigh scattering?",
        "q_science",
        ctx=make_ctx(tok, retriever=FakeRetriever(hits),
                     features={"fast_path": False}, tmp=tmp_path))
    assert res["final_answer"] == "Rayleigh scattering"
    assert res["termination_reason"] in ("SOLVED_VERIFIED",
                                         "SOLVED_UNVERIFIED")
    assert res["evidence_status"] in ("VERIFIED", "STRONGLY_SUPPORTED",
                                      "PARTIALLY_SUPPORTED")
    assert res["steps_executed"] == 2
    assert res["replans"] == 0
    assert res["evidence_status"] in st.EVIDENCE_STATUSES
    # transitions: every recorded transition is legal
    for a, b in zip(res["transitions"], res["transitions"][1:]):
        assert st.validate_transition(a, b) == []
        assert b in st.STATES


def test_runner_replan_reexecutes_replacement_plan(tmp_path):
    """Regression: a replan must RE-ARM the replacement plan's steps
    (never silently skip them as 'already completed') and must not wipe
    pre-replan evidence."""
    tok = FakeTok(default_responder)
    retr = FakeRetriever([])
    ctx = make_ctx(tok, retriever=retr,
                   features={"fast_path": False, "replanning": True},
                   tmp=tmp_path)
    res = run_executive(
        "Why is the sky blue according to Rayleigh scattering?",
        "q_empty",
        ctx=ctx)
    assert res["termination_reason"] in ("STALLED",
                                         "INSUFFICIENT_INFORMATION",
                                         "CONFLICTING_EVIDENCE")
    assert res["replans"] <= 2
    # the replacement plan's RETRIEVE step actually ran again (old bug:
    # id collision made every replan execute zero steps)
    assert len(retr.queries) == res["replans"] + 1
    assert len(res["observations"]) >= 2


def test_runner_zero_model_call_budget_makes_no_calls(tmp_path):
    tok = FakeTok(default_responder)
    ctx = make_ctx(tok, features={"fast_path": False}, tmp=tmp_path)
    ctx.budgets = bmod.Budgets(max_model_calls=0)
    res = run_executive("What color is the sky?", "q_cap0", ctx=ctx)
    assert tok.calls == 0
    assert res["termination_reason"] == "BUDGET_EXHAUSTED"
    assert res["state"]["status"] == st.BUDGET_EXHAUSTED
    assert res["transitions"][-1] == st.BUDGET_EXHAUSTED


def test_runner_checkpoint_resume_restores_state(tmp_path):
    """A durable checkpoint restores completed steps + observations; a
    completed retrieval is never duplicated on resume (T7.30)."""
    tok = FakeTok(default_responder)
    retr = FakeRetriever([{"source_id": "w", "chunk_id": "c1",
                           "text": "e"}])
    cp = ckpt.RunCheckpointer(tmp_path)
    plan = {"steps": [
        {"id": "s1", "action": "RETRIEVE", "description": "find",
         "depends_on": [], "input": "sky blue"},
        {"id": "s2", "action": "SYNTHESIZE", "description": "combine",
         "depends_on": ["s1"], "input": ""}],
        "source": "model"}
    cp.save({"run_id": "q_resume", "problem": "Why is the sky blue?",
             "completed_steps": ["s1"],
             "observations": [{"step_id": "s1", "action": "RETRIEVE",
                               "status": "OK", "summary": "evidence: c1",
                               "detail": {"chunks": [
                                   {"chunk_id": "c1", "source_id": "w",
                                    "text": "e"}]}}],
             "plan": plan, "plan_version": 1, "replans": 0,
             "conflicts": [], "included_facts": [], "distractors": []},
            {"nodes": [], "edges": []})
    ctx = make_ctx(tok, retriever=retr, features={"fast_path": False},
                   tmp=tmp_path)
    res = run_executive("Why is the sky blue?", "q_resume", ctx=ctx)
    assert retr.queries == []       # s1 never re-executed
    assert tok.calls == 1           # only s2 (SYNTHESIZE) ran
    assert res["termination_reason"] in ("SOLVED_VERIFIED",
                                         "SOLVED_UNVERIFIED")
    assert res["final_answer"] == "Rayleigh scattering"


def test_correction_ctx_requires_real_evidence():
    from sciencemath.executive.runner import _correction_ctx
    cctx = _correction_ctx({"verdict": "FAILED",
                            "citations": {"invalid_refs": [],
                                          "valid_refs": []}}, [])
    assert cctx["contradicting_evidence"] == ""
    ok, why = corr.correction_eligible(
        {}, {"verdict": "FAILED", "contradicting_evidence": "(none)"}, 0)
    assert not ok and "external" in why
    cctx2 = _correction_ctx({"verdict": "FAILED",
                             "citations": {"invalid_refs": ["cX"],
                                           "valid_refs": []}}, [])
    assert "cX" in cctx2["contradicting_evidence"]


def test_runner_plan_fallback_on_garbage_model_plan(tmp_path):
    def bad_responder(prompt):
        if "JSON execution plan" in prompt:
            return "I think we should just try hard."  # not JSON
        return default_responder(prompt)

    tok = FakeTok(bad_responder)
    res = run_executive(
        "Why is the sky blue according to Rayleigh scattering?",
        "q_badplan",
        ctx=make_ctx(tok, retriever=FakeRetriever([]),
                     features={"fast_path": False}, tmp=tmp_path))
    assert res["first_attempt_plan_valid"] is False
    assert res["retry_plan_valid"] is False
    assert res["plan_fallback_used"] is True
    assert res["plan_source"] == "deterministic_fallback"


def test_runner_model_call_failure_is_recorded_not_raised(tmp_path):
    def exploding_responder(prompt):
        raise RuntimeError("CUDA OOM simulated")

    tok = FakeTok(exploding_responder)
    res = run_executive("What color is the sky?", "q_err",
                        ctx=make_ctx(tok, features={"fast_path": False},
                                     tmp=tmp_path))
    # the failure must be recorded and bounded, never raised
    assert res["termination_reason"] in ("SYSTEM_ERROR", "STALLED",
                                         "INSUFFICIENT_INFORMATION")
    assert res["transitions"][-1] in st.TERMINAL_STATES


def test_execute_plan_resume_skips_completed_steps(tmp_path):
    tok = FakeTok(default_responder)
    retr = FakeRetriever([{"source_id": "w", "chunk_id": "c1",
                           "text": "e"}])
    ctx = make_ctx(tok, retriever=retr,
                   features={"fast_path": False}, tmp=tmp_path)
    state = st.new_run("r1", "Why is the sky blue?").to_dict()
    state = st.transition(state, st.CLASSIFYING)
    state = st.transition(state, st.PLANNING)
    state["plan"] = {"steps": [
        {"id": "s1", "action": "RETRIEVE", "description": "find",
         "depends_on": [], "input": "q"},
        {"id": "s2", "action": "SYNTHESIZE", "description": "combine",
         "depends_on": ["s1"], "input": ""}]}
    state["completed_steps"] = ["s1"]
    obs = {"s1": {"step_id": "s1", "action": "RETRIEVE", "status": "OK",
                  "summary": "evidence: c1", "detail": {}}}
    _execute_plan(state, obs, ctx, [], [], time.perf_counter())
    # s1 (RETRIEVE) must NOT be re-executed on resume: no retrieval query
    assert retr.queries == []  # (T7.30 no duplicate tool calls)
    assert "s2" in state["completed_steps"]
    # but s2 (SYNTHESIZE) did run — exactly one model call
    assert tok.calls == 1


def test_off_arm_shape_matches_on_arm_result_schema():
    """The OFF arm does not use the runner, but the comparison script
    must produce compatible result dicts — checked via the pack fields
    present in an ON result."""
    tok = FakeTok(default_responder)
    res = run_executive("What color is the sky?", "q_shape",
                        ctx=make_ctx(tok, features={"fast_path": True}))
    for key in ("final_answer", "termination_reason", "evidence_status",
                "latency_s", "steps_executed", "replans",
                "first_attempt_plan_valid", "plan_fallback_used"):
        assert key in res

# ---- round-2 review fixes ---------------------------------------------------
def test_citation_source_prefix_is_anchored():
    # models commonly decorate chunk ids with the source prefix ("w:c1"
    # for "c1") — anchored, not fabricated; an unknown id still fails
    chunks = [{"source_id": "w", "chunk_id": "c1", "text": "x"}]
    r = ver.verify_citations("Sky is blue [w:c1]", chunks)
    assert r["ok"] and r["valid_refs"] == ["w:c1"]
    r2 = ver.verify_citations("Sky is blue [other:cX]", chunks)
    assert not r2["ok"] and r2["invalid_refs"] == ["other:cX"]


def test_citation_colon_chunk_ids_parse():
    # real corpus chunk ids contain colons and must be citable
    chunks = [{"source_id": "wiki-18716923",
               "chunk_id": "wiki-18716923:intro_3cee6746:0", "text": "x"}]
    r = ver.verify_citations("Per the source [wiki-18716923:intro_3cee6746:0]",
                             chunks)
    assert r["ok"] and r["valid_refs"]


def test_verify_math_answer_dict_payload():
    # the calculator's ToolResult.result is a dict; compare against the
    # VALUE field, never the dict repr
    tr = {"expression": "34/17", "value": 2, "exact": "2"}
    assert ver.verify_math_answer("2", tr) == "VERIFIED"
    assert ver.verify_math_answer("3", tr) == "FAILED"
    assert ver.verify_math_answer("2", {"expression": "x"}) == "UNKNOWN"


def test_master_switch_off_runs_direct_path(tmp_path):
    # features {'executive': false} (A_off) never touches the executive
    # machinery: no plan steps, no retrieval, no tool calls
    retr = FakeRetriever([{"source_id": "w", "chunk_id": "c1", "text": "e"}])
    reg = FakeRegistry()
    tok = FakeTok(default_responder)
    res = run_executive("What is 6 times 7?", "q_off", ctx=make_ctx(
        tok, registry=reg, retriever=retr,
        features={"executive": False, "fast_path": False}, tmp=tmp_path))
    assert res["fast_path"] is True
    assert res["steps_executed"] == 0
    assert res["model_calls"] == 1
    assert res["tool_calls"] == 0
    assert res["retrievals"] == 0


def test_amend_plan_retrieval_failure_forces_retrieval():
    # a RETRIEVAL_INSUFFICIENT amendment must re-query: a GENERAL/NONE
    # fallback plan has no RETRIEVE step, so the amendment forces one
    c = {"problem_type": "GENERAL", "complexity": "MULTI_STEP",
         "resources": "NONE"}
    u = {"question_target": "why is the sky blue", "knowns": ["scattering"],
         "unknowns": ["reason"], "expression": "", "constraints": [],
         "missing": []}
    base = plan_mod.fallback_plan(c, u)
    assert all(s["action"] != "RETRIEVE" for s in base["steps"])
    u["force_retrieval"] = True
    amended = plan_mod.fallback_plan(c, u)
    assert any(s["action"] == "RETRIEVE" for s in amended["steps"])
    ids = [s["id"] for s in amended["steps"]]
    assert len(ids) == len(set(ids))


def test_retrieval_history_survives_replan_rearm(tmp_path):
    # after a replan drops the failed RETRIEVE observation, the run must
    # still know retrieval never produced evidence (decline, not guess)
    tok = FakeTok(default_responder)
    ctx = make_ctx(tok, retriever=FakeRetriever([]),
                   features={"fast_path": False, "replanning": False},
                   tmp=tmp_path)
    res = run_executive("Why is the sky blue according to Rayleigh "
                        "scattering?", "q_hist", ctx=ctx)
    assert res["termination_reason"] in ("INSUFFICIENT_INFORMATION",
                                         "STALLED")
    assert res["evidence_status"] in ("INSUFFICIENT_INFORMATION",)
