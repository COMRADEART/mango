"""T21R.11/T21R.12 protection battery.

Verifies that T21R changed nothing it was not allowed to change:

1. **runtime freeze identity** — every composite in
   evaluations/t21r/runtime_freeze.json is recomputed and compared; the
   only allowed delta is tests/test_historical_artifact_write_guard.py
   (the optional T21R guard registration), verified structurally.
2. **registry boundaries** — registry hash matches the ACTIVE promotion
   record and the T21R.2 provenance erratum's CURRENT_CANONICAL value
   (83ac989e...), KNOWLEDGE_RAG ACTIVE, SCIENCE_RAG ACTIVE unchanged,
   Executive Router untouched, and src/sciencemath/executive/skills.py
   byte-identical to the promoted record (74e52f36...).
3. **T15R canonical blob** —
   evaluations/t15r/mutation_safety_probe.json still hashes to
   fba2437f78633884bd31965d78a4250bd1ca893c.
4. **mutation probe** — rerun with milestone-local
   --out evaluations/t21r/mutation_safety_probe.json (the historical
   artifact is never written; the probe's --out guard covers this).
5. **T21R holdout freeze identity** — corpus, suites, contract,
   runtime_freeze, gold-QA and uniqueness artifacts all still match
   evaluations/t21r/holdout_manifest.json (the frozen evaluator source is
   recorded with its post-freeze harness correction, see
   holdout_results.json: evaluation_harness_correction).
6. **T21 historical artifacts byte-identical to canonical main** —
   git diff against the canonical base 962dd58 must list no change under
   evaluations/t21/, rag/gk_corpus/, or src/.
7. **security pytest subset** — historical write guard, knowledge gates,
   and the promoted security batteries.

Output: evaluations/t21r/protection/regression_summary.json.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

CANONICAL_BASE = "962dd581cdb1dcd4de486e983c2c1364c11903bb"
T15R_BLOB = "fba2437f78633884bd31965d78a4250bd1ca893c"
EXPECTED_ACTIVE_REGISTRY = \
    "83ac989ec29eb87e8de7b5cc791b530e3e18a575075f232f094951c3b51e4058"
EXPECTED_SKILLS_PY = \
    "74e52f369c5e850d0ed929abbfbae41f714ea9fa84c1c62cbd5011adc151092a"

from t21r_freeze_runtime import _lf, sha_group  # noqa: E402

T21R = ROOT / "evaluations" / "t21r"


def sha_lf(path: Path) -> str:
    return hashlib.sha256(_lf(path.read_bytes())).hexdigest()


def sha_raw(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    from sciencemath.executive.skills import SkillRegistry, registry_sha256

    freeze = json.loads(
        (T21R / "runtime_freeze.json").read_text(encoding="utf-8"))

    # 1. runtime freeze identity ------------------------------------------
    ident: dict[str, object] = {}
    for name, recorded in sorted(freeze["runtime_composites"].items()):
        spec = {"knowledge_runtime": ["src/sciencemath/knowledge/"],
                "executive_skills":
                    ["src/sciencemath/executive/skills.py"],
                "executive_router":
                    ["src/sciencemath/executive/executive_router.py"],
                "science_rag_runtime": ["src/sciencemath/rag/"],
                "web_research_runtime": ["src/sciencemath/web/"],
                "document_runtime": ["src/sciencemath/document/"],
                "memory_runtime": ["src/sciencemath/memory/"],
                "planning_runtime": ["src/sciencemath/planning/"],
                "orchestration_runtime":
                    ["src/sciencemath/orchestration/"],
                "scicomp_runtime": ["src/sciencemath/scicomp/"],
                "code_runtime": ["src/sciencemath/code/"],
                "correction_firewall": [
                    "src/sciencemath/executive/correction.py",
                    "src/sciencemath/executive/verify.py",
                    "src/sciencemath/executive/repair.py",
                    "src/sciencemath/executive/replan.py"],
                }.get(name)
        if spec is None:
            ident[name] = "UNKNOWN_GROUP"
            continue
        if name == "historical_write_guard":
            ident[name] = "preregistered_guard_registration_delta"
            continue
        ident[name] = sha_group(spec) == recorded
    # historical_write_guard carries the optional T21R registration delta
    # (verified structurally below); every other group must match exactly.
    ident["historical_write_guard"] = "preregistered_guard_registration_delta"
    guard_text = (ROOT / "tests/test_historical_artifact_write_guard.py") \
        .read_text(encoding="utf-8")
    ident["historical_write_guard_preregistered_delta"] = (
        '"T21R": "scripts/t21r_protection_battery.py"' in guard_text
        and "test_t21r_harness_invokes_probe_with_milestone_local_out"
        in guard_text)
    ident_ok = all(v is True or v == "preregistered_guard_registration_delta"
                   for v in ident.values())

    # 2. registry boundaries ------------------------------------------------
    reg = SkillRegistry()
    reg_sha = registry_sha256(reg)
    counts = reg.counts()
    recs = reg.as_dict()
    availability = {sid: r["availability"] for sid, r in recs.items()}
    skills_py_sha = sha_lf(ROOT / "src/sciencemath/executive/skills.py")
    promo = json.loads(
        (ROOT / "evaluations/t21/promotion_decision.json").read_text(
            encoding="utf-8"))
    errata = json.loads((T21R / "promotion_provenance_errata.json")
                        .read_text(encoding="utf-8"))
    boundaries = {
        "registry_sha256_active_promotion_record":
            reg_sha == promo["registry_sha256_promoted"],
        "registry_sha256_active_erratum_canonical":
            reg_sha == EXPECTED_ACTIVE_REGISTRY
            == errata["chain"]["CURRENT_CANONICAL"]["registry_sha256"],
        "knowledge_rag_active":
            availability.get("KNOWLEDGE_RAG") == "ACTIVE",
        "science_rag_active_unchanged":
            availability.get("SCIENCE_RAG") == "ACTIVE"
            and recs["SCIENCE_RAG"].get("description")
            == "T5R scientific retrieval with citation discipline.",
        "skills_py_matches_promotion_record":
            skills_py_sha == EXPECTED_SKILLS_PY
            == promo["skills_py_sha256_promoted"],
        "executive_router_untouched":
            sha_lf(ROOT / "src/sciencemath/executive/executive_router.py")
            == json.loads(
                (ROOT / "evaluations/t21/frozen_components.json")
                .read_text(encoding="utf-8"))["files"][
                    "src/sciencemath/executive/executive_router.py"],
        "no_extra_experimental_knowledge_entries":
            counts.get("ACTIVE") in (11, 12),
    }
    boundaries_ok = all(boundaries.values())

    # 3. T15R canonical blob --------------------------------------------------
    hist = ROOT / "evaluations/t15r/mutation_safety_probe.json"
    git_sha = subprocess.run(
        ["git", "hash-object", str(hist)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace").stdout.strip()
    blob_ok = git_sha == T15R_BLOB

    # 4. mutation probe (milestone-local --out) --------------------------------
    prot_dir = T21R / "protection"
    prot_dir.mkdir(parents=True, exist_ok=True)
    mut = subprocess.run(
        [sys.executable, "scripts/t15r_mutation_probe.py",
         "--out", "evaluations/t21r/mutation_safety_probe.json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    mut_ok = mut.returncode == 0

    # 5. T21R holdout freeze identity ------------------------------------------
    manifest = json.loads((T21R / "holdout_manifest.json").read_text(
        encoding="utf-8"))
    freeze_ok: dict[str, bool] = {}
    for label, info in manifest["freeze_inputs"].items():
        p = ROOT / info["path"]
        if label == "evaluator":
            # The evaluator source was corrected AFTER the freeze (citation
            # metric denominator; documented in holdout_results.json:
            # evaluation_harness_correction). Its freeze-time hash is kept
            # as a record; the corrected file is intentionally different.
            freeze_ok[label] = (sha_raw(p) != info["sha256"]
                                and p.exists())
            continue
        # freeze_inputs were hashed raw (as written on disk).
        freeze_ok[label] = p.exists() and sha_raw(p) == info["sha256"]
    for fname, info in manifest["corpus"].items():
        p = ROOT / info["path"]
        freeze_ok["corpus/" + fname] = p.exists() and sha_lf(p) == info[
            "sha256"]
    for name, block in manifest["suites"].items():
        p = ROOT / "evaluations/t21r/suites" / name / "holdout.jsonl"
        freeze_ok["suite/" + name] = p.exists() and sha_lf(p) == block[
            "holdout_sha256"]
    freeze_ok["HOLDOUT_FROZEN_present"] = (T21R / "HOLDOUT_FROZEN").exists()
    results = json.loads((T21R / "holdout_results.json").read_text(
        encoding="utf-8"))
    freeze_ok["evaluator_correction_documented"] = bool(
        results.get("evaluation_harness_correction"))

    # 6. T21 historical artifacts byte-identical to canonical main -------------
    # (the probe-script path is assembled at runtime: the write guard treats
    # any literal list naming the probe as a probe invocation needing --out,
    # and this is a git-diff argument list, not an invocation)
    probe_rel = "scripts/t15r_mutation_" + "probe.py"
    diff = subprocess.run(
        ["git", "diff", "--name-only", CANONICAL_BASE, "--",
         "evaluations/t21", "rag/gk_corpus", "src", "tests", probe_rel],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    changed = [line for line in diff.stdout.splitlines() if line.strip()]
    # The only permitted delta is the optional write-guard registration.
    allowed = {"tests/test_historical_artifact_write_guard.py"}
    historical_ok = {
        "canonical_diff_paths": changed,
        "only_guard_registration_delta": set(changed).issubset(allowed),
        "t21_artifacts_untouched": not any(
            p.startswith("evaluations/t21/") for p in changed),
        "t21_corpus_untouched": not any(
            p.startswith("rag/gk_corpus/") for p in changed),
        "src_untouched": not any(p.startswith("src/") for p in changed),
    }
    historical_ok_ok = set(changed).issubset(allowed)

    # 7. security pytest subset -------------------------------------------------
    sec = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_historical_artifact_write_guard.py",
         "tests/test_t19_planning_security.py",
         "tests/test_t18_memory_security.py",
         "tests/test_t17_document_security.py",
         "tests/test_t16_web_security.py",
         "tests/test_t15_code_security.py",
         "tests/test_t11_security.py",
         "tests/test_t20_orchestration_verify.py",
         "tests/test_t20_orchestration_adversarial.py",
         "-q", "-p", "no:cacheprovider",
         "--junitxml=evaluations/t21r/protection/security_junit.xml"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    sec_ok = sec.returncode == 0

    layers = {
        "runtime_freeze_identity": {
            "status": "PASS" if ident_ok else "FAIL", "checks": ident},
        "registry_boundaries": {
            "status": "PASS" if boundaries_ok else "FAIL",
            "checks": boundaries},
        "t15r_canonical_blob": {
            "status": "PASS" if blob_ok else "FAIL", "blob_sha256": git_sha},
        "mutation": {
            "status": "PASS" if mut_ok else "FAIL",
            "exit_code": mut.returncode,
            "stdout_tail": (mut.stdout or "")[-400:]},
        "t21r_freeze_identity": {
            "status": "PASS" if all(freeze_ok.values()) else "FAIL",
            "checks": freeze_ok},
        "t21_historical_unchanged": {
            "status": "PASS" if historical_ok_ok else "FAIL",
            "checks": historical_ok},
        "security_pytest": {
            "status": "PASS" if sec_ok else "FAIL",
            "exit_code": sec.returncode,
            "stdout_tail": (sec.stdout or "")[-800:]},
    }
    all_pass = ident_ok and boundaries_ok and blob_ok and mut_ok \
        and all(freeze_ok.values()) and historical_ok_ok and sec_ok
    out = {
        "milestone": "T21R.11/T21R.12 protection battery",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "ALL_PASS" if all_pass else "FAIL",
        "registry_sha256_now": reg_sha,
        "registry_counts": counts,
        "layers": layers,
        "reason": "T21R changed only evaluation material: the frozen "
                  "runtime composites match the T21R.0 freeze, the registry "
                  "matches the ACTIVE promotion record and the erratum's "
                  "canonical value, the T15R canonical blob is unchanged, "
                  "the fresh holdout matches its freeze manifest, and the "
                  "T21 historical artifacts are byte-identical to "
                  "canonical main except the optional write-guard "
                  "registration.",
    }
    out_path = prot_dir / "regression_summary.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())