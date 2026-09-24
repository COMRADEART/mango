#!/usr/bin/env python3
"""Build and reproduce only public-safe T26 preconstruction artifacts.

This entrypoint has no command for real blind construction or evaluation.
Those one-shot phases are guarded separately by exact future tokens.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from t21_protocol.util import sha256_json  # noqa: E402
from t26_protocol.contract import (authority_graph, design, execution_contract,  # noqa: E402
                                   live_web_firewall_registry, metric_registry,
                                   production_graph, storage_policy)
from t26_protocol.doctor import run_doctor  # noqa: E402
from t26_protocol.freeze import build_freeze, verify_freeze  # noqa: E402
from t26_protocol.native_smoke import native_case, run_native_smoke  # noqa: E402
from t26_protocol.protection import run_protection  # noqa: E402
from t26_protocol.qualification import (build_public_cases,  # noqa: E402
                                        exclusion_fingerprints,
                                        run_qualification)
from t26_protocol.rehearsal import run_rehearsals  # noqa: E402
from t26_protocol.test_gate import run_test_gate  # noqa: E402

OUT = ROOT / "evaluations" / "t26"
T25_PROMOTION = "8940d96aacb08d8acf110e5f3e45e9ce84f03577"


def _write(path: Path, document) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True,
                                    ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8", newline="\n")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


def _candidate_identity() -> dict:
    candidate = _git("rev-parse", "HEAD")
    parent = _git("rev-parse", "HEAD^")
    if parent != T25_PROMOTION:
        raise ValueError("T26 runtime candidate must directly descend from T25 promotion")
    tree = _git("rev-parse", "HEAD^{tree}")
    prior = json.loads((ROOT / "evaluations/t25/candidate_identity.json")
                       .read_text(encoding="utf-8"))["t25_candidate"]
    changed = _git("diff", "--name-only", T25_PROMOTION, candidate).splitlines()
    expected_changed = ["src/sciencemath/integrated/__init__.py",
                        "src/sciencemath/integrated/runner.py"]
    if changed != expected_changed:
        raise ValueError(f"T26 runtime candidate changed unexpected files: {changed}")
    mapping = dict(prior["runtime_component_sha256"])
    for relative in expected_changed:
        path = ROOT / relative
        content = path.read_bytes()
        committed = subprocess.run(["git", "show", f"{candidate}:{relative}"],
                                   cwd=ROOT, capture_output=True, check=True).stdout
        if content != committed:
            raise ValueError(f"candidate runtime working-tree drift: {relative}")
        mapping[relative] = hashlib.sha256(content).hexdigest()
    return {"schema_version": "t26-candidate-identity-v1",
            "artifact": "T26_CANDIDATE_IDENTITY",
            "candidate_commit": candidate, "candidate_tree": tree,
            "parent_candidate": prior["candidate_commit"],
            "promotion_base": T25_PROMOTION,
            "changed_from_t25": True,
            "changed_runtime_files": expected_changed,
            "runtime_component_count": len(mapping),
            "runtime_component_sha256": dict(sorted(mapping.items())),
            "runtime_root": sha256_json(mapping),
            "public_safe_justification": "Bounded internal multi-capability runner with explicit plan, T25 router dispatch validation, handoff provenance, independent verification, retry/replan budgets, checkpoint resume and fail-closed completion. No T25 private evidence was used."}


def build_static() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    candidate = _candidate_identity()
    _write(OUT / "candidate_identity.json", candidate)
    artifacts = {
        "prospective_design.json": design(),
        "t26_execution_contract.json": execution_contract(),
        "metric_registry.json": metric_registry(),
        "authority_graph.json": authority_graph(),
        "production_graph.json": production_graph(),
        "private_storage_policy.json": storage_policy(),
    }
    for filename, document in artifacts.items():
        _write(OUT / filename, document)
    cases, gold, _ = build_public_cases()
    _jsonl(OUT / "qualification" / "inputs.jsonl", cases)
    _jsonl(OUT / "qualification" / "gold.jsonl", gold)
    exclusions = exclusion_fingerprints(cases + [native_case()[0]])
    _write(OUT / "qualification_exclusions.json", exclusions)
    _write(OUT / "live_web_firewall_registry.json", live_web_firewall_registry(ROOT))
    qualification = run_qualification()
    _write(OUT / "qualification_report.json", qualification)
    native = run_native_smoke(ROOT, exclusions)
    _write(OUT / "native_smoke_report.json", native)
    rehearsals = run_rehearsals()
    _write(OUT / "rehearsal_report.json", rehearsals)
    return {"candidate_commit": candidate["candidate_commit"],
            "candidate_tree": candidate["candidate_tree"],
            "runtime_root": candidate["runtime_root"],
            "qualification": qualification["status"],
            "native_smoke": native["status"],
            "rehearsals": rehearsals["status"]}


def build_protection() -> dict:
    result = run_protection(ROOT)
    _write(OUT / "protection_report.json", result)
    return {"status": result["status"],
            "t19": result["t19"]["tests"],
            "t20": result["t20"]["tests"],
            "t22": result["t22"],
            "t25_router": result["t25_router"],
            "t25_dispatch": result["t25_dispatch"]["status"]}


def build_test_gate() -> dict:
    result = run_test_gate(ROOT)
    _write(OUT / "test_gate_report.json", result)
    return result


def finalize() -> dict:
    freeze_path = OUT / "preconstruction_freeze.json"
    if freeze_path.exists():
        raise ValueError("T26 preconstruction freeze already exists")
    frozen = build_freeze(ROOT)
    _write(freeze_path, frozen)
    doctor = run_doctor(ROOT)
    _write(OUT / "protocol_doctor_report.json", doctor)
    status = "PASS" if doctor["status"] == "PASS" else "FAIL"
    verdict = {
        "schema_version": "t26-preconstruction-verdict-v1",
        "artifact": "T26_PRECONSTRUCTION_VERDICT",
        "status": status,
        "verdict": "T26_INTEGRATED_INTERNAL_EXECUTION_PRECONSTRUCTION_PASS"
        if status == "PASS" else
        "T26_INTEGRATED_INTERNAL_EXECUTION_PRECONSTRUCTION_FAIL",
        "doctor_check_count": doctor["check_count"],
        "freeze_sha256": frozen["freeze_sha256"],
        "component_count": frozen["component_count"],
        "component_root": frozen["component_root"],
        "freeze_root": frozen["freeze_root"],
        "real_blind_rows": 0,
        "real_construction_attempts": 0,
        "real_evaluation_attempts": 0,
        "t25_private_rows_accessed": 0,
    }
    _write(OUT / "T26_PRECONSTRUCTION_VERDICT.json", verdict)
    return verdict


def reproduce() -> dict:
    expected = {
        filename: json.loads((OUT / filename).read_text(encoding="utf-8"))
        for filename in ("qualification_report.json", "native_smoke_report.json",
                         "rehearsal_report.json",
                         "protection_report.json", "test_gate_report.json")}
    actual = {"qualification_report.json": run_qualification(),
              "native_smoke_report.json": run_native_smoke(
                  ROOT, json.loads((OUT / "qualification_exclusions.json").read_text(encoding="utf-8"))),
              "rehearsal_report.json": run_rehearsals(),
              "protection_report.json": run_protection(ROOT),
              "test_gate_report.json": run_test_gate(ROOT)}
    # The committed reports are JSON; a live rehearsal may hold tuple-valued
    # semantic trace entries that serialize as the same JSON arrays. Compare
    # the public artifact representation, not Python container identity.
    canonical = lambda value: json.dumps(value, sort_keys=True,
                                         separators=(",", ":"),
                                         ensure_ascii=False)
    drift = [name for name in expected if
             canonical(expected[name]) != canonical(actual[name])]
    frozen = json.loads((OUT / "preconstruction_freeze.json").read_text(encoding="utf-8"))
    freeze_report = verify_freeze(ROOT, frozen)
    doctor = run_doctor(ROOT)
    passed = not drift and freeze_report["status"] == doctor["status"] == "PASS"
    return {"schema_version": "t26-fresh-worktree-reproduction-v1",
            "artifact": "T26_FRESH_WORKTREE_REPRODUCTION",
            "status": "PASS" if passed else "FAIL",
            "drifted_artifacts": drift,
            "freeze": freeze_report,
            "doctor_status": doctor["status"],
            "qualification_status": actual["qualification_report.json"]["status"],
            "native_smoke_status": actual["native_smoke_report.json"]["status"],
            "rehearsal_status": actual["rehearsal_report.json"]["status"],
            "protection_status": actual["protection_report.json"]["status"],
            "test_gate_status": actual["test_gate_report.json"]["status"],
            "public_blind_blob_count": doctor["checks"]["GIT_LEAK_SCAN"]["public_blind_blob_count"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("static", "protection", "tests",
                                          "finalize", "reproduce"))
    args = parser.parse_args()
    result = {"static": build_static, "protection": build_protection,
              "tests": build_test_gate, "finalize": finalize,
              "reproduce": reproduce}[args.phase]()
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("status") == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
