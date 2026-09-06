"""Adversarial verification: does retrieved chunk TEXT reach any model
prompt in the executive loop? Capture every prompt and check."""
import sys, json
sys.path.insert(0, "src")

from sciencemath.executive.runner import run_executive, ExecContext
from sciencemath.executive import checkpoint as ckpt

PLAN_JSON = json.dumps({"steps": [
    {"id": "s1", "action": "RETRIEVE", "description": "find facts",
     "depends_on": [], "input": "why is the sky blue"},
    {"id": "s2", "action": "SYNTHESIZE", "description": "combine",
     "depends_on": ["s1"], "input": ""},
]})


class FakeTok:
    pad_token_id = 0
    eos_token_id = 1
    prompts = []

    def apply_chat_template(self, messages, **kw):
        return "User: " + messages[0]["content"] + "\nAssistant:"

    def __call__(self, text, return_tensors="pt", truncation=False,
                 max_length=None):
        import torch
        FakeTok.prompts.append(text)
        ids = torch.arange(16).reshape(1, 16)
        return {"input_ids": ids, "attention_mask": torch.ones_like(ids)}

    def decode(self, ids, skip_special_tokens=True):
        # answer only from parametric knowledge; report what we saw
        return ("Answer: Rayleigh scattering")


class FakeModel:
    device = "cpu"
    def __init__(self, tok):
        self.tok = tok
    def generate(self, **kw):
        import torch
        base = kw["input_ids"]
        return torch.cat([base, torch.tensor([[7, 7, 7]])], dim=1)


class FakeRetriever:
    def search(self, query, k=3):
        return [{"source_id": "w", "chunk_id": "wiki-18716923:intro_3cee6746:0",
                 "text": "Rayleigh scattering makes the sky blue."}]


ctx = ExecContext(
    model=FakeModel(FakeTok()), tokenizer=FakeTok(),
    registry=None, retriever=FakeRetriever(),
    generation={"seed": 42, "max_new_tokens": 64},
    features={"fast_path": False},
)
res = run_executive("Why is the sky blue according to Rayleigh scattering?",
                    "q_ev", ctx=ctx)

CHUNK_TEXT = "Rayleigh scattering makes the sky blue"
print("=== ALL PROMPTS SEEN BY THE MODEL ===")
for i, p in enumerate(FakeTok.prompts):
    print(f"--- prompt {i} ---")
    print(p)
print("=== ANALYSIS ===")
any_text = [i for i, p in enumerate(FakeTok.prompts) if CHUNK_TEXT in p]
any_ids = [i for i, p in enumerate(FakeTok.prompts)
           if "wiki-18716923" in p]
print("prompts containing chunk TEXT:", any_text or "NONE")
print("prompts containing chunk IDs :", any_ids or "NONE")
print("final_answer:", res["final_answer"])
print("evidence_status:", res["evidence_status"])
print("termination_reason:", res["termination_reason"])