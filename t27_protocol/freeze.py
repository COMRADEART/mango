"""Repository-byte T27 preconstruction freeze."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

EXCLUDED = frozenset({
    "evaluations/t27/preconstruction_freeze.json",
    "evaluations/t27/protocol_doctor_report.json",
    "evaluations/t27/T27_PRECONSTRUCTION_VERDICT.json",
    "evaluations/t27/fresh_remote_reproduction.json",
    "evaluations/t27/preconstruction_freeze_v2.json",
    "evaluations/t27/T27_INFRASTRUCTURE_REQUALIFICATION_VERDICT.json",
    "evaluations/t27/fresh_remote_reproduction_v2.json",
})


def _sha_json(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()


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
    for path in (root / "t27_protocol").glob("*.py"):
        roles[path.relative_to(root).as_posix()] = "T27_PROTOCOL_RUNTIME"
    for pattern, role in (
        ("scripts/t27*.py", "T27_ENTRYPOINT"),
        ("tests/test_t27*.py", "T27_TEST_GATE"),
        ("evaluations/t27/*.json", "T27_PUBLIC_ARTIFACT"),
    ):
        for path in root.glob(pattern):
            relative = path.relative_to(root).as_posix()
            if relative not in EXCLUDED:
                roles[relative] = role
    for relative in (
        "evaluations/t26/T26_EVALUATION_PUBLIC_RECEIPT.json",
        "evaluations/t25/T25_FINAL_PROMOTION_RECORD.json",
        "evaluations/t25/candidate_identity.json",
        "evaluations/t22/T22_FINAL_PROMOTION_RECORD.json",
        "evaluations/t19/promotion_floors.json",
        "evaluations/t20/floors.json",
    ):
        roles[relative] = "HISTORICAL_PUBLIC_ANCHOR"
    return dict(sorted(roles.items()))


def runtime_identity(root: Path) -> tuple[dict[str, str], str]:
    root = Path(root).resolve()
    relatives = sorted(
        path.relative_to(root).as_posix()
        for path in (root / "src" / "sciencemath" / "integrated").glob("*.py"))
    relatives.append("t27_protocol/production.py")
    mapping = {relative: hashlib.sha256(
        _repository_bytes(root / relative)).hexdigest() for relative in relatives}
    return mapping, _sha_json(mapping)


def build_candidate_identity(root: Path) -> dict:
    root = Path(root).resolve()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                            capture_output=True, text=True, check=True).stdout.strip()
    tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=root,
                          capture_output=True, text=True, check=True).stdout.strip()
    receipt_commit = "55b05efe10645bc65f9ba5591c5655b91393009d"
    changed = subprocess.run(
        ["git", "diff", "--name-only", receipt_commit, commit],
        cwd=root, capture_output=True, text=True, check=True).stdout.splitlines()
    mapping, runtime_root = runtime_identity(root)
    return {
        "schema_version": "t27-candidate-identity-v1",
        "artifact": "T27_CANDIDATE_IDENTITY", "classification": "PUBLIC_SAFE",
        "candidate_commit": commit, "candidate_tree": tree,
        "base_receipt_commit": receipt_commit,
        "parent_candidate": "6cb029c0f4edb4116c7f9a1f187cdc4671077a1f",
        "parent_candidate_tree": "6199df3a4537e5af480098a4bd009c357ecc2910",
        "parent_runtime_root": "28f83990f5382400bac72cb34448ad5854c875d74655f1a571703f50d9cb453c",
        "changed_files": sorted(changed),
        "runtime_component_count": len(mapping),
        "runtime_component_sha256": mapping,
        "runtime_root": runtime_root,
        "public_synthetic_reproducer":
            "evaluations/t27/T27_PUBLIC_ROOT_CAUSE_REPRODUCTION.json",
        "candidate_changed": True,
    }


def build_freeze(root: Path) -> dict:
    root = Path(root).resolve()
    candidate = json.loads((root / "evaluations/t27/candidate_identity.json").read_text(
        encoding="utf-8"))
    entries = []
    for relative, role in components(root).items():
        path = root / relative
        if not path.is_file():
            raise ValueError(f"freeze component missing: {relative}")
        data = _repository_bytes(path)
        entries.append({"path": relative,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "byte_size": len(data), "role": role})
    component_root = _sha_json(entries)
    root_input = {
        "schema_version": "t27-preconstruction-freeze-v1",
        "artifact": "T27_PRECONSTRUCTION_FREEZE",
        "classification": "PUBLIC_SAFE", "experiment": "t27",
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "runtime_root": candidate["runtime_root"],
        "component_root": component_root,
        "terminal_semantics_frozen": True,
        "completion_recovery_replan_abstention_frozen": True,
        "provider_and_scorer_bindings_frozen": True,
        "construction_authorized": False,
        "evaluation_authorized": False,
        "real_blind_rows": 0, "real_gold_rows": 0,
    }
    freeze = {**root_input, "component_count": len(entries),
              "components": entries, "freeze_root": _sha_json(root_input)}
    freeze["freeze_sha256"] = _sha_json(freeze)
    return freeze


def verify_freeze(root: Path, frozen: dict) -> dict:
    computed = build_freeze(root)
    keys = ("candidate_commit", "candidate_tree", "runtime_root",
            "component_count", "component_root", "freeze_root", "freeze_sha256")
    mismatches = [key for key in keys if frozen.get(key) != computed.get(key)]
    if frozen.get("components") != computed.get("components"):
        mismatches.append("components")
    return {"status": "PASS" if not mismatches else "FAIL",
            "mismatches": mismatches,
            **{key: computed[key] for key in keys}}


def build_freeze_v2(root: Path) -> dict:
    """Construction-ready infrastructure freeze; authorization stays false."""
    root = Path(root).resolve()
    candidate = json.loads((root / "evaluations/t27/candidate_identity.json").read_text(
        encoding="utf-8"))
    entries = []
    for relative, role in components(root).items():
        path = root / relative
        if not path.is_file():
            raise ValueError(f"freeze component missing: {relative}")
        data = _repository_bytes(path)
        entries.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(),
                        "byte_size": len(data), "role": role})
    component_root = _sha_json(entries)
    protocol_paths = {
        "terminal_contract": "evaluations/t27/terminal_contract.json",
        "metric_registry": "evaluations/t27/metric_registry.json",
        "nonvacuity_policy": "evaluations/t27/nonvacuity_policy.json",
        "construction_protocol": "t27_protocol/construction.py",
        "evaluation_protocol": "t27_protocol/evaluation.py",
        "ledgers_and_store": "t27_protocol/store.py",
        "t26_overlap_oracle": "t26_protocol/t27_private_oracle.py",
        "historical_exclusion": "evaluations/t27/historical_exclusion_policy_v2.json",
        "official_runner_and_gold_firewall": "evaluations/t27/official_runner_identity.json",
        "production_graph": "evaluations/t27/production_graph.json",
        "authority_graph": "evaluations/t27/authority_graph.json",
        "doctor": "t27_protocol/doctor.py",
        "tests": "tests/test_t27_construction_infrastructure.py",
        "rehearsals": "evaluations/t27/construction_rehearsal_report.json",
    }
    identities = {name: hashlib.sha256(_repository_bytes(root / relative)).hexdigest()
                  for name, relative in protocol_paths.items()}
    root_input = {
        "schema_version": "t27-preconstruction-freeze-v2",
        "artifact": "T27_PRECONSTRUCTION_FREEZE_V2",
        "classification": "PUBLIC_SAFE", "experiment": "t27",
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "runtime_root": candidate["runtime_root"],
        "component_root": component_root, "protocol_identities": identities,
        "supersedes": {
            "artifact": "T27_PRECONSTRUCTION_FREEZE_V1_SUPERSEDED_PRE_EXPOSURE",
            "freeze_sha256": "ac11569f973ca819795eef370d5befe384b9cb2dcc23c850a0ef84ea1bb536b8",
            "reason": "REAL_CONSTRUCTION_LIFECYCLE_NOT_YET_IMPLEMENTED",
            "blind_material_existed": False,
        },
        "candidate_runtime_changed": False,
        "construction_and_evaluation_infrastructure_frozen": True,
        "real_construction_authorized": False,
        "real_evaluation_authorized": False,
        "real_blind_rows": 0, "real_gold_rows": 0,
        "real_construction_attempts": 0, "real_evaluation_attempts": 0,
    }
    freeze = {**root_input, "component_count": len(entries),
              "components": entries, "freeze_root": _sha_json(root_input)}
    freeze["freeze_sha256"] = _sha_json(freeze)
    return freeze


def verify_freeze_v2(root: Path, frozen: dict) -> dict:
    computed = build_freeze_v2(root)
    keys = ("candidate_commit", "candidate_tree", "runtime_root",
            "component_count", "component_root", "freeze_root", "freeze_sha256")
    mismatches = [key for key in keys if frozen.get(key) != computed.get(key)]
    if frozen.get("components") != computed.get("components"):
        mismatches.append("components")
    if frozen.get("protocol_identities") != computed.get("protocol_identities"):
        mismatches.append("protocol_identities")
    return {"status": "PASS" if not mismatches else "FAIL",
            "mismatches": mismatches,
            **{key: computed[key] for key in keys}}
