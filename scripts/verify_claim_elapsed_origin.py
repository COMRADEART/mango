"""Adversarial check of runner.py:441 claim (current code).

Scenario: plan attempt 1 invalid (60s), retry valid (60s) -> planning
burns 120s. max_total_seconds=180. If elapsed_s started at first step
end (claim), execution would get 180s AFTER planning (~360s wall).
If elapsed_s starts at run start (current code), first step guard sees
~120s and the run must terminate at ~180s wall total.
"""
import sys
import time as _time

sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath\src")
sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath\tests")

CLOCK = {"now": 1000.0}
_time.perf_counter = lambda: CLOCK["now"]

import json  # noqa: E402
import tempfile  # noqa: E402
from test_executive_core import FakeTok, FakeRetriever, FakeRegistry, make_ctx  # noqa: E402
from sciencemath.executive.runner import run_executive  # noqa: E402

PLAN_JSON = json.dumps({"steps": [
    {"id": "s1", "action": "RETRIEVE", "description": "find",
     "depends_on": [], "input": "rayleigh"},
    {"id": "s2", "action": "SYNTHESIZE", "description": "combine",
     "depends_on": ["s1"], "input": ""}]})

Q = "Why is the sky blue according to Rayleigh scattering?"
CALL_SECONDS = 60.0


def responder(prompt):
    CLOCK["now"] += CALL_SECONDS
    if "Output ONLY the JSON object" in prompt:
        return PLAN_JSON                       # retry attempt valid
    if "JSON execution plan" in prompt:
        return "not json at all"               # attempt 1 invalid
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

CLOCK["now"] = 1000.0
res = run_executive(Q, "q_check", ctx=ctx)
true_wall = CLOCK["now"] - 1000.0
bg = res["state"].get("budget_usage") or {}
print("termination_reason        =", res["termination_reason"])
print("failure_category          =", res["failure_category"])
print("true wall (fake clock)    =", round(true_wall, 1), "s")
print("budget_usage.elapsed_s    =", bg.get("elapsed_s"))
print("latency_s                 =", res["latency_s"])
print("model_calls               =", res["model_calls"])
print("plan_attempts             =", res["plan_attempts"])
print("=> wall 360 vs ~180?      ", "TRUE-WALL-CAPPED-AT-180"
      if true_wall <= 181.0 else "BUG: wall exceeded cap by",
      round(true_wall - 180.0, 1))
print("=> elapsed_s == latency_s within rounding:",
      abs((bg.get("elapsed_s") or 0) - res["latency_s"]) < 0.01)