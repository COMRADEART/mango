"""One disposable nonblind provider/evaluator protection run; no real T23 paths."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from t23_shadow_lifecycle import ROOT, _general_context
from t23_protocol.construction import run_shadow_construction
from t23_protocol.evaluation import run_shadow_evaluation
from t23_protocol.registry import check_real_path_registry


def main() -> None:
    before = check_real_path_registry(ROOT, require_absent=True)
    context = _general_context()
    with TemporaryDirectory(prefix="t23-protection-requalification-") as directory:
        workspace = Path(directory)
        construction = run_shadow_construction(ROOT, workspace)
        evaluation = run_shadow_evaluation(ROOT, workspace, general_context=context)
        after = check_real_path_registry(ROOT, require_absent=True)
        parity = evaluation["provider_parity"]
        report = {
            "status": "PASS" if (construction["status"] == "PASS"
                                and evaluation["status"] == "PASS"
                                and parity["status"] == "PASS"
                                and parity["rows"] == 1280
                                and not any(parity["mismatches"].values())
                                and evaluation["protected_t22_floors"] == 32
                                and after["present"] == before["present"] == 0) else "FAIL",
            "rows": evaluation["rows"],
            "provider_parity": parity,
            "router_floor_pass_count": sum(item["pass"] for item in evaluation["router_metrics"]["floors"].values()),
            "protected_t22_floors": evaluation["protected_t22_floors"],
            "real_paths_touched": after["present"] - before["present"],
        }
        print(json.dumps(report, sort_keys=True), flush=True)
        if report["status"] != "PASS":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
