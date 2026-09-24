"""T24 private evaluation workspace: frozen public source plus mounted private holdout.

The workspace lives outside the repository. The frozen public source is proved
byte-identical against the preconstruction freeze before any execution; the
private holdout is mounted from the store and never enters Git.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _freeze_path(source_root: Path) -> Path:
    path = source_root / "evaluations" / "t24" / "preconstruction_freeze.json"
    if not path.is_file():
        raise ValueError("T24 preconstruction freeze absent")
    return path


def verify_source_identity(source_root: Path, *,
                           freeze_document: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every frozen component must be byte-identical in the evaluation source.

    Real evaluation reads the frozen preconstruction freeze; disposable
    rehearsals pass their rehearsal-local freeze document instead. In the
    authorized T25 successor tree the T24 freeze binding is historical; drift
    is accepted only when the T25 successor freeze binds every drifted byte
    exactly (authorized T25 remediation + successor protocol code).
    """
    from .successor import successor_binding

    source_root = Path(source_root).resolve()
    if freeze_document is None:
        freeze = json.loads(_freeze_path(source_root).read_text(encoding="utf-8"))
    else:
        freeze = freeze_document
    mismatches = []
    for component in freeze["components"]:
        path = source_root / component["path"]
        if not path.is_file():
            mismatches.append({"path": component["path"], "reason": "MISSING"})
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != component["sha256"]:
            mismatches.append({"path": component["path"], "reason": "HASH_DRIFT"})
    candidate = json.loads((source_root / "evaluations" / "t24" / "candidate_identity.json")
                           .read_text(encoding="utf-8"))["t24_candidate"]
    for relative, expected in candidate.get("runtime_component_sha256", {}).items():
        path = source_root / relative
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "MISSING"
        if digest != expected:
            mismatches.append({"path": relative, "reason": "CANDIDATE_RUNTIME_DRIFT"})
    if mismatches:
        successor = successor_binding(source_root,
                                      sorted(mismatch["path"] for mismatch in mismatches))
        if successor is None:
            raise ValueError(f"T24 evaluation source identity drift: {mismatches[:5]}")
        return {"status": "PASS", "components": freeze["component_count"],
                "freeze_sha256": freeze["freeze_sha256"],
                "candidate_runtime_components": len(candidate.get("runtime_component_sha256", {})),
                "successor_interpretation": successor}
    return {"status": "PASS", "components": freeze["component_count"],
            "freeze_sha256": freeze["freeze_sha256"],
            "candidate_runtime_components": len(candidate.get("runtime_component_sha256", {}))}


def corpus_jsonl_bytes(logical_id: str, store: Any) -> str:
    """Corpus rows re-serialized in the frozen corpus jsonl format.

    The store keeps canonical bytes; the frozen corpus loader verifies
    file_checksums over the corpus format, so mounted corpus files must be
    re-serialized exactly as the corpus builder wrote them.
    """
    rows = store.read(logical_id)
    return "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n"
                   for row in rows)


def create_private_workspace(source_root: Path, store: Any, *, purpose: str,
                             freeze_document: dict[str, Any] | None = None) -> tuple[Path, dict[str, Any]]:
    """Private workspace outside the repository; private holdout mounted from the store."""
    source_root = Path(source_root).resolve()
    identity = verify_source_identity(source_root, freeze_document=freeze_document)
    workspace = Path(tempfile.mkdtemp(prefix=f"t24-private-{purpose}-"))
    # Prove the workspace root is outside the repository.
    if workspace.resolve().is_relative_to(ROOT.resolve()):
        shutil.rmtree(workspace, ignore_errors=True)
        raise ValueError("T24 private workspace must live outside the repository")
    mounted = []
    for entry in store.commitments():
        if entry["classification"] != "PRIVATE_BLIND":
            continue
        logical_id = entry["artifact_logical_id"]
        target = workspace / "holdout" / logical_id
        target.parent.mkdir(parents=True, exist_ok=True)
        if logical_id.startswith("corpus/") and logical_id.endswith(".jsonl"):
            target.write_text(corpus_jsonl_bytes(logical_id, store),
                              encoding="utf-8", newline="\n")
        elif logical_id == "corpus/corpus_manifest.json":
            target.write_text(json.dumps(store.read(logical_id), indent=2,
                                         ensure_ascii=False) + "\n",
                              encoding="utf-8", newline="\n")
        else:
            target.write_bytes(store.read_bytes(logical_id))
        mounted.append({"locator": entry["locator"], "mounted_path": str(target),
                        "canonical_sha256": entry["canonical_sha256"]})
    report = {"status": "PASS", "workspace": str(workspace), "purpose": purpose,
              "source_identity": identity, "mounted_count": len(mounted),
              "mounts": mounted, "outside_repository": True}
    return workspace, report


def dispose_workspace(workspace: Path) -> None:
    shutil.rmtree(Path(workspace), ignore_errors=True)


def corpus_dir_in(workspace: Path) -> Path:
    return Path(workspace) / "holdout" / "corpus"


def holdout_dir_in(workspace: Path) -> Path:
    return Path(workspace) / "holdout"


def suites_dir_in(workspace: Path) -> Path:
    return Path(workspace) / "holdout" / "suites"