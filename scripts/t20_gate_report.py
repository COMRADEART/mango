"""T20.61 zero-tolerance gate report.

Reruns every run-mode FINAL case and asserts all 24 zero-tolerance
counters are exactly zero on each run, scoped to run-mode cases (probe
cases have no run). Emits evaluations/t20/results/gate_report.json and
exits nonzero on any violation. NETWORK OFF; fixture providers only.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import t20_run_eval as R  # noqa: E402
from sciencemath.orchestration.contract import ZERO_TOLERANCE_KEYS  # noqa: E402

SUITES_DIR = ROOT / "evaluations" / "t20" / "suites"
RESULTS_DIR = ROOT / "evaluations" / "t20" / "results"


def load_run_rows() -> list[tuple[str, dict]]:
    rows = []
    for suite_dir in sorted(SUITES_DIR.iterdir()):
        path = suite_dir / "final.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("mode") == "run":
                rows.append((suite_dir.name, row))
    return rows


def main(argv: list[str]) -> int:
    rows = load_run_rows()
    violations: list[dict] = []
    checked = 0
    per_suite: dict[str, dict] = defaultdict(lambda: {"cases": 0, "ok": 0})
    for suite, row in rows:
        res = R.run_case(row, R.EVAL_PLANNER)
        run = res.get("run")
        checked += 1
        suite_stat = per_suite[suite]
        suite_stat["cases"] += 1
        bad = {}
        if run is not None:
            for k in ZERO_TOLERANCE_KEYS:
                v = run.counters.get(k, 0)
                if v:
                    bad[k] = v
            replay = res.get("replay_ok")
            if replay is False:
                bad["replay_equivalent"] = "False"
        if res.get("failures"):
            bad["gold_failures"] = res["failures"]
        if bad:
            violations.append({"case_id": res["case_id"], "suite": suite,
                               "violations": bad})
        else:
            suite_stat["ok"] += 1

    out = {
        "gate": "T20.61 zero-tolerance",
        "scope": "run-mode FINAL cases",
        "cases_checked": checked,
        "violations": violations,
        "per_suite": {s: dict(v) for s, v in sorted(per_suite.items())},
        "ok": not violations,
    }
    (RESULTS_DIR / "gate_report.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "violations"},
                     indent=2))
    if violations:
        print(json.dumps(violations, indent=2))
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))