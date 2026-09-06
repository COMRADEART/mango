"""Definitive adversarial check of the claim against CURRENT code:
run_executive crashes mid-question (after RETRIEVE + MATH_TOOL completed);
a fresh re-run with the same question_id and checkpointer dir must NOT
re-execute any completed tool/retrieval call."""
import json
import sys
import tempfile

sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath\src")
sys.path.insert(0, r"C:\Users\allam\Documents\new\model\sciencemath\tests")

from test_executive_core import (FakeTok, FakeRetriever, FakeRegistry,
                                 make_ctx, default_responder)
from sciencemath.executive import checkpoint as ckpt
from sciencemath.executive.runner import run_executive

tmp = tempfile.mkdtemp()
Q = "A car travels 30 m/s for 60 s. Calculate the total distance."
QID = "q_crash"
HITS = [{"source_id": "w", "chunk_id": "c1", "text": "distance facts"}]

counts = {"calc": 0, "search": 0}


class CountingRegistry:
    def __init__(self, inner):
        self.inner = inner

    def invoke(self, name, arguments):
        if name == "calculator":
            counts["calc"] += 1
        return self.inner.invoke(name, arguments)

    def manifest(self):
        return self.inner.manifest()


class CountingRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.queries = []

    def search(self, query, k=3):
        counts["search"] += 1
        self.queries.append(query)
        return self.hits


def fresh_ctx():
    tok = FakeTok(default_responder)
    return (make_ctx(tok, registry=CountingRegistry(FakeRegistry()),
                     retriever=CountingRetriever(list(HITS)),
                     features={"fast_path": False}, tmp=tmp), tok)


# run 1: crash simulation — run to completion of first two steps by
# using a real full run (the fake plan produces RETRIEVE + SYNTHESIZE;
# to also exercise MATH_TOOL we instead hand-build a checkpoint the way
# the runner itself writes one after each completed step)
ctx1, tok1 = fresh_ctx()
r1 = run_executive(Q, QID, ctx=ctx1)
print("run1:", r1["termination_reason"], "steps:", r1["steps_executed"],
      "tool_calls:", r1["tool_calls"], "retrievals:", r1["retrievals"])

# Now the crash scenario proper: hand-write a checkpoint as the runner
# does after step completion (RETRIEVE done, MATH_TOOL done, rest pending)
state = {
    "run_id": QID, "problem": Q, "status": "OBSERVING",
    "completed_steps": ["s1", "s2"],
    "plan": {"source": "model", "steps": [
        {"id": "s1", "action": "RETRIEVE", "description": "find facts",
         "depends_on": [], "input": "car speed"},
        {"id": "s2", "action": "MATH_TOOL", "description": "compute",
         "depends_on": ["s1"], "input": "30 * 60"},
        {"id": "s3", "action": "SYNTHESIZE", "description": "combine",
         "depends_on": ["s2"], "input": ""}]},
    "plan_version": 1, "replans": 0, "conflicts": [],
    "included_facts": ["A car travels 30 m/s for 60 s."],
    "distractors": [],
    "observations": [
        {"step_id": "s1", "action": "RETRIEVE", "status": "OK",
         "summary": "evidence: c1",
         "detail": {"chunks": [{"source_id": "w", "chunk_id": "c1",
                                "text": "car travels 30 m/s"}],
                    "signature": "x1"}},
        {"step_id": "s2", "action": "MATH_TOOL", "status": "OK",
         "summary": "1800", "detail": {"result": 1800, "signature": "x2"}},
    ],
}
ckpt.RunCheckpointer(tmp).save(state, {"nodes": [], "edges": []})

counts["calc"] = 0
counts["search"] = 0
ctx2, tok2 = fresh_ctx()
r2 = run_executive(Q, QID, ctx=ctx2)
print("run2 (crash resume):", r2["termination_reason"],
      "steps:", r2["steps_executed"], "resumed:", r2["state"].get("resumed"),
      "tool_calls:", r2["tool_calls"], "retrievals:", r2["retrievals"])
print("run2 duplicate calculator invocations:", counts["calc"])
print("run2 duplicate retriever searches:", counts["search"])
print("VERDICT:", "resume works, no duplicate tool/retrieval calls"
      if counts["calc"] == 0 and counts["search"] == 0
      else "CLAIM CONFIRMED: completed tool calls re-executed")