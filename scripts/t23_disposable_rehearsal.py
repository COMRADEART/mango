"""Two independent 1280-row public-safe construction runs and root comparison."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from t23_protocol.construction import run_shadow_construction  # noqa: E402
from t23_protocol.contract import PATHS  # noqa: E402
from t23_protocol.manifest import verify_seal  # noqa: E402
from t23_protocol.registry import check_real_path_registry  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_once() -> dict:
    with TemporaryDirectory(prefix="t23-disposable-rehearsal-") as directory:
        workspace = Path(directory)
        result = run_shadow_construction(ROOT, workspace)
        verify_seal(ROOT, workspace)
        out = workspace / "evaluations/t23"
        return {
            "rows": result["rows"], "families": result["gate"]["family_count"],
            "suites": result["gate"]["suite_count"],
            "leaf_requirements": result["gate"]["leaf_requirement_count"],
            "gate_checks": result["gate"]["check_count"],
            "manifest_artifacts": result["seal"]["bindings"],
            "semantic": {
                "manifest": result["manifest_semantic_root"],
                "seal": result["seal"]["semantic_root"],
                "static_audit": sha(out / "suites/static_audit.json"),
                "blindness_audit": sha(out / "suites/blindness_audit.json"),
                "uniqueness_audit": sha(out / "suites/uniqueness_audit.json"),
                "construction_gate": sha(out / "suites/construction_gate.json"),
            },
            "raw": {
                "ledger": sha(out / "construction_run_ledger.json"),
                "manifest": sha(out / "holdout_manifest.json"),
                "seal": sha(out / "HOLDOUT_FROZEN"),
            },
        }


def main() -> None:
    before = check_real_path_registry(ROOT, require_absent=True)
    first, second = run_once(), run_once()
    after = check_real_path_registry(ROOT, require_absent=True)
    if any(run["rows"] != 1280 or run["families"] != 16 or run["suites"] != 16
           for run in (first, second)):
        raise SystemExit("T23 disposable construction exact design failed")
    semantic_difference = sum(first["semantic"][key] != second["semantic"][key]
                              for key in first["semantic"])
    raw_difference = sum(first["raw"][key] != second["raw"][key] for key in first["raw"])
    if semantic_difference or before["present"] or after["present"] or after["registered"] != 22:
        raise SystemExit("T23 disposable construction semantic or exposure failure")
    result = {
        "schema_version": "t23-disposable-construction-rehearsal-v1",
        "status": "PASS", "run1": first, "run2": second,
        "semantic_difference": semantic_difference, "raw_volatile_difference": raw_difference,
        "registered_real_paths": after["registered"],
        "real_paths_touched": after["present"] - before["present"],
        "candidate_real_rows": 0, "official_evaluator_invocations": 0,
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
