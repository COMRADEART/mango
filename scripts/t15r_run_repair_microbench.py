"""T15R.21 — run mango-code-repair-loop-v1 and score registered metrics."""
from __future__ import annotations

import json
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.code import contract as C  # noqa: E402
from sciencemath.code import repair_state as RS  # noqa: E402
from sciencemath.code import runner as RN  # noqa: E402

SUITE = ROOT / "evaluations/t15r/suites/mango-code-repair-loop-v1"
OUT = ROOT / "evaluations/t15r/repair_microbench"


def _state(d: dict) -> RS.RepairState:
    kw = dict(d)
    kw.setdefault("diff_hash", "x")
    kw.setdefault("test_result", {})
    kw.setdefault("full_tests_passed_if_run", None)
    kw.setdefault("lint_status", RS.OK)
    kw.setdefault("acceptance_conditions_satisfied", 0)
    kw.setdefault("unrelated_edit_count", 0)
    return RS.RepairState(**kw)


def run_case(case: dict) -> dict:
    h = case["harness"]
    exp = case.get("expect") or {}
    got: dict = {"task_id": case["task_id"], "harness": h,
                 "category": case["category"]}
    flags = defaultdict(int)
    if h == "rank":
        best = RS.select_best([_state(s) for s in case["states"]])
        got["best_state_id"] = best.state_id
        ok = best.state_id == exp.get("best_state_id")
        got["ok"] = ok
        if exp.get("unsafe_accepted") is False and not best.is_original:
            if best.safety_status != RS.OK or best.destructive \
                    or best.secret_leakage or best.unauthorized_network \
                    or best.unauthorized_paid_compute \
                    or best.protected_component_status != RS.OK:
                flags["unsafe_accepted"] = 1
        if exp.get("test_weakening_accepted") is False and best.test_weakening:
            flags["test_weakening_accepted"] = 1
        flags["best_state_ok"] = int(ok)
        if exp.get("unnecessary_revert") is False \
                and exp.get("best_state_id") != "s0":
            flags["unnecessary_revert"] = int(best.state_id == "s0")
    elif h == "delta":
        d = RS.failure_delta(case["before"], case["after"])
        want = exp["delta"]
        ok = all(d.get(k) == want[k] for k in want)
        got["ok"] = ok
        got["delta"] = {k: d[k] for k in
                        ("resolved", "introduced", "remaining", "net_change")}
        flags["delta_ok"] = int(ok)
    elif h == "session":
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "a.py").write_text(case["file_before"], encoding="utf-8")
            sess = RS.RepairSession(p, involved_files=["a.py"])
            sess.bind_original_tests(case["orig_test"])
            if case.get("two_step"):
                (p / "a.py").write_text(case["file_after_good"], encoding="utf-8")
                g = sess.capture_candidate(case["good_test"])
                sess.consider(g)
                (p / "a.py").write_text(case["file_after_bad"], encoding="utf-8")
                b = sess.capture_candidate(case["bad_test"],
                                           **(case.get("bad_flags") or {}))
                sess.consider(b)
            else:
                (p / "a.py").write_text(case["file_after"], encoding="utf-8")
                c = sess.capture_candidate(case["cand_test"])
                sess.consider(c)
            fin = sess.finalize()
            body = (p / "a.py").read_text(encoding="utf-8")
            got["fin"] = {k: fin[k] for k in
                          ("best_retained", "reverted_to_original",
                           "unsafe_revert") if k in fin}
            got["body"] = body
            ok = True
            if "best_retained" in exp:
                ok = ok and fin["best_retained"] is exp["best_retained"]
            if "reverted_to_original" in exp:
                ok = ok and fin["reverted_to_original"] is exp[
                    "reverted_to_original"]
            if "file_equals" in exp:
                ok = ok and body == exp["file_equals"]
            got["ok"] = ok
            flags["best_state_ok"] = int(ok)
            if exp.get("best_retained") and fin["reverted_to_original"]:
                flags["unnecessary_revert"] = 1
            if exp.get("unsafe_accepted") is False and fin.get("best_retained"):
                if sess.best.safety_status != RS.OK:
                    flags["unsafe_accepted"] = 1
            if exp.get("test_weakening_accepted") is False \
                    and sess.best.test_weakening:
                flags["test_weakening_accepted"] = 1
    elif h == "runner":
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for rel, content in case["fixture"].items():
                fp = base / rel
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(content, encoding="utf-8")
            seq = list(case.get("generate_sequence") or [])
            idx = {"i": 0}

            def gen(_prompt):
                i = idx["i"]
                idx["i"] += 1
                payload = seq[min(i, len(seq) - 1)] if seq else []
                return json.dumps(payload)

            res = RN.run_coding_task(
                base, case["request"], op=case.get("op"),
                edits=case.get("edits"),
                repair_candidates=case.get("repair_candidates") or [],
                context_files=case.get("context_files"),
                tests_to_run=case.get("tests_to_run"),
                generate=gen if seq else None)
            got["status"] = res["status"]
            got["files_touched"] = res.get("files_touched")
            src_files = list((base / "src").glob("*.py")) if (
                base / "src").exists() else []
            body = "\n".join(p.read_text(encoding="utf-8") for p in src_files)
            tests = ""
            if (base / "tests").exists():
                tests = "\n".join(
                    p.read_text(encoding="utf-8")
                    for p in (base / "tests").glob("test_*.py"))
            ok = True
            if exp.get("status_in"):
                ok = ok and res["status"] in exp["status_in"]
            if exp.get("status_not"):
                ok = ok and res["status"] != exp["status_not"]
            if "files_touched" in exp:
                ok = ok and res.get("files_touched") == exp["files_touched"]
            if exp.get("retain_partial"):
                ok = ok and bool(res.get("files_touched"))
            if exp.get("body_contains"):
                ok = ok and exp["body_contains"] in body
            if exp.get("no_weakening"):
                ok = ok and "assert True" not in tests
                flags["test_weakening_accepted"] = int(
                    "assert True" in tests)
            got["ok"] = ok
            flags["converge_ok"] = int(
                res["status"] == C.EXECUTED_PASS) if (
                    exp.get("status_in") == ["EXECUTED_PASS"]) else int(ok)
            if exp.get("retain_partial") and not res.get("files_touched"):
                flags["unnecessary_revert"] = 1
            if exp.get("status_in") == ["EXECUTED_PASS"]:
                flags["converge_n"] = 1
                flags["converge_ok"] = int(res["status"] == C.EXECUTED_PASS)
    else:
        got["ok"] = False
        got["error"] = f"unknown harness {h}"
    got["flags"] = dict(flags)
    return got


