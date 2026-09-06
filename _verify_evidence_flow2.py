"""Adversarial verification #2: forced retrieval plan — does chunk TEXT
reach the REASON dep_notes or the SYNTHESIZE step results?"""
import sys, json
sys.path.insert(0, "src")

from sciencemath.executive.runner import run_executive, ExecContext

PLAN_JSON = json.dumps({"steps": [
    {"id": "s1", "action": "RETRIEVE", "description": "find facts",
     "depends_on": [], "input": "why is the sky blue"},
    {"id": "s2", "action": "REASON", "description": "answer from evidence",
     "depends_on": ["s1"], "input": ""},
    {"id": "s3", "action": "SYNTHESIZE", "description": "combine",
     "depends_on": ["s2"], "input": ""},
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
        p = FakeTok.prompts[-1]
        if "JSON execution plan" in p:
            return PLAN_JSON
        if "Combine the step results" in p:
            return "The sky is blue.\nAnswer: Rayleigh scattering"
        return "Answer: Rayleigh scattering"


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
        return [{"source_id": "w",
                 "chunk_id": "wiki-18716923:intro_3cee6746:0",
                 "text": "Rayleigh scattering makes the sky blue."}]


ctx = ExecContext(
    model=FakeModel(FakeTok()), tokenizer=FakeTok(),
    registry=None, retriever=FakeRetriever(),
    generation={"seed": 42, "max_new_tokens": 64},
    features={"fast_path": False},
)
res = run_executive("Why is the sky blue according to Rayleigh scattering?",
                    "q_ev2", ctx=ctx)
print("=== NON-PLAN PROMPTS THE MODEL SAW ===")
for i, p in enumerate(FakeTok.prompts):
    if "JSON execution plan" in p:
        continue
    print(f"--- prompt {i} ---")
    print(p)
TEXT = "Rayleigh scattering makes the sky blue"
IDS = "wiki-18716923"
print("=== ANALYSIS ===")
print("prompts containing chunk TEXT:",
      [i for i, p in enumerate(FakeTok.prompts) if TEXT in p] or "NONE")
print("prompts containing chunk IDS :",
      [i for i, p in enumerate(FakeTok.prompts) if IDS in p] or "NONE")
for ob in res["observations"]:
    print(ob["step_id"], ob["action"], ob["status"], "|", ob["summary"][:80])
print("final:", res["final_answer"], "|", res["evidence_status"],
      "|", res["termination_reason"])