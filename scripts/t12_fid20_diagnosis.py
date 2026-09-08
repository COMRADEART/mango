"""T12 diagnostic (CPU-only): fidelity-suite item 20 + false-reject reasons."""
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rows(p):
    lines = Path(p).read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lines if l.strip()]


items = rows(ROOT / "evaluations/t12/suites/fidelity/v1/questions.jsonl")
it = None
for x in items:
    eid = x.get("eval_id", x.get("qid", ""))
    if eid == "mfid-v1-0020":
        it = x
        break
if it is None:
    it = items[19]
show = {}
for k in it:
    if k in ("eval_id", "qid", "kind", "category", "question", "operation",
             "expected_status", "mutating_inputs", "faithful_inputs",
             "split"):
        show[k] = it[k]
print("ITEM 20:")
print(json.dumps(show, indent=1, default=str)[:1200])

b12 = rows(ROOT / "evaluations/t12/runs/t12-final-scicomp-B/predictions.jsonl")
pf = [r for r in b12
      if r["fidelity_status"] == "PARAMETER_FIDELITY_FAIL"
      and r["kind"] in ("numeric_oracle", "mixed")]
print()
print("PARAMETER_FIDELITY_FAIL numeric rows + reasons:")
for r in pf:
    print(" ", r["eval_id"], r["necessity"], "|", r["fidelity_failures"])

print()
print("fidelity_status of fidelity-B rows so far (partial attempt 1):")
fb = rows(ROOT / "evaluations/t12/runs/t12-final-fidelity-B/predictions.jsonl")
print("  rows:", len(fb))
print("  ", dict(collections.Counter(str(r["fidelity_status"]) for r in fb)))
print("  ", dict(collections.Counter(str(r["envelope_status"]) for r in fb)))

cb = ROOT / "evaluations/t12/runs/t12-final-conceptual-B"
if (cb / "predictions.jsonl").exists():
    print()
    print("conceptual-B rows so far:", len(rows(cb / "predictions.jsonl")))