"""T25 remediation tests (authorization §7 synthetic reproduction, §10
deterministic GENERAL matrix, §21 negative controls).

Synthetic non-blind reproduction: every terminal status branch of the
executive runtime is exercised on stub model/registry/retriever with
freshly authored synthetic questions. NO T24 private material is
referenced, loaded, or paraphrased (authorization §3/§13). The frozen
dispatch evaluator rule is imported unchanged and asserted as the
backstop; t25_protocol.status_contract adds the closed-set guard."""
from __future__ import annotations

import json

import pytest

from sciencemath.executive import state as st
from sciencemath.executive import budgets as bmod
from sciencemath.executive import checkpoint as ckpt
from sciencemath.executive.runner import ExecContext, run_executive, _hard_fail
from t23_protocol.evaluation import evaluate_capability
from t23_protocol.provider import ProductionDispatchError, ProductionRouterProvider
from t25_protocol import status_contract


# ---- stubs (same idiom as test_executive_core.py) ---------------------------
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
        return {"input_ids": ids, "attention_mask": torch.ones_like(ids)}

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


class FakeRegistry:
    def __init__(self, value=42, error=None):
        self.value = value
        self.error = error

    def invoke(self, name, arguments):
        from types import SimpleNamespace
        if self.error:
            return SimpleNamespace(status="error", error=self.error,
                                   result=None)
        return SimpleNamespace(status="ok", error=None, result=self.value)


class FakeRetriever:
    def __init__(self, hits=None, error=None):
        self.hits = hits or []
        self.error = error
        self.queries = []

    def search(self, query, k=3):
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.hits


def _ctx(tok, registry=None, retriever=None, features=None, budgets=None):
    return ExecContext(
        model=FakeModel(tok), tokenizer=tok,
        registry=registry or FakeRegistry(),
        retriever=retriever or FakeRetriever([]),
        generation={"seed": 42, "max_new_tokens": 64},
        features=dict(features) if features else None,
    )
    # budgets are overridden by the caller via ctx.budgets when needed


def _synth_only_responder(prompt):
    return "Considered carefully.\nAnswer: 42"


def _plan_responder(prompt):
    plan = json.dumps({"steps": [
        {"id": "s1", "action": "RETRIEVE", "description": "find facts",
         "depends_on": [], "input": "synthetic retrieval target"},
        {"id": "s2", "action": "SYNTHESIZE", "description": "combine",
         "depends_on": ["s1"], "input": ""},
    ]})
    if "JSON execution plan" in prompt:
        return plan
    if "Combine the step results" in prompt:
        return ("The retrieved fact applies [c1].\nAnswer: 42")
    return "Step done.\nAnswer: 42"


STATUSES = set(st.EVIDENCE_STATUSES)


def _assert_defined_status(res):
    """§7 core invariant: NO terminal leaves the runtime without a
    defined evidence status (rule R1)."""
    status = res.get("evidence_status")
    assert isinstance(status, str) and status, \
        f"terminal without a status: {res.get('termination_reason')}"
    assert status in STATUSES, f"status outside the closed set: {status!r}"
    assert status != "UNKNOWN"


# ---- §7: every terminal status branch ---------------------------------------
def test_fast_path_terminal_has_status():
    tok = FakeTok(_synth_only_responder)
    res = run_executive("What color is the sky?", "t25_fast",
                        ctx=_ctx(tok, features={"fast_path": True}))
    assert res["termination_reason"] == "SOLVED_UNVERIFIED"
    assert res["evidence_status"] == "PARTIALLY_SUPPORTED"


def test_off_arm_terminal_has_status():
    tok = FakeTok(_synth_only_responder)
    res = run_executive("What color is the sky?", "t25_off",
                        ctx=_ctx(tok, features={"executive": False}))
    assert res["termination_reason"] == "SOLVED_UNVERIFIED"
    assert res["evidence_status"] == "PARTIALLY_SUPPORTED"


