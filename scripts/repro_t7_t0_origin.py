"""Adversarial verification of runner.py:441 claim.

Part 1: _t0 origin is at the FIRST budget guard (after step 1), so
elapsed_s excludes classification + understanding + up to 2 plan model
calls + step-1 latency -> max_total_seconds can be overshot.
Part 2: _t0 persists into checkpoint JSON and result['state']; a state
loaded back from the checkpoint (the documented resume payload) makes
elapsed_s negative in a fresh process, so 'exceeded' can never fire on
the elapsed axis.
"""
import json
import sys
import tempfile
import time as _time

sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath\src")
sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath\tests")

CLOCK = {"now": 1000.0}

class FakePerf:
    def __call__(self):
        return CLOCK["now"]

_time.perf_counter = FakePerf()  # runner does `import time` -> shared module

from test_executive_core import FakeTok, FakeRetriever, FakeRegistry, make_ctx
from sciencemath.executive import checkpoint as ckpt
from sciencemath.executive import budgets as bmod
from sciencemath.executive.runner import run_executive, _execute_plan

PLAN_JSON = (
    '{"steps": ['
    '{"id": "s1", "action": "RETRIEVE", "description": "find",'
    ' "depends_on": [], "input": "rayleigh"},'
    '{"id": "s2", "action": "SYNTHESIZE", "description": "combine",'
    ' "depends_on": ["s1"], "input": ""}]}')

Q = "Why is the sky blue according to Rayleigh scattering?"
QID = "q_t0"

MODEL_CALL_SECONDS = 60.0   # pretend each generation call takes 60 s

def responder(prompt):
    # every model call costs 60 s of fake wall time
    CLOCK["now"] += MODEL_CALL_SECONDS
    if "Output ONLY the JSON object" in prompt:
        return PLAN_JSON                      # plan retry succeeds
    if "JSON execution plan" in prompt:
        return "not json at all"              # plan attempt 1 invalid
    if "Combine the step results" in prompt:
        return ("The sky is blue due to Rayleigh scattering [w:c1].\n"
                "Answer: Rayleigh scattering")
    return "Step: compute.\nAnswer: 42"

tmp = tempfile.mkdtemp()
HITS = [{"source_id": "w", "chunk_id": "c1",
         "text": "Rayleigh scattering makes the sky blue."}]

tok = FakeTok(responder)
ctx = make_ctx(tok, registry=FakeRegistry(),
               retriever=FakeRetriever(list(HITS)),
               features={"fast_path": False}, tmp=tmp)
ctx.budgets.max_total_seconds = 180.0

print("=== PART 1: wrong origin ===")
print("max_total_seconds =", ctx.budgets.max_total_seconds)
CLOCK["now"] = 1000.0
res = run_executive(Q, QID, ctx=ctx)
true_wall = CLOCK["now"] - 1000.0
print("true wall time (fake clock) =", true_wall, "s")
print("termination_reason =", res["termination_reason"])
print("budget_usage last seen by guard =", res["state"].get("budget_usage"))
print("latency_s reported =", res["latency_s"])
print("_t0 in result['state'] =", res["state"].get("_t0"))
print("=> cap 180 s, true wall %.0f s, guard-observed elapsed %s"
      % (true_wall, (res["state"].get("budget_usage") or {}).get("elapsed_s")))

print()
print("=== PART 2: _t0 persisted / negative elapsed on resume ===")
ck = ckpt.RunCheckpointer(tmp)
payload = ck.load(QID)
print("checkpoint state contains _t0:", "_t0" in payload["state"],
      "->", payload["state"].get("_t0"))

# Simulate the documented resume: load checkpoint state in a FRESH
# process (perf_counter restarts near zero), keep completed_steps so
# executed steps are skipped (T7.30), add a pending step, and let the
# budget guard run inside _execute_plan exactly as in production.
resumed = json.loads(json.dumps(payload["state"]))
resumed["status"] = "OBSERVING"
resumed["plan"]["steps"] = resumed["plan"]["steps"] + [
    {"id": "s3", "action": "SYNTHESIZE", "description": "retry synth",
     "depends_on": [], "input": ""}]
CLOCK["now"] = 10.0   # fresh process: perf_counter restarts near zero

def responder2(prompt):
    CLOCK["now"] += MODEL_CALL_SECONDS
    return "The sky is blue.\nAnswer: Rayleigh scattering"

tok2 = FakeTok(responder2)
ctx2 = make_ctx(tok2, registry=FakeRegistry(), retriever=FakeRetriever([]),
                features={"fast_path": False}, tmp=None)
ctx2.budgets.max_total_seconds = 180.0
state2 = _execute_plan(resumed, {}, ctx2, [], [])
bg = state2.get("budget_usage") or {}
print("RESUMED guard elapsed_s =", bg.get("elapsed_s"))
print("exceeded() on resumed usage =",
      bmod.exceeded(bg, ctx2.budgets),
      "(elapsed axis can never fire with a negative elapsed_s)")
print("budget_usage stored in state2 =", bg)