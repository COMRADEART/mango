"""Debug long-horizon lh-0000: dump blockers, transitions, artifacts."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.orchestration.orchestrator import Orchestrator
from sciencemath.planning.pipeline import Planner

row = None
for line in (ROOT / "evaluations/t20/suites/"
             "mango-orchestration-long-horizon-v1/dev.jsonl"
             ).read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    if r["case_id"] == "lh-0000":
        row = r
        break

planner = Planner()
orch = Orchestrator(planner=planner)
rr = orch.create({"plan": row["plan"], "now": "2026-01-01T00:00:00Z"})
run = rr.run
replans = 0
for i in range(1, 201):
    res = orch.step({"run": run, "case": row["case"], "now":
                     "2026-01-01T00:%02d:%02dZ" % ((i // 60) % 60, i % 60)})
    run = res.run
    if run.status == "NEEDS_REPLAN" and replans < 3:
        replans += 1
        res = orch.replan({"run": run, "replan_trigger":
                           (run.replan_state or {}).get("trigger", ""),
                           "now": "2026-01-01T00:%02d:%02dZ"
                                  % ((i // 60) % 60, i % 60)})
        run = res.run
    if run.status in ("COMPLETE", "BLOCKED", "FAILED"):
        break

print("steps:", run.steps, "status:", run.status)
print("blockers:", json.dumps(run.blockers[-6:], indent=1))
arts = [(a["artifact_id"], a.get("task_id"), a.get("verification_status"),
         a.get("verification_required")) for a in run.artifacts]
print("artifacts:", len(arts))
bad = [a for a in arts if a[3] and a[2] not in ("PASSED", "NOT_REQUIRED")]
print("mandatory pending:", bad[:8])
tasks = {t.get("task_id"): t.get("status")
         for t in (run.plan.get("tasks") or [])}
nsucc = sum(1 for s in tasks.values() if s == "SUCCEEDED")
print("plan tasks succeeded:", nsucc, "/", len(tasks))
print("run.tasks:", sorted(set(run.tasks.values())))
# event-type histogram
from collections import Counter
c = Counter(e["event_type"] for e in run.events)
print(dict(c))
# verification events with artifact ids
vids = [(e["payload"].get("artifact_id"), e["event_type"])
        for e in run.events
        if e["event_type"] in ("VERIFICATION_PASSED",
                               "VERIFICATION_FAILED")]
print("verifications:", vids[:10])
# where replay diverges: compare reduce vs run
from sciencemath.orchestration.events import reduce_events
state = reduce_events(run.run_id, run.events)
st_tasks = state["tasks"]
mism = []
for tid, st in run.tasks.items():
    if st in ("ASSIGNED", "RUNNING", "SUCCEEDED", "REVISION_REQUESTED") \
            and st_tasks.get(tid) != st:
        mism.append((tid, st, st_tasks.get(tid)))
print("task mismatches:", mism[:10])
art_mism = []
for a in run.artifacts:
    st_a = state["artifacts"].get(a["artifact_id"])
    if st_a != a.get("verification_status") and \
            a.get("verification_required"):
        art_mism.append((a["artifact_id"], a.get("verification_status"),
                         st_a))
print("artifact mismatches:", art_mism[:10])