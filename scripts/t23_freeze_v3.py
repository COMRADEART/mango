"""Create T23 v3 preconstruction freeze from the committed infrastructure tree."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from t23_protocol.contract import (BASE_PRECONSTRUCTION_COMMIT, CANDIDATE_COMMIT,
                                   CANDIDATE_TREE, OLD_FREEZE_SHA256, canonical)

OLD = ROOT / "evaluations/t23/preconstruction_production_freeze_v2.json"
TARGET = ROOT / "evaluations/t23/preconstruction_production_freeze_v3.json"


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    if TARGET.exists():
        raise SystemExit("T23 v3 freeze already exists")
    if sha(OLD.read_bytes()) != OLD_FREEZE_SHA256:
        raise SystemExit("historical T23 freeze changed")
    commit = git("rev-parse", "HEAD").decode().strip()
    parent = git("rev-parse", "HEAD^").decode().strip()
    tree = git("show", "-s", "--format=%T", "HEAD").decode().strip()
    if parent != BASE_PRECONSTRUCTION_COMMIT:
        raise SystemExit("infrastructure commit does not descend directly from frozen preconstruction")
    if git("rev-parse", f"{CANDIDATE_COMMIT}^{{tree}}").decode().strip() != CANDIDATE_TREE:
        raise SystemExit("candidate tree changed")
    old = json.loads(OLD.read_text(encoding="utf-8"))
    roles = {item["path"]: item["role"] for item in old["components"]}
    tracked = git("ls-tree", "-r", "--name-only", "HEAD").decode().splitlines()
    for relative in tracked:
        if (relative.startswith(("t23_protocol/", "scripts/t23", "tests/test_t23"))
                or relative.startswith("evaluations/t23/") and relative != TARGET.relative_to(ROOT).as_posix()):
            roles.setdefault(relative, "T23_CONSTRUCTION_INFRASTRUCTURE_OR_EVIDENCE")
    roles["evaluations/t23/preconstruction_production_freeze_v2.json"] = "HISTORICAL_PRECONSTRUCTION_FREEZE"
    entries = []
    for relative, role in sorted(roles.items()):
        data = git("show", f"{commit}:{relative}")
        if (ROOT / relative).read_bytes() != data:
            raise SystemExit(f"component differs from committed infrastructure: {relative}")
        entries.append({"path": relative, "role": role, "sha256": sha(data)})
    component_root = sha(canonical(entries))
    root_input = {
        "schema_version": "t23-preconstruction-production-freeze-v3",
        "candidate_commit": CANDIDATE_COMMIT, "candidate_tree": CANDIDATE_TREE,
        "infrastructure_commit": commit, "infrastructure_parent": parent,
        "infrastructure_tree": tree,
        "previous_freeze_sha256": OLD_FREEZE_SHA256,
        "component_root": component_root,
    }
    freeze = {
        **root_input, "artifact": "T23_PRECONSTRUCTION_PRODUCTION_FREEZE",
        "experiment": "t23", "construction_authorized": False,
        "real_t23_exposure": 0, "component_count": len(entries),
        "components": entries, "freeze_root": sha(canonical(root_input)),
    }
    TARGET.write_text(json.dumps(freeze, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    print(json.dumps({"infrastructure_commit": commit,
                      "component_count": len(entries),
                      "component_root": component_root,
                      "freeze_root": freeze["freeze_root"]}, sort_keys=True))


if __name__ == "__main__":
    main()
