import sys, json
sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath\src")
sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath")

from tests.test_executive_core import (
    FakeTok, default_responder, FakeRetriever, FakeRegistry, make_ctx, FakeModel, FakeTok)
from sciencemath.executive.runner import run_executive, ExecContext
from sciencemath.executive import state as st

hits = [{"source_id": "w", "chunk_id": "c1",
         "text": "Rayleigh scattering makes the sky blue."}]
tok = FakeTok(default_responder)
ctx = ExecContext(
    model=FakeModel(tok), tokenizer=tok,
    registry=FakeRegistry(), retriever=FakeRetriever(hits),
    generation={"seed": 42, "max_new_tokens": 64},
)
res = run_executive("Why is the sky blue according to Rayleigh scattering?",
                    "q_probe", ctx=ctx)
print("termination:", res["termination_reason"], "replans:", res["replans"])
print("transitions:", res["transitions"])

# count VERIFYING entries vs actual verify calls per round
verifying = [t for t in res["transitions"] if t == "VERIFYING"]
print("VERIFYING hops in trace:", len(verifying))