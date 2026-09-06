import sys
sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath\src")
sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath")

from tests.test_executive_core import (
    FakeTok, default_responder, FakeRetriever, FakeRegistry, FakeModel)
from sciencemath.executive.runner import run_executive, ExecContext

def run(retriever_hits, label):
    tok = FakeTok(default_responder)
    ctx = ExecContext(
        model=FakeModel(tok), tokenizer=tok,
        registry=FakeRegistry(), retriever=FakeRetriever(retriever_hits),
        generation={"seed": 42, "max_new_tokens": 64},
    )
    res = run_executive("Why is the sky blue according to Rayleigh scattering?",
                        "q_" + label, ctx=ctx)
    print(f"[{label}] term={res['termination_reason']} replans={res['replans']}"
          f" plan_version={res['state'].get('plan_version')}")
    print("  transitions:", res["transitions"])
    replanning_hops = [t for t in res["transitions"] if t == "REPLANNING"]
    print("  REPLANNING hops:", len(replanning_hops), " while replans counter =", res["replans"])

run([{"source_id": "w", "chunk_id": "c1", "text": "Rayleigh scattering makes the sky blue."}], "ok")
run([], "empty_retrieval")