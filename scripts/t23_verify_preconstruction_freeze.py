"""Independently rehash every committed T23 freeze component and both roots."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "evaluations/t23/preconstruction_production_freeze_v2.json"


def hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze["construction_authorized"] is not False:
        raise SystemExit("freeze unexpectedly authorizes construction")
    candidate_tree = subprocess.run(
        ["git", "show", "-s", "--format=%T", freeze["candidate_commit"]],
        cwd=ROOT, capture_output=True, check=True, text=True).stdout.strip()
    if candidate_tree != freeze["candidate_tree"]:
        raise SystemExit("candidate tree differs from frozen identity")
    entries = freeze["components"]
    if len(entries) != freeze["component_count"] or len({x["path"] for x in entries}) != len(entries):
        raise SystemExit("freeze component registry invalid")
    for item in entries:
        relative = item["path"]
        committed = subprocess.run(["git", "show", f"{freeze['candidate_commit']}:{relative}"],
                                   cwd=ROOT, capture_output=True, check=True).stdout
        if hash_bytes(committed) != item["sha256"] or hash_bytes((ROOT / relative).read_bytes()) != item["sha256"]:
            raise SystemExit(f"freeze component mismatch: {relative}")
    encode = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=False).encode("utf-8")
    component_root = hash_bytes(encode(entries))
    if component_root != freeze["component_root"]:
        raise SystemExit("independent component root mismatch")
    root_input = {key: freeze[key] for key in (
        "schema_version", "candidate_commit", "candidate_tree",
        "previous_freeze_sha256", "component_root")}
    independent_root = hash_bytes(encode(root_input))
    if independent_root != freeze["freeze_root"]:
        raise SystemExit("independent freeze root mismatch")
    if hash_bytes((ROOT / "evaluations/t23/preconstruction_freeze.json").read_bytes()) != freeze["previous_freeze_sha256"]:
        raise SystemExit("previous freeze changed")
    print(json.dumps({"status": "PASS", "component_count": len(entries),
                      "component_root": component_root, "independent_root": independent_root,
                      "root_match": True}, sort_keys=True))


if __name__ == "__main__":
    main()
