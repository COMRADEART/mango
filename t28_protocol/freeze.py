"""Repository-byte T28 preconstruction freeze.

T28 inherits the T27 candidate unchanged (candidate runtime changes = 0):
the official candidate commit, tree, and runtime root are pinned to the T27
authoritative values, and the inherited runtime bytes in the T28 repository
must reproduce the official runtime root exactly or the freeze refuses.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from t21_protocol.util import sha256_json

PINNED_CANDIDATE_COMMIT = "11d76c6392ec1f3d08840cfca641618ca61d9247"
PINNED_CANDIDATE_TREE = "1b1a0296232d1b89f94d95902dbce515f59bb266"
PINNED_RUNTIME_ROOT = (
    "c55da12937ed4bce5df0f0ad3692a85c0ae323278a5bacd5610fdf87f258a44d")
T27_ADJUDICATION_COMMIT = "16314c515312e8da86f2b268d788f9aa6b0abd7f"

EXCLUDED = frozenset({
    "evaluations/t28/preconstruction_freeze.json",
    "evaluations/t28/preconstruction_freeze_v1.json",
    "evaluations/t28/protocol_doctor_report.json",
    "evaluations/t28/T28_PRECONSTRUCTION_VERDICT.json",
    "evaluations/t28/fresh_remote_reproduction.json",
})


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _repository_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if b"\0" not in data:
        data = data.replace(b"\r\n", b"\n")
    return data


def components(root: Path) -> dict[str, str]:
    root = Path(root).resolve()
    roles: dict[str, str] = {}
    for directory in ("executive", "planning", "orchestration", "tools",
                      "rag", "knowledge", "web", "document", "scicomp",
                      "code", "memory", "integrated"):
        for path in (root / "src" / "sciencemath" / directory).rglob("*.py"):
            roles[path.relative_to(root).as_posix()] = "CANDIDATE_OR_PROTECTED_RUNTIME"
    for path in (root / "t28_protocol").glob("*.py"):
        roles[path.relative_to(root).as_posix()] = "T28_PROTOCOL_RUNTIME"
    for pattern, role in (
        ("scripts/t28*.py", "T28_ENTRYPOINT"),
        ("tests/test_t28*.py", "T28_TEST_GATE"),
        ("evaluations/t28/*.json", "T28_PUBLIC_ARTIFACT"),
    ):
        for path in root.glob(pattern):
            relative = path.relative_to(root).as_posix()
            if relative not in EXCLUDED:
                roles[relative] = role
    for relative in (
        "evaluations/t27/T27_OFFICIAL_EVALUATION_ELIGIBILITY_ADJUDICATION.json",
        "evaluations/t27/construction/T27_PUBLIC_CONSTRUCTION_RECEIPT.json",
        "evaluations/t27/construction/T27_PUBLIC_CONSTRUCTION_COMMITMENT.json",
        "evaluations/t27/candidate_identity.json",
        "evaluations/t26/T26_EVALUATION_PUBLIC_RECEIPT.json",
        "evaluations/t26/T26_EVALUATION_PROTOCOL_ADDENDUM_V3.json",
        "evaluations/t25/T25_FINAL_PROMOTION_RECORD.json",
        "evaluations/t25/candidate_identity.json",
        "evaluations/t22/T22_FINAL_PROMOTION_RECORD.json",
        "evaluations/t19/promotion_floors.json",
        "evaluations/t20/floors.json",
    ):
        if (root / relative).is_file():
            roles[relative] = "HISTORICAL_PUBLIC_ANCHOR"
    return dict(sorted(roles.items()))


def runtime_identity(root: Path) -> tuple[dict[str, str], str]:
    """Successor runtime identity inherited unchanged from T27.

    The official T28 runtime root equals the T27 authoritative value
    (c55da129…), which is the hash of the T27 mapping — integrated runner
    modules plus the T27 protected production module whose bytes the T28
    repository must not touch.  ``t28_protocol/production.py`` is protocol
    dispatch (public qualification routes directly through the integrated
    runner), so it stays outside the candidate runtime identity.
    """
    root = Path(root).resolve()
    relatives = sorted(
        path.relative_to(root).as_posix()
        for path in (root / "src" / "sciencemath" / "integrated").glob("*.py"))
    relatives.append("t27_protocol/production.py")
    mapping = {relative: _sha_bytes(_repository_bytes(root / relative))
               for relative in relatives}
    return mapping, sha256_json(mapping)


def _repository_candidate_bytes(root: Path,
                                relative: str) -> bytes:
    blob = subprocess.run(
        ["git", "show", f"{PINNED_CANDIDATE_COMMIT}:{relative}"], cwd=root,
        capture_output=True, check=True).stdout
    if b"\0" not in blob:
        blob = blob.replace(b"\r\n", b"\n")
    return blob


def verify_inherited_runtime(root: Path) -> dict[str, object]:
    """Fail closed: T28 ships the T27 candidate runtime unchanged."""
    root = Path(root).resolve()
    commit = subprocess.run(["git", "rev-parse", PINNED_CANDIDATE_COMMIT],
                            cwd=root, capture_output=True, text=True,
                            check=True).stdout.strip()
    if commit != PINNED_CANDIDATE_COMMIT:
        raise ValueError("pinned T28 candidate commit is not reachable")
    mapping, runtime_root = runtime_identity(root)
    blob_matches = {}
    for relative, sha in mapping.items():
        blob_matches[relative] = _sha_bytes(
            _repository_candidate_bytes(root, relative)) == sha
    identical = all(blob_matches.values()) and runtime_root == PINNED_RUNTIME_ROOT
    return {
        "status": "PASS" if identical else "FAIL",
        "pinned_candidate_commit": PINNED_CANDIDATE_COMMIT,
        "pinned_candidate_tree": PINNED_CANDIDATE_TREE,
        "pinned_runtime_root": PINNED_RUNTIME_ROOT,
        "computed_runtime_root": runtime_root,
        "runtime_component_count": len(mapping),
        "candidate_runtime_changes": 0,
        "runtime_component_sha256": mapping,
        "blobs_match_pinned_candidate": blob_matches,
    }


def build_candidate_identity(root: Path) -> dict:
    root = Path(root).resolve()
    inherited = verify_inherited_runtime(root)
    if inherited["status"] != "PASS":
        raise ValueError("T28 candidate runtime deviates from the pinned T27 "
                         "successor runtime; candidate runtime changes = 0 "
                         "is violated")
    adjudication = json.loads(
        (root / "evaluations/t27/T27_OFFICIAL_EVALUATION_ELIGIBILITY_ADJUDICATION.json")
        .read_text(encoding="utf-8"))
    return {
        "schema_version": "t28-candidate-identity-v1",
        "artifact": "T28_CANDIDATE_IDENTITY", "classification": "PUBLIC_SAFE",
        "candidate_commit": PINNED_CANDIDATE_COMMIT,
        "candidate_tree": PINNED_CANDIDATE_TREE,
        "candidate_runtime_changes": 0,
        "candidate_runtime_changes_policy":
            "T28_INHERITS_T27_CANDIDATE_RUNTIME_UNCHANGED",
        "runtime_component_count": inherited["runtime_component_count"],
        "runtime_component_sha256": inherited["runtime_component_sha256"],
        "runtime_root": inherited["computed_runtime_root"],
        "predecessor_adjudication_commit": T27_ADJUDICATION_COMMIT,
        "predecessor_public_construction_commit": adjudication[
            "public_construction"]["commit"],
        "runtime_root_matches_pinned_successor":
            inherited["computed_runtime_root"] == PINNED_RUNTIME_ROOT,
        "candidate_changed": False,
    }


def build_freeze(root: Path) -> dict:
    root = Path(root).resolve()
    candidate = json.loads((root / "evaluations/t28/candidate_identity.json")
                           .read_text(encoding="utf-8"))
    entries = []
    for relative, role in components(root).items():
        path = root / relative
        if not path.is_file():
            raise ValueError(f"freeze component missing: {relative}")
        data = _repository_bytes(path)
        entries.append({"path": relative,
                        "sha256": _sha_bytes(data),
                        "byte_size": len(data), "role": role})
    component_root = sha256_json(entries)
    root_input = {
        "schema_version": "t28-preconstruction-freeze-v1",
        "artifact": "T28_PRECONSTRUCTION_FREEZE",
        "classification": "PUBLIC_SAFE", "experiment": "t28",
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "runtime_root": candidate["runtime_root"],
        "candidate_runtime_changes": 0,
        "component_root": component_root,
        "terminal_semantics_frozen": True,
        "completion_recovery_replan_abstention_frozen": True,
        "provider_and_scorer_bindings_frozen": True,
        "real_construction_authorized": False,
        "real_evaluation_authorized": False,
        "real_blind_rows": 0, "real_gold_rows": 0,
        "real_construction_attempts": 0, "real_evaluation_attempts": 0,
    }
    freeze = {**root_input, "component_count": len(entries),
              "components": entries, "freeze_root": sha256_json(root_input)}
    freeze["freeze_sha256"] = sha256_json(freeze)
    return freeze


def verify_freeze(root: Path, frozen: dict) -> dict:
    computed = build_freeze(root)
    keys = ("candidate_commit", "candidate_tree", "runtime_root",
            "candidate_runtime_changes", "component_count", "component_root",
            "freeze_root", "freeze_sha256")
    mismatches = [key for key in keys if frozen.get(key) != computed.get(key)]
    if frozen.get("components") != computed.get("components"):
        mismatches.append("components")
    return {"status": "PASS" if not mismatches else "FAIL",
            "mismatches": mismatches,
            **{key: computed[key] for key in keys}}