def test_verified_tool_match_terminal():
    plan = json.dumps({"steps": [
        {"id": "s1", "action": "MATH_TOOL", "description": "compute",
         "depends_on": [], "input": "6*7"},
        {"id": "s2", "action": "SYNTHESIZE", "description": "combine",
         "depends_on": ["s1"], "input": ""},
    ]})

    def _responder(prompt):
        if "JSON execution plan" in prompt:
            return plan
        return "Computed.\nAnswer: 42"

    tok = FakeTok(_responder)
    res = run_executive(
        "Compute the value 6 times 7 with the calculator.", "t25_tool",
        ctx=_ctx(tok, registry=FakeRegistry(value=42),
                 features={"fast_path": False}))
    assert res["termination_reason"] == "SOLVED_VERIFIED"
    _assert_defined_status(res)
    assert res["evidence_status"] == "VERIFIED"


def test_retrieval_backed_clean_citations_verified():
    hits = [{"source_id": "w", "chunk_id": "c1",
             "text": "Synthetic evidence text about Rayleigh scattering."}]
    tok = FakeTok(_plan_responder)
    res = run_executive(
        "Why is the sky blue according to Rayleigh scattering physics?",
        "t25_cite", ctx=_ctx(tok, retriever=FakeRetriever(hits),
                             features={"fast_path": False}))
    assert res["termination_reason"] in ("SOLVED_VERIFIED", "SOLVED_UNVERIFIED")
    _assert_defined_status(res)


def test_unverified_no_signals_is_uncertain():
    tok = FakeTok(_synth_only_responder)
    # long multi-step wording, no tool/retrieval cues, resources NONE:
    # single-SYNTHESIZE fallback plan, no evidence signals -> UNCERTAIN
    res = run_executive(
        "Discuss how everyday routines organize a household "
        "schedule and what that reveals about time management "
        "practices across many different kinds of families and "
        "settings over the years in various places and seasons, "
        "in general terms.", "t25_uncertain",
        ctx=_ctx(tok, features={"fast_path": False, "replanning": False}))
    assert res["termination_reason"] in ("SOLVED_UNVERIFIED", "SOLVED_VERIFIED")
    _assert_defined_status(res)
    assert res["evidence_status"] == "UNCERTAIN"


def test_empty_final_text_is_insufficient_information():
    tok = FakeTok(lambda p: "")  # model empty output
    ctx = _ctx(tok, features={"fast_path": False, "replanning": False})
    ctx.budgets = bmod.Budgets(max_model_calls=64, max_plan_attempts=1)
    res = run_executive(
        "A very long synthetic open question about ordinary things "
        "that keeps growing and grows with many plain words but no "
        "cues at all in it whatsoever here.", "t25_empty",
        ctx=ctx)
    assert res["termination_reason"] == "INSUFFICIENT_INFORMATION"
    assert res["evidence_status"] == "INSUFFICIENT_INFORMATION"


def test_empty_retrieval_decline_is_insufficient_information():
    tok = FakeTok(_plan_responder)
    res = run_executive(
        "Who discovered the synthetic element in the standard "
        "reference and when?", "t25_decline",
        ctx=_ctx(tok, retriever=FakeRetriever([]),
                 features={"fast_path": False, "replanning": False}))
    assert res["evidence_status"] == "INSUFFICIENT_INFORMATION"


def test_conflict_question_declines_with_conflicting_evidence():
    conflicting = ("The tank holds 30 liters of coolant. The tank "
                   "however holds 40 liters of coolant. How many "
                   "liters does the tank hold?")
    tok = FakeTok(_synth_only_responder)
    res = run_executive(conflicting, "t25_conflict",
                        ctx=_ctx(tok, features={"fast_path": False,
                                                "replanning": False}))
    assert res["evidence_status"] == "CONFLICTING_EVIDENCE"


