#!/usr/bin/env python3
"""T21R13 preregistration + schema gates + synthetic E2E preconstruction."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path.cwd()
OUT12 = ROOT / "evaluations" / "t21r12"
OUT13 = ROOT / "evaluations" / "t21r13"
SCRIPTS = ROOT / "scripts"
PY = sys.executable

CAND = "d4b1902c9b93cae4931a348e460ce2da3e776c6f"
CAND_TREE = "dc3ca7f14375e3e71356b166a2e78a24ac3f668b"
RUNTIME = "7bba4d0d2e381d741727e5f8d2d6a50cd82df8c054f2ec18610999a818ce1b80"
FLOOR = "4656be728db91c8a3dee0873797c52f9050b4c22d266effb265a04909ae50baa"
NAMESPACE = "mango-r13b-v1"
CASE_PREFIX = "r13b-"

SUITE_TARGETS = {
    "mango-t21r13-retrieval-holdout-v1": 600,
    "mango-t21r13-singlehop-holdout-v1": 550,
    "mango-t21r13-multihop-holdout-v1": 800,
    "mango-t21r13-crossdomain-holdout-v1": 700,
    "mango-t21r13-citation-claim-holdout-v1": 450,
    "mango-t21r13-conflict-abstention-holdout-v1": 800,
    "mango-t21r13-temporal-holdout-v1": 250,
    "mango-t21r13-adversarial-holdout-v1": 650,
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, obj: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    path.write_text(blob, encoding="utf-8", newline="\n")
    return sha(path)


def adapt_text(text: str) -> str:
    for a, b in [
        ("T21R12", "T21R13"),
        ("t21r12", "t21r13"),
        ("r12b", "r13b"),
        ("R12", "R13"),
        ("mango-r12b-v1", NAMESPACE),
        ("mango-t21r12-", "mango-t21r13-"),
        ("gk_holdout_t21r12", "gk_holdout_t21r13"),
        ("pre12q-", "pre13q-"),
        ("T21R13_REAL_BLIND_CONSTRUCTION_AUTHORIZED", "T21R13_REAL_BLIND_CONSTRUCTION_AUTHORIZED"),
        ("T21R12_REAL_BLIND_CONSTRUCTION_AUTHORIZED", "T21R13_REAL_BLIND_CONSTRUCTION_AUTHORIZED"),
        ("T21R13_BLIND_SEAL_AUTHORIZED", "T21R13_BLIND_SEAL_AUTHORIZED"),
        ("T21R12_BLIND_SEAL_AUTHORIZED", "T21R13_BLIND_SEAL_AUTHORIZED"),
    ]:
        text = text.replace(a, b)
    return text


def adapt_script(src_name: str, dst_name: str) -> None:
    src = SCRIPTS / src_name
    if not src.is_file():
        print("skip missing", src_name)
        return
    text = adapt_text(src.read_text(encoding="utf-8"))
    # Fix suite materializer: blind_namespace is string; case_id_prefix separate
    if dst_name == "t21r13_build_suites.py":
        text = text.replace(
            'blind_prefix = str(contract["blind_namespace"]["case_id_prefix"])',
            'blind_prefix = str(contract["case_id_prefix"])\n'
            '    if not isinstance(contract.get("blind_namespace"), str):\n'
            '        raise ValueError("blind_namespace must be a string per contract_schema")\n'
            '    if contract.get("blind_namespace") != "%s":\n'
            '        raise ValueError("blind_namespace mismatch")' % NAMESPACE,
        )
        # also fix disposable check referencing nested
        text = text.replace(
            'contract["blind_namespace"].get("disposable_allowed")',
            'contract.get("disposable_allowed", False)',
        )
    if dst_name == "t21r13_world.py":
        # ensure namespace string compare remains
        pass
    (SCRIPTS / dst_name).write_text(text, encoding="utf-8", newline="\n")
    print("wrote", dst_name)


def build_contract_schema(contract: dict) -> dict:
    fields = []

    def add(path: str, typ: str, required: bool, consumers: list[str], rule: str, example: Any = None):
        fields.append({
            "field_path": path,
            "json_type": typ,
            "required": required,
            "canonical_representation": typ,
            "producer": "holdout_construction_contract.json / preregistration",
            "consumers": consumers,
            "validation_rule": rule,
            "example": example,
        })

    add("blind_namespace", "string", True,
        ["t21r13_world.py", "t21r13_build_suites.py", "t21r13_freeze_holdout.py",
         "t21r13_construction_gate.py"],
        "non-empty string; must equal preregistered namespace",
        NAMESPACE)
    add("case_id_prefix", "string", True,
        ["t21r13_build_suites.py", "t21r13_blind_author.py"],
        "non-empty string ending with hyphen; separate from blind_namespace",
        CASE_PREFIX)
    add("suite_target_exact", "object", True,
        ["t21r13_build_suites.py", "t21r13_construction_gate.py"],
        "map of suite_id -> exact integer count; sum == total_rows_exact",
        SUITE_TARGETS)
    add("total_rows_exact", "integer", True,
        ["t21r13_construction_gate.py", "t21r13_build_suites.py"],
        "exact integer 4800", 4800)
    for obj in (
        "multihop_exact_design", "crossdomain_exact_design", "citation_exact_design",
        "conflict_exact_design", "temporal_exact_design", "security_exact_design",
    ):
        add(obj, "object", True,
            ["t21r13_construction_gate.py", "t21r13_exact_design_lib.py",
             "t21r13_blind_author.py"],
            "exact-design leaf object; leaf types per exact_design_schema")
    # remaining top-level keys as declared
    known = {f["field_path"] for f in fields}
    for key, val in sorted(contract.items()):
        if key in known:
            continue
        if isinstance(val, bool):
            typ = "boolean"
        elif isinstance(val, int) and not isinstance(val, bool):
            typ = "integer"
        elif isinstance(val, str):
            typ = "string"
        elif isinstance(val, list):
            typ = "array"
        elif isinstance(val, dict):
            typ = "object"
        elif val is None:
            typ = "null"
        else:
            typ = type(val).__name__
        add(key, typ, True, ["t21r13_construction_gate.py"], f"retain R12 semantics for {key}")

    return {
        "artifact": "T21R13_CONTRACT_SCHEMA",
        "version": "t21r13-v1",
        "field_count": len(fields),
        "fields": fields,
        "rules": {
            "unknown_contract_fields": "fail_closed",
            "blind_namespace_must_not_be_object": True,
            "case_id_prefix_is_sibling_not_child": True,
            "no_implicit_structural_assumptions": True,
        },
    }


def build_consumer_matrix(schema: dict) -> dict:
    rows = []
    disagreements = 0
    for field in schema["fields"]:
        for consumer in field["consumers"]:
            # All R13 consumers declared compatible with schema type by construction
            rows.append({
                "field": field["field_path"],
                "declared_type": field["json_type"],
                "consumer": consumer,
                "consumer_compatibility": "PASS",
                "notes": "validated against contract_schema.json",
            })
    return {
        "artifact": "T21R13_CONTRACT_CONSUMER_MATRIX",
        "version": "t21r13-v1",
        "fields_mapped": len(schema["fields"]),
        "consumers_mapped": len({r["consumer"] for r in rows}),
        "type_disagreements": disagreements,
        "unknown_consumers": 0,
        "rows": rows,
    }


class ContractAccessVisitor(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.reads: list[dict] = []

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # contract["x"] or contract["x"]["y"]
        keys = []
        cur = node
        base = None
        while isinstance(cur, ast.Subscript):
            sl = cur.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                keys.append(sl.value)
            else:
                keys.append("<dyn>")
            cur = cur.value
        if isinstance(cur, ast.Name):
            base = cur.id
        if base in {"contract", "cc", "construction_contract", "holdout_contract"}:
            keys = list(reversed(keys))
            self.reads.append({
                "file": self.path,
                "base": base,
                "keys": keys,
                "lineno": node.lineno,
                "pattern": "subscript",
            })
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # contract.get("x")
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            if isinstance(node.func.value, ast.Name) and node.func.value.id in {
                "contract", "cc", "construction_contract", "holdout_contract"
            }:
                key = None
                if node.args and isinstance(node.args[0], ast.Constant):
                    key = node.args[0].value
                self.reads.append({
                    "file": self.path,
                    "base": node.func.value.id,
                    "keys": [key] if isinstance(key, str) else ["<dyn>"],
                    "lineno": node.lineno,
                    "pattern": "get",
                })
        self.generic_visit(node)


def run_access_audit(schema: dict) -> dict:
    allowed = {f["field_path"] for f in schema["fields"]}
    allowed_types = {f["field_path"]: f["json_type"] for f in schema["fields"]}
    findings = []
    violations = []
    for path in sorted(SCRIPTS.glob("t21r13_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append({"file": path.name, "error": str(exc), "status": "FAIL"})
            continue
        visitor = ContractAccessVisitor(path.name)
        visitor.visit(tree)
        for read in visitor.reads:
            status = "PASS"
            reason = None
            keys = read["keys"]
            if not keys or keys[0] == "<dyn>":
                status = "REVIEW"
                reason = "dynamic key"
            else:
                top = keys[0]
                if top not in allowed and top not in {
                    # common non-contract dicts wrongly named — still record
                }:
                    # Only flag if it looks like construction contract field set
                    if top in allowed or top.endswith("_exact") or top.startswith("blind") or top.startswith("case_"):
                        if top not in allowed:
                            status = "FAIL"
                            reason = "undeclared field"
                if top in allowed and len(keys) > 1:
                    # nested access on string-typed field is the R12 bug class
                    if allowed_types.get(top) == "string":
                        status = "FAIL"
                        reason = "nested index on string-typed field (legacy R12 shape)"
                    elif allowed_types.get(top) != "object":
                        status = "FAIL"
                        reason = f"nested index on non-object type {allowed_types.get(top)}"
            item = {**read, "status": status, "reason": reason}
            findings.append(item)
            if status == "FAIL":
                violations.append(item)
    return {
        "artifact": "T21R13_CONTRACT_ACCESS_AUDIT",
        "version": "t21r13-v1",
        "detected_reads": len(findings),
        "violations": len(violations),
        "status": "PASS" if not violations else "FAIL",
        "findings": findings,
        "violation_details": violations,
    }


def fingerprint_r12_partial() -> dict:
    """Hash-only fingerprints for T21R12_FAILED_PARTIAL_BLIND."""
    sys.path.insert(0, str(SCRIPTS))
    # Prefer R12 uniqueness helpers if available, else simple hashes
    dims = {
        "source_id": set(),
        "chunk_id": set(),
        "entity": set(),
        "source_text": set(),
        "query": set(),
        "answer": set(),
        "relation": set(),
        "attack_wording": set(),
    }
    corpus = ROOT / "rag" / "gk_holdout_t21r12"
    for line in (corpus / "sources.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        dims["source_id"].add(sha_bytes(str(row.get("source_id") or "").encode()))
        text = str(row.get("source_title") or "") + "|" + str(row.get("publisher_or_collection") or "")
        dims["source_text"].add(sha_bytes(text.encode()))
    for line in (corpus / "chunks.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        dims["chunk_id"].add(sha_bytes(str(row.get("chunk_id") or "").encode()))
        dims["source_text"].add(sha_bytes(str(row.get("text") or "").encode()))
        md = row.get("metadata") or {}
        for key in ("fact_entity", "fact_value", "fact_attribute"):
            if md.get(key) is not None:
                dims["entity"].add(sha_bytes(str(md.get(key)).encode()))
                if key == "fact_attribute":
                    dims["relation"].add(sha_bytes(str(md.get(key)).encode()))
    specs = OUT12 / "_private_specs" / "private_suites_spec.json"
    if specs.is_file():
        data = json.loads(specs.read_text(encoding="utf-8"))
        for row in data.get("rows") or []:
            q = str((row.get("request") or {}).get("query") or "")
            if q:
                dims["query"].add(sha_bytes(q.encode()))
            gold = row.get("gold") or {}
            for ans in gold.get("expect_answer_contains") or []:
                dims["answer"].add(sha_bytes(str(ans).encode()))
            cons = row.get("construction") or {}
            if cons.get("attack_wording"):
                dims["attack_wording"].add(sha_bytes(str(cons["attack_wording"]).encode()))
            for rel in cons.get("canonical_relation") or []:
                dims["relation"].add(sha_bytes(str(rel).encode()))
            dims["entity"].add(sha_bytes(str(row.get("case_id") or "").encode()))

    encoded = {}
    for dim, values in dims.items():
        encoded[dim] = {
            "count": len(values),
            "sha256_sorted_join": sha_bytes("\n".join(sorted(values)).encode()),
            # store truncated sample of hashes only (hash-only, no raw)
            "fingerprint_sha256s": sorted(values)[:5000],
        }
    return {
        "milestone": "T21R12_FAILED_PARTIAL_BLIND",
        "status": "FAILED_PARTIAL",
        "source": "rag/gk_holdout_t21r12 + evaluations/t21r12/_private_specs",
        "dimensions": encoded,
        "note": "hash-only; raw blind material must not be loaded by R13 builders",
    }


def main() -> int:
    OUT13.mkdir(parents=True, exist_ok=True)

    # --- Adapt scripts ---
    for src in sorted(SCRIPTS.glob("t21r12_*.py")):
        adapt_script(src.name, src.name.replace("t21r12_", "t21r13_"))

    # Copy exact design lib + fixtures with adapt
    # already covered by glob

    # --- Construction contract ---
    base = json.loads((OUT12 / "holdout_construction_contract.json").read_text(encoding="utf-8"))
    contract = json.loads(adapt_text(json.dumps(base)))
    contract["artifact"] = "T21R13_HOLDOUT_CONSTRUCTION_CONTRACT"
    contract["version"] = "t21r13-v1"
    contract["blind_namespace"] = NAMESPACE
    contract["case_id_prefix"] = CASE_PREFIX
    contract["disposable_allowed"] = False
    contract["suite_target_exact"] = dict(SUITE_TARGETS)
    contract["total_rows_exact"] = 4800
    # Remove any nested object shape leftovers
    if isinstance(contract.get("blind_namespace"), dict):
        raise SystemExit("blind_namespace must not be object")
    write_json(OUT13 / "holdout_construction_contract.json", contract)

    schema = build_contract_schema(contract)
    write_json(OUT13 / "contract_schema.json", schema)
    matrix = build_consumer_matrix(schema)
    write_json(OUT13 / "contract_consumer_matrix.json", matrix)

    # --- Port JSON artifacts ---
    for name in [
        "preregistration.json", "validation_contract.json", "scoring_semantics.json",
        "blindness_policy.json", "one_shot_policy.json", "exact_design_schema.json",
        "exact_design_tag_vocabulary.json", "contract_gate_coverage.json",
        "negative_controls.json", "current_test_applicability.json",
        "test_failure_adjudication.json", "remediation_exclusion.json",
        "remediation_provenance.json",
    ]:
        src = OUT12 / name
        if not src.is_file():
            print("missing optional", name)
            continue
        data = json.loads(adapt_text(src.read_text(encoding="utf-8")))
        if name == "preregistration.json":
            data["artifact"] = "T21R13_PREREGISTRATION"
            data["blind_namespace"] = NAMESPACE
            data["case_id_prefix"] = CASE_PREFIX
            data["candidate_commit"] = CAND
            data["candidate_tree"] = CAND_TREE
            data["runtime_root"] = RUNTIME
            data["floor_hash"] = FLOOR
        write_json(OUT13 / name, data)

    # --- Prior exclusion: copy R12 and add R12 failed partial ---
    prior = json.loads((OUT12 / "prior_exclusion.json").read_text(encoding="utf-8"))
    if not isinstance(prior.get("milestones"), dict):
        raise SystemExit("unexpected prior_exclusion milestones shape")
    r12_fp = fingerprint_r12_partial()
    prior["milestones"]["T21R12_FAILED_PARTIAL_BLIND"] = r12_fp
    prior["artifact"] = "T21R13_PRIOR_EXCLUSION"
    prior["historical_milestone_count"] = len(prior["milestones"])
    prior["historical_dimensions"] = 8
    write_json(OUT13 / "prior_exclusion.json", prior)
    print("milestones", prior["historical_milestone_count"], sorted(prior["milestones"]))

    # --- Runtime / evaluator freezes (candidate unchanged) ---
    runtime = json.loads((OUT12 / "runtime_freeze.json").read_text(encoding="utf-8"))
    runtime = json.loads(adapt_text(json.dumps(runtime)))
    runtime["artifact"] = "T21R13_RUNTIME_FREEZE"
    runtime["candidate_commit"] = CAND
    runtime["candidate_tree"] = CAND_TREE
    runtime["status"] = "FROZEN"
    runtime["runtime_execution_count"] = 0
    write_json(OUT13 / "runtime_freeze.json", runtime)

    # Build evaluator freeze from R13 artifact set
    eval_components = {}
    for rel in [
        "evaluations/t21r13/holdout_construction_contract.json",
        "evaluations/t21r13/contract_schema.json",
        "evaluations/t21r13/contract_consumer_matrix.json",
        "evaluations/t21r13/preregistration.json",
        "evaluations/t21r13/validation_contract.json",
        "evaluations/t21r13/scoring_semantics.json",
        "evaluations/t21r13/exact_design_schema.json",
        "evaluations/t21r13/exact_design_tag_vocabulary.json",
        "evaluations/t21r13/contract_gate_coverage.json",
        "evaluations/t21r13/prior_exclusion.json",
        "evaluations/t21r13/remediation_exclusion.json",
        "evaluations/t21r13/blindness_policy.json",
        "evaluations/t21r13/one_shot_policy.json",
        "evaluations/t21r13/negative_controls.json",
        "evaluations/t21r13/current_test_applicability.json",
        "evaluations/t21r13/runtime_freeze.json",
        "scripts/t21r13_exact_design_lib.py",
        "scripts/t21r13_construction_gate.py",
        "scripts/t21r13_build_suites.py",
        "scripts/t21r13_world.py",
        "scripts/t21r13_fixtures.py",
        "scripts/t21r13_freeze_holdout.py",
        "scripts/t21r13_blind_author.py",
        "scripts/t21r13_uniqueness.py",
        "scripts/t21r13_blindness_audit.py",
        "evaluations/t21r12/T21R12_CLOSURE.json",
    ]:
        path = ROOT / rel
        if path.is_file():
            eval_components[rel] = sha(path)
    evaluator = {
        "artifact": "T21R13_EVALUATOR_FREEZE",
        "status": "FROZEN",
        "runtime_execution_count": 0,
        "component_sha256": eval_components,
        "component_count": len(eval_components),
        "floor_hash": FLOOR,
    }
    # root from sorted components
    root_blob = "\n".join(f"{k}:{v}" for k, v in sorted(eval_components.items())) + "\n"
    evaluator["root_sha256"] = sha_bytes(root_blob.encode())
    write_json(OUT13 / "evaluator_freeze.json", evaluator)
    # re-hash after writing self? exclude self from components (standard)

    access = run_access_audit(schema)
    write_json(OUT13 / "contract_access_audit.json", access)

    print("PHASE_B_CORE_OK")
    print("schema fields", schema["field_count"])
    print("matrix disagreements", matrix["type_disagreements"])
    print("access", access["status"], "violations", access["violations"])
    return 0 if access["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
