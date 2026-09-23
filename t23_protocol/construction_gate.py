"""Static T23 construction gate; executes neither candidate nor evaluator."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from t21_protocol.util import iter_jsonl
from .construction_ledger import construction_state, frozen_bindings, verify_ledger
from .contract import CANDIDATE_COMMIT, CANDIDATE_TREE, enumerate_leaf_requirements, load_t23_contract, sha256_json
from .lock import verify_lock


def run_construction_gate(source_root: Path, material_root: Path, *,
                          real: bool, namespace: str) -> dict[str, Any]:
    """Read frozen construction bytes and issue a machine-verifiable gate result."""
    source_root, material_root = Path(source_root).resolve(), Path(material_root).resolve()
    contract_path = source_root / "evaluations/t23/t23_master_contract.json"
    contract = load_t23_contract(contract_path)
    design = contract.get("construction_design")
    requirements = contract.get("construction_requirements")
    leaves = enumerate_leaf_requirements(contract.document)
    out = material_root / "evaluations/t23"
    suites = out / "suites"
    expected = frozen_bindings(source_root, real=real, namespace=namespace)
    ledger = verify_ledger(out / "construction_run_ledger.json", expected)
    author_lock = verify_lock(source_root / "evaluations/t23/author_lock.json")
    lock_bytes = (source_root / "evaluations/t23/author_lock.json").read_bytes()
    audits = {name: json.loads((suites / f"{name}_audit.json").read_text(encoding="utf-8"))
              for name in ("static", "blindness", "uniqueness")}
    audit_summary = json.loads((out / "construction_audits.json").read_text(encoding="utf-8"))
    inputs = list(iter_jsonl(suites / "inputs.jsonl"))
    gold = list(iter_jsonl(suites / "gold.jsonl"))
    counts = Counter(row.get("family") for row in gold)
    suite_counts: dict[str, int] = {}
    for family, relative in design["suite_mapping"].items():
        path = material_root / relative
        if not path.is_file():
            raise ValueError(f"T23 missing family suite {family}")
        rows = list(iter_jsonl(path))
        expected_rows = [
            {"case_id": inp["case_id"], "family": expected["family"],
             "candidate_input": inp["candidate_input"],
             "expected_route": expected["expected_route"],
             "expected_reason": expected["expected_reason"]}
            for inp, expected in zip(inputs, gold) if expected.get("family") == family
        ]
        if rows != expected_rows:
            raise ValueError(f"T23 suite family mismatch: {family}")
        suite_counts[family] = len(rows)
    checks = {
        "authorization_identity": expected["authorization"] == ledger["bindings"]["authorization"],
        "candidate_identity": ledger["bindings"]["candidate_commit"] == CANDIDATE_COMMIT
                              and ledger["bindings"]["candidate_tree"] == CANDIDATE_TREE
                              and author_lock["status"] == "PASS",
        "preconstruction_freeze_identity": ledger["bindings"]["preconstruction_freeze_sha256"] == expected["preconstruction_freeze_sha256"]
                                               and ledger["bindings"]["component_root"] == expected["component_root"]
                                               and ledger["bindings"]["freeze_root"] == expected["freeze_root"],
        "ledger_integrity": ledger["identity_root"] == sha256_json(expected),
        "one_shot_attempt": ledger["bindings"]["attempt"] == requirements["one_shot_attempt"],
        "exact_namespace": ledger["bindings"]["real_namespace"] == namespace,
        "construction_contract": ledger["bindings"]["construction_contract_sha256"] == hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        "author_lock": ledger["bindings"]["author_lock_sha256"] == hashlib.sha256(lock_bytes).hexdigest(),
        "expected_total_rows": len(inputs) == len(gold) == design["total_rows"],
        "expected_family_suite_design": counts == {name: design["cases_per_family"] for name in design["families"]}
                                        and suite_counts == {name: design["cases_per_family"] for name in design["families"]},
        "route_reason_design": audits["static"].get("route_counts") == design["route_counts"]
                               and audits["static"].get("reason_counts") == design["reason_counts"],
        "zero_runtime_execution": audits["static"].get("candidate_rows_executed") == requirements["candidate_rows_executed"],
        "zero_evaluator_execution": audits["static"].get("evaluator_rows_executed") == requirements["evaluator_rows_executed"],
        "zero_annotation_violations": audits["static"].get("annotation_violations") == requirements["annotation_violations"],
        "exclusion_audit": audits["uniqueness"].get("status") == requirements["exclusion_status"],
        "blindness_audit": audits["blindness"].get("status") == requirements["blindness_status"]
                           and audits["blindness"].get("violations") == 0,
        "uniqueness_audit": audits["uniqueness"].get("status") == requirements["uniqueness_status"]
                            and audits["uniqueness"].get("violations") == 0,
        "static_audit": audits["static"].get("status") == "PASS",
        "audit_summary_integrity": audit_summary.get("status") == "PASS"
                                   and all(audit_summary.get(name) == value
                                           for name, value in audits.items()),
        "manifest_prerequisites": all((suites / f"{name}_audit.json").is_file()
                                      for name in ("static", "blindness", "uniqueness"))
                                  and (material_root / "rag/gk_holdout_t23/corpus_manifest.json").is_file(),
        "state": construction_state(material_root) == "AUDITED",
        "contract_leaves": len(leaves) > 0,
    }
    if not all(checks.values()):
        raise ValueError(f"T23 construction gate refused: {[k for k,v in checks.items() if not v]}")
    return {"schema_version": "t23-construction-gate-v1", "status": "PASS",
            "checks": checks, "check_count": len(checks),
            "leaf_requirement_count": len(leaves),
            "leaf_requirement_root": sha256_json(leaves),
            "rows": len(inputs), "family_count": len(counts), "suite_count": len(suite_counts),
            "candidate_rows_executed": 0, "evaluator_rows_executed": 0}
