"""Exact, evidence-checked T23 historical test applicability qualification.

No pytest outcome is changed here. Raw failures remain visible and are only
interpreted after all collected tests have executed.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .lifecycle import verify_historical_transition, verify_lifecycle


LEDGER = "evaluations/t23/historical_applicability.json"
AUDIT = "evaluations/t23/HISTORICAL_FAILURE_RECONCILIATION.md"
PRIOR = "evaluations/t22/test_failure_adjudication.json"
PROMOTION = "evaluations/t22/T22_FINAL_PROMOTION_RECORD.json"
FREEZE = "evaluations/t22/evaluator_freeze.json"
REGISTRY = "evaluations/t23/experiment_lifecycle_registry.json"
RESULT = "evaluations/t23/unrestricted_pytest_result.json"
REPLACEMENT = "t23_protocol.applicability:verify_replacement"
REPLACEMENT_TEST = "tests/test_t23_applicability.py::test_all_historical_replacements"
CLASSES = {"STALE_PRECONSTRUCTION_ASSERTION", "SUPERSEDED_HISTORICAL_ASSERTION"}


def _file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"missing or escaping component: {relative}")
    return path


def _sha(root: Path, relative: str) -> str:
    return hashlib.sha256(_file(root, relative).read_bytes()).hexdigest()


def _json(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads(_file(root, relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid JSON object: {relative}")
    return value


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _committed_bytes(root: Path, relative: str) -> bytes:
    proc = subprocess.run(["git", "show", f"HEAD:{relative}"], cwd=root,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode:
        raise ValueError(f"historical test not tracked at HEAD: {relative}")
    return proc.stdout


def _audit_rows(root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in _file(root, AUDIT).read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `tests/"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) != 8:
            raise ValueError("malformed reconciliation row")
        node, experiment, assertion, expected, observed, premise, classification, repair = cells
        if not node.startswith("`tests/") or not node.endswith("`"):
            raise ValueError("malformed reconciliation node")
        rows.append({"nodeid": node[1:-1], "experiment": experiment,
                     "historical_assertion": assertion,
                     "historical_expected": expected, "current_observed": observed,
                     "original_lifecycle_premise": premise.split("→", 1)[0].strip(),
                     "audit_class": classification, "audit_repair": repair})
    if len(rows) != 26 or len({row["nodeid"] for row in rows}) != 26:
        raise ValueError("reconciliation must contain exactly 26 unique nodes")
    return rows


def _original_experiment(nodeid: str, audit_experiment: str) -> str:
    name = nodeid.split("/", 1)[1].split(".py::", 1)[0]
    for marker in ("t21r10", "t21r11", "t21r12", "t21r13", "t21r15", "t21r16", "t21r17", "t22"):
        if name.startswith(f"test_{marker}_") or name == f"test_{marker}":
            return marker
    if audit_experiment.lower() == "t21r15":
        return "t21r15"
    return "historical_runtime"


def build_ledger(root: Path) -> dict[str, Any]:
    """Derive exact entries from the 26-row audit and frozen T22 adjudication."""
    root = Path(root).resolve()
    prior = _json(root, PRIOR)
    frozen = _json(root, FREEZE)
    if _sha(root, PRIOR) != frozen.get("component_sha256", {}).get(PRIOR):
        raise ValueError("T22 adjudication is not frozen by the evaluator root")
    old_nodes = {entry["nodeid"] for entry in prior["entries"]}
    if len(old_nodes) != 25:
        raise ValueError("frozen T22 adjudication count changed")
    if verify_lifecycle(root, "t22")["status"] != "PASS":
        raise ValueError("T22 promotion is not authenticated")
    rows = _audit_rows(root)
    if len({row["nodeid"] for row in rows} - old_nodes) != 1:
        raise ValueError("reconciliation does not extend T22 by exactly one node")
    entries = []
    for row in rows:
        nodeid = row["nodeid"]
        relative_test = nodeid.split("::", 1)[0]
        digest = _sha(root, relative_test)
        if hashlib.sha256(_committed_bytes(root, relative_test)).hexdigest() != digest:
            raise ValueError(f"historical test changed in working tree: {relative_test}")
        if relative_test in frozen["component_sha256"] and frozen["component_sha256"][relative_test] != digest:
            raise ValueError(f"T22 hash-bound test changed: {relative_test}")
        classification = {"A": "STALE_PRECONSTRUCTION_ASSERTION",
                          "B": "SUPERSEDED_HISTORICAL_ASSERTION"}.get(row["audit_class"])
        if classification is None:
            raise ValueError(f"unclassified audit node: {nodeid}")
        original = _original_experiment(nodeid, row["experiment"])
        if nodeid in old_nodes:
            supersession = PRIOR
            prior_entry = next(entry for entry in prior["entries"] if entry["nodeid"] == nodeid)
            if prior_entry["classification"] not in {
                "OBSOLETE_HISTORICAL_ASSERTION", "SUPERSEDED_BY_CURRENT_FROZEN_COVERAGE"
            }:
                raise ValueError("prior adjudication does not authorize this classification")
            if classification == "STALE_PRECONSTRUCTION_ASSERTION":
                if original == "historical_runtime":
                    raise ValueError("stale path assertion has no experiment transition")
                transition = verify_historical_transition(root, original)
                if transition["status"] != "PASS":
                    raise ValueError(f"historical transition invalid: {original}")
                lifecycle_state = transition["state"]
                lifecycle_evidence = transition["evidence"]
            else:
                lifecycle_state = "SUPERSEDED_BY_T22_PROMOTED"
                lifecycle_evidence = PROMOTION
        else:
            if original != "t22" or classification != "STALE_PRECONSTRUCTION_ASSERTION":
                raise ValueError("unadjudicated node lacks authenticated T22 phase transition")
            supersession = PROMOTION
            lifecycle_state = "PROMOTED"
            lifecycle_evidence = PROMOTION
        entries.append({
            "test_node_id": nodeid,
            "experiment": row["experiment"],
            "original_experiment": original,
            "frozen_test_hash": digest,
            "historical_assertion": row["historical_assertion"],
            "historical_expected": row["historical_expected"],
            "current_observed": row["current_observed"],
            "original_lifecycle_premise": row["original_lifecycle_premise"],
            "current_authenticated_lifecycle": lifecycle_state,
            "classification": classification,
            "superseding_evidence": supersession,
            "superseding_evidence_hash": _sha(root, supersession),
            "lifecycle_evidence": lifecycle_evidence,
            "lifecycle_evidence_hash": _sha(root, lifecycle_evidence),
            "replacement_protection": REPLACEMENT,
            "replacement_test_or_validator": REPLACEMENT_TEST,
            "adjudicated_before_t23_blind_construction": True,
        })
    entries.sort(key=lambda entry: entry["test_node_id"])
    return {
        "schema_version": "t23-historical-applicability-v1",
        "artifact": "T23_HISTORICAL_APPLICABILITY",
        "experiment": "t23",
        "construction_authorized": False,
        "source_reconciliation_sha256": _sha(root, AUDIT),
        "frozen_t22_adjudication_sha256": _sha(root, PRIOR),
        "promotion_record_sha256": _sha(root, PROMOTION),
        "lifecycle_registry_sha256": _sha(root, REGISTRY),
        "entries": entries,
    }


def verify_replacement(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    """Check the actual successor invariant, never suppress the old test."""
    root = Path(root).resolve()
    original = entry["original_experiment"]
    if entry["classification"] == "STALE_PRECONSTRUCTION_ASSERTION" and original != "t22":
        transition = verify_historical_transition(root, original)
        if (transition["status"] != "PASS" or transition["state"] != entry["current_authenticated_lifecycle"]
                or transition["evidence"] != entry["lifecycle_evidence"]
                or transition["evidence_sha256"] != entry["lifecycle_evidence_hash"]):
            raise ValueError(f"replacement lifecycle mismatch: {entry['test_node_id']}")
    else:
        promoted = verify_lifecycle(root, "t22")
        if promoted["status"] != "PASS" or promoted["state"] != "PROMOTED":
            raise ValueError("T22 successor is not authenticated")
        if (original == "t22" and
                (promoted["registered_paths"] != 28 or promoted["present_paths"] != 28)):
            raise ValueError("promoted T22 path registry mismatch")
        # A later promoted state alone is not a replacement for earlier
        # runtime/evaluator hash assertions. Rehash the promoted successor's
        # complete frozen component sets for every such adjudication.
        for freeze in ("evaluations/t22/runtime_freeze.json", FREEZE):
            components = _json(root, freeze).get("component_sha256", {})
            if not components or any(_sha(root, relative) != expected
                                     for relative, expected in components.items()):
                raise ValueError("T22 successor frozen bytes changed")
    return {"status": "PASS", "nodeid": entry["test_node_id"],
            "classification": entry["classification"]}


def validate_applicability(root: Path, result_path: str = RESULT,
                           *, require_tracked: bool = False) -> dict[str, Any]:
    root = Path(root).resolve()
    observed = _json(root, result_path)
    ledger = _json(root, LEDGER)
    if observed.get("schema_version") != "t23-unrestricted-pytest-result-v1":
        raise ValueError("unknown unrestricted result schema")
    if ledger != build_ledger(root):
        raise ValueError("historical applicability ledger differs from authenticated derivation")
    failures = observed.get("failed_nodeids")
    if not isinstance(failures, list) or failures != sorted(set(failures)):
        raise ValueError("invalid observed failure set")
    entries = ledger["entries"]
    ledger_nodes = {entry["test_node_id"] for entry in entries}
    observed_nodes = set(failures)
    missing = sorted(observed_nodes - ledger_nodes)
    extra = sorted(ledger_nodes - observed_nodes)
    if observed.get("deselected") or observed.get("skipped_nodeids") or observed.get("xfail_nodeids") or observed.get("xpass_nodeids"):
        raise ValueError("unrestricted execution had deselection, skip, xfail, or xpass")
    if not observed.get("execution_complete") or observed.get("executed") != observed.get("collected"):
        raise ValueError("unrestricted execution was incomplete")
    counts = observed.get("counts", {})
    if (not isinstance(counts, dict) or sum(counts.values()) != observed["executed"]
            or counts.get("failed") != len(failures)
            or counts.get("skipped") != 0 or counts.get("xfail") != 0
            or counts.get("xpass") != 0
            or observed.get("pytest_exit_code") != (1 if failures else 0)):
        raise ValueError("unrestricted outcome counters are inconsistent")
    passed_nodes = set(observed.get("passed_nodeids", []))
    unexpected_passes = sorted(ledger_nodes & passed_nodes)
    if missing or extra or unexpected_passes:
        return {"status": "FAIL", "observed_failures": len(failures),
                "unrecognized_failures": missing, "unexpected_historical_passes": unexpected_passes,
                "missing_historical_failures": extra,
                "live_failures": 0, "unknown_failures": len(missing) + len(extra),
                "failure_set_sha256": _canonical_hash(failures)}
    if REPLACEMENT_TEST not in passed_nodes:
        raise ValueError("replacement protection test did not pass")
    if require_tracked:
        critical = [LEDGER, REGISTRY, AUDIT, "t23_protocol/applicability.py",
                    "t23_protocol/lifecycle.py", "tests/test_t23_applicability.py",
                    "tests/test_t23_lifecycle.py", "scripts/t23_capture_unrestricted.py"]
        for relative in critical:
            proc = subprocess.run(["git", "ls-files", "--error-unmatch", "--", relative],
                                  cwd=root, capture_output=True, check=False)
            if proc.returncode:
                raise ValueError(f"replacement component is not tracked: {relative}")
    module_name, member = REPLACEMENT.split(":", 1)
    if not callable(getattr(importlib.import_module(module_name), member)):
        raise ValueError("replacement validator not callable")
    protections = [verify_replacement(root, entry) for entry in entries]
    if any(item["status"] != "PASS" for item in protections):
        raise ValueError("replacement protection failed")
    decisions = [{"nodeid": entry["test_node_id"], "classification": entry["classification"],
                  "frozen_test_hash": entry["frozen_test_hash"],
                  "superseding_evidence_hash": entry["superseding_evidence_hash"],
                  "lifecycle_evidence_hash": entry["lifecycle_evidence_hash"],
                  "replacement": protection["status"]}
                 for entry, protection in zip(entries, protections)]
    stale = sum(entry["classification"] == "STALE_PRECONSTRUCTION_ASSERTION" for entry in entries)
    superseded = len(entries) - stale
    return {
        "schema_version": "t23-applicability-verdict-v1",
        "status": "PASS", "verdict": "T23_APPLICABILITY_AWARE_TEST_GATE_PASS",
        "raw_pytest_failed": len(failures), "observed_failures": len(failures),
        "recognized_historical_failures": len(entries), "stale_preconstruction": stale,
        "superseded_historical": superseded, "live_failures": 0, "unknown_failures": 0,
        "unrecognized_failures": [], "unexpected_historical_passes": [],
        "unexpected_historical_failures": 0,
        "classified_failures": [{"test_node_id": entry["test_node_id"],
                                 "classification": entry["classification"]}
                                for entry in entries],
        "replacement_protections_passed": len(protections),
        "replacement_protections_total": len(entries),
        "failure_set_sha256": _canonical_hash(failures),
        "applicability_decision_root": _canonical_hash(decisions),
    }
