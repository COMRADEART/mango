"""Create the versioned T23 preconstruction freeze from committed bytes only."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from t23_protocol.lifecycle import verify_lifecycle  # noqa: E402

TARGET = ROOT / "evaluations/t23/preconstruction_production_freeze_v2.json"
OLD = ROOT / "evaluations/t23/preconstruction_freeze.json"


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          check=True).stdout


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def components() -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted((ROOT / "evaluations/t23").glob("*.json")):
        if path == TARGET:
            continue
        result[path.relative_to(ROOT).as_posix()] = "T23_PUBLIC_PRECONSTRUCTION_ARTIFACT"
    for path in sorted((ROOT / "evaluations/t23").glob("*.jsonl")):
        result[path.relative_to(ROOT).as_posix()] = "T23_PUBLIC_NONBLIND_EVIDENCE"
    for path in sorted((ROOT / "t23_protocol").glob("*.py")):
        result[path.relative_to(ROOT).as_posix()] = "T23_PRODUCTION_OR_QUALIFICATION_CODE"
    for path in sorted((ROOT / "t21_protocol").glob("*.py")):
        result[path.relative_to(ROOT).as_posix()] = "SHARED_LEDGER_AND_T22_PROTECTION_RUNTIME"
    for path in sorted((ROOT / "scripts").glob("t23*.py")):
        result[path.relative_to(ROOT).as_posix()] = "T23_REPRODUCTION_ENTRYPOINT"
    for path in sorted((ROOT / "tests").glob("test_t23*.py")):
        result[path.relative_to(ROOT).as_posix()] = "T23_QUALIFICATION_TEST"
    for directory in ("executive", "web", "document", "knowledge", "training"):
        for path in sorted((ROOT / "src/sciencemath" / directory).rglob("*.py")):
            result[path.relative_to(ROOT).as_posix()] = "T23_SELECTED_CAPABILITY_RUNTIME"
    for relative in (
        ".gitignore", "evaluations/t23/HISTORICAL_FAILURE_RECONCILIATION.md",
        "evaluations/t22/T22_FINAL_PROMOTION_RECORD.json",
        "evaluations/t22/T22_FINAL_PROMOTION_RECORD.sha256",
        "evaluations/t22/runtime_freeze.json",
        "evaluations/t22/evaluator_freeze.json",
        "src/sciencemath/executive/router_v2.py",
        "src/sciencemath/executive/runner.py",
        "src/sciencemath/web/pipeline.py",
        "src/sciencemath/document/pipeline.py",
        "src/sciencemath/knowledge/pipeline.py",
        "src/sciencemath/training/attach.py",
    ):
        result[relative] = "PRIVACY_OR_RUNTIME_ROOT_OF_TRUST"
    for name in ("runtime_freeze.json", "evaluator_freeze.json"):
        freeze = json.loads((ROOT / "evaluations/t22" / name).read_text(encoding="utf-8"))
        for relative in freeze["component_sha256"]:
            result.setdefault(relative, "T22_PROTECTED_COMPONENT")
    return dict(sorted(result.items()))


def main() -> None:
    if verify_lifecycle(ROOT, "t23")["status"] != "PASS":
        raise SystemExit("real T23 paths present or preconstruction state invalid")
    candidate = git("rev-parse", "HEAD").decode().strip()
    tree = git("show", "-s", "--format=%T", "HEAD").decode().strip()
    old_sha = digest(OLD.read_bytes())
    entries = []
    for relative, role in components().items():
        committed = git("show", f"{candidate}:{relative}")
        if (ROOT / relative).read_bytes() != committed:
            raise SystemExit(f"component differs from committed candidate: {relative}")
        entries.append({"path": relative, "sha256": digest(committed), "role": role})
    component_root = digest(canonical(entries))
    root_input = {
        "schema_version": "t23-preconstruction-production-freeze-v2",
        "candidate_commit": candidate,
        "candidate_tree": tree,
        "previous_freeze_sha256": old_sha,
        "component_root": component_root,
    }
    freeze = {
        **root_input,
        "artifact": "T23_PRECONSTRUCTION_PRODUCTION_FREEZE",
        "experiment": "t23",
        "construction_authorized": False,
        "component_count": len(entries),
        "components": entries,
        "freeze_root": digest(canonical(root_input)),
    }
    TARGET.write_bytes((json.dumps(freeze, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"candidate_commit": candidate, "component_count": len(entries),
                      "component_root": component_root, "freeze_root": freeze["freeze_root"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
