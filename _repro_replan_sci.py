"""Repro part 3: reviewer's exact scenario — SCIENCE/RETRIEVAL question,
model plan s1=RETRIEVE/s2=SYNTHESIZE, empty corpus. Fallback has identical
ids. Count work executed AFTER the replan."""
import json, sys, tempfile
import torch
from sciencemath.executive.runner import ExecContext, run_executive
from sciencemath.executive import budgets as bmod
from sciencemath.executive import classify as cls_mod

calls = {"plan": 0, "retrievals": 0, "model_steps": 0}
ROUND = {"n": 0}  # which plan_version is executing

# force SCIENCE / RETRIEVAL classification (deterministic router is
# irrelevant here; we control the fake retriever anyway)
_orig = cls_mod.classify_problem
cls_mod.classify_problem = lambda q: {**_orig(q),
                                      "problem_type": "SCIENCE",
                                      "resources": "RETRIEVAL"}

PLAN_JSON = json.dumps({"steps": [
    {"id": "s1", "action": "RETRIEVE", "description": "find facts",
     "depends_on": [], "input": "why is the sky blue"},
    {"id": "s2", "action": "SYNTHESIZE", "description": "combine",
     "depends_on": ["s1"], "input": ""}]})

class FakeTok:
    pad_token_id = 0
    eos_token_id = 1
    def __init__(self, responder):
        self.responder = responder
        self.last_prompt = ""
    def apply_chat_template(self, messages, **kw):
        return "User: " + messages[0]["content"] + "\nAssistant:"
    def __call__(self, text, return_tensors="pt", truncation=False,
                 max_length=None):
        self.last_prompt = text
        ids = torch.arange(16).reshape(1, 16)
        return {"input_ids": ids,
                "attention_mask": torch.ones_like(ids)}
    def decode(self, ids, skip_special_tokens=True):
        return self.responder(self.last_prompt)

class FakeModel:
    device = "cpu"
    def __init__(self, tok):
        self.tok = tok
    def generate(self, **kw):
        base = kw["input_ids"]
        return torch.cat([base, torch.tensor([[7, 7, 7]])], dim=1)

snap = {"retr": 0, "steps": 0}

def responder(prompt):
    if "JSON execution plan" in prompt:
        calls["plan"] += 1
        return PLAN_JSON
    calls["model_steps"] += 1
    return "guessing\nAnswer: blue"

class FakeRetriever:
    def search(self, query, k=3):
        calls["retrievals"] += 1
        return []  # empty corpus -> RETRIEVE FAILED

def go(tag, budgets):
    calls.update(plan=0, retrievals=0, model_steps=0)
    tok = FakeTok(responder)
    ctx = ExecContext(
        model=FakeModel(tok), tokenizer=tok,
        registry=None, retriever=FakeRetriever(),
        generation={"seed": 42, "max_new_tokens": 64},
        features={"fast_path": False},
        checkpointer=None, budgets=budgets)
    res = run_executive(
        "Why is the sky blue according to Rayleigh scattering?",
        tag, ctx=ctx)
    print(f"--- {tag} ---")
    print("termination:", res["termination_reason"],
          "| category:", res["failure_category"],
          "| replans:", res["replans"],
          "| plan_version:", res["state"].get("plan_version"))
    print("final_answer:", repr(res["final_answer"]))
    print("steps_executed:", res["steps_executed"])
    print("completed_steps:", res["state"].get("completed_steps"))
    print("amended plan ids/actions:",
          [(s["id"], s["action"])
           for s in (res["state"].get("plan") or {})["steps"]])
    print("n_observations:", len(res["observations"]))
    print("total retrievals:", calls["retrievals"],
          "| total step model calls:", calls["model_steps"])
    print("failure_fingerprints:",
          len(res["state"].get("failure_fingerprints", [])))
    print()

go("SCI default-budgets", bmod.Budgets())
go("SCI max_replans=1", bmod.Budgets(max_replans=1))