def test_stalled_replan_identical_plan_derives_defined_status_empty_retrieval():
    """Retrieval-cued question, retriever returns nothing: the amended
    plan is fingerprint-identical (RETRIEVE already present) -> STALLED;
    the derived status is INSUFFICIENT_INFORMATION (RETRIEVAL_EMPTY is a
    recorded unusable-retrieval signal), never UNKNOWN."""
    tok = FakeTok(_plan_responder)
    res = run_executive(
        "Who discovered the synthetic element and in which year exactly?",
        "t25_stalled_empty", ctx=_ctx(tok, retriever=FakeRetriever([]),
                                      features={"fast_path": False}))
    assert res["termination_reason"] == "STALLED"
    _assert_defined_status(res)
    assert res["evidence_status"] == "INSUFFICIENT_INFORMATION"


def test_stalled_replan_derives_defined_status_retrieval_error():
    """Retriever raises: RETRIEVAL_ERROR is not an empty-retrieval
    signal, so the frozen engine yields UNCERTAIN (no usable evidence,
    unverified) — a defined, honest status; never UNKNOWN."""
    tok = FakeTok(_plan_responder)
    res = run_executive(
        "Who discovered the synthetic element and in which year exactly?",
        "t25_stalled_error",
        ctx=_ctx(tok, retriever=FakeRetriever(error=RuntimeError("down")),
                 features={"fast_path": False}))
    assert res["termination_reason"] == "STALLED"
    _assert_defined_status(res)
    assert res["evidence_status"] == "UNCERTAIN"


def test_budget_exhausted_pre_step_derives_defined_status():
    tok = FakeTok(_plan_responder)
    ctx = _ctx(tok, features={"fast_path": False})
    ctx.budgets = bmod.Budgets(max_model_calls=0)
    res = run_executive(
        "Who discovered the synthetic element and in which year exactly?",
        "t25_budget0", ctx=ctx)
    assert res["termination_reason"] == "BUDGET_EXHAUSTED"
    _assert_defined_status(res)
    assert res["evidence_status"] == "UNCERTAIN"  # no observations recorded


def test_budget_exhausted_post_step_derives_defined_status():
    tok = FakeTok(_plan_responder)
    hits = [{"source_id": "w", "chunk_id": "c1", "text": "Synthetic fact."}]
    ctx = _ctx(tok, retriever=FakeRetriever(hits),
               features={"fast_path": False})
    # 1 call funds the (accepted) model plan; the SYNTH step runs, then
    # the post-step guard terminates with observations recorded
    ctx.budgets = bmod.Budgets(max_model_calls=2)
    res = run_executive(
        "Who discovered the synthetic element and in which year exactly?",
        "t25_budget1", ctx=ctx)
    assert res["termination_reason"] == "BUDGET_EXHAUSTED"
    _assert_defined_status(res)
    # usable retrieval evidence was recorded before the cap fired
    assert res["evidence_status"] == "PARTIALLY_SUPPORTED"


def test_budget_exhausted_step_wall_time_derives_defined_status():
    tok = FakeTok(_plan_responder)
    hits = [{"source_id": "w", "chunk_id": "c1", "text": "Synthetic fact."}]
    ctx = _ctx(tok, retriever=FakeRetriever(hits),
               features={"fast_path": False})
    ctx.budgets = bmod.Budgets(max_step_seconds=0.0)
    res = run_executive(
        "Who discovered the synthetic element and in which year exactly?",
        "t25_budget_wall", ctx=ctx)
    assert res["termination_reason"] == "BUDGET_EXHAUSTED"
    _assert_defined_status(res)


def test_system_error_hard_fail_derives_defined_status(tmp_path):
    class _Boom(ckpt.RunCheckpointer):
        def save(self, state, graph):
            raise RuntimeError("checkpoint save boom")

    tok = FakeTok(_plan_responder)
    ctx = ExecContext(
        model=FakeModel(tok), tokenizer=tok, registry=FakeRegistry(),
        retriever=FakeRetriever([{"source_id": "w", "chunk_id": "c1",
                                  "text": "Synthetic fact."}]),
        generation={"seed": 42, "max_new_tokens": 64},
        features={"fast_path": False},
        checkpointer=_Boom(tmp_path))
    res = run_executive(
        "Who discovered the synthetic element and in which year exactly?",
        "t25_syserr", ctx=ctx)
    assert res["termination_reason"] == "SYSTEM_ERROR"
    assert res["failure_category"] == "SYSTEM_ERROR"
    assert res["error"]
    _assert_defined_status(res)


