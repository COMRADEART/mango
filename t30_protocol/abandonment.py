"""T29 abandoned real package: immutable commitment + sealed exclusion oracle.

T30 authorization §7–§9/§32/§33.  The T29 real package (512/512) was authored
and finalized privately but never sealed into ``T29-STORE-01``: its
construction one-shot is UNSPENT_BUT_PERMANENTLY_INELIGIBLE.  It is retained
immutable as historical audit evidence and is predecessor-private material for
T30 exclusion.

Prospective determination (§32): a sealed machine-only abandonment oracle IS
required before any T30 real construction, because the abandoned package is
real clean-room material that never reached a sealed store and so is covered
by neither the T27/T28 sealed oracles nor the public historical index.  It can
be done without opening or publishing any T29 row: the private package
directory holds a hash-only nine-dimension fingerprint file (SHA-256 values
produced by the frozen fingerprint formula at T29 finalization).  The oracle
authenticates that file against the public one-way commitment (its
fingerprint root must equal the committed prospective root, and the private
finalization record must reproduce the committed finalization root), then
counts overlaps.  Row files (scenarios/gold) are never opened.  If the
hash-only file is absent or does not reproduce the commitment, the oracle
fails closed and T30 real construction is refused.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

from .exclusion import DIMENSIONS, GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS

T29_ADJUDICATION_PATH = (
    "evaluations/t29/T29_REAL_CONSTRUCTION_ELIGIBILITY_ADJUDICATION.json")
T29_ABANDONMENT_COMMITMENT_PATH = "evaluations/t30/t29_abandonment_commitment.json"
PACKAGE_CLASSIFICATION = "T29_ABANDONED_REAL_PACKAGE_INELIGIBLE_FOR_SUCCESSOR_USE"
T29_TERMINAL = ("T29_REAL_PACKAGE_AUTHORED_BUT_CONSTRUCTION_PERMANENTLY_"
                "INELIGIBLE_DUE_TO_FROZEN_T28_ACCESS_JOURNAL_SCHEMA_DEFECT")
#: The only files the oracle may read inside the private package boundary.
HASH_ONLY_FINGERPRINT_FILE = "fingerprints.json"
FINALIZATION_FILE = "finalization.json"
#: Row files that must never be opened by any T30 code path.
FORBIDDEN_ROW_FILES = ("cases.json", "gold.json", "author_seed.private.json")
COMMITMENT_FIELDS = ("scenario_bundle_root", "gold_bundle_root",
                     "prospective_fingerprint_root", "finalization_root",
                     "package_classification")
ORACLE_IMPLEMENTATION = (
    "t30_protocol.abandonment:run_sealed_t29_abandoned_to_t30_overlap_oracle")
ARTIFACT = "T29_ABANDONED_TO_T30_OVERLAP_ORACLE_RESULT"
REAL_SCHEMA = "t30-t29-abandoned-sealed-overlap-oracle-result-v1"
SYNTHETIC_SCHEMA = "t30-t29-abandoned-synthetic-overlap-oracle-result-v1"
OFFICIAL_SCOPE = "OFFICIAL_T29_ABANDONED"
RESULT_FIELDS = frozenset({
    "schema_version", "artifact", "experiment", "mode",
    "official_commitment_scope", "oracle_implementation",
    "t29_abandonment_commitment_root", "t29_package_classification",
    "t29_prospective_fingerprint_root", "t29_finalization_root",
    "t29_package_authenticated", "t29_row_files_opened",
    "t29_structural_exempt_populations",
    "t30_prospective_fingerprint_root", "dimensions",
    "overall_prohibited_overlap", "oracle_execution_timestamp",
    "outside_boundary_private_rows_exposed", "result_sha256",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hex64(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _hash_sets(values: Any, label: str) -> dict[str, set[str]]:
    if not isinstance(values, dict) or set(values) != set(DIMENSIONS):
        raise ValueError(f"{label} requires all nine dimensions")
    result = {}
    for name in DIMENSIONS:
        items = values[name]
        if not isinstance(items, list) or not all(_hex64(item) for item in items):
            raise ValueError(f"{label} dimension must hold SHA-256 values: {name}")
        result[name] = set(items)
    return result


def _fingerprint_root(sets: dict[str, set[str]]) -> str:
    return sha256_json({name: sorted(sets[name]) for name in DIMENSIONS})


def t29_abandonment_commitment(root: Path) -> dict[str, Any]:
    """One-way immutable commitment derived from the PUBLIC_SAFE T29
    adjudication (roots + classification only; no row data)."""
    root = Path(root).resolve()
    adjudication = json.loads((root / T29_ADJUDICATION_PATH).read_text(
        encoding="utf-8"))
    core_adjudication = {key: value for key, value in adjudication.items()
                         if key != "adjudication_root"}
    if adjudication.get("adjudication_root") != sha256_json(core_adjudication):
        raise ValueError("T29 adjudication root does not reproduce")
    package = adjudication.get("abandoned_package") or {}
    if (adjudication.get("terminal") != T29_TERMINAL
            or adjudication.get("classification") != "PUBLIC_SAFE"
            or adjudication.get("blind_content_included") is not False
            or package.get("classification") != PACKAGE_CLASSIFICATION
            or package.get("reuse_permitted") is not False
            or package.get("row_content_published") is not False):
        raise ValueError("T29 adjudication does not bind an abandoned package")
    core = {
        "schema_version": "t30-t29-abandonment-commitment-v1",
        "artifact": "T30_T29_ABANDONMENT_COMMITMENT",
        "classification": "PUBLIC_SAFE",
        "scenario_bundle_root": package["scenario_bundle_root"],
        "gold_bundle_root": package["gold_bundle_root"],
        "prospective_fingerprint_root": package["prospective_fingerprint_root"],
        "finalization_root": package["finalization_root"],
        "package_classification": package["classification"],
        "source_adjudication": T29_ADJUDICATION_PATH,
        "source_adjudication_root": adjudication["adjudication_root"],
        "t29_terminal": adjudication["terminal"],
        "construction_one_shot": "UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        "capability_verdict": "NOT_MEASURED",
        "reuse_permitted": False, "row_data_included": False,
    }
    if not all(_hex64(core[name]) for name in COMMITMENT_FIELDS[:4]):
        raise ValueError("T29 abandonment commitment roots invalid")
    return {**core, "commitment_root": sha256_json(
        {name: core[name] for name in COMMITMENT_FIELDS})}


def abandonment_oracle_requirement() -> dict[str, Any]:
    """§32 prospective determination (frozen before any T30 real authoring)."""
    return {
        "schema_version": "t30-t29-abandonment-oracle-requirement-v1",
        "artifact": "T30_T29_ABANDONMENT_ORACLE_REQUIREMENT",
        "classification": "PUBLIC_SAFE",
        "sealed_machine_only_abandonment_oracle_required": True,
        "reason": ("the abandoned T29 package is real clean-room material that "
                   "never reached a sealed store; neither the T27/T28 sealed "
                   "oracles nor the public historical index cover it"),
        "mechanism": ("hash-only nine-dimension fingerprint file authenticated "
                      "against the public one-way commitment; row files are "
                      "never opened"),
        "oracle_implementation": ORACLE_IMPLEMENTATION,
        "readable_files": [HASH_ONLY_FINGERPRINT_FILE, FINALIZATION_FILE],
        "forbidden_files": list(FORBIDDEN_ROW_FILES),
        "invocation": ("inside t30_protocol.construction:construct_real (live "
                       "recomputation bound to the packaged result)"),
        "fail_closed_policy": ("absent hash-only file, commitment mismatch, or "
                               "nonzero overlap refuses T30 construction "
                               "pre-ledger"),
        "t29_package_reuse_forbidden": True,
        "t30_real_material_must_be_newly_authored": True,
    }


def _authenticate_package(package_dir: Path, commitment: dict[str, Any]
                          ) -> dict[str, set[str]]:
    package_dir = Path(package_dir)
    finalization = json.loads((package_dir / FINALIZATION_FILE).read_text(
        encoding="utf-8"))
    core = {key: value for key, value in finalization.items()
            if key != "finalization_root"}
    if (finalization.get("finalization_root") != sha256_json(core)
            or finalization["finalization_root"] != commitment["finalization_root"]
            or finalization.get("scenario_bundle_root")
            != commitment["scenario_bundle_root"]
            or finalization.get("gold_bundle_root")
            != commitment["gold_bundle_root"]
            or finalization.get("prospective_fingerprint_root")
            != commitment["prospective_fingerprint_root"]):
        raise ValueError("T29 abandoned package finalization does not reproduce "
                         "the public commitment")
    fingerprints = _hash_sets(json.loads(
        (package_dir / HASH_ONLY_FINGERPRINT_FILE).read_text(encoding="utf-8")),
        "T29 abandoned fingerprint file")
    if _fingerprint_root(fingerprints) != commitment["prospective_fingerprint_root"]:
        raise ValueError("T29 abandoned fingerprint file does not reproduce the "
                         "committed prospective root")
    return fingerprints


def run_sealed_t29_abandoned_to_t30_overlap_oracle(
        *, root: Path, package_dir: Path, prospective_root: str,
        prospective: dict[str, list[str]],
        commitment: dict[str, Any] | None = None,
        timestamp: str | None = None) -> dict[str, Any]:
    """Sealed machine-only T29-abandoned → T30 overlap oracle.

    ``commitment`` None = official scope (derived from the repository's public
    adjudication; caller commitments are refused in official scope by
    construction).  A supplied commitment = DISPOSABLE_STANDIN scope."""
    if commitment is None:
        commitment = t29_abandonment_commitment(root)
        scope = OFFICIAL_SCOPE
    else:
        scope = "DISPOSABLE_STANDIN"
    future = _hash_sets(prospective, "T30 prospective oracle input")
    if _fingerprint_root(future) != prospective_root:
        raise ValueError("prospective fingerprint root does not bind the "
                         "supplied hashes")
    authenticated = _authenticate_package(Path(package_dir), commitment)
    # Frozen structural policy (same as the T27/T28 sealed oracles'
    # observed_bundle_fingerprints): family names, capability labels, the
    # fixed fallback condition and step relations are contract-forced
    # vocabulary, not identity; they are STRUCTURAL_SHARED_FROZEN_EMPTY on the
    # historical side and only their populations are recorded.
    exempt = {name: (len(authenticated[name])
                     if name in GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS else 0)
              for name in DIMENSIONS}
    historical = {name: (set() if name in GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS
                         else authenticated[name]) for name in DIMENSIONS}
    dimensions = {}
    total = 0
    for name in DIMENSIONS:
        overlap = len(future[name] & historical[name])
        total += overlap
        dimensions[name] = {"applicable": bool(future[name]),
                            "prospective_population": len(future[name]),
                            "historical_population": len(historical[name]),
                            "overlap_count": overlap}
    core = {
        "schema_version": REAL_SCHEMA, "artifact": ARTIFACT,
        "experiment": "t30", "mode": "REAL_SEALED",
        "official_commitment_scope": scope,
        "oracle_implementation": ORACLE_IMPLEMENTATION,
        "t29_abandonment_commitment_root": commitment["commitment_root"],
        "t29_package_classification": commitment["package_classification"],
        "t29_prospective_fingerprint_root":
            commitment["prospective_fingerprint_root"],
        "t29_finalization_root": commitment["finalization_root"],
        "t29_package_authenticated": True, "t29_row_files_opened": 0,
        "t29_structural_exempt_populations": exempt,
        "t30_prospective_fingerprint_root": prospective_root,
        "dimensions": dimensions, "overall_prohibited_overlap": total,
        "oracle_execution_timestamp": timestamp or _now(),
        "outside_boundary_private_rows_exposed": 0,
    }
    return {**core, "result_sha256": sha256_json(core)}


def synthetic_abandonment_oracle_result(prospective_root: str,
                                        prospective: dict[str, list[str]],
                                        *, variant: int = 0) -> dict[str, Any]:
    """Explicitly disposable SYNTHETIC result (lifecycle rehearsals only)."""
    future = _hash_sets(prospective, "T30 prospective oracle input")
    commitment_root = sha256_json(("synthetic-t29-abandonment", variant))
    dimensions = {name: {"applicable": bool(future[name]),
                         "prospective_population": len(future[name]),
                         "historical_population": 1, "overlap_count": 0}
                  for name in DIMENSIONS}
    core = {
        "schema_version": SYNTHETIC_SCHEMA, "artifact": ARTIFACT,
        "experiment": "t30", "mode": "SYNTHETIC_DISPOSABLE",
        "official_commitment_scope": "SYNTHETIC_DISPOSABLE",
        "oracle_implementation":
            "t30_protocol.abandonment:synthetic_abandonment_oracle_result",
        "t29_abandonment_commitment_root": commitment_root,
        "t29_package_classification": "SYNTHETIC_DISPOSABLE_PACKAGE",
        "t29_prospective_fingerprint_root": sha256_json(
            ("synthetic-t29-prospective", variant)),
        "t29_finalization_root": sha256_json(
            ("synthetic-t29-finalization", variant)),
        "t29_package_authenticated": False, "t29_row_files_opened": 0,
        "t29_structural_exempt_populations": {name: 0 for name in DIMENSIONS},
        "t30_prospective_fingerprint_root": prospective_root,
        "dimensions": dimensions, "overall_prohibited_overlap": 0,
        "oracle_execution_timestamp": f"2026-09-30T00:00:0{variant % 10}+00:00",
        "outside_boundary_private_rows_exposed": 0,
    }
    return {**core, "result_sha256": sha256_json(core)}


def verify_abandonment_oracle_result(
        result: dict[str, Any], *, mode: str, root: Path | None = None,
        expected_t30_root: str | None = None,
        expected_commitment_root: str | None = None) -> dict[str, Any]:
    if mode not in {"REAL", "REAL_REHEARSAL", "SYNTHETIC"}:
        raise ValueError("unknown T29 abandonment oracle verification mode")
    if not isinstance(result, dict) or set(result) != RESULT_FIELDS:
        raise ValueError("T29 abandonment oracle result has unknown or absent "
                         "fields")
    if result["artifact"] != ARTIFACT or result["experiment"] != "t30":
        raise ValueError("T29 abandonment oracle result identity mismatch")
    commitment_exact = False
    if mode == "REAL":
        if root is None:
            raise ValueError("real abandonment verification requires the "
                             "repository root")
        official = t29_abandonment_commitment(root)
        if (result["schema_version"] != REAL_SCHEMA
                or result["mode"] != "REAL_SEALED"
                or result["official_commitment_scope"] != OFFICIAL_SCOPE
                or result["oracle_implementation"] != ORACLE_IMPLEMENTATION
                or result["t29_package_authenticated"] is not True):
            raise ValueError("real construction requires the authenticated "
                             "sealed T29 abandonment oracle")
        commitment_exact = (
            result["t29_abandonment_commitment_root"]
            == official["commitment_root"]
            and result["t29_prospective_fingerprint_root"]
            == official["prospective_fingerprint_root"]
            and result["t29_finalization_root"] == official["finalization_root"]
            and result["t29_package_classification"] == PACKAGE_CLASSIFICATION)
        if not commitment_exact:
            raise ValueError("T29 abandonment oracle commitment is not the "
                             "official public commitment")
    elif mode == "REAL_REHEARSAL":
        if (result["schema_version"] != REAL_SCHEMA
                or result["mode"] != "REAL_SEALED"
                or result["official_commitment_scope"] != "DISPOSABLE_STANDIN"
                or result["oracle_implementation"] != ORACLE_IMPLEMENTATION
                or result["t29_package_authenticated"] is not True):
            raise ValueError("T29 abandonment rehearsal is not authenticated")
        commitment_exact = (expected_commitment_root is None
                            or result["t29_abandonment_commitment_root"]
                            == expected_commitment_root)
        if not commitment_exact:
            raise ValueError("T29 abandonment rehearsal commitment mismatch")
    else:
        if (result["schema_version"] != SYNTHETIC_SCHEMA
                or result["mode"] != "SYNTHETIC_DISPOSABLE"
                or result["t29_package_authenticated"] is not False):
            raise ValueError("synthetic abandonment oracle must be explicit")
    if expected_t30_root is not None and \
            result["t30_prospective_fingerprint_root"] != expected_t30_root:
        raise ValueError("abandonment oracle prospective T30 root mismatch")
    exempt = result["t29_structural_exempt_populations"]
    if (not isinstance(exempt, dict) or set(exempt) != set(DIMENSIONS)
            or any(type(value) is not int or value < 0
                   or (value and name not in GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS)
                   for name, value in exempt.items())):
        raise ValueError("abandonment structural exemption is not the frozen "
                         "policy")
    for name in GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS:
        entry = result["dimensions"].get(name) if isinstance(
            result["dimensions"], dict) else None
        if isinstance(entry, dict) and entry.get("historical_population") not in (
                0, None) and mode != "SYNTHETIC":
            raise ValueError("structural dimension compared against the "
                             "abandoned package")
    if result["t29_row_files_opened"] != 0:
        raise ValueError("T29 abandoned row files were opened")
    if not isinstance(result["dimensions"], dict) or set(
            result["dimensions"]) != set(DIMENSIONS):
        raise ValueError("abandonment oracle must bind nine dimensions")
    total = 0
    for name in DIMENSIONS:
        entry = result["dimensions"][name]
        if not isinstance(entry, dict) or set(entry) != {
                "applicable", "prospective_population",
                "historical_population", "overlap_count"}:
            raise ValueError(f"abandonment dimension binding mismatch: {name}")
        if any(type(entry[field]) is not int or entry[field] < 0 for field in (
                "prospective_population", "historical_population",
                "overlap_count")):
            raise ValueError(f"abandonment population invalid: {name}")
        total += entry["overlap_count"]
    if total != 0 or result["overall_prohibited_overlap"] != 0:
        raise ValueError("T29-abandoned-to-T30 prohibited overlap is nonzero")
    if result["outside_boundary_private_rows_exposed"] != 0:
        raise ValueError("abandonment oracle exposed private rows")
    if result["result_sha256"] != sha256_json(
            {key: value for key, value in result.items()
             if key != "result_sha256"}):
        raise ValueError("T29 abandonment oracle result hash mismatch")
    return {"status": "PASS", "mode": mode, "dimension_count": len(DIMENSIONS),
            "overall_prohibited_overlap": 0,
            "result_sha256": result["result_sha256"],
            "t29_package_authenticated": result["t29_package_authenticated"],
            "t29_commitment_exact": commitment_exact,
            "t29_abandonment_commitment_root":
                result["t29_abandonment_commitment_root"],
            "t29_row_files_opened": 0,
            "outside_boundary_private_rows_exposed": 0}


def disposable_t29_abandoned_package(parent: Path, *, variant: int = 0
                                     ) -> tuple[Path, dict[str, Any]]:
    """Disposable official-layout abandoned package (hash-only file,
    finalization record, and deliberately present decoy row files that the
    oracle must never open)."""
    package = Path(parent) / f"CLEAN_ROOM_T29_STANDIN_{variant}"
    package.mkdir(parents=True, exist_ok=False)
    fingerprints = {name: sorted({sha256_json(("t29-abandoned-standin", variant,
                                               name, index))
                                  for index in range(3)})
                    for name in DIMENSIONS}
    prospective_root = sha256_json(fingerprints)
    finalization_core = {
        "schema_version": "t29-real-package-finalization-v1",
        "classification": "PRIVATE_AUDIT",
        "scenario_bundle_root": sha256_json(("standin-scenarios", variant)),
        "gold_bundle_root": sha256_json(("standin-gold", variant)),
        "prospective_fingerprint_root": prospective_root,
    }
    finalization = {**finalization_core,
                    "finalization_root": sha256_json(finalization_core)}
    (package / HASH_ONLY_FINGERPRINT_FILE).write_text(
        json.dumps(fingerprints, sort_keys=True) + "\n", encoding="utf-8")
    (package / FINALIZATION_FILE).write_text(
        json.dumps(finalization, sort_keys=True) + "\n", encoding="utf-8")
    for name in FORBIDDEN_ROW_FILES:
        # Decoys: unreadable garbage — any accidental open/parse fails loudly.
        (package / name).write_bytes(b"\xff\xfeDISPOSABLE-DECOY-NEVER-OPEN")
    core = {
        "schema_version": "t30-t29-abandonment-commitment-v1",
        "artifact": "T30_T29_ABANDONMENT_COMMITMENT",
        "classification": "SYNTHETIC_DISPOSABLE",
        "scenario_bundle_root": finalization["scenario_bundle_root"],
        "gold_bundle_root": finalization["gold_bundle_root"],
        "prospective_fingerprint_root": prospective_root,
        "finalization_root": finalization["finalization_root"],
        "package_classification": "DISPOSABLE_STANDIN_ABANDONED_PACKAGE",
    }
    commitment = {**core, "commitment_root": sha256_json(
        {name: core[name] for name in COMMITMENT_FIELDS})}
    return package, commitment


def official_abandonment_readiness(root: Path, package_dir: Path
                                   ) -> dict[str, Any]:
    """Preconstruction readiness (§32): authenticate the actual private
    hash-only fingerprint file against the public commitment, report only
    aggregate populations; row files are never opened."""
    commitment = t29_abandonment_commitment(root)
    package_dir = Path(package_dir)
    row_files_present = all((package_dir / name).is_file()
                            for name in ("cases.json", "gold.json"))
    fingerprints = _authenticate_package(package_dir, commitment)
    return {
        "schema_version": "t30-t29-abandonment-readiness-v1",
        "artifact": "T30_T29_ABANDONMENT_READINESS",
        "classification": "PUBLIC_SAFE", "status": "PASS",
        "commitment_root": commitment["commitment_root"],
        "hash_only_fingerprint_file_authenticated": True,
        "fingerprint_populations": {name: len(fingerprints[name])
                                    for name in DIMENSIONS},
        "package_retained_immutable": row_files_present,
        "t29_row_files_opened": 0, "private_rows_exposed": 0,
        "sealed_machine_only_abandonment_oracle_required": True,
    }
