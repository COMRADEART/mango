"""Independently verify T23 v3 freeze components and roots from committed bytes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "evaluations/t23/preconstruction_production_freeze_v3.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def main() -> None:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze["construction_authorized"] is not False or freeze["real_t23_exposure"] != 0:
        raise SystemExit("T23 v3 freeze exposure state invalid")
    commit = freeze["infrastructure_commit"]
    if git("rev-parse", f"{commit}^{{tree}}").decode().strip() != freeze["infrastructure_tree"]:
        raise SystemExit("infrastructure tree mismatch")
    if git("rev-parse", f"{commit}^").decode().strip() != freeze["infrastructure_parent"]:
        raise SystemExit("infrastructure parent mismatch")
    entries = freeze["components"]
    if len(entries) != freeze["component_count"] or len({e["path"] for e in entries}) != len(entries):
        raise SystemExit("freeze component registry invalid")
    for item in entries:
        relative = item["path"]
        committed = git("show", f"{commit}:{relative}")
        if sha(committed) != item["sha256"] or sha((ROOT / relative).read_bytes()) != item["sha256"]:
            raise SystemExit(f"component mismatch: {relative}")
    component_root = sha(canonical(entries))
    if component_root != freeze["component_root"]:
        raise SystemExit("component root mismatch")
    keys = ("schema_version", "candidate_commit", "candidate_tree", "infrastructure_commit",
            "infrastructure_parent", "infrastructure_tree", "previous_freeze_sha256",
            "component_root")
    root = sha(canonical({key: freeze[key] for key in keys}))
    if root != freeze["freeze_root"]:
        raise SystemExit("freeze root mismatch")
    old = ROOT / "evaluations/t23/preconstruction_production_freeze_v2.json"
    if sha(old.read_bytes()) != freeze["previous_freeze_sha256"]:
        raise SystemExit("historical freeze mismatch")
    print(json.dumps({"status": "PASS", "component_count": len(entries),
                      "component_root": component_root,
                      "independent_root": root}, sort_keys=True))


if __name__ == "__main__":
    main()
