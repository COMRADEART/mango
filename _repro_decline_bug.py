"""Repro: answer_should_decline discards VERIFIED answers when one
RETRIEVE step was empty (arm C/D shape: replanning disabled, no MATH_TOOL)."""
import sys, json
sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath\src")
sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath\tests")

from test_executive_core import FakeTok, FakeModel, make_ctx  # noqa: E402
from sciencemath.executive.runner import run_executive  # noqa: E402

PLAN = json.dumps({"steps": [
    {"id": "s1", "action": "RETRIEVE", "description": "look up X",
     "depends_on": [], "input": "obscure query that fails"},
    {"id": "s2", "action": "RETRIEVE", "description": "look up Y",
     "depends_on": [], "input": "rayleigh scattering sky blue"},
    {"id": "s3", "action": "SYNTHESIZE", "description": "combine",
     "depends_on": ["s2"], "input": ""},
]})


class MixedRetriever:
    """First query (s1) empty; second query (s2) returns good chunks."""
    def search(self, query, k=3):
        if "obscure" in query:
            return []
        return [{"source_id": "w", "chunk_id": "c1",
                 "text": "Rayleigh scattering makes the sky blue."}]


def responder(prompt):
    if "JSON execution plan" in prompt or "previous plan was invalid" \
            in prompt.lower():
        return PLAN
    if "Combine the step results" in prompt:
        return ("Evidence [w:c1] says Rayleigh scattering.\n"
                "Answer: Rayleigh scattering")
    return "Answer: Rayleigh scattering"


tok = FakeTok(responder)
ctx = make_ctx(tok, registry=None, retriever=MixedRetriever(),
               features={"fast_path": False, "replanning": False})  # arm D
res = run_executive("Why is the sky blue according to Rayleigh scattering?",
                    "q_repro", ctx=ctx, answer_type="text")
for k in ("termination_reason", "evidence_status", "final_answer"):
    print(f"{k}: {res[k]!r}")
print("plan_source:", res["plan_source"], "steps:", res["steps_executed"])
print("observations:", [(o["step_id"], o["action"], o["status"])
                        for o in res["observations"]])

assert res["termination_reason"] == "CONFLICTING_EVIDENCE", "not reproduced"
assert res["evidence_status"] == "VERIFIED"
assert res["final_answer"] == "There is insufficient information to answer."
print("BUG REPRODUCED: verified+cited answer discarded, mislabeled CONFLICTING_EVIDENCE")