"""Exact 22-path real T23 exposure registry and namespace preflight."""
from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from .contract import PATHS

NEW_PUBLIC = {
    "construction_exclusion_sources.json", "t22_exclusion_anchor.json",
    "preconstruction_production_freeze_v3.json",
    "unrestricted_pytest_requalification.json", "applicability_requalification_report.json",
}


def check_real_path_registry(root: Path, *, require_absent: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    registered = list(PATHS.values())
    if len(registered) != 22 or len(set(registered)) != 22:
        raise ValueError("T23 real path registry is not exactly 22")
    present = [p for p in registered if (root / p).exists()]
    graph = root / "evaluations/t23/production_evaluation_graph.json"
    import json
    nodes = json.loads(graph.read_text(encoding="utf-8"))["nodes"]
    graph_paths = {node["path"] for node in nodes.values()}
    if set(registered) != graph_paths | {PATHS["suites"]}:
        raise ValueError("real path registry differs from evaluation graph")
    tracked = subprocess.run(["git", "ls-files", "--", "evaluations/t23"],
                             cwd=root, capture_output=True, text=True, check=True).stdout.splitlines()
    allowed_public = {Path(path).name for path in tracked
                      if path.startswith("evaluations/t23/") and len(Path(path).parts) == 3}
    allowed_public.update(NEW_PUBLIC)
    allowed_private = {Path(path).name for path in registered
                       if path.startswith("evaluations/t23/") and len(Path(path).parts) == 3}
    output = root / "evaluations/t23"
    unknown = sorted(path.name for path in output.iterdir()
                     if path.name not in allowed_public | allowed_private | {"suites"})
    if unknown or (require_absent and present):
        raise ValueError(f"T23 real path preflight failed: present={present}, unknown={unknown}")
    return {"status": "PASS", "registered": 22, "present": len(present),
            "present_paths": present, "unknown": unknown}
