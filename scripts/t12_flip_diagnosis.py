"""T12 diagnostic (CPU-only): mechanism of the arm-B numeric regression
vs T11 arm B on the frozen scicomp suite. Read-only analysis."""
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rows(p):
    lines = open(p, encoding="utf-8").read().splitlines()
    return [json.loads(l) for l in lines if l.strip()]


b12 = rows(ROOT / "evaluations/t12/runs/t12-final-scicomp-B/predictions.jsonl")
b11 = rows(ROOT / "evaluations/t11/runs/t11-h2h-armb/predictions.jsonl")
a11 = rows(ROOT / "evaluations/t11/runs/t11-h2h-arma/predictions.jsonl")
NUM = ("numeric_oracle", "mixed")
n12 = {r["eval_id"]: r for r in b12 if r["kind"] in NUM}
n11 = {r["eval_id"]: r for r in b11 if r["kind"] in NUM}
na11 = {r["eval_id"]: r for r in a11 if r["kind"] in NUM}

wrong12 = set(i for i, r in n12.items() if not r.get("correct"))
wrong11 = set(i for i, r in n11.items() if r.get("numeric_correct") is not True)
wrongA11 = set(i for i, r in na11.items() if r.get("numeric_correct") is not True)
flip = sorted(wrong12 - wrong11)
t11_right = len(n11) - len(wrong11)
t11a_right = len(na11) - len(wrongA11)
t12_right = len(n12) - len(wrong12)
print("T12-B numeric right:", t12_right, "/", len(n12))
print("T11-B numeric right:", t11_right, "/ 138 | T11-A:", t11a_right, "/ 138")
print("flipped right->wrong:", len(flip),
      "| wrong-both:", len(wrong12 & wrong11),
      "| newly right:", len(wrong11 - wrong12))

inv = [r for r in b12 if r["invoked"]]
st = collections.Counter(r["envelope_status"] for r in inv)
print("invoked:", len(inv), "| statuses:", dict(st))
print("guard_blocked:", sum(1 for r in b12 if r.get("guard_blocked")))
nec = collections.Counter(r["necessity"] for r in b12)
print("necessity:", dict(nec))
necinv = collections.Counter((r["necessity"], r["invoked"]) for r in b12)
print("necessity x invoked:", dict(necinv))

mech = collections.Counter()
for r in b12:
    if r["eval_id"] in flip:
        key = (r["invoked"], r["guard_blocked"], r["envelope_status"],
               r["schema_status"])
        mech[key] += 1
print("flip mechanisms (invoked, guard, env, schema):")
for k, v in mech.most_common():
    print("  ", k, v)
for r in b12:
    if r["eval_id"] in flip[:8]:
        fa = str(r["final_answer"])[:70].replace("\n", " ")
        print("FLIP", r["eval_id"], r["gold_route"], "nec=", r["necessity"],
              "inv=", r["invoked"], "env=", r["envelope_status"], "|", fa)

nonpass = [r for r in b12 if r["invoked"] and r["envelope_status"] != "PASS"]
print("non-PASS invocations:", len(nonpass))
for r in nonpass[:10]:
    fa = str(r["final_answer"])[:60].replace("\n", " ")
    print("  NONPASS", r["eval_id"], r["necessity"], r["envelope_status"], "|", fa)