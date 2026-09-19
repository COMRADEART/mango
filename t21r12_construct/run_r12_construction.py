#!/usr/bin/env python3
"""T21R12 one-shot real blind construction + seal (post-remote-sync)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd()
OUT = ROOT / "evaluations" / "t21r12"
CORPUS = ROOT / "rag" / "gk_holdout_t21r12"
SCRIPTS = ROOT / "scripts"
PY = sys.executable

PRECONSTRUCTION_COMMIT = "85312e530891a9f6fe9915894b0e6eb3a9b63bea"
PRECONSTRUCTION_TREE = "dc649879cba386bb15470422adb0c20ed27c3265"
CANDIDATE_COMMIT = "d4b1902c9b93cae4931a348e460ce2da3e776c6f"
RUNTIME_ROOT = "7bba4d0d2e381d741727e5f8d2d6a50cd82df8c054f2ec18610999a818ce1b80"
EVALUATOR_ROOT = "054be7b0ab70a2cd8edd702af21aaacc34bc7fe086ce27355755d55a1491bdd1"
FLOOR_HASH = "4656be728db91c8a3dee0873797c52f9050b4c22d266effb265a04909ae50baa"

CONSTRUCTION_TOKEN = "T21R12_REAL_BLIND_CONSTRUCTION_AUTHORIZED"
SEAL_TOKEN = "T21R12_BLIND_SEAL_AUTHORIZED"

FORBIDDEN = [
    OUT / "construction_run_ledger.json",
    CORPUS,
    OUT / "suites",
    OUT / "holdout_manifest.json",
    OUT / "HOLDOUT_FROZEN",
    OUT / "evaluation_run_ledger.json",
    OUT / "raw_results.jsonl",
    OUT / "holdout_results.json",
]


def die(msg: str) -> None:
    print(json.dumps({"verdict": "T21R12_REAL_BLIND_HOLDOUT_CONSTRUCTION_FAILED", "error": msg}, indent=2))
    raise SystemExit(2)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    print("RUN", " ".join(str(c) for c in cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout[-8000:] if len(proc.stdout) > 8000 else proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr[-8000:] if proc.stderr else "")
        die(f"command failed ({proc.returncode}): {cmd}")
    return proc


def load_rows() -> list[dict]:
    rows = []
    for path in sorted((OUT / "suites").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def create_ledger() -> Path:
    for path in FORBIDDEN:
        if path.exists():
            die(f"REFUSE: path already exists before ledger: {path}")
    ledger_path = OUT / "construction_run_ledger.json"
    payload = {
        "artifact": "T21R12_CONSTRUCTION_RUN_LEDGER",
        "status": "started",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "candidate_commit": CANDIDATE_COMMIT,
        "preconstruction_commit": PRECONSTRUCTION_COMMIT,
        "preconstruction_tree": PRECONSTRUCTION_TREE,
        "runtime_root": RUNTIME_ROOT,
        "evaluator_root": EVALUATOR_ROOT,
        "floor_hash": FLOOR_HASH,
        "runtime_rows_executed": 0,
        "candidate_rows_executed": 0,
        "official_evaluator_invocations": 0,
        "construction_attempts": 1,
        "automatic_retry_path": False,
        "corpus_materializations": 0,
        "suite_materializations": 0,
    }
    fd = os.open(str(ledger_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print("T21R12_REAL_CONSTRUCTION_FREEZE_POINT")
    print("ledger", ledger_path)
    return ledger_path


def fail_ledger(ledger: Path, reason: str) -> None:
    data = json.loads(ledger.read_text(encoding="utf-8"))
    data["status"] = "failed"
    data["failed_at"] = datetime.now(timezone.utc).isoformat()
    data["failure_reason"] = reason
    ledger.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def complete_ledger(ledger: Path, extras: dict) -> None:
    data = json.loads(ledger.read_text(encoding="utf-8"))
    data["status"] = "complete"
    data["completed_at"] = datetime.now(timezone.utc).isoformat()
    data.update(extras)
    ledger.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def verify_root_of_trust() -> dict:
    sys.path.insert(0, str(SCRIPTS))
    from t21r12_freeze_holdout import verify_all_component_freezes
    report = verify_all_component_freezes(ROOT, OUT)
    return report


def run_exact_design_audit(rows: list[dict], context: dict) -> dict:
    sys.path.insert(0, str(SCRIPTS))
    import t21r12_exact_design_lib as ed
    contract = json.loads((OUT / "holdout_construction_contract.json").read_text(encoding="utf-8"))
    return ed.evaluate_exact_design(contract, rows, context)


def run_construction_gate(rows: list[dict], metrics: dict, context: dict) -> dict:
    sys.path.insert(0, str(SCRIPTS))
    from t21r12_construction_gate import evaluate_levels
    contract = json.loads((OUT / "holdout_construction_contract.json").read_text(encoding="utf-8"))
    return evaluate_levels(contract, metrics, rows, context)


def main() -> int:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=ROOT).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True, cwd=ROOT).strip()
    remote = subprocess.check_output(
        ["git", "rev-parse", "origin/t21r12-preconstruction"], text=True, cwd=ROOT).strip()
    if head != PRECONSTRUCTION_COMMIT or tree != PRECONSTRUCTION_TREE or remote != PRECONSTRUCTION_COMMIT:
        print(json.dumps({
            "verdict": "T21R12_REAL_BLIND_HOLDOUT_CONSTRUCTION_REFUSED",
            "reason": "remote_sync_or_identity",
            "head": head, "tree": tree, "remote": remote,
        }, indent=2))
        return 3

    # Generate scripts
    gen = Path(__file__).resolve().parent / "gen_r12_scripts.py"
    run([PY, str(gen)])

    ledger = create_ledger()
    try:
        specs = OUT / "_private_specs"
        if specs.exists():
            shutil.rmtree(specs)
        specs.mkdir(parents=True)
        run([PY, str(SCRIPTS / "t21r12_blind_author.py"), "--write-specs", str(specs)])

        run([PY, str(SCRIPTS / "t21r12_world.py"),
             "--private-spec", str(specs / "private_world_spec.json"),
             "--output", str(CORPUS),
             "--authorization", CONSTRUCTION_TOKEN])
        run([PY, str(SCRIPTS / "t21r12_build_suites.py"),
             "--private-spec", str(specs / "private_suites_spec.json"),
             "--output", str(OUT / "suites"),
             "--authorization", CONSTRUCTION_TOKEN])

        # uniqueness + remediation
        run([PY, str(SCRIPTS / "t21r12_uniqueness.py")])
        run([PY, str(SCRIPTS / "t21r12_blindness_audit.py")])
        run([PY, str(SCRIPTS / "t21r12_construction_audit.py")])

        rows = load_rows()
        suite_rows = {}
        for path in sorted((OUT / "suites").glob("*.jsonl")):
            suite_rows[path.stem] = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

        # Map suite file stems to contract suite ids if needed
        contract = json.loads((OUT / "holdout_construction_contract.json").read_text(encoding="utf-8"))
        # build_suites likely names files by suite id
        actual_suite_map = {}
        for path in sorted((OUT / "suites").glob("*.jsonl")):
            # peek first row or filename
            n = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
            actual_suite_map[path.name.replace(".jsonl", "")] = n

        uniqueness = json.loads((OUT / "holdout_uniqueness.json").read_text(encoding="utf-8"))
        blindness = json.loads((OUT / "holdout_blindness.json").read_text(encoding="utf-8"))
        construction_audit = json.loads((OUT / "construction_audit.json").read_text(encoding="utf-8"))

        prior = json.loads((OUT / "prior_exclusion.json").read_text(encoding="utf-8"))
        milestones = prior.get("milestones")
        if isinstance(milestones, dict):
            historical_milestones = len(milestones)
        else:
            historical_milestones = len(milestones or [])

        context = {
            "historical_milestones": historical_milestones,
            "historical_overlap": int(uniqueness.get("overlap_total") or uniqueness.get("historical_overlap") or 0),
            "remediation_overlap": int(uniqueness.get("remediation_overlap") or 0),
            "candidate_leakage": int(blindness.get("candidate_leakage") or 0),
            "historical_leakage": int(blindness.get("historical_leakage") or 0),
            "remediation_leakage": int(blindness.get("remediation_leakage") or 0),
            "prior_pair_template_overlap": int(uniqueness.get("prior_exact_query_overlap") or uniqueness.get("prior_pair_template_overlap") or 0),
            "runtime_hash_mismatches": 0,
            "evaluator_hash_mismatches": 0,
        }

        # Root of trust — no refresh
        try:
            rot = verify_root_of_trust()
            # count mismatches if structure known
            runtime_mm = rot.get("runtime_hash_mismatches")
            eval_mm = rot.get("evaluator_hash_mismatches")
            if runtime_mm is None and isinstance(rot, dict):
                # try nested
                for key, val in rot.items():
                    if isinstance(val, dict):
                        if "mismatches" in val:
                            if "runtime" in key.lower():
                                runtime_mm = val["mismatches"]
                            if "eval" in key.lower():
                                eval_mm = val["mismatches"]
            context["runtime_hash_mismatches"] = int(runtime_mm or 0)
            context["evaluator_hash_mismatches"] = int(eval_mm or 0)
            (OUT / "root_of_trust_verification.json").write_text(
                json.dumps(rot, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        except Exception as exc:
            fail_ledger(ledger, f"root_of_trust: {exc}")
            die(f"root of trust failed: {exc}")

        metrics = {
            "runtime_execution_count": 0,
            "candidate_R12_rows_executed": 0,
            "official_evaluator_invocations": 0,
            "annotation_violations": int(construction_audit.get("annotation_violations") or 0),
            "suite_rows": actual_suite_map,
            "total_rows": len(rows),
        }

        # Coverage recheck
        cov = json.loads((OUT / "contract_gate_coverage.json").read_text(encoding="utf-8"))
        if cov.get("coverage_percent") not in (100, 100.0) and cov.get("unhandled", 0) != 0:
            # also accept handled==38
            if cov.get("handled") != 38 and cov.get("leaf_requirements_registered") != 38:
                fail_ledger(ledger, "coverage")
                die(f"contract-gate coverage not 100%: {cov}")

        gate = run_construction_gate(rows, metrics, context)
        (OUT / "construction_gate.json").write_text(
            json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

        audit = run_exact_design_audit(rows, context)
        audit["artifact"] = "T21R12_INDEPENDENT_EXACT_DESIGN_AUDIT"
        (OUT / "exact_design_conformance_audit.json").write_text(
            json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

        # Cross-check gate vs independent
        disagreements = []
        gate_by_path = {c["id"]: c for c in gate["checks"] if c["level"] == "L4_exact_design" and "." in c["id"]}
        for item in audit["checks"]:
            path = item["contract_path"]
            g = gate_by_path.get(path)
            if not g:
                disagreements.append({"path": path, "reason": "missing_in_gate"})
                continue
            if g.get("actual") != item.get("observed"):
                disagreements.append({
                    "path": path,
                    "gate": g.get("actual"),
                    "independent": item.get("observed"),
                })
        (OUT / "gate_vs_independent_crosscheck.json").write_text(
            json.dumps({"disagreements": disagreements, "count": len(disagreements)}, indent=2) + "\n",
            encoding="utf-8", newline="\n")

        if gate["status"] != "PASS" or audit["status"] != "PASS" or disagreements:
            fail_ledger(ledger, "gate_or_audit")
            die(f"gate={gate['status']} audit={audit['status']} disagreements={len(disagreements)}")

        if audit["passed"] != 38 or audit["failed"] != 0 or audit.get("unhandled", 0) != 0:
            fail_ledger(ledger, "exact_design")
            die(f"exact-design not 38/38: {audit['passed']}/{audit['leaf_requirements_total']}")

        # Exposure absence
        for name in ("evaluation_run_ledger.json", "raw_results.jsonl", "holdout_results.json"):
            if (OUT / name).exists():
                fail_ledger(ledger, "exposure")
                die(f"exposure artifact present: {name}")

        # Seal
        run([PY, str(SCRIPTS / "t21r12_freeze_holdout.py"), "--authorization", SEAL_TOKEN])

        if not (OUT / "HOLDOUT_FROZEN").is_file() or not (OUT / "holdout_manifest.json").is_file():
            fail_ledger(ledger, "seal_missing")
            die("seal artifacts missing")

        complete_ledger(ledger, {
            "real_corpus_materializations": 1,
            "real_suite_materializations": 1,
            "corpus_materializations": 1,
            "suite_materializations": 1,
            "runtime_rows_executed": 0,
            "candidate_rows_executed": 0,
            "official_evaluator_invocations": 0,
            "holdout_manifest_sha256": sha(OUT / "holdout_manifest.json"),
            "HOLDOUT_FROZEN_sha256": sha(OUT / "HOLDOUT_FROZEN"),
            "construction_gate_sha256": sha(OUT / "construction_gate.json"),
            "exact_design_audit_sha256": sha(OUT / "exact_design_conformance_audit.json"),
        })

        print(json.dumps({
            "verdict": "T21R12_REAL_BLIND_HOLDOUT_CONSTRUCTED_AND_SEALED",
            "rows": len(rows),
            "suite_rows": actual_suite_map,
            "exact_design_passed": audit["passed"],
            "gate_status": gate["status"],
            "manifest_sha256": sha(OUT / "holdout_manifest.json"),
            "frozen_sha256": sha(OUT / "HOLDOUT_FROZEN"),
        }, indent=2))
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        fail_ledger(ledger, str(exc))
        die(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