def score(rows: list[dict], cases: list[dict], targets: dict) -> dict:
    by_id = {c["task_id"]: c for c in cases}
    m = {
        "best_state_selection": {"ok": 0, "n": 0},
        "failure_delta_correctness": {"ok": 0, "n": 0},
        "unsafe_state_acceptance": {"ok": 0, "n": 0},
        "test_weakening_acceptance": {"ok": 0, "n": 0},
        "unnecessary_revert": {"ok": 0, "n": 0},
        "repair_loop_convergence": {"ok": 0, "n": 0},
    }
    for r in rows:
        c = by_id[r["task_id"]]
        metrics = c.get("metrics") or []
        flags = r.get("flags") or {}
        if "best_state_selection" in metrics:
            m["best_state_selection"]["n"] += 1
            m["best_state_selection"]["ok"] += int(
                flags.get("best_state_ok", r.get("ok")))
        if "failure_delta_correctness" in metrics:
            m["failure_delta_correctness"]["n"] += 1
            m["failure_delta_correctness"]["ok"] += int(
                flags.get("delta_ok", r.get("ok")))
        if "unsafe_state_acceptance" in metrics:
            m["unsafe_state_acceptance"]["n"] += 1
            m["unsafe_state_acceptance"]["ok"] += int(
                flags.get("unsafe_accepted", 0))
        if "test_weakening_acceptance" in metrics:
            m["test_weakening_acceptance"]["n"] += 1
            m["test_weakening_acceptance"]["ok"] += int(
                flags.get("test_weakening_accepted", 0))
        if "unnecessary_revert" in metrics:
            m["unnecessary_revert"]["n"] += 1
            m["unnecessary_revert"]["ok"] += int(
                flags.get("unnecessary_revert", 0))
        if "repair_loop_convergence" in metrics:
            m["repair_loop_convergence"]["n"] += 1
            m["repair_loop_convergence"]["ok"] += int(
                flags.get("converge_ok", r.get("ok")))
    rates = {}
    for k, v in m.items():
        rates[k] = (v["ok"] / v["n"]) if v["n"] else 0.0
        rates[k + "_n"] = v["n"]
        rates[k + "_hits"] = v["ok"]
    verdicts = {}
    # min metrics vs max/exact
    verdicts["best_state_selection"] = rates["best_state_selection"] >= targets[
        "best_state_selection"]
    verdicts["failure_delta_correctness"] = rates[
        "failure_delta_correctness"] >= targets["failure_delta_correctness"]
    verdicts["unsafe_state_acceptance"] = rates[
        "unsafe_state_acceptance"] == targets["unsafe_state_acceptance"]
    verdicts["test_weakening_acceptance"] = rates[
        "test_weakening_acceptance"] == targets["test_weakening_acceptance"]
    verdicts["unnecessary_revert"] = rates["unnecessary_revert"] <= targets[
        "unnecessary_revert"]
    verdicts["repair_loop_convergence"] = rates[
        "repair_loop_convergence"] >= targets["repair_loop_convergence"]
    return {"rates": rates, "verdicts": verdicts,
            "all_pass": all(verdicts.values())}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="final", choices=("dev", "final", "all"))
    args = ap.parse_args()
    man = json.loads((SUITE / "manifest.json").read_text(encoding="utf-8"))
    paths = []
    if args.split in ("dev", "all"):
        paths.append(SUITE / "dev.jsonl")
    if args.split in ("final", "all"):
        paths.append(SUITE / "final.jsonl")
    cases = []
    for p in paths:
        cases.extend(json.loads(l) for l in p.read_text(encoding="utf-8")
                     .splitlines() if l.strip())
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in cases:
        rows.append(run_case(c))
        if not rows[-1].get("ok"):
            print("FAIL", c["task_id"], c["category"], c["harness"],
                  rows[-1])
    sc = score(rows, cases, man["targets"])
    summary = {
        "benchmark": "mango-code-repair-loop-v1",
        "split": args.split,
        "n": len(rows),
        "n_pass": sum(1 for r in rows if r.get("ok")),
        "checksum_final": man["final_sha256"],
        "checksum_dev": man["dev_sha256"],
        "targets": man["targets"],
        **sc,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    (OUT / "predictions.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in
                      ("n", "n_pass", "all_pass", "rates", "verdicts")
                      if k in summary}, indent=2))
    return 0 if sc["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
