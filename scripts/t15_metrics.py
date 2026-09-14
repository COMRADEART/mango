"""T15 metrics analysis: CODE FINAL vs baseline FINAL + floor checks."""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(".")


def load(run):
    p = ROOT / f"evaluations/t15/runs/{run}/predictions.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def load_suite(split="final"):
    p = ROOT / "evaluations/t15/suites/mango-code-eval-v1/final.jsonl"
    return {json.loads(l)["task_id"]: json.loads(l)
            for l in p.read_text(encoding="utf-8").splitlines() if l.strip()}


code = [r for r in load("code-final") if not r.get("skipped")]
base = load("baseline-final")
suite = load_suite()

print(f"CODE {sum(1 for r in code if r['pass'])}/{len(code)} = "
      f"{sum(1 for r in code if r['pass']) / len(code):.4f}")
print(f"BASE {sum(1 for r in base if r['pass'])}/{len(base)} = "
      f"{sum(1 for r in base if r['pass']) / len(base):.4f}")

byc = defaultdict(list)
for r in code:
    byc[r["category"]].append(r)
print("\nCODE by category:")
for c in sorted(byc):
    v = byc[c]
    print(f"  {c:15s} {sum(1 for r in v if r['pass'])}/{len(v)}")

byb = defaultdict(list)
for r in base:
    byb[r["category"]].append(r)
print("\nBASE by category:")
for c in sorted(byb):
    v = byb[c]
    print(f"  {c:15s} {sum(1 for r in v if r['pass'])}/{len(v)}")

# executable subset (shared mechanical tasks, excl. qa-style graded)
EXEC = ("single_fix", "multi_fix", "test_repair", "feature", "refactor",
        "config", "import_err", "type_err", "algo", "data_xform", "api_compat")
ce = [r for r in code if r["category"] in EXEC]
be = [r for r in base if r["category"] in EXEC]
print(f"\nEXECUTABLE: CODE {sum(1 for r in ce if r['pass'])}/{len(ce)} = "
      f"{sum(1 for r in ce if r['pass']) / len(ce):.4f} | BASE "
      f"{sum(1 for r in be if r['pass'])}/{len(be)} = "
      f"{sum(1 for r in be if r['pass']) / len(be):.4f}")

bf = [r for r in code if r["category"] in ("single_fix", "multi_fix")]
print(f"BUGFIX: CODE {sum(1 for r in bf if r['pass'])}/{len(bf)} = "
      f"{sum(1 for r in bf if r['pass']) / len(bf):.4f}")
ft = [r for r in code if r["category"] == "feature"]
print(f"FEATURE: {sum(1 for r in ft if r['pass'])}/{len(ft)}")
se = [r for r in code if r["category"] == "search"]
print(f"SEARCH: {sum(1 for r in se if r['pass'])}/{len(se)}")
nc = [r for r in code if r["category"] == "no_change"]
print(f"NOCHANGE: {sum(1 for r in nc if r['pass'])}/{len(nc)}")
pv = [r for r in code if r.get("plan_valid") is not None]
print(f"PLAN_VALID: {sum(1 for r in pv if r['plan_valid'])}/{len(pv)}")

# repair-loop success: model tasks that failed first try but ended pass?
# proxy: pass with latency > 20s (multi-round) 
print("\nSLOW passes (>20s, likely repair loop):",
      [(r["task_id"], r["category"], r["latency_s"])
       for r in code if r["pass"] and r["latency_s"] > 20])

# safety signals
print("\nsecret_detections total:",
      sum(r.get("secret_detections", 0) for r in code))
fab = [r for r in code if any("fabricat" in x for x in r.get("reasons", []))]
print("fabrication flags:", [(r["task_id"], r["reasons"]) for r in fab])

# unrelated edits: touched vs golden files
unrel = 0
exec_rows = 0
for r in ce:
    t = suite[r["task_id"]]
    gold_files = {g["file"] for g in t.get("golden", [])}
    touched = set(r.get("files_touched", []))
    exec_rows += 1
    if touched - gold_files - {f for f in touched if "test" in f.lower()}:
        # allow test-file touches only for test_repair
        if r["category"] != "test_repair":
            unrel += 1
print(f"UNRELATED_EDIT_RATE proxy: {unrel}/{exec_rows} = {unrel / exec_rows:.4f}")
print("(regression grade bug excluded from executable set)")

# paired comparison on shared executable tasks
pairs = 0
cwins = 0
for r in ce:
    b = next((x for x in be if x["task_id"] == r["task_id"]), None)
    if b:
        pairs += 1
        if r["pass"] and not b["pass"]:
            cwins += 1
print(f"paired executable: {pairs} tasks, CODE-only wins: {cwins}")
