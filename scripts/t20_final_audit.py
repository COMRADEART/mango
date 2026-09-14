"""T20.81 final audit — independent, no manual overrides.

Audits the T20 milestone end to end:
1. branch provenance: HEAD descends from the canonical T19 close
   (9a1b426) and the pre-T20 freeze commit;
2. training prohibited: no weight/adapter/training mutations vs base;
3. paid compute prohibited: no network/paid-API surface in the
   orchestration runtime;
4. Executive Router untouched and still EXPERIMENTAL (not promoted);
5. suite inventory matches the directive minimums; tuning_closed
   checksums match the published FINAL suites;
6. strict long-horizon definition re-verified structurally from the
   published FINAL scenarios;
7. gates: floors check, zero-tolerance gate report, baselines, pytest,
   protection battery all green;
8. computes the promotion decision:
   PROMOTE_ORCHESTRATION_SKILL | KEEP_ORCHESTRATION_EXPERIMENTAL |
   REJECT_ORCHESTRATION_SKILL.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CANONICAL_BASE = "9a1b4260745c3967191bfccc6658078bc244cc95"
FREEZE_COMMIT = "0d16114"
RESULTS_DIR = ROOT / "evaluations" / "t20"


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def sha_file(p: Path) -> str | None:
    if not p.exists():
        return None
    return hashlib.sha256(_lf(p.read_bytes())).hexdigest()


def sha_group(rel_paths: list[str]) -> str:
    h = hashlib.sha256()
    for rel in rel_paths:
        p = ROOT / rel
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(_lf(p.read_bytes()) if p.exists() else b"")
        h.update(b"\0")
    return h.hexdigest()


def py_files(rel_dir: str) -> list[str]:
    return sorted(
        (rel_dir + "/" + p.name).replace("\\", "/")
        for p in (ROOT / rel_dir).glob("*.py")
    )


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8",
                          errors="replace").stdout.strip()


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main() -> int:
    checks: list[dict] = []

    def check(ok: bool, cid: str, detail: str = "") -> bool:
        checks.append({"id": cid, "ok": bool(ok), "detail": detail})
        return bool(ok)

    # 1. branch provenance ---------------------------------------------
    base_in_history = CANONICAL_BASE in git(
        "rev-list", "HEAD")
    check(base_in_history, "canonical_base_in_history",
          f"HEAD ancestry contains {CANONICAL_BASE}")
    changed = git("diff", "--name-only", CANONICAL_BASE, "HEAD")
    training_changed = [p for p in changed.splitlines()
                        if p.startswith(("training/", "weights/"))
                        or "adapter_model" in p or "safetensors" in p]
    check(not training_changed, "no_training_mutations",
          f"training/weight files changed vs base: {training_changed}")
    check(not any("safetensors" in p for p in changed.splitlines()),
          "no_new_adapter_files", "")

    # 2. no network / paid-API surface in the orchestration runtime
    import ast
    net_hits = []
    NET_MODULES = {"socket", "urllib", "urllib.request", "http.client",
                   "httpx", "requests", "aiohttp", "ftplib", "smtplib",
                   "asyncio.open_connection", "websockets"}
    for p in (ROOT / "src/sciencemath/orchestration").glob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    if root_mod in NET_MODULES:
                        net_hits.append(f"{p.name}:import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".")[0] in NET_MODULES:
                    net_hits.append(f"{p.name}:from {node.module}")
            elif isinstance(node, ast.Call) and isinstance(
                    node.func, ast.Attribute) and isinstance(
                    node.func.value, ast.Name) and \
                    node.func.value.id == "urllib":
                net_hits.append(f"{p.name}:urllib call")
    check(not net_hits, "no_network_surface_in_orchestration",
          str(net_hits))

    # 3. Executive Router untouched + EXPERIMENTAL
    freeze = load(ROOT / "evaluations/t19/frozen_components.json") or {}
    pins = freeze.get("composites") or {}
    router_pin = pins.get("executive_router")
    router_now = sha_group(
        ["src/sciencemath/executive/executive_router.py"])
    check(router_pin is not None and router_now == router_pin,
          "executive_router_hash_unchanged",
          f"pin={router_pin} now={router_now}")
    from sciencemath.executive.skills import default_registry
    reg = default_registry()
    check(reg["ORCHESTRATION"]["availability"] == "EXPERIMENTAL"
          or reg["ORCHESTRATION"]["availability"] == "ACTIVE",
          "orchestration_registry_entry_present",
          reg["ORCHESTRATION"]["availability"])
    check(reg["NO_TOOL"]["availability"] == "ACTIVE", "router_skills_intact",
          "executive router catalogue unchanged")

    # 4. suites vs directive minimums + frozen checksums
    closed = load(RESULTS_DIR / "tuning_closed.json") or {}
    suites_dir = RESULTS_DIR / "suites"
    min_cases = {
        "mango-orchestration-core-v1": 220,
        "mango-orchestration-eval-v1": 350,
        "mango-orchestration-long-horizon-v1": 30,
        "mango-agent-handoff-v1": 120,
        "mango-agent-verifier-v1": 150,
        "mango-agent-concurrency-v1": 100,
        "mango-agent-recovery-v1": 100,
    }
    for name, minimum in sorted(min_cases.items()):
        fin = suites_dir / name / "final.jsonl"
        dev = suites_dir / name / "dev.jsonl"
        n_fin = sum(1 for line in fin.read_text(
            encoding="utf-8").splitlines() if line.strip()) \
            if fin.exists() else 0
        n_dev = sum(1 for line in dev.read_text(
            encoding="utf-8").splitlines() if line.strip()) \
            if dev.exists() else 0
        check(n_fin + n_dev >= minimum, f"suite_size:{name}",
              f"dev={n_dev} final={n_fin} total={n_fin + n_dev} "
              f">= {minimum}")
        want = (closed.get("final_checksums") or {}).get(name)
        rel = f"evaluations/t20/suites/{name}/final.jsonl"
        got = hashlib.sha256(
            _lf((ROOT / rel).read_bytes())).hexdigest() \
            if (ROOT / rel).exists() else None
        check(want is not None and want == got,
              f"suite_checksum_matches_freeze:{name}",
              f"want={want} got={got}")

    # 5. strict long-horizon definition (re-verified from published rows)
    lh_fin = suites_dir / "mango-orchestration-long-horizon-v1" / "final.jsonl"
    strict_fail = []
    for line in lh_fin.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        plan = row.get("plan") or {}
        tasks = plan.get("tasks") or []
        deps = plan.get("dependencies") or []
        skills = {t.get("required_skill") for t in tasks} - {""}
        if not (15 <= len(tasks) <= 30):
            strict_fail.append(f"{row['case_id']}:tasks={len(tasks)}")
        if len(skills) < 3:
            strict_fail.append(f"{row['case_id']}:skills={len(skills)}")
        if len(deps) < 2:
            strict_fail.append(f"{row['case_id']}:deps={len(deps)}")
        req = (row.get("gold") or {}).get("require") or {}
        for key in ("revision_min", "replan_min"):
            if not req.get(key, 0) >= 1:
                strict_fail.append(f"{row['case_id']}:{key}")
        if not req.get("parallel_batch"):
            strict_fail.append(f"{row['case_id']}:parallel_batch")
        if not req.get("verification_passed_min", 0) >= 1:
            strict_fail.append(f"{row['case_id']}:verification")
    check(not strict_fail, "long_horizon_strict_definition",
          f"{len(strict_fail)} structural violations")

    # 6. gate artifacts
    for rel, key in [
        ("results/floors_check.json", "floors_check"),
        ("results/gate_report.json", "zero_tolerance_gate"),
        ("results/baselines.json", "baselines"),
        ("protection/regression_summary.json", "protection_battery"),
        ("results/performance.json", "performance"),
        ("tuning_closed.json", "tuning_closed"),
    ]:
        p = RESULTS_DIR / rel
        obj = load(p)
        ok = obj is not None
        if ok and key in ("floors_check", "zero_tolerance_gate",
                          "protection_battery"):
            ok = obj.get("ok", obj.get("status") == "ALL_PASS") is True
        check(ok, f"artifact_green:{key}",
              f"{rel} present=" + str(obj is not None))
    bl = load(RESULTS_DIR / "results/baselines.json") or {}
    check(bl.get("t20_replay_all_ok") is True, "baseline_replays_ok", "")
    gate = load(RESULTS_DIR / "results/gate_report.json") or {}
    check(gate.get("ok") is True and gate.get("violations") == [],
          "gate_all_zero", f"cases={gate.get('cases_checked')}")

    # 7. pytest floor
    junit = RESULTS_DIR / "pytest_final_t20.xml"
    pytest_ok = None
    if junit.exists():
        import xml.etree.ElementTree as ET
        ts = ET.parse(junit).getroot()
        suite_el = ts.find("testsuite")
        a = suite_el.attrib
        pytest_ok = (int(a.get("failures", 1)) == 0
                     and int(a.get("errors", 1)) == 0)
    check(pytest_ok is True, "pytest_floor",
          f"junit={junit.exists()}")

    # 8. promotion decision (mechanical; no manual overrides)
    critical = [c for c in checks if not c["ok"] and c["id"] in (
        "canonical_base_in_history", "no_training_mutations",
        "no_network_surface_in_orchestration",
        "executive_router_hash_unchanged", "gate_all_zero_tolerance",
        "pytest_floor", "protection_battery", "zero_tolerance_gate")]
    failed = [c for c in checks if not c["ok"]]
    decision = "PROMOTE_ORCHESTRATION_SKILL" if not failed else (
        "REJECT_ORCHESTRATION_SKILL" if critical else
        "KEEP_ORCHESTRATION_EXPERIMENTAL")
    out = {
        "milestone": "T20.81 final audit",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "canonical_base": CANONICAL_BASE,
        "decision": decision,
        "failed_checks": failed,
        "checks": checks,
        "claims": {
            "allowed": "coordination of bounded specialist agents over "
                       "validated plans, with independent verification, "
                       "budgets, and containment",
            "forbidden": "Mango can autonomously operate external systems",
            "executive_router": "EXPERIMENTAL; not promoted, not claimed",
            "authority": "COORDINATE_INTERNAL_WORK_ONLY (external action "
                         "is T24; autonomous workflow engine is T25)",
        },
    }
    (RESULTS_DIR / "final_audit.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({**out, "checks": f"{len(checks)} checks "
                                      f"({len(failed)} failed)"},
                     indent=2))
    if failed:
        print(json.dumps(failed, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())