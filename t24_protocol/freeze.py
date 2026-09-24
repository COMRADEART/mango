"""T24 preconstruction freeze: byte identity for every public-safe T24 component.

The freeze binds the base infrastructure commit/tree constants and hashes every
frozen component from the working tree. Real construction and evaluation verify
component bytes against this freeze before any execution (section 38).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

from .contract import BASE_PRECONSTRUCTION_COMMIT, BASE_PRECONSTRUCTION_TREE, EXPERIMENT

ROOT = Path(__file__).resolve().parents[1]
FREEZE_SCHEMA = "t24-preconstruction-freeze-v1"
FREEZE_PATH = ROOT / "evaluations" / "t24" / "preconstruction_freeze.json"
FROZEN_POLICY = {
    "REAL_BLIND_CONTENT_PUBLICATION_ALLOWED_BEFORE_EVALUATION": False,
    "T23_EXPOSED_MATERIAL_REUSE_ALLOWED": False,
    "PUBLIC_GIT_BLIND_BLOB_COUNT_REQUIRED": 0,
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def freeze_components(root: Path) -> dict[str, str]:
    """Every public-safe T24 byte: protocol code, artifacts, runtimes, tests.

    Post-freeze outputs are never components: the freeze itself (write_freeze
    refuses to overwrite it), the doctor report, and the preconstruction
    verdict are all written after the freeze, so binding them would make the
    component set depend on file presence at build time and drift on
    reproduction.
    """
    root = Path(root).resolve()
    result: dict[str, str] = {}
    skip = {
        "evaluations/t24/preconstruction_freeze.json",
        "evaluations/t24/protocol_doctor_report.json",
        "evaluations/t24/T24_PRECONSTRUCTION_VERDICT.json",
    }
    for path in sorted((root / "evaluations/t24").glob("*.json")):
        relative = path.relative_to(root).as_posix()
        if relative in skip:
            continue
        result[relative] = "T24_PUBLIC_PRECONSTRUCTION_ARTIFACT"
    for path in sorted((root / "evaluations/t24").glob("*.jsonl")):
        result[path.relative_to(root).as_posix()] = "T24_PUBLIC_NONBLIND_EVIDENCE"
    for directory in ("qualification",):
        for path in sorted((root / "evaluations/t24" / directory).rglob("*")):
            if path.is_file():
                result[path.relative_to(root).as_posix()] = "T24_PUBLIC_QUALIFICATION_DATA"
    for path in sorted((root / "t24_protocol").glob("*.py")):
        result[path.relative_to(root).as_posix()] = "T24_PROTOCOL_OR_QUALIFICATION_CODE"
    for path in sorted((root / "t23_protocol").glob("*.py")):
        result[path.relative_to(root).as_posix()] = "T23_FROZEN_PROTOCOL_RUNTIME"
    for path in sorted((root / "t21_protocol").glob("*.py")):
        result[path.relative_to(root).as_posix()] = "SHARED_LEDGER_AND_T22_PROTECTION_RUNTIME"
    for path in sorted((root / "scripts").glob("t24*.py")):
        result[path.relative_to(root).as_posix()] = "T24_REPRODUCTION_ENTRYPOINT"
    for path in sorted((root / "tests").glob("test_t24*.py")):
        result[path.relative_to(root).as_posix()] = "T24_QUALIFICATION_TEST"
    for directory in ("executive", "web", "document", "knowledge", "training"):
        for path in sorted((root / "src/sciencemath" / directory).rglob("*.py")):
            result[path.relative_to(root).as_posix()] = "T24_SELECTED_CAPABILITY_RUNTIME"
    for relative in (
        ".gitignore",
        "evaluations/t23/HISTORICAL_FAILURE_RECONCILIATION.md",
        "evaluations/t22/T22_FINAL_PROMOTION_RECORD.json",
        "evaluations/t22/T22_FINAL_PROMOTION_RECORD.sha256",
        "evaluations/t22/runtime_freeze.json",
        "evaluations/t22/evaluator_freeze.json",
        "src/sciencemath/executive/router_v2.py",
        "src/sciencemath/executive/runner.py",
        "src/sciencemath/web/pipeline.py",
        "src/sciencemath/web/fixture_provider.py",
        "src/sciencemath/document/pipeline.py",
        "src/sciencemath/knowledge/pipeline.py",
        "src/sciencemath/training/attach.py",
    ):
        result[relative] = "PRIVACY_OR_RUNTIME_ROOT_OF_TRUST"
    for name in ("runtime_freeze.json", "evaluator_freeze.json"):
        freeze = json.loads((root / "evaluations/t22" / name).read_text(encoding="utf-8"))
        for relative in freeze["component_sha256"]:
            result.setdefault(relative, "T22_PROTECTED_COMPONENT")
    for relative in ("rag/gk_corpus/sources.jsonl", "rag/gk_corpus/chunks.jsonl",
                     "rag/gk_corpus/corpus_manifest.json"):
        result[relative] = "T24_REHEARSAL_CORPUS_SOURCE"
    return dict(sorted(result.items()))


def build_freeze(root: Path, *, infrastructure_commit: str = BASE_PRECONSTRUCTION_COMMIT,
                 infrastructure_tree: str = BASE_PRECONSTRUCTION_TREE) -> dict[str, Any]:
    root = Path(root).resolve()
    if infrastructure_commit != BASE_PRECONSTRUCTION_COMMIT \
            or infrastructure_tree != BASE_PRECONSTRUCTION_TREE:
        raise ValueError("T24 freeze infrastructure identity is frozen")
    entries = []
    for relative, role in freeze_components(root).items():
        path = root / relative
        if not path.is_file():
            raise ValueError(f"T24 freeze component missing: {relative}")
        data = path.read_bytes()
        entries.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(),
                        "byte_size": len(data), "role": role})
    entries.sort(key=lambda entry: entry["path"])
    component_root = sha256_json(entries)
    root_input = {"schema_version": FREEZE_SCHEMA,
                  "artifact": "T24_PRECONSTRUCTION_FREEZE", "experiment": EXPERIMENT,
                  "infrastructure_commit": infrastructure_commit,
                  "infrastructure_tree": infrastructure_tree,
                  "construction_authorized": False,
                  "component_root": component_root,
                  "frozen_policy": dict(FROZEN_POLICY)}
    freeze = {**root_input, "component_count": len(entries), "components": entries,
              "freeze_root": sha256_json(root_input)}
    freeze["freeze_sha256"] = hashlib.sha256(_canonical(freeze)).hexdigest()
    return freeze


def write_freeze(root: Path, document: dict[str, Any]) -> Path:
    target = Path(root) / "evaluations/t24/preconstruction_freeze.json"
    if target.exists():
        raise ValueError("T24 preconstruction freeze already exists")
    required = ("infrastructure_commit", "infrastructure_tree", "component_root",
                "freeze_root", "freeze_sha256", "frozen_policy")
    if any(key not in document for key in required):
        raise ValueError("incomplete T24 freeze document")
    if document["frozen_policy"] != FROZEN_POLICY:
        raise ValueError("T24 freeze publication policy forbidden or incomplete")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((json.dumps(document, sort_keys=True, indent=2) + "\n")
                       .encode("utf-8"))
    return target


def load_freeze(path: Path | None = None) -> dict[str, Any]:
    path = Path(path) if path is not None else FREEZE_PATH
    document = json.loads(path.read_text(encoding="utf-8"))
    stored = document.get("freeze_sha256")
    if not isinstance(stored, str):
        raise ValueError("T24 freeze missing freeze_sha256")
    recomputed = hashlib.sha256(_canonical(
        {key: value for key, value in document.items() if key != "freeze_sha256"})).hexdigest()
    if recomputed != stored:
        raise ValueError("T24 preconstruction freeze hash mismatch")
    if (document.get("schema_version") != FREEZE_SCHEMA
            or document.get("infrastructure_commit") != BASE_PRECONSTRUCTION_COMMIT
            or document.get("infrastructure_tree") != BASE_PRECONSTRUCTION_TREE
            or document.get("frozen_policy") != FROZEN_POLICY):
        raise ValueError("T24 preconstruction freeze identity or policy drift")
    return document