"""Prospective T26 preconstruction byte freeze and independent verification."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from t21_protocol.util import sha256_json

SCHEMA = "t26-preconstruction-freeze-v3"
EXCLUDED = frozenset({
    "evaluations/t26/preconstruction_freeze.json",
    "evaluations/t26/protocol_doctor_report.json",
    "evaluations/t26/T26_PRECONSTRUCTION_VERDICT.json",
    "evaluations/t26/fresh_worktree_reproduction.json",
})
V1_FREEZE_SHA256 = ("ff09bed6caf8b7c9760bf57b7f2954374a22610797e785c35e54b78daa033ac6")
V2_FREEZE_SHA256 = ("98ae5124de494e99fb1398633f19131e1e5af976cbeb672249c57c83d3d9ae35")


def _text_attributes(root: Path, relatives: list[str]) -> dict[str, str]:
    request = b"".join(relative.encode("utf-8") + b"\0" for relative in relatives)
    raw = subprocess.run(
        ["git", "check-attr", "-z", "--stdin", "text"], cwd=root,
        input=request, capture_output=True, check=True,
    ).stdout.split(b"\0")
    fields = [field.decode("utf-8") for field in raw if field]
    if len(fields) % 3:
        raise ValueError("unexpected git check-attr response")
    return {fields[index]: fields[index + 2]
            for index in range(0, len(fields), 3)}


def _repository_bytes(root: Path, relative: str, text_attribute: str) -> bytes:
    """Return the byte representation Git will store for a component.

    The freeze is a commitment to the public repository, not to a particular
    worktree's checkout conversion.  On Windows an older checkout can still
    contain CRLF bytes after ``.gitattributes`` was changed to require LF;
    hashing those worktree bytes makes a clean fresh checkout fail the freeze
    even though both worktrees represent the same Git blob.  Apply Git's text
    normalization rule before hashing while preserving ``-text``/binary data
    byte-for-byte.
    """
    path = root / relative
    data = path.read_bytes()
    if text_attribute not in {"unset", "unspecified"} and b"\0" not in data:
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
    for directory in ("t26_protocol",):
        for path in (root / directory).glob("*.py"):
            roles[path.relative_to(root).as_posix()] = "T26_PROTOCOL_RUNTIME"
    for pattern, role in (("scripts/t26*.py", "T26_ENTRYPOINT"),
                          ("tests/test_t26*.py", "T26_TEST_GATE"),
                          ("evaluations/t26/*.json", "T26_PUBLIC_ARTIFACT"),
                          ("evaluations/t26/qualification/*.jsonl", "T26_PUBLIC_QUALIFICATION")):
        for path in root.glob(pattern):
            relative = path.relative_to(root).as_posix()
            if relative not in EXCLUDED:
                roles[relative] = role
    for relative in (
        "evaluations/t25/T25_FINAL_PROMOTION_RECORD.json",
        "evaluations/t25/candidate_identity.json",
        "evaluations/t25/capability_registry.json",
        "evaluations/t25/live_web_source_firewall_registry.json",
        "evaluations/t25/t23_exposed_sealed_anchor.json",
        "evaluations/t25/t24_sealed_evaluated_anchor.json",
        "evaluations/t25/preconstruction_freeze.json",
        "evaluations/t22/T22_FINAL_PROMOTION_RECORD.json",
        "evaluations/t19/promotion_floors.json",
        "evaluations/t20/floors.json",
    ):
        roles[relative] = "HISTORICAL_PUBLIC_ANCHOR"
    return dict(sorted(roles.items()))


def build_freeze(root: Path) -> dict:
    root = Path(root).resolve()
    candidate = json.loads((root / "evaluations/t26/candidate_identity.json").read_text(encoding="utf-8"))
    entries = []
    component_roles = components(root)
    text_attributes = _text_attributes(root, list(component_roles))
    for relative, role in component_roles.items():
        path = root / relative
        if not path.is_file():
            raise ValueError(f"freeze component missing: {relative}")
        data = _repository_bytes(root, relative, text_attributes[relative])
        entries.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(),
                        "byte_size": len(data), "role": role})
    component_root = sha256_json(entries)
    root_input = {
        "schema_version": SCHEMA, "artifact": "T26_PRECONSTRUCTION_FREEZE",
        "experiment": "t26", "t25_promotion_commit":
        "8940d96aacb08d8acf110e5f3e45e9ce84f03577",
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "runtime_root": candidate["runtime_root"],
        "component_root": component_root,
        "superseded_freeze_v1_sha256": V1_FREEZE_SHA256,
        "superseded_freeze_v2_sha256": V2_FREEZE_SHA256,
        "superseded_freeze_v2_classification":
            "T26_PRECONSTRUCTION_FREEZE_V2_SUPERSEDED_PRE_EXPOSURE",
        "superseded_freeze_v2_reason":
            "ZERO_FIXTURE_CONTRACT_OPTIONALITY_WIRING_DEFECT",
        "construction_lifecycle_frozen": (
            "LEDGER_CREATED->MATERIALIZED->AUDITED->GATE_PASS->"
            "MANIFESTED->SEALED with terminal FAILED"),
        "real_blind_construction_authorized": False,
        "external_action_authority": False,
    }
    freeze = {**root_input, "component_count": len(entries),
              "components": entries, "freeze_root": sha256_json(root_input)}
    freeze["freeze_sha256"] = hashlib.sha256(json.dumps(
        freeze, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    return freeze


def verify_freeze(root: Path, frozen: dict) -> dict:
    recomputed = build_freeze(root)
    mismatches = []
    for key in ("component_count", "component_root", "freeze_root",
                "freeze_sha256", "candidate_commit", "candidate_tree",
                "runtime_root"):
        if frozen.get(key) != recomputed.get(key):
            mismatches.append(key)
    if frozen.get("components") != recomputed.get("components"):
        mismatches.append("components")
    return {"status": "PASS" if not mismatches else "FAIL",
            "component_count": recomputed["component_count"],
            "component_root": recomputed["component_root"],
            "freeze_root": recomputed["freeze_root"],
            "freeze_sha256": recomputed["freeze_sha256"],
            "mismatches": mismatches}
