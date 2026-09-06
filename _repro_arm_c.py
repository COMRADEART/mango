"""Arm C shape: verification off, replanning off, same mixed retrieval."""
import sys, json
sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath\src")
sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath\tests")

from test_executive_core import FakeTok, make_ctx  # noqa: E402
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
    def search(self, query, k=3):
        if "obscure" in query:
            return []
        return [{"source_id": "w", "chunk_id": "c1",
                 "text": "Rayleigh scattering makes the sky blue."}]


def responder(prompt):
    if "JSON execution plan" in prompt:
        return PLAN
    if "Combine the step results" in prompt:
        return "Evidence [w:c1] says Rayleigh scattering.\nAnswer: Rayleigh scattering"
    return "Answer: Rayleigh scattering"


tok = FakeTok(responder)
ctx = make_ctx(tok, registry=None, retriever=MixedRetriever(),
               features={"fast_path": False, "replanning": False,
                         "verification": False, "correction_gate": False})
res = run_executive("Why is the sky blue according to Rayleigh scattering?",
                    "q_repro_c", ctx=ctx, answer_type="text")
print({k: res[k] for k in ("termination_reason", "evidence_status",
                           "final_answer")})