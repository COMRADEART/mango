"""T21.58 — final audit: inventory of every preregistered T21 artifact.

Aggregates the milestone evidence into evaluations/t21/final_audit.json:
entry gate, freeze, registration, corpus, suites, floors, evaluation,
baselines, performance, smoke, protection, failure analysis, focused and
full pytest. Every entry is verified on disk, not assumed.

Output: evaluations/t21/final_audit.json.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

T21 = ROOT / "evaluations" / "t21"
ENTRY_HEAD = "17359be4092ba1dc5687f77a3c37cc1acbe03185"
T15R_BLOB = "fba2437f78633884bd31965d78a4250bd1ca893c"
CORPUS_MANIFEST = "944d45043afd0d080f0e26d1f8000a25f905b6284840588d966c511264b076a0"


def _read(rel: str):
    return json.loads((T21 / rel).read_text(encoding="utf-8"))


def _lf(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def main() -> int:
    import subprocess
    checks: dict[str, dict] = {}

    def check(name: str, ok: bool, detail: str) -> None:
        checks[name] = {"status": "PASS" if ok else "FAIL", "detail": detail}

    # T21.0 entry gate
    entry = _read("entry_freeze.json")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    check("t21_0_entry_gate", entry.get("status") == "PASS",
          f"entry head {entry.get('git_head', '?')[:12]}, current {head[:12]}")

    # T21.1 freeze + T21.2 registration
    reg = _read("registry_registration.json")
    frozen = _read("frozen_components.json")
    check("t21_1_frozen_components", frozen["git_head"] == ENTRY_HEAD,
          "frozen pre-T21 architecture at entry head")
    check("t21_2_registration_experimental",
          reg["decision"] == "REGISTER_KNOWLEDGE_RAG_EXPERIMENTAL"
          and reg["counts"] == {"ACTIVE": 11, "EXPERIMENTAL": 1},
          f"registry {reg['registry_sha256_after'][:12]}...")

    # corpus freeze (T21.5/T21.6)
    closed = _read("tuning_closed.json")
    corpus_manifest = json.loads(
        (ROOT / "rag/gk_corpus/corpus_manifest.json").read_text(
            encoding="utf-8"))
    if "manifest" in corpus_manifest:
        corpus_manifest = corpus_manifest["manifest"]
    check("t21_5_corpus_frozen",
          closed["corpus_manifest_checksum"] == CORPUS_MANIFEST
          == corpus_manifest.get("manifest_checksum"),
          f"corpus manifest {CORPUS_MANIFEST[:12]}...")

    # suites (T21.33-T21.39): sizes + manifests; preregistered totals
    MIN_TOTALS = {
        "mango-general-knowledge-rag-v1": 600,
        "mango-general-retrieval-v1": 400,
        "mango-general-citation-v1": 300,
        "mango-general-abstention-v1": 240,
        "mango-general-temporal-boundary-v1": 200,
        "mango-general-multihop-v1": 240,
        "mango-general-adversarial-v1": 240,
    }
    sizes = {}
    suite_root = T21 / "suites"
    for d in sorted(suite_root.iterdir()):
        if d.is_dir():
            m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            dev_n = sum(1 for l in (d / "dev.jsonl").read_text(
                encoding="utf-8").splitlines() if l.strip())
            final_n = sum(1 for l in (d / "final.jsonl").read_text(
                encoding="utf-8").splitlines() if l.strip())
            ok = (dev_n == m["dev_n"] and final_n == m["final_n"]
                  and m["total"] == m["dev_n"] + m["final_n"]
                  and m["total"] >= MIN_TOTALS[d.name])
            sizes[d.name] = {"dev": dev_n, "final": final_n,
                             "total": m["total"], "min": MIN_TOTALS[d.name],
                             "ok": ok}
    check("t21_33_built_suites",
          len(sizes) == 7 and all(v["ok"] for v in sizes.values()),
          json.dumps(sizes))

    # floors preregistered (T21.43-T21.49)
    floors = _read("floors.json")
    check("t21_43_floors_preregistered",
          len(floors["suites"]) == 7
          and len(floors["zero_tolerance_gates"]) == 20,
          "7 suite floor maps + 20 zero-tolerance gates")

    # evaluation (T21.50)
    results = _read("eval_results.json")
    check("t21_50_final_recorded",
          results["overall_pass"] is True
          and results["corpus_manifest_checksum"] == CORPUS_MANIFEST
          and set(results["splits"]) == {"dev", "final"},
          "all floors pass on dev and final, zero tolerance all zero")

    # baselines (T21.40/T21.41), performance (T21.53), smoke (T21.56)
    baselines = _read("baselines.json")
    check("t21_40_model_only_baseline",
          baselines["model_only_baseline"].get("ok") is True,
          "Qwen3-4B-Instruct-2507, retrieval disabled, recorded subset")
    check("t21_41_bm25_baseline",
          baselines["bm25_baseline"]["recall_at_5"] >= 0.94,
          f"BM25 recall@5 {baselines['bm25_baseline']['recall_at_5']}")
    perf = _read("performance.json")
    check("t21_53_performance_floor", perf["pass"] is True,
          f"retrieval p95 {perf['retrieval_ms']['p95']} ms <= 500 ms")
    smoke = _read("smoke.json")
    check("t21_56_local_smoke", smoke["status"] == "ALL_PASS",
          "8 query types end-to-end")

    # protection (T21.51/T21.52)
    prot = _read("protection/regression_summary.json")
    probe = _read("mutation_safety_probe.json")
    hist_sha = subprocess.run(
        ["git", "hash-object",
         str(ROOT / "evaluations/t15r/mutation_safety_probe.json")],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    check("t21_51_protection_battery",
          prot["status"] == "ALL_PASS" and hist_sha == T15R_BLOB
          and probe.get("passed") is True,
          f"T15R canonical blob {hist_sha[:12]}... unchanged")

    # science rag non-regression (T21.42)
    sci = _read("science_rag_regression.json")
    check("t21_42_science_rag_non_regression", sci["status"] == "PASS",
          "T5R + router + registry tests, t5r_rag hash pin")

    # failure analysis (T21.57)
    fa = _read("failure_analysis.json")
    check("t21_57_failure_analysis", fa["final_split_failures"] == 0,
          f"{len(fa['dev_tuning_defects_resolved_before_freeze'])} dev "
          "tuning defects resolved before freeze; no open defects")

    # focused tests (T21.61) + full pytest
    focused = T21 / "pytest_focused.json"
    if focused.exists():
        f = _read("pytest_focused.json")
        check("t21_61_focused_tests",
              f["failures"] == 0 and f["errors"] == 0,
              f"{f['tests']} tests")
    else:
        check("t21_61_focused_tests", False, "pytest_focused.json missing")
    full = T21 / "pytest_final.json"
    if full.exists():
        f = _read("pytest_final.json")
        check("t21_61_full_pytest",
              f["failures"] == 0 and f["errors"] == 0,
              f"{f['tests']} tests, {f['skipped']} skipped")
    else:
        check("t21_61_full_pytest", False, "pytest_final.json missing")

    # promotion decision (T21.59/T21.60)
    promo_path = T21 / "promotion_decision.json"
    if promo_path.exists():
        promo = _read("promotion_decision.json")
        check("t21_59_promotion_decision", True,
              f"{promo['decision']} (applied={promo.get('applied')})")
    else:
        check("t21_59_promotion_decision", False,
              "promotion_decision.json not yet written")

    report = ROOT / "evaluations/t21/T21_FINAL_REPORT.md"
    check("t21_62_final_report", report.exists(),
          "T21_FINAL_REPORT.md")

    all_pass = all(c["status"] == "PASS" for c in checks.values())
    doc = {
        "milestone": "T21.58 final audit",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "status": "ALL_PASS" if all_pass else "FAIL",
        "checks": checks,
    }
    (T21 / "final_audit.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(doc, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())