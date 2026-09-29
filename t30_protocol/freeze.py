"""Repository-byte T30 preconstruction freeze.

T30 inherits the T27 candidate unchanged (candidate runtime changes = 0):
the official candidate commit, tree, and runtime root are pinned to the T27
authoritative values, and the inherited runtime bytes in the T30 repository
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

# §7 single canonical preconstruction freeze path: every code path that reads
# or writes the T30 preconstruction freeze consumes this constant; no raw
# path literal (and no `_v1` alias) may appear anywhere else in production.
T30_PRECONSTRUCTION_FREEZE_PATH = "evaluations/t30/preconstruction_freeze.json"
FREEZE_LOADER_ID = "t30_protocol.freeze:load_preconstruction_freeze"
PROVISIONAL_FREEZE_BUILDER_ID = "t30_protocol.freeze:build_freeze:driver-provisional"
#: §12 immutable PUBLIC_SAFE T29 predecessor-status record (T30 has no
#: superseded freeze of its own; T29's freeze 85d4f923 stays with T29).
T29_PREDECESSOR_STATUS_PATH = "evaluations/t30/t29_predecessor_status.json"

EXCLUDED = frozenset({
    "evaluations/t30/preconstruction_freeze.json",
    "evaluations/t30/protocol_doctor_report.json",
    "evaluations/t30/T30_PRECONSTRUCTION_VERDICT.json",
    "evaluations/t30/fresh_remote_reproduction.json",
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
    for path in (root / "t30_protocol").glob("*.py"):
        roles[path.relative_to(root).as_posix()] = "T30_PROTOCOL_RUNTIME"
    for pattern, role in (
        ("scripts/t30*.py", "T30_ENTRYPOINT"),
        ("tests/test_t30*.py", "T30_TEST_GATE"),
        ("evaluations/t30/*.json", "T30_PUBLIC_ARTIFACT"),
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
        # T30 successor anchors: sealed/abandoned predecessor public records
        # and the frozen producer/consumer of the T29 refusal defect.
        "evaluations/t28/construction/T28_PUBLIC_CONSTRUCTION_RECEIPT.json",
        "evaluations/t28/construction/T28_PUBLIC_CONSTRUCTION_COMMITMENT.json",
        "evaluations/t28/T28_OFFICIAL_EVALUATION_ELIGIBILITY_ADJUDICATION.json",
        "evaluations/t29/T29_REAL_CONSTRUCTION_ELIGIBILITY_ADJUDICATION.json",
        "evaluations/t29/preconstruction_freeze.json",
        "t28_protocol/store.py",
        "t29_protocol/oracle.py",
    ):
        if (root / relative).is_file():
            roles[relative] = "HISTORICAL_PUBLIC_ANCHOR"
    return dict(sorted(roles.items()))


def runtime_identity(root: Path) -> tuple[dict[str, str], str]:
    """Successor runtime identity inherited unchanged from T27.

    The official T30 runtime root equals the T27 authoritative value
    (c55da129…), which is the hash of the T27 mapping — integrated runner
    modules plus the T27 protected production module whose bytes the T30
    repository must not touch.  ``t30_protocol/production.py`` is protocol
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
    """Fail closed: T30 ships the T27 candidate runtime unchanged."""
    root = Path(root).resolve()
    commit = subprocess.run(["git", "rev-parse", PINNED_CANDIDATE_COMMIT],
                            cwd=root, capture_output=True, text=True,
                            check=True).stdout.strip()
    if commit != PINNED_CANDIDATE_COMMIT:
        raise ValueError("pinned T30 candidate commit is not reachable")
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
        raise ValueError("T30 candidate runtime deviates from the pinned T27 "
                         "successor runtime; candidate runtime changes = 0 "
                         "is violated")
    adjudication = json.loads(
        (root / "evaluations/t27/T27_OFFICIAL_EVALUATION_ELIGIBILITY_ADJUDICATION.json")
        .read_text(encoding="utf-8"))
    return {
        "schema_version": "t30-candidate-identity-v1",
        "artifact": "T30_CANDIDATE_IDENTITY", "classification": "PUBLIC_SAFE",
        "candidate_commit": PINNED_CANDIDATE_COMMIT,
        "candidate_tree": PINNED_CANDIDATE_TREE,
        "candidate_runtime_changes": 0,
        "candidate_runtime_changes_policy":
            "T30_INHERITS_T27_CANDIDATE_RUNTIME_UNCHANGED",
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
    candidate = json.loads((root / "evaluations/t30/candidate_identity.json")
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
        "schema_version": "t30-preconstruction-freeze-v1",
        "artifact": "T30_PRECONSTRUCTION_FREEZE",
        "classification": "PUBLIC_SAFE", "experiment": "t30",
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


def _recompute_freeze_identity(frozen: dict) -> list[str]:
    """Recompute the frozen identity from the document itself.

    Mirrors :func:`build_freeze` hashing exactly (component root over the
    component entries, freeze root over the root-input fields, freeze
    SHA-256 over the freeze document without its own SHA-256 field) so a
    tampered document is refused with a named field before any repository
    access.  Used by the canonical loader; repository-byte agreement is
    then verified separately by :func:`verify_freeze`.
    """
    if not isinstance(frozen, dict):
        return ["document"]
    entries = frozen.get("components")
    if (not isinstance(entries, list) or not entries
            or not all(isinstance(entry, dict)
                       and set(entry) == {"path", "sha256", "byte_size", "role"}
                       and isinstance(entry["sha256"], str)
                       and len(entry["sha256"]) == 64
                       for entry in entries)):
        return ["components"]
    root_inputs, mismatches = {}, []
    for key, value in frozen.items():
        if key in ("component_count", "components", "freeze_root",
                   "freeze_sha256"):
            continue
        root_inputs[key] = value
    if not isinstance(frozen.get("component_count"), int) or (
            frozen["component_count"] != len(entries)):
        mismatches.append("component_count")
    if sha256_json(entries) != frozen.get("component_root"):
        mismatches.append("component_root")
    if sha256_json(root_inputs) != frozen.get("freeze_root"):
        mismatches.append("freeze_root")
    if sha256_json({key: value for key, value in frozen.items()
                    if key != "freeze_sha256"}) != frozen.get(
            "freeze_sha256"):
        mismatches.append("freeze_sha256")
    return mismatches


def load_preconstruction_freeze(root: Path) -> dict:
    """Canonical T30 preconstruction freeze loader (authorization §8).

    Reads only the canonical path, validates the schema/artifact identity
    and component count, recomputes the component root, the freeze root,
    and the freeze SHA-256, verifies the frozen byte identity against the
    repository, and refuses the pinned authorization state if anything is
    absent, stale, or tampered.  No `_v1` path is ever read; the historical
    superseded record is never a loadable freeze.
    """
    root = Path(root).resolve()
    path = root / T30_PRECONSTRUCTION_FREEZE_PATH
    if not path.is_file():
        raise ValueError("T30 canonical preconstruction freeze absent: "
                         + T30_PRECONSTRUCTION_FREEZE_PATH)
    try:
        frozen = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError("T30 canonical preconstruction freeze malformed: "
                         + str(exc)) from exc
    if (not isinstance(frozen, dict)
            or frozen.get("schema_version") != "t30-preconstruction-freeze-v1"
            or frozen.get("artifact") != "T30_PRECONSTRUCTION_FREEZE"
            or frozen.get("classification") != "PUBLIC_SAFE"
            or frozen.get("experiment") != "t30"):
        raise ValueError("T30 canonical preconstruction freeze schema invalid")
    if (frozen.get("real_construction_authorized") is not False
            or frozen.get("real_evaluation_authorized") is not False
            or frozen.get("candidate_runtime_changes") != 0
            or frozen.get("real_blind_rows") != 0
            or frozen.get("real_gold_rows") != 0
            or frozen.get("real_construction_attempts") != 0
            or frozen.get("real_evaluation_attempts") != 0):
        raise ValueError("T30 preconstruction freeze authorization state invalid")
    if (frozen.get("candidate_commit") != PINNED_CANDIDATE_COMMIT
            or frozen.get("candidate_tree") != PINNED_CANDIDATE_TREE
            or frozen.get("runtime_root") != PINNED_RUNTIME_ROOT):
        raise ValueError("T30 preconstruction freeze candidate identity "
                         "deviates from the pinned successor candidate")
    mismatches = _recompute_freeze_identity(frozen)
    if mismatches:
        raise ValueError("T30 preconstruction freeze identity recomputation "
                         "mismatch: " + ",".join(sorted(set(mismatches))))
    try:
        verified = verify_freeze(root, frozen)
    except Exception as exc:
        raise ValueError("T30 canonical preconstruction freeze repository "
                         "verification refused: " + type(exc).__name__) from exc
    if verified["status"] != "PASS":
        raise ValueError("T30 preconstruction freeze repository identity "
                         "drift: " + ",".join(verified["mismatches"]))
    if frozen["freeze_sha256"] != verified["freeze_sha256"]:
        raise ValueError("T30 preconstruction freeze SHA-256 mismatch")
    document = {key: value for key, value in frozen.items()
                if key != "freeze_path"}
    document["freeze_path"] = T30_PRECONSTRUCTION_FREEZE_PATH
    document["canonical_freeze_loader"] = FREEZE_LOADER_ID
    document["freeze_path_verified"] = True
    return document