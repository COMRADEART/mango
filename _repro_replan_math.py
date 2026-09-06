"""Repro part 2: MATH question whose model plan starts with a RETRIEVE
step that fails; the deterministic fallback (s1=MATH_TOOL, s2=SYNTHESIZE)
must be silently skipped due to stale completed_steps."""
import json, sys, tempfile
import torch
from sciencemath.executive.runner import ExecContext, run_executive
from sciencemath.executive import budgets as bmod

calls = {"plan": 0, "retrievals": 0, "model_steps": 0, "calc": []}

# model plan for a MATH question that (wrongly) begins with RETRIEVE
PLAN_MATH = json.dumps({"steps": [
    {"id": "s1", "action": "RETRIEVE", "description": "look up formula",
     "depends_on": [], "input": "average formula"},
    {"id": "s2", "action": "REASON", "description": "derive the average",
     "depends_on": ["s1"], "input": ""},
    {"id": "s3", "action": "SYNTHESIZE", "description": "combine",
     "depends_on": ["s2"], "input": ""}]})

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

def responder(prompt):
    if "JSON execution plan" in prompt:
        calls["plan"] += 1
        return PLAN_MATH
    calls["model_steps"] += 1
    return "reasoning\nAnswer: 34"

class FakeRetriever:
    def search(self, query, k=3):
        calls["retrievals"] += 1
        return []  # always empty -> RETRIEVE FAILED

class FakeRegistry:
    def invoke(self, name, args):
        from types import SimpleNamespace
        calls["calc"].append((name, args))
        return SimpleNamespace(status="ok", error=None, result=34)

def go(tag, budgets):
    tok = FakeTok(responder)
    ctx = ExecContext(
        model=FakeModel(tok), tokenizer=tok,
        registry=FakeRegistry(), retriever=FakeRetriever(),
        generation={"seed": 42, "max_new_tokens": 64},
        features={"fast_path": False},
        checkpointer=None, budgets=budgets)
    res = run_executive(
        "Calculate the average of 12, 34 and 56 students recorded per day.",
        tag, ctx=ctx, answer_type="numeric")
    print(f"--- {tag} ---")
    print("termination:", res["termination_reason"],
          "| category:", res["failure_category"],
          "| replans:", res["replans"])
    print("final_answer:", repr(res["final_answer"]))
    print("steps_executed:", res["steps_executed"],
          "| plan_source:", res["plan_source"],
          "| plan_version:", res["state"].get("plan_version"))
    print("n_observations:", len(res["observations"]))
    print("completed_steps:", res["state"].get("completed_steps"))
    print("final plan:", [(s["id"], s["action"]) for s in
                          (res["state"].get("plan") or {})["steps"]])
    print("calculator invocations:", calls["calc"])
    print("retrievals:", calls["retrievals"],
          "| step model calls:", calls["model_steps"])
    print("error:", res.get("error"))
    print("transitions:", res["transitions"])
    print()

go("MATH default-budgets", bmod.Budgets())
calls.update(plan=0, retrievals=0, model_steps=0, calc=[])
go("MATH max_replans=1", bmod.Budgets(max_replans=1))