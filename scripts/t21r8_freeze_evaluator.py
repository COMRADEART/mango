"""T21R8 — freeze the evaluator / official-runner / builder-tooling
identity BEFORE any blind world.

Writes ``evaluations/t21r8/evaluator_freeze.json`` recording the evaluator
source hash, the scoring-semantics definition + canonical hash (proven
identical across the semantics file, the validation contract, the evaluator
module, and the qualification artifact), the exactly-32 floors, the raw
schemes, the qualification artifact hash, the official runner identity, the
full freeze-ordering chain, and the hashes of ALL seven preregistered
blind-builder / audit programs (these exact hashes become the authorized
builder/audit tooling).

Requires ``evaluations/t21r8/runtime_freeze.json`` to already exist and
validate.  Refuses when any future blind material exists or when the
qualification gate is not PASS.  It generates NO holdout data of any kind.

After this file exists: NO edits to the evaluator, the official runner, the
scoring semantics, the contracts, or any builder/audit script.  If a defect
is discovered before HOLDOUT_FROZEN: STOP FOR CHATGPT REVIEW — no silent
repair after freeze.

Usage: python scripts/t21r8_freeze_evaluator.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t21r8_run_eval as evaluator  # noqa: E402
from t21r8_freeze_runtime import BLIND_MATERIAL, refuse_blind_material  # noqa: E402


OUT_DIR = ROOT / "evaluations" / "t21r8"

EVALUATOR = ROOT / "scripts" / "t21r8_run_eval.py"
OFFICIAL_COMMAND = "python scripts/t21r8_official_eval.py"

# Preregistered blind-builder / audit tooling: hashed here and immutable
# afterwards.
BUILDER_SCRIPTS = (
    "t21r8_world.py",
    "t21r8_build_suites.py",
    "t21r8_construction_audit.py",
    "t21r8_construction_gate.py",
    "t21r8_static_gold_audit.py",
    "t21r8_uniqueness.py",
    "t21r8_blindness_audit.py",
)

ORDERING = (
    "runtime freeze < evaluator freeze < blind-world generation < "
    "static gold audit < uniqueness audit < blindness audit < "
    "holdout manifest < HOLDOUT_FROZEN < official one-shot evaluation"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_object(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _check_runtime_freeze(root: Path) -> dict:
    path = root / "evaluations" / "t21r8" / "runtime_freeze.json"
    if not path.exists():
        raise SystemExit(
            "T21R8_FREEZE_ORDER_VIOLATION: runtime_freeze.json missing; the "
            "runtime must freeze before the evaluator")
    runtime_freeze = json.loads(path.read_text(encoding="utf-8"))
    for field in ("recorded_at", "git_head", "git_tree_sha",
                  "runtime_composites"):
        if not runtime_freeze.get(field):
            raise SystemExit(
                f"T21R8_FREEZE_ORDER_VIOLATION: runtime freeze lacks "
                f"{field}")
    return runtime_freeze


def _check_qualification(root: Path, evaluator_sha: str) -> dict:
    path = root / "evaluations" / "t21r8" / "evaluator_qualification.json"
    if not path.exists():
        raise SystemExit(
            "T21R8_EVALUATOR_INVALID: evaluator_qualification.json missing")
    qualification = json.loads(path.read_text(encoding="utf-8"))
    if not qualification.get("qualification_passed") or \
            not qualification.get("all_cases_pass") or \
            not qualification.get("all_metric_paths_exercised") or \
            qualification.get("uncaught_exceptions") != 0 or \
            qualification.get("n_cases", 0) < 55:
        raise SystemExit(
            "T21R8_EVALUATOR_INVALID: qualification gate is not PASS")
    if qualification.get("evaluator_source_sha256") != evaluator_sha:
        raise SystemExit(
            "T21R8_EVALUATOR_INVALID: qualification source hash differs "
            "from scripts/t21r8_run_eval.py")
    return qualification


def main(root: Path = ROOT) -> int:
    refuse_blind_material(root)
    if (root / "evaluations" / "t21r8" / "evaluator_freeze.json").exists():
        raise SystemExit(
            "T21R8_FREEZE_ORDER_VIOLATION: evaluator_freeze.json already "
            "exists; the evaluator freezes exactly once")
    runtime_freeze = _check_runtime_freeze(root)

    evaluator_sha = _sha256(root / "scripts" / "t21r8_run_eval.py")
    qualification = _check_qualification(root, evaluator_sha)

    out_dir = root / "evaluations" / "t21r8"
    contract = json.loads(
        (out_dir / "validation_contract.json").read_text(encoding="utf-8"))
    semantics_document = json.loads(
        (out_dir / "scoring_semantics.json").read_text(encoding="utf-8"))
    construction_contract = out_dir / "holdout_construction_contract.json"

    # Scoring-semantics identity across semantics file, validation contract,
    # evaluator module, and qualification artifact.
    canonical = evaluator.scoring_semantics_sha256()
    if semantics_document.get("definition") != evaluator.SCORING_SEMANTICS:
        raise SystemExit(
            "T21R8_EVALUATOR_INVALID: scoring_semantics.json definition "
            "differs from the evaluator module semantics")
    if contract.get("scoring_semantics") != evaluator.SCORING_SEMANTICS or \
            contract.get("scoring_semantics_sha256") != canonical or \
            qualification.get("scoring_semantics_sha256") != canonical:
        raise SystemExit(
            "T21R8_EVALUATOR_INVALID: evaluator/contract/qualification "
            "scoring-semantics identity fails")
    n_floors = sum(len(group) for group in contract["floors"].values())
    if n_floors != 32:
        raise SystemExit(
            f"T21R8_EVALUATOR_INVALID: validation contract must contain "
            f"exactly 32 floors, found {n_floors}")

    raw_schema = {
        "raw_answer_fields": list(evaluator.RAW_ANSWER_FIELDS),
        "raw_retrieval_fields": list(evaluator.RAW_RETRIEVAL_FIELDS),
    }
    builder_hashes = {
        script: _sha256(root / "scripts" / script)
        for script in BUILDER_SCRIPTS
    }
    document = {
        "milestone": "T21R8 evaluator freeze (before blind-world "
                     "construction)",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "ordering": ORDERING,
        "qualification_recorded_at": qualification["recorded_at"],
        "qualification_cases": {
            "n_cases": qualification["n_cases"],
            "n_passed": qualification["n_passed"],
            "all_cases_pass": qualification["all_cases_pass"],
            "all_metric_paths_exercised":
                qualification["all_metric_paths_exercised"],
            "uncaught_exceptions": qualification["uncaught_exceptions"],
        },
        "scoring_semantics": evaluator.SCORING_SEMANTICS,
        "scoring_semantics_sha256": canonical,
        "frozen_hashes": {
            "evaluator_path": "scripts/t21r8_run_eval.py",
            "evaluator_source_sha256": evaluator_sha,
            "validation_contract_sha256": _sha256(
                out_dir / "validation_contract.json"),
            "construction_contract_sha256": _sha256(construction_contract),
            "qualification_artifact_sha256": _sha256(
                out_dir / "evaluator_qualification.json"),
            "floors_sha256": _hash_object(contract["floors"]),
            "suite_minimums_sha256": _hash_object(contract["suite_minimums"]),
            "zero_tolerance_note_sha256": _hash_object(
                contract["zero_tolerance_note"]),
            "raw_results_schema_sha256": _hash_object(raw_schema),
            "runtime_freeze_sha256": _sha256(
                out_dir / "runtime_freeze.json"),
            "official_runner_path": "scripts/t21r8_official_eval.py",
            "official_runner_sha256": _sha256(
                root / "scripts" / "t21r8_official_eval.py"),
            "official_command": OFFICIAL_COMMAND,
            "builder_audit_scripts_sha256": builder_hashes,
        },
        "raw_results_schema": raw_schema,
        "runtime_freeze_recorded_at": runtime_freeze["recorded_at"],
        "rule": (
            "After this file exists the evaluator, the official runner, the "
            "scoring semantics, the contracts, and every builder/audit "
            "script are immutable. If a defect is discovered before "
            "HOLDOUT_FROZEN: STOP FOR CHATGPT REVIEW; no silent repair "
            "after freeze."
        ),
    }
    evaluator.validate_semantics_artifacts(contract, document)
    out = out_dir / "evaluator_freeze.json"
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({
        "status": "EVALUATOR_FROZEN",
        "path": str(out),
        "evaluator_sha256": evaluator_sha,
        "builder_scripts": len(builder_hashes),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())