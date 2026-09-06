"""Adversarial verification: does run_executive resume from a checkpoint?

Re-invokes run_executive for the same question_id with the same
RunCheckpointer directory (simulating a crashed and restarted process)
and counts retrieval queries / registry invocations / model calls.
"""
import sys, tempfile

sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath\src")
sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath\tests")

from test_executive_core import (FakeTok, FakeRetriever, FakeRegistry,
                                 make_ctx, default_responder)
from sciencemath.executive import checkpoint as ckpt
from sciencemath.executive.runner import run_executive

tmp = tempfile.mkdtemp()
Q = "Why is the sky blue according to Rayleigh scattering?"
QID = "q_dup"
HITS = [{"source_id": "w", "chunk_id": "c1",
         "text": "Rayleigh scattering makes the sky blue."}]

def fresh_ctx():
    tok = FakeTok(default_responder)
    retr = FakeRetriever(list(HITS))
    ctx = make_ctx(tok, registry=FakeRegistry(), retriever=retr,
                   features={"fast_path": False}, tmp=tmp)
    return ctx, tok, retr

ctx1, tok1, retr1 = fresh_ctx()
r1 = run_executive(Q, QID, ctx=ctx1)
q1 = list(retr1.queries)
n1 = tok1.calls
ck = ckpt.RunCheckpointer(tmp)
print("after run1: checkpoint exists:", ck._path(QID).exists())
print("after run1: checkpoint completed_steps:",
      sorted(ck.completed_step_ids(QID)))

# "crash" and restart: brand-new ctx, same question_id, same checkpointer
ctx2, tok2, retr2 = fresh_ctx()
r2 = run_executive(Q, QID, ctx=ctx2)
q2 = list(retr2.queries)
n2 = tok2.calls

print("run1 retriever queries:", q1)
print("run2 retriever queries:", q2)
print("run2 re-executed retrievals:", q2 == q1)
print("run1 model calls:", n1, "run2 model calls:", n2,
      "run2 re-called model:", n2 == n1)
print("run2 completed_tool_signatures still present:",
      bool(ck.completed_tool_signatures(QID)) and
      "never consulted by runner")
print("run2 termination:", r2["termination_reason"],
      "steps_executed:", r2["steps_executed"])