"""T21R8 — seal the blind holdout (preregistered BEFORE blind construction).

This script runs ONLY AFTER: blind corpus construction, suite construction,
static gold audit PASS, uniqueness audit UNIQUE, blindness audit PASS.  It
then creates exactly ``evaluations/t21r8/holdout_manifest.json`` and, LAST,
``evaluations/t21r8/HOLDOUT_FROZEN``.  It executes ZERO production-runtime
rows: it is data-only (construction/gate remeasurement + hashing + writing
the two freeze artifacts).

Before trusting any blind data the script mechanically re-verifies the
FROZEN identities: all 14 runtime composites, the evaluator source, the
official runner, every frozen contract/semantics/qualification artifact,
and all seven frozen builder/audit scripts.  Any mismatch is
``T21R8_FROZEN_IDENTITY_VIOLATION``.

The manifest records the exact SHA-256 of every frozen input, the corpus,
and all eight suites; the marker records the SHA-256 of the EXACT manifest
bytes.  On any failed precondition the marker is never written.  If the
manifest is written but the marker fails, the seal is INCOMPLETE and stops
without a rerun.  If either artifact already exists, the script refuses.

After this commit: DO NOT EDIT THIS SCRIPT.

Usage: python scripts/t21r8_freeze_holdout.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import t21r4_freeze_runtime as freeze_runtime_module  # noqa: E402
import t21r8_construction_audit as construction_audit  # noqa: E402
import t21r8_construction_gate as gate  # noqa: E402
from t21r4_freeze_runtime import RUNTIME_GROUPS  # noqa: E402


# Audited root-of-trust anchors.  These values are preregistered here rather
# than learned from either freeze document: neither document, nor the helper
# used to interpret the runtime freeze, is trusted until its exact bytes match.
EXPECTED_RUNTIME_FREEZE_SHA256 = (
    "ef5e15de897ccff1e18c6ece650fd23ec0671e3b20edb752de1e7c9a19cdea93"
)
EXPECTED_EVALUATOR_FREEZE_SHA256 = (
    "9467c322b873fe01ecd5d619fc45291245800aa9eb6fee692592d346f7b60c3c"
)
EXPECTED_RUNTIME_HASH_HELPER_SHA256 = (
    "58eeccc72104b2ec79b5ffa7594c075ca1e5c101375b875c176202c8d58a4e24"
)


# Artifacts whose existence means the one-shot exposure already began.
EXPOSURE_ARTIFACTS = (
    "evaluation_run_ledger.json",
    "raw_results.jsonl",
    "holdout_results.json",
)

BUILDER_SCRIPTS = (
    "t21r8_world.py",
    "t21r8_build_suites.py",
    "t21r8_construction_audit.py",
    "t21r8_construction_gate.py",
    "t21r8_static_gold_audit.py",
    "t21r8_uniqueness.py",
    "t21r8_blindness_audit.py",
)

# Exact physical holdout shape: NOT merely the contract minimums.
EXPECTED_TOTAL = 4800
EXACT_SUITE_COUNTS = {
    "retrieval": 600,
    "singlehop": 550,
    "multihop": 800,
    "crossdomain": 700,
    "citation_claim": 450,
    "conflict_abstention": 800,
    "temporal": 250,
    "adversarial": 650,
}

CORPUS_FILES = ("world.jsonl", "sources.jsonl", "chunks.jsonl",
                "corpus_manifest.json")

ONE_SHOT_RULE = (
    "Exactly one official T21R8 runtime exposure. No preview, smoke test, "
    "sample runtime execution, repair, or rerun."
)
OFFICIAL_COMMAND = "python scripts/t21r8_official_eval.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _composites(root: Path) -> dict:
    """Recompute all 14 runtime composites for THIS tree with the canonical
    freeze hash program (sha_group is retargeted to ``root`` for the
    duration of the call)."""
    original = freeze_runtime_module.ROOT
    freeze_runtime_module.ROOT = root
    try:
        return {name: freeze_runtime_module.sha_group(spec)
                for name, spec in RUNTIME_GROUPS.items()}
    finally:
        freeze_runtime_module.ROOT = original


def refuse_existing_seal(root: Path) -> None:
    """Refuse if the seal already happened or the exposure already began."""
    out_dir = root / "evaluations" / "t21r8"
    if (out_dir / "holdout_manifest.json").exists():
        raise SystemExit(
            "T21R8_FREEZE_ORDER_VIOLATION: holdout_manifest.json already "
            "exists; the holdout seals exactly once")
    if (out_dir / "HOLDOUT_FROZEN").exists():
        raise SystemExit(
            "T21R8_FREEZE_ORDER_VIOLATION: HOLDOUT_FROZEN already exists; "
            "the holdout seals exactly once")
    for name in EXPOSURE_ARTIFACTS:
        if (out_dir / name).exists():
            raise SystemExit(
                "T21R8_FREEZE_ORDER_VIOLATION: exposure artifact "
                f"{name} already exists; the official one-shot exposure "
                "precedes any seal")


def verify_frozen_identity(root: Path) -> tuple[dict, dict]:
    """Load both freezes and re-verify every frozen identity mechanically."""
    out_dir = root / "evaluations" / "t21r8"
    runtime_path = out_dir / "runtime_freeze.json"
    evaluator_path = out_dir / "evaluator_freeze.json"
    runtime_hash_helper_path = root / "scripts" / "t21r4_freeze_runtime.py"

    def _violation(detail: str) -> None:
        raise SystemExit(f"T21R8_FROZEN_IDENTITY_VIOLATION: {detail}")

    # Existence first, then all three exact byte identities.  Nothing from
    # either freeze is parsed, and the runtime hash helper is not used, until
    # these independent roots of trust pass.
    if not runtime_path.exists():
        _violation("runtime_freeze.json missing")
    if not evaluator_path.exists():
        _violation("evaluator_freeze.json missing")
    if _sha256(runtime_path) != EXPECTED_RUNTIME_FREEZE_SHA256:
        _violation("runtime_freeze.json SHA-256 differs from the "
                   "preregistered root")
    if _sha256(evaluator_path) != EXPECTED_EVALUATOR_FREEZE_SHA256:
        _violation("evaluator_freeze.json SHA-256 differs from the "
                   "preregistered root")
    if (_sha256(runtime_hash_helper_path) !=
            EXPECTED_RUNTIME_HASH_HELPER_SHA256):
        _violation("scripts/t21r4_freeze_runtime.py SHA-256 differs from "
                   "the preregistered root")

    runtime_freeze = json.loads(runtime_path.read_text(encoding="utf-8"))
    evaluator_freeze = json.loads(evaluator_path.read_text(encoding="utf-8"))

    # All 14 runtime composites must still equal the freeze.
    composites = _composites(root)
    for name, value in composites.items():
        if value != runtime_freeze["runtime_composites"].get(name):
            _violation(f"runtime group {name} drifted from the runtime "
                       "freeze")

    frozen = evaluator_freeze["frozen_hashes"]
    # Evaluator source and official runner.
    evaluator_sha = _sha256(root / "scripts" / "t21r8_run_eval.py")
    if evaluator_sha != frozen["evaluator_source_sha256"]:
        _violation("scripts/t21r8_run_eval.py drifted from the evaluator "
                   "freeze")
    runner_sha = _sha256(root / "scripts" / "t21r8_official_eval.py")
    if runner_sha != frozen["official_runner_sha256"]:
        _violation("scripts/t21r8_official_eval.py drifted from the "
                   "official-runner freeze")

    # Frozen contract / semantics / qualification / runtime-freeze artifacts.
    artifact_checks = {
        "validation_contract":
            ("evaluations/t21r8/validation_contract.json",
             frozen["validation_contract_sha256"]),
        "construction_contract":
            ("evaluations/t21r8/holdout_construction_contract.json",
             frozen["construction_contract_sha256"]),
        "qualification_artifact":
            ("evaluations/t21r8/evaluator_qualification.json",
             frozen["qualification_artifact_sha256"]),
        "runtime_freeze":
            ("evaluations/t21r8/runtime_freeze.json",
             frozen["runtime_freeze_sha256"]),
        "scoring_semantics":
            ("evaluations/t21r8/scoring_semantics.json",
             runtime_freeze["scoring_semantics_file_sha256"]),
    }
    for label, (rel, expected) in artifact_checks.items():
        if _sha256(root / rel) != expected:
            _violation(f"{rel} drifted from its frozen identity")
    for label, key in (("validation_contract",
                        "validation_contract_sha256"),
                       ("construction_contract",
                        "holdout_construction_contract_sha256")):
        if runtime_freeze[key] != frozen[label + "_sha256"]:
            _violation(f"{label} identity differs between the two freezes")

    # Every frozen builder/audit script.
    for script, expected in frozen["builder_audit_scripts_sha256"].items():
        if _sha256(root / "scripts" / script) != expected:
            _violation(f"builder/audit script {script} drifted from the "
                       "evaluator freeze")
    return runtime_freeze, evaluator_freeze


def require_data_only_audits(root: Path) -> dict:
    """Require the three data-only audits: PASS / UNIQUE / PASS at zero
    runtime executions and zero pre-freeze exposures."""
    out_dir = root / "evaluations" / "t21r8"
    for name in ("static_gold_audit.json", "holdout_uniqueness.json",
                 "blindness_audit.json"):
        if not (out_dir / name).exists():
            raise SystemExit(
                "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: required audit missing: "
                f"{name}")
    static = json.loads(
        (out_dir / "static_gold_audit.json").read_text(encoding="utf-8"))
    uniqueness = json.loads(
        (out_dir / "holdout_uniqueness.json").read_text(encoding="utf-8"))
    blindness = json.loads(
        (out_dir / "blindness_audit.json").read_text(encoding="utf-8"))
    if static.get("status") != "PASS":
        raise SystemExit(
            "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: static gold audit is not "
            "PASS")
    if static.get("runtime_execution_count") != 0:
        raise SystemExit(
            "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: static gold audit records "
            "nonzero runtime executions")
    if uniqueness.get("verdict") != "UNIQUE":
        raise SystemExit(
            "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: uniqueness verdict is not "
            "UNIQUE")
    if uniqueness.get("runtime_execution_count") != 0:
        raise SystemExit(
            "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: uniqueness audit records "
            "nonzero runtime executions")
    if blindness.get("status") != "PASS":
        raise SystemExit(
            "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: blindness audit is not PASS")
    if blindness.get("official_runtime_exposures_before_freeze") != 0:
        raise SystemExit(
            "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: blindness audit records "
            "pre-freeze runtime exposures")
    return {"static": static, "uniqueness": uniqueness,
            "blindness": blindness}


def require_corpus(root: Path) -> dict:
    """Require exactly the four corpus files, parsed but unmodified."""
    corpus_dir = root / "rag" / "gk_holdout_t21r8"
    hashes: dict[str, dict[str, str]] = {}
    for name in CORPUS_FILES:
        path = corpus_dir / name
        if not path.exists():
            raise SystemExit(
                "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: corpus file missing: "
                f"rag/gk_holdout_t21r8/{name}")
        text = path.read_text(encoding="utf-8")
        if name.endswith(".jsonl"):
            for line in text.splitlines():
                if line.strip():
                    json.loads(line)
        else:
            json.loads(text)
        hashes[name] = {"path": f"rag/gk_holdout_t21r8/{name}",
                        "sha256": _sha256(path)}
    return hashes


def recompute_construction(root: Path) -> dict:
    """Remeasure the exact candidate files with the FROZEN audit programs;
    do not trust copied audit counters."""
    out_dir = root / "evaluations" / "t21r8"
    contract_path = out_dir / "holdout_construction_contract.json"
    measured = construction_audit.measure_candidate(root)
    metrics = measured["metrics"]
    if measured["annotation_violation_details"]:
        raise SystemExit(
            "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: recomputed construction "
            f"audit finds {len(measured['annotation_violation_details'])} "
            "annotation violations")
    contract = gate.load_contract(contract_path)
    checks = gate.evaluate_metrics(contract, metrics)
    failed = [check["id"] for check in checks if not check["passed"]]
    if failed:
        raise SystemExit(
            "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: construction gate failed "
            f"requirements: {failed[:10]}")
    static = json.loads(
        (out_dir / "static_gold_audit.json").read_text(encoding="utf-8"))
    embedded = (static.get("construction_contract") or {}).get("metrics")
    if embedded != metrics:
        raise SystemExit(
            "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: recomputed construction "
            "metrics differ from the metrics embedded in "
            "static_gold_audit.json")
    return {
        "metrics": metrics,
        "checks": checks,
        "requirements_evaluated": len(checks),
        "requirements_passed": sum(check["passed"] for check in checks),
    }


def require_physical_holdout(root: Path, suite_records: dict) -> int:
    """Require the EXACT physical holdout: 4800 rows, exact per-suite
    counts, all eight expected suite IDs, and no unexpected suite."""
    out_dir = root / "evaluations" / "t21r8"
    suites_dir = out_dir / "suites"
    if not suites_dir.is_dir():
        raise SystemExit(
            "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: evaluations/t21r8/suites is "
            "missing")
    actual_suites = {path.name for path in suites_dir.iterdir()
                     if path.is_dir()}
    expected_ids = {record["suite_id"] for record in suite_records.values()}
    if actual_suites != expected_ids:
        raise SystemExit(
            "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: suite directories "
            f"{sorted(actual_suites)} differ from the eight expected suite "
            f"IDs {sorted(expected_ids)}")
    total = 0
    for short_name, record in suite_records.items():
        path = suites_dir / record["suite_id"] / "holdout.jsonl"
        if not path.exists():
            raise SystemExit(
                "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: suite file missing: "
                f"{record['suite_id']}/holdout.jsonl")
        rows = [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        expected_rows = record["exact_rows"]
        if len(rows) != expected_rows:
            raise SystemExit(
                "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: suite "
                f"{record['suite_id']} has {len(rows)} rows; exactly "
                f"{expected_rows} are required")
        record["rows"] = len(rows)
        record["sha256"] = _sha256(path)
        record["path"] = f"evaluations/t21r8/suites/{record['suite_id']}" \
                         "/holdout.jsonl"
        total += len(rows)
    if total != EXPECTED_TOTAL:
        raise SystemExit(
            f"T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: holdout total is {total}; "
            f"exactly {EXPECTED_TOTAL} rows are required")
    return total


def build_freeze_inputs(root: Path) -> dict:
    """SHA-256 of every frozen input the manifest must anchor."""
    paths = {
        "runtime_freeze": "evaluations/t21r8/runtime_freeze.json",
        "evaluator_freeze": "evaluations/t21r8/evaluator_freeze.json",
        "validation_contract": "evaluations/t21r8/validation_contract.json",
        "construction_contract":
            "evaluations/t21r8/holdout_construction_contract.json",
        "scoring_semantics": "evaluations/t21r8/scoring_semantics.json",
        "evaluator_qualification":
            "evaluations/t21r8/evaluator_qualification.json",
        "official_runner": "scripts/t21r8_official_eval.py",
        "evaluator": "scripts/t21r8_run_eval.py",
        "static_gold_audit": "evaluations/t21r8/static_gold_audit.json",
        "holdout_uniqueness": "evaluations/t21r8/holdout_uniqueness.json",
        "blindness_audit": "evaluations/t21r8/blindness_audit.json",
        "seal_script": "scripts/t21r8_freeze_holdout.py",
    }
    for script in BUILDER_SCRIPTS:
        paths[f"builder_{script}"] = f"scripts/{script}"
    return {name: {"path": rel, "sha256": _sha256(root / rel)}
            for name, rel in paths.items()}


def main(root: Path = ROOT) -> int:
    out_dir = root / "evaluations" / "t21r8"
    refuse_existing_seal(root)
    runtime_freeze, _evaluator_freeze = verify_frozen_identity(root)
    _audits = require_data_only_audits(root)
    corpus_hashes = require_corpus(root)
    construction = recompute_construction(root)
    print(f"seal script sha256: {_sha256(root / 'scripts'
                                        / 't21r8_freeze_holdout.py')}")

    contract = gate.load_contract(
        root / "evaluations" / "t21r8" / "holdout_construction_contract.json")
    suite_records = {
        name: {"suite_id": rule["suite_id"], "exact_rows": rule["minimum"]}
        for name, rule in contract["suite_target_minimums"].items()
    }
    # The preregistered exact shape must equal the contract minimums.
    if {name: record["exact_rows"]
            for name, record in suite_records.items()} != EXACT_SUITE_COUNTS:
        raise SystemExit(
            "T21R8_HOLDOUT_SEAL_ENTRY_BLOCKED: contract suite minimums "
            "differ from the preregistered exact holdout shape")
    total = require_physical_holdout(root, suite_records)

    document = {
        "milestone": "T21R8 blind holdout manifest (sealed before exposure)",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "holdout_total": total,
        "construction": {
            "requirements_evaluated": construction["requirements_evaluated"],
            "requirements_passed": construction["requirements_passed"],
        },
        "freeze_inputs": build_freeze_inputs(root),
        "corpus": corpus_hashes,
        "suites": suite_records,
        "one_shot_rule": ONE_SHOT_RULE,
        "official_command": OFFICIAL_COMMAND,
        "runtime_execution_count_before_freeze": 0,
    }
    manifest_path = out_dir / "holdout_manifest.json"
    manifest_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")

    # The marker is written LAST, anchoring the exact manifest bytes.
    marker = {
        "HOLDOUT_FROZEN": True,
        "frozen_at": document["frozen_at"],
        "holdout_manifest_sha256": _sha256(manifest_path),
        "holdout_total": total,
        "construction_contract_sha256": document["freeze_inputs"][
            "construction_contract"]["sha256"],
        "runtime_freeze_sha256": document["freeze_inputs"][
            "runtime_freeze"]["sha256"],
        "evaluator_freeze_sha256": document["freeze_inputs"][
            "evaluator_freeze"]["sha256"],
        "rule": ONE_SHOT_RULE,
    }
    try:
        _write_marker(out_dir, marker)
    except OSError as exc:
        raise SystemExit(
            "T21R8_HOLDOUT_SEAL_INCOMPLETE: holdout_manifest.json is "
            f"written but HOLDOUT_FROZEN failed: {exc}; STOP — do not "
            "silently rerun or overwrite") from exc
    print(json.dumps({
        "status": "HOLDOUT_SEALED",
        "holdout_total": total,
        "holdout_manifest_sha256": marker["holdout_manifest_sha256"],
        "runtime_execution_count_before_freeze": 0,
    }, indent=2))
    return 0


def _write_marker(out_dir: Path, marker: dict) -> None:
    (out_dir / "HOLDOUT_FROZEN").write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")


if __name__ == "__main__":
    raise SystemExit(main())