def test_hard_fail_malformed_state_uses_transition_error_branch():
    """_hard_fail on a malformed state dict exercises the TransitionError
    fallback branch and still derives a defined status."""
    state = _hard_fail({}, "SYSTEM_ERROR", "malformed", observations={})
    assert state["status"] == st.FAILED
    assert state["termination_reason"] == "SYSTEM_ERROR"
    assert state["evidence_status"] == "UNCERTAIN"


def test_provider_never_sees_an_absent_status_across_all_terminals():
    """§7 closure: pack the terminal classes through the provider-status
    chain (evidence_status or 'UNKNOWN') — every terminal class now
    yields a defined status, so the 'UNKNOWN' fallback term is dead."""
    from sciencemath.executive import runner as runner_mod

    class _BoomSave(ckpt.RunCheckpointer):
        def save(self, state, graph):
            raise RuntimeError("boom")

    cases = [
        ("What color is the sky?",
         _ctx(FakeTok(_synth_only_responder), features={"fast_path": True})),
        ("What color is the sky?",
         _ctx(FakeTok(_synth_only_responder), features={"executive": False})),
        ("Who discovered the synthetic element and in which year exactly?",
         _ctx(FakeTok(_plan_responder), retriever=FakeRetriever([]),
              features={"fast_path": False})),
        ("Who discovered the synthetic element and in which year exactly?",
         _ctx(FakeTok(_plan_responder), features={"fast_path": False})),
        ("What color is the sky?",
         _ctx(FakeTok(_synth_only_responder), features={"fast_path": False,
                                                        "replanning": False})),
    ]
    for question, ctx in cases:
        res = run_executive(question, "t25_provider", ctx=ctx)
        status = res.get("evidence_status") or res.get("status") or "UNKNOWN"
        assert status != "UNKNOWN", res.get("termination_reason")
        _assert_defined_status(res)


# ---- §10: deterministic GENERAL matrix --------------------------------------
MATRIX = [
    # (label, question, retriever, features, budget-override, expected status)
    ("fast_path", "What color is the sky?", None, {"fast_path": True}, None,
     "PARTIALLY_SUPPORTED"),
    ("synth_only_uncertain", "A very long synthetic open question about "
     "ordinary things that keeps going on and on about routines and "
     "seasons and places and habits in general terms without any cues "
     "at all here.", None,
     {"fast_path": False, "replanning": False}, None, "UNCERTAIN"),
    ("retrieval_empty_decline", "Who discovered the synthetic element "
     "and in which year exactly?", FakeRetriever([]),
     {"fast_path": False, "replanning": False}, None,
     "INSUFFICIENT_INFORMATION"),
    ("stalled_empty", "Who discovered the synthetic element and in "
     "which year exactly?", FakeRetriever([]),
     {"fast_path": False}, None, "INSUFFICIENT_INFORMATION"),
    ("retrieval_error_uncertain", "Who discovered the synthetic element "
     "and in which year exactly?",
     FakeRetriever(error=RuntimeError("down")), {"fast_path": False}, None,
     "UNCERTAIN"),
    ("conflict", "The tank holds 30 liters of coolant. The tank "
     "however holds 40 liters of coolant. How many liters does the "
     "tank hold?", None, {"fast_path": False, "replanning": False}, None,
     "CONFLICTING_EVIDENCE"),
]


@pytest.mark.parametrize("label,question,retriever,features,budgets,expected",
                         MATRIX, ids=[m[0] for m in MATRIX])
def test_deterministic_general_matrix(label, question, retriever, features,
                                      budgets, expected):
    statuses = []
    for run in range(2):
        tok = FakeTok(_plan_responder if label.startswith("retrieval")
                      else _synth_only_responder)
        ctx = _ctx(tok, retriever=retriever, features=features)
        if budgets is not None:
            ctx.budgets = budgets
        res = run_executive(question, f"t25_matrix_{label}_{run}", ctx=ctx)
        statuses.append((res["evidence_status"],
                         res["termination_reason"]))
        assert res["evidence_status"] == expected, \
            (label, res["termination_reason"], res["evidence_status"])
    # nondeterministic-status negative control: identical inputs give
    # identical statuses
    assert statuses[0] == statuses[1]


