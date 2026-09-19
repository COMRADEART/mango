"""Independent data-only T21R13 exact-design auditor.

Mechanically re-expresses the frozen control-fixture recipe (the one-shot
operator script ``t21r13_fixtures.py``) in importable form so the
preconstruction rehearsal and the real pre-seal audit can live-invoke the
exact-design evaluation instead of trusting a cached artifact.  It introduces
no new rule: control rows are generated from the committed contract and
evaluated exclusively by the frozen ``t21r13_exact_design_lib`` handlers,
and real-material observations are derived per leaf with
contract_path / required / observed / status.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r13"
CONTRACT_PATH = OUT_DIR / "holdout_construction_contract.json"
sys.path.insert(0, str(ROOT / "scripts"))

import t21r13_construction_gate as gate  # noqa: E402
import t21r13_exact_design_lib as ed  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bindings() -> dict:
    return {
        "holdout_construction_contract_sha256": _sha(CONTRACT_PATH),
        "exact_design_schema_sha256": _sha(
            OUT_DIR / "exact_design_schema.json"),
        "exact_design_tag_vocabulary_sha256": _sha(
            OUT_DIR / "exact_design_tag_vocabulary.json"),
    }


# --- control fixtures: exact mechanical copies of the frozen recipe ---------

def _make_count_rows(tag, n):
    return [{"case_id": f"syn-{tag}-{i:04d}", "category": tag,
             "construction_tags": [tag],
             "request": {"query": f"synthetic {tag} {i}"},
             "gold": {"expect_status": "ANSWER"}, "mode": "answer"}
            for i in range(n)]


def make_valid_fixture(contract):
    rows = []
    for obj, leaves in ed.LEAF_TYPES.items():
        for leaf, typ in leaves.items():
            if typ != "COUNT" or leaf == "novel_pair_families":
                continue
            rows.extend(_make_count_rows(leaf, int(contract[obj][leaf])))
    per = int(contract["crossdomain_exact_design"]["rows_per_pair"])
    for tag in ed.CROSSDOMAIN_PAIR_TAGS:
        rows.extend(_make_count_rows(tag, per))
    return rows


def make_negative_fixture(contract, obj, leaf):
    rows = make_valid_fixture(contract)
    leaf_type = ed.LEAF_TYPES[obj][leaf]
    if leaf == "novel_pair_families":
        drop = ed.CROSSDOMAIN_PAIR_TAGS[0]
        return [r for r in rows
                if drop not in (r.get("construction_tags") or [])]
    if leaf == "rows_per_pair":
        tag = ed.CROSSDOMAIN_PAIR_TAGS[0]
        out = []
        removed = False
        for r in rows:
            if not removed and tag in (r.get("construction_tags") or []):
                removed = True
                continue
            out.append(r)
        return out
    if leaf_type in {"FORBIDDEN_OVERLAP", "BOOLEAN"}:
        return rows
    out = []
    removed = False
    for r in rows:
        if not removed and leaf in (r.get("construction_tags") or []):
            removed = True
            continue
        out.append(r)
    return out


# --- audits -----------------------------------------------------------------

def audit_controls(contract: dict | None = None) -> dict:
    """Live per-leaf positive/negative controls (38 + 38 control families).

    Positive control: a mechanically valid fixture must PASS every leaf.
    Negative control: a deliberate single-leaf violation (or a forbidden prior
    overlap for FORBIDDEN_OVERLAP/BOOLEAN leaves) must be rejected.
    """
    contract = contract if contract is not None else json.loads(
        CONTRACT_PATH.read_text(encoding="utf-8"))
    controls = []
    for obj, leaf, required, leaf_type in ed.enumerate_leaves(contract):
        pos_rows = make_valid_fixture(contract)
        pos_ctx = {"prior_exact_query_overlap": 0,
                   "prior_pair_template_overlap": 0}
        if leaf == "novel_pair_families":
            pos = ed.check_novel_pair_families(int(required), pos_rows, leaf)
        else:
            pos = ed.evaluate_leaf(obj, leaf, required, leaf_type,
                                   pos_rows, pos_ctx)
        if leaf_type in {"FORBIDDEN_OVERLAP", "BOOLEAN"} and \
                leaf != "novel_pair_families":
            neg_ctx = {"prior_exact_query_overlap": 1,
                       "prior_pair_template_overlap": 1}
            neg_rows = make_valid_fixture(contract)
        else:
            neg_ctx = pos_ctx
            neg_rows = make_negative_fixture(contract, obj, leaf)
        if leaf == "novel_pair_families":
            neg = ed.check_novel_pair_families(int(required), neg_rows, leaf)
        else:
            neg = ed.evaluate_leaf(obj, leaf, required, leaf_type,
                                   neg_rows, neg_ctx)
        pos_ok = bool(pos.get("passed"))
        neg_rejects = not bool(neg.get("passed"))
        controls.append({
            "contract_path": f"{obj}.{leaf}",
            "requirement_type": leaf_type,
            "required": required,
            "positive_control": "PASS" if pos_ok else "FAIL",
            "negative_control": "PASS" if neg_rejects else "FAIL",
            "status": "PASS" if (pos_ok and neg_rejects) else "FAIL",
        })
    passed = sum(1 for c in controls if c["status"] == "PASS")
    return {
        "artifact": "T21R13_EXACT_DESIGN_AUDIT",
        "version": "t21r13-v1",
        "mode": "controls",
        "total_leaves": len(controls),
        "passed": passed,
        "failed": len(controls) - passed,
        "unverifiable": 0,
        "controls": controls,
        "bindings": _bindings(),
        "status": "PASS" if passed == len(controls) else "FAIL",
        "runtime_execution_count": 0,
    }


def audit_rows(rows: list[dict], contract: dict | None = None,
               context: dict | None = None) -> dict:
    """Independent per-leaf observation of candidate rows (real pre-seal)."""
    contract = contract if contract is not None else json.loads(
        CONTRACT_PATH.read_text(encoding="utf-8"))
    design = ed.evaluate_exact_design(contract, rows, context or {})
    return {
        "artifact": "T21R13_EXACT_DESIGN_AUDIT",
        "version": "t21r13-v1",
        "mode": "rows",
        "rows": len(rows),
        "leaf_requirements_total": design["leaf_requirements_total"],
        "passed": design["passed"],
        "failed": design["failed"],
        "unverifiable": design["unhandled"],
        "unknown_construction_tags": design["unknown_construction_tags"],
        "leaves": [{"contract_path": check["contract_path"],
                    "required": check["required"],
                    "observed": check.get("observed"),
                    "status": check["status"]}
                   for check in design["checks"]],
        "bindings": _bindings(),
        "status": design["status"],
        "runtime_execution_count": 0,
    }


def cross_check_with_gate(gate_report: dict, audit_report: dict) -> dict:
    """Gate/auditor disagreement check over every represented leaf."""
    gate_by_path = {check["id"]: check for check in gate_report["checks"]
                    if check.get("level") == "L4_exact_design"}
    disagreements = []
    for leaf in audit_report["leaves"]:
        gate_check = gate_by_path.get(leaf["contract_path"])
        if gate_check is None:
            disagreements.append({"contract_path": leaf["contract_path"],
                                  "reason": "leaf not represented in gate"})
            continue
        gate_pass = bool(gate_check["passed"])
        audit_pass = leaf["status"] == "PASS"
        status_disagreement = gate_pass != audit_pass
        value_disagreement = (
            leaf["observed"] is not None and
            gate_check["actual"] != leaf["observed"])
        if status_disagreement or value_disagreement:
            disagreements.append({
                "contract_path": leaf["contract_path"],
                "gate_observed": gate_check["actual"],
                "audit_observed": leaf["observed"],
            })
    return {
        "artifact": "T21R13_GATE_AUDITOR_CROSSCHECK",
        "version": "t21r13-v1",
        "disagreement_count": len(disagreements),
        "disagreements": disagreements,
        "status": "PASS" if not disagreements else "FAIL",
        "runtime_execution_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--controls", action="store_true",
                        help="audit the frozen control fixtures live")
    parser.add_argument("--output", type=Path,
                        default=OUT_DIR / "exact_design_audit.json")
    arguments = parser.parse_args()
    if arguments.controls:
        report = audit_controls()
    else:
        raise SystemExit("select --controls (rows mode is operator-driven "
                         "during authorized construction only)")
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({"status": report["status"],
                      "passed": report["passed"],
                      "total": report["total_leaves"],
                      "runtime_execution_count": 0}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

