
from __future__ import annotations
import hashlib, json, os, shutil, subprocess, sys, gzip, base64
from copy import deepcopy
from datetime import datetime
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "scripts"))
import t21r14_exact_design_lib as ed
import t21r11_uniqueness as uniq

OUT = ROOT / "evaluations" / "t21r14"
R11 = ROOT / "evaluations" / "t21r11"
EXT = Path(r"C:\Users\allam\Documents\new\t21r11_junit_symlink")

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def wj(p, o):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    t = json.dumps(o, indent=2, sort_keys=True) + "\n"
    p.write_text(t, encoding="utf-8", newline="\n")
    return hashlib.sha256(t.encode()).hexdigest()
def lj(p): return json.loads(Path(p).read_text(encoding="utf-8"))

contract = lj(OUT / "holdout_construction_contract.json")

if __name__ == "__main__":
    # Prior exclusion + R11 fingerprints
    def pack(hashes):
        payload = "\n".join(sorted(hashes)) + ("\n" if hashes else "")
        return base64.b64encode(gzip.compress(payload.encode("utf-8"))).decode("ascii")

    suites = R11 / "suites"
    corpus = ROOT / "rag" / "gk_holdout_t21r11"
    rows, _ = uniq._rows(suites)
    sources = uniq._load_jsonl(corpus / "sources.jsonl")
    chunks = uniq._load_jsonl(corpus / "chunks.jsonl")
    world = uniq._load_jsonl(corpus / "world.jsonl") if (corpus / "world.jsonl").is_file() else []
    values = uniq.material_values(sources, chunks, rows, world)
    dimensions = {dim: pack(values[dim]) for dim in uniq.DIMENSIONS}
    source_artifacts = []
    for path in sorted(suites.glob("*/holdout.jsonl")):
        rel = path.relative_to(ROOT).as_posix()
        source_artifacts.append({"identity": f"git:283442e468fd04de391ee8fbf4a05a281d6f74c5/{rel}", "sha256": sha(path)})
    for name in ("sources.jsonl", "chunks.jsonl", "world.jsonl", "corpus_manifest.json"):
        p = corpus / name
        if p.is_file():
            source_artifacts.append({"identity": f"git:283442e468fd04de391ee8fbf4a05a281d6f74c5/rag/gk_holdout_t21r11/{name}", "sha256": sha(p)})

    prior = deepcopy(lj(R11 / "prior_exclusion.json"))
    prior["artifact"] = "T21R14_PRIOR_EXCLUSION"
    prior["version"] = "t21r14-v1"
    prior["milestones"]["T21R11_INVALID_SEALED"] = {
      "dimensions": dimensions,
      "source_artifacts": source_artifacts,
      "sealed_commit": "283442e468fd04de391ee8fbf4a05a281d6f74c5",
      "status": "INVALID_UNEVALUATED_HOLDOUT",
      "raw_material_committed": True,
      "official_evaluation_executed": False,
      "holdout_reuse": "forbidden",
      "note": "Fingerprints only; builders must not load R11 raw blind content",
    }
    prior["milestone_order"] = [
      "T21","T21R","T21R2","T21R3","T21R4","T21R5","T21R6","T21R7",
      "T21R8_DIAGNOSTIC","T21R9_SEALED","T21R10_SEALED","T21R11_INVALID_SEALED",
    ]
    prior["historical_milestones"] = 12
    prior["historical_dimensions"] = 8
    assert set(prior["milestone_order"]) == set(prior["milestones"])
    wj(OUT / "prior_exclusion.json", prior)

    rem = deepcopy(lj(R11 / "remediation_exclusion.json"))
    rem["artifact"] = "T21R14_REMEDIATION_EXCLUSION"; rem["version"] = "t21r14-v1"; rem["class"] = "OPEN_REMEDIATION_MATERIAL"
    wj(OUT / "remediation_exclusion.json", rem)
    print("prior milestones", len(prior["milestone_order"]))

    # Fixtures
    def make_count_rows(tag, n):
        return [{"case_id": f"syn-{tag}-{i:04d}", "category": tag, "construction_tags": [tag],
                 "request": {"query": f"synthetic {tag} {i}"}, "gold": {"expect_status": "ANSWER"}, "mode": "answer"} for i in range(n)]

    def make_valid_fixture(contract):
        rows = []
        for obj, leaves in ed.LEAF_TYPES.items():
            for leaf, typ in leaves.items():
                if typ != "COUNT" or leaf == "novel_pair_families":
                    continue
                rows.extend(make_count_rows(leaf, int(contract[obj][leaf])))
        per = int(contract["crossdomain_exact_design"]["rows_per_pair"])
        for tag in ed.CROSSDOMAIN_PAIR_TAGS:
            rows.extend(make_count_rows(tag, per))
        return rows

    def make_negative_fixture(contract, obj, leaf):
        rows = make_valid_fixture(contract)
        leaf_type = ed.LEAF_TYPES[obj][leaf]
        if leaf == "novel_pair_families":
            drop = ed.CROSSDOMAIN_PAIR_TAGS[0]
            return [r for r in rows if drop not in (r.get("construction_tags") or [])]
        if leaf == "rows_per_pair":
            tag = ed.CROSSDOMAIN_PAIR_TAGS[0]
            out=[]; removed=False
            for r in rows:
                if not removed and tag in (r.get("construction_tags") or []):
                    removed=True; continue
                out.append(r)
            return out
        if leaf_type in {"FORBIDDEN_OVERLAP", "BOOLEAN"}:
            return rows
        out=[]; removed=False
        for r in rows:
            if not removed and leaf in (r.get("construction_tags") or []):
                removed=True; continue
            out.append(r)
        return out

    # Coverage
    schema = lj(OUT / "exact_design_schema.json")
    cov_rows = []
    for leaf_meta in schema["leaves"]:
        path = leaf_meta["contract_path"]; obj, leaf = path.split(".", 1)
        leaf_type = leaf_meta["requirement_type"]
        pos_rows = make_valid_fixture(contract)
        pos_ctx = {"prior_exact_query_overlap": 0, "prior_pair_template_overlap": 0}
        if leaf == "novel_pair_families":
            pos = ed.check_novel_pair_families(int(contract[obj][leaf]), pos_rows, leaf)
            pos.update({"status": "PASS" if pos["passed"] else "FAIL"})
        else:
            pos = ed.evaluate_leaf(obj, leaf, contract[obj][leaf], leaf_type, pos_rows, pos_ctx)
        neg_ctx = pos_ctx
        if leaf_type in {"FORBIDDEN_OVERLAP", "BOOLEAN"} and leaf != "novel_pair_families":
            neg_ctx = {"prior_exact_query_overlap": 1, "prior_pair_template_overlap": 1}
            neg_rows = make_valid_fixture(contract)
        else:
            neg_rows = make_negative_fixture(contract, obj, leaf)
        if leaf == "novel_pair_families":
            neg = ed.check_novel_pair_families(int(contract[obj][leaf]), neg_rows, leaf)
            neg.update({"status": "PASS" if neg["passed"] else "FAIL"})
        else:
            neg = ed.evaluate_leaf(obj, leaf, contract[obj][leaf], leaf_type, neg_rows, neg_ctx)
        pos_ok = pos.get("passed") is True
        neg_rejects = not (neg.get("passed") is True)
        gf = leaf_meta.get("gate_function") or ("check_novel_pair_families" if leaf == "novel_pair_families" else None)
        covered = pos_ok and neg_rejects and bool(gf)
        cov_rows.append({
          "contract_path": path, "requirement_type": leaf_type, "gate_function": gf,
          "source_field": leaf_meta.get("source_field"), "comparison": pos.get("comparison"),
          "synthetic_positive_control": "PASS" if pos_ok else "FAIL",
          "synthetic_negative_control": "PASS" if neg_rejects else "FAIL",
          "status": "COVERED" if covered else "UNWIRED",
        })
    covered_n = sum(1 for r in cov_rows if r["status"] == "COVERED")
    coverage = {
      "artifact": "T21R14_CONTRACT_GATE_COVERAGE", "version": "t21r14-v1",
      "leaf_requirements_registered": len(cov_rows), "covered": covered_n,
      "unwired_requirements": len(cov_rows) - covered_n,
      "coverage_percent": round(100.0 * covered_n / len(cov_rows), 4) if cov_rows else 0.0,
      "rows": cov_rows,
    }
    wj(OUT / "contract_gate_coverage.json", coverage)
    print("coverage", coverage["coverage_percent"], "unwired", coverage["unwired_requirements"])

    # Negative controls
    controls = []
    for name, path in [
      ("missing_holdout_manifest", OUT / "holdout_manifest.json"),
      ("missing_HOLDOUT_FROZEN", OUT / "HOLDOUT_FROZEN"),
      ("missing_real_corpus", ROOT / "rag" / "gk_holdout_t21r14"),
      ("missing_real_suites", OUT / "suites"),
      ("absent_evaluation_ledger", OUT / "evaluation_run_ledger.json"),
      ("absent_raw_results", OUT / "raw_results.jsonl"),
      ("absent_holdout_results", OUT / "holdout_results.json"),
    ]:
        ok = not path.exists()
        controls.append({"name": name, "kind": "infrastructure", "status": "PASS" if ok else "FAIL", "detail": f"exists={path.exists()}"})

    for obj, leaf, required, leaf_type in ed.enumerate_leaves(contract):
        pos_rows = make_valid_fixture(contract)
        pos_ctx = {"prior_exact_query_overlap": 0, "prior_pair_template_overlap": 0}
        if leaf == "novel_pair_families":
            pos = ed.check_novel_pair_families(int(required), pos_rows, leaf)
        else:
            pos = ed.evaluate_leaf(obj, leaf, required, leaf_type, pos_rows, pos_ctx)
        if leaf_type in {"FORBIDDEN_OVERLAP", "BOOLEAN"} and leaf != "novel_pair_families":
            neg_ctx = {"prior_exact_query_overlap": 1, "prior_pair_template_overlap": 1}
            neg_rows = make_valid_fixture(contract)
        else:
            neg_ctx = pos_ctx
            neg_rows = make_negative_fixture(contract, obj, leaf)
        if leaf == "novel_pair_families":
            neg = ed.check_novel_pair_families(int(required), neg_rows, leaf)
        else:
            neg = ed.evaluate_leaf(obj, leaf, required, leaf_type, neg_rows, neg_ctx)
        pos_ok = bool(pos.get("passed")); neg_rejects = not bool(neg.get("passed"))
        controls.append({
          "name": f"exact_design.{obj}.{leaf}", "kind": "exact_design_leaf",
          "requirement_type": leaf_type,
          "positive_control": "PASS" if pos_ok else "FAIL",
          "negative_control": "PASS" if neg_rejects else "FAIL",
          "status": "PASS" if (pos_ok and neg_rejects) else "FAIL",
        })
    passed = sum(1 for c in controls if c["status"] == "PASS")
    negatives = {"artifact": "T21R14_NEGATIVE_CONTROLS", "version": "t21r14-v1", "total": len(controls),
                 "passed": passed, "failed": len(controls)-passed, "controls": controls,
                 "status": "PASS" if passed == len(controls) else "FAIL"}
    wj(OUT / "negative_controls.json", negatives)
    print("negatives", negatives["status"], negatives["passed"], "/", negatives["total"])

    # Synthetic
    pos_rows = make_valid_fixture(contract)
    pos = ed.evaluate_exact_design(contract, pos_rows, {"prior_exact_query_overlap": 0, "prior_pair_template_overlap": 0})
    rejections = []
    for obj in ed.EXACT_DESIGN_OBJECTS:
        leaf = sorted(contract[obj])[0]
        if ed.LEAF_TYPES[obj][leaf] in {"FORBIDDEN_OVERLAP", "BOOLEAN"}:
            ctx = {"prior_exact_query_overlap": 1, "prior_pair_template_overlap": 1}
            neg_rows = make_valid_fixture(contract)
        else:
            ctx = {"prior_exact_query_overlap": 0, "prior_pair_template_overlap": 0}
            neg_rows = make_negative_fixture(contract, obj, leaf)
        neg = ed.evaluate_exact_design(contract, neg_rows, ctx)
        rejections.append({"violated_leaf": f"{obj}.{leaf}", "status": neg["status"], "rejected": neg["status"] == "FAIL"})
    all_rejected = all(r["rejected"] for r in rejections)
    synthetic = {
      "artifact": "T21R14_SYNTHETIC_PROTOCOL_REPORT", "version": "t21r14-v1",
      "valid_fixture": {"status": pos["status"], "leaf_requirements_total": pos["leaf_requirements_total"],
                        "passed": pos["passed"], "failed": pos["failed"], "unhandled": pos["unhandled"]},
      "deliberate_violations": rejections,
      "all_valid_cases_PASS": pos["status"] == "PASS",
      "all_deliberate_violations_rejected": all_rejected,
      "real_R14_rows": 0, "candidate_R14_rows_executed": 0, "official_evaluator_invocations": 0,
      "status": "PASS" if pos["status"] == "PASS" and all_rejected else "FAIL",
    }
    wj(OUT / "synthetic_protocol_report.json", synthetic)
    print("synthetic", synthetic["status"])

    # Save fixture helpers for tests
    helpers = {
      "make_valid_fixture_row_count": len(make_valid_fixture(contract)),
    }
    wj(OUT / "_synthetic_fixture_meta.json", helpers)


    # fixture functions above are available by re-importing this file section via build — tests use lib directly
