"""Adversarial verification: is exceeded()'s max_replans axis dead, and
does budget_usage under-report replans/plan_attempts/steps_executed?"""
from __future__ import annotations
import json, sys, tempfile

from sciencemath.executive import budgets as bmod
from sciencemath.executive.runner import ExecContext, run_executive

PLAN_JSON = json.dumps({"steps": [
    {"id": "s1", "action": "RETRIEVE", "description": "find facts",
     "depends_on": [], "input": "why is the sky blue"},
    {"id": "s2", "action": "SYNTHESIZE", "description": "combine",
     "depends_on": ["s1"], "input": ""},
]})

def default_responder(prompt):
    if "JSON execution plan" in prompt or "previous plan was invalid" in prompt.lower():
        return PLAN_JSON
    if "Combine the step results" in prompt:
        return "The sky is blue due to Rayleigh scattering.\nAnswer: Rayleigh scattering"
    return "Step: compute.\nAnswer: 42"

class FakeTok:
    pad_token_id = 0
    eos_token_id = 1
    def __init__(self, responder): self.responder = responder
    def apply_chat_template(self, messages, **kw):
        return "User: " + messages[0]["content"] + "\nAssistant:"
    def __call__(self, text, return_tensors=None, truncation=None,
                 max_length=None):
        import torch
        self.last_prompt = text
        return {"input_ids": torch.tensor([[1, 2, 3]])}
    def decode(self, ids, skip_special_tokens=True):
        return self.responder(self.last_prompt)

class FakeModel:
    device = "cpu"
    def __init__(self, tok): self.tok = tok
    def generate(self, **kw):
        import torch
        return torch.cat([kw["input_ids"], torch.tensor([[7, 7, 7]])], dim=1)

class FakeRetriever:
    def __init__(self, hits): self.hits = hits; self.queries = []
    def search(self, query, k=3):
        self.queries.append(query)
        return self.hits

def make_ctx(retriever):
    tok = FakeTok(default_responder)
    return ExecContext(
        model=FakeModel(tok), tokenizer=tok,
        registry=None, retriever=retriever,
        generation={"seed": 42, "max_new_tokens": 64},
        features={"fast_path": False, "replanning": True},
    )

print("=== A) run that replans (empty retrieval) ===")
retr = FakeRetriever([])
ctx = make_ctx(retr)
res = run_executive("Why is the sky blue according to Rayleigh scattering?",
                    "q_replan", ctx=ctx)
bu = res["state"].get("budget_usage") or {}
print("result replans =", res["replans"], " queries =", len(retr.queries))
print("state['budget_usage'] =", {k: bu.get(k) for k in
      ("replans", "plan_attempts", "steps_executed", "model_calls")})
print("under-reports replans as 0:", bu.get("replans") == 0 and res["replans"] > 0)

print()
print("=== B) config max_replans=0: does the whole run die? ===")
ctx2 = make_ctx(FakeRetriever([{"source_id": "w", "chunk_id": "c1",
                                "text": "Rayleigh scattering makes the sky blue."}]))
ctx2.budgets = bmod.Budgets(max_replans=0)
res2 = run_executive("Why is the sky blue according to Rayleigh scattering?",
                     "q_cap0", ctx=ctx2)
print("termination_reason =", res2["termination_reason"])
print("failure_category   =", res2["failure_category"])
print("steps_executed     =", res2["steps_executed"])
print("final_answer       =", res2["final_answer"])

print()
print("=== C) default budgets: does exceeded() ever fire max_replans? ===")
u = bmod.default_usage()
print("exceeded(default usage, default budgets) =", bmod.exceeded(u, bmod.Budgets()))
print("usage['replans'] after a replanning run =", ctx.usage.get("replans"))
print("usage['plan_attempts'] after the run    =", ctx.usage.get("plan_attempts"))
print("usage['steps_executed'] after the run   =", ctx.usage.get("steps_executed"))