# ---- §21: negative controls at the dispatch boundary -------------------------
def _row(status):
    return {"case_id": "c", "selected_capability": "GENERAL",
            "executed_capability": "GENERAL", "status": status,
            "dispatch_match": True}


def test_frozen_dispatch_rule_unknown_unmatched():
    rows = evaluate_capability([{
        "case_id": "c",
        "router_decision": {"selected_capability": "GENERAL"},
        "selected_capability_execution": {"capability": "GENERAL",
                                          "status": "UNKNOWN"},
    }])
    assert rows[0]["dispatch_match"] is False


@pytest.mark.parametrize("status", [None, "", 7, b"UNKNOWN", {}])
def test_frozen_dispatch_rule_malformed_status_fail_closed(status):
    rows = evaluate_capability([{
        "case_id": "c",
        "router_decision": {"selected_capability": "GENERAL"},
        "selected_capability_execution": {"capability": "GENERAL",
                                          "status": status},
    }])
    assert rows[0]["dispatch_match"] is False
    # the frozen rule is byte-identical to T24 and does NOT reject a
    # whitespace-only string — the T25 closed-set guard does (§21)
    ws = evaluate_capability([{
        "case_id": "c",
        "router_decision": {"selected_capability": "GENERAL"},
        "selected_capability_execution": {"capability": "GENERAL",
                                          "status": "   "},
    }])
    ok, reason = status_contract.validate_status("GENERAL", "   ")
    assert not ok and reason == "status_empty"


def test_t25_status_contract_fail_closed():
    ok, _ = status_contract.validate_status("GENERAL", "UNCERTAIN")
    assert ok
    for status in ("UNKNOWN", None, "", "   ", 7, "WIBBLE"):
        ok, reason = status_contract.validate_status("GENERAL", status)
        assert not ok and reason
    with pytest.raises(ValueError):
        status_contract.assert_status_valid("GENERAL", "UNKNOWN")
    with pytest.raises(ValueError):
        status_contract.assert_status_valid("GENERAL", "WIBBLE")
    with pytest.raises(KeyError):
        status_contract.status_set("NOT_A_CAPABILITY")


def test_t25_status_contract_all_capabilities_covered():
    sets = status_contract.load_contract()["closed_status_sets"]
    assert set(sets) == {"NO_TOOL", "KNOWLEDGE_RAG", "WEB_RESEARCH",
                         "DOCUMENT", "GENERAL"}
    assert "UNKNOWN" not in status_contract.status_set("GENERAL")
    assert "UNKNOWN" not in status_contract.status_set("DOCUMENT")


def test_t25_dispatch_rows_validator_fail_closed():
    good = {"case_id": "ok", "selected_capability": "GENERAL",
            "executed_capability": "GENERAL", "status": "UNCERTAIN",
            "dispatch_match": True}
    bad = {"case_id": "bad", "selected_capability": "GENERAL",
           "executed_capability": "GENERAL", "status": "UNKNOWN",
           "dispatch_match": False}
    report = status_contract.validate_dispatch_rows([good, bad])
    assert report["status"] == "FAIL"
    assert report["violations"][0]["case_id"] == "bad"
    ok_report = status_contract.validate_dispatch_rows([good])
    assert ok_report["status"] == "PASS"


def test_provider_exception_fail_closed_missing_general_context():
    # construct without the corpus-loading __init__ (synthetic test —
    # no corpus required to assert the dispatch guard)
    provider = object.__new__(ProductionRouterProvider)
    provider.general_context = None
    with pytest.raises(ProductionDispatchError):
        provider._dispatch({"route_id": "GENERAL",
                            "selected_capability": "GENERAL"},
                           "q", {}, "case")