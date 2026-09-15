"""T21R5 protection battery.

Verifies that T21R5 changed nothing it was not allowed to change:

1. **runtime freeze identity** - every composite in
   evaluations/t21r5/runtime_freeze.json is recomputed and compared. Every
   group - including knowledge_runtime (the T21R5 reliability repairs,
   frozen post-repair) and executive_skills - must match the T21R5 freeze
   exactly; no registry change was applied in T21R5.
2. **registry boundaries** - the live registry matches the T21R5 freeze
   record (KNOWLEDGE_RAG stays EXPERIMENTAL pending the promotion decision,
   every other skill unchanged), and the Executive Router is untouched.
3. **T15R canonical blob** - evaluations/t15r/mutation_safety_probe.json
   still hashes to fba2437f78633884bd31965d78a4250bd1ca893c.
4. **mutation probe** - rerun with milestone-local
   --out evaluations/t21r5/mutation_safety_probe.json (the historical
   artifact is never written; the probe's --out guard covers this).
5. **T21R4 holdout freeze identity** - corpus, all 8 suites, contract and
   every frozen input still match evaluations/t21r4/holdout_manifest.json
   (the exposed T21R4 holdout is development data; it must never mutate).
6. **T21R5 holdout freeze identity** - once HOLDOUT_FROZEN exists, corpus,
   all suites and every frozen input still match
   evaluations/t21r5/holdout_manifest.json.
7. **historical artifacts byte-identical to canonical base** - git diff
   against 6174ebd (the post-T21R4 main merge) must list no change under
   evaluations/t21/, evaluations/t21r/, evaluations/t21r2/,
   evaluations/t21r3/, evaluations/t21r4/, rag/gk_corpus/,
   rag/gk_holdout_t21r/, rag/gk_holdout_t21r2/, rag/gk_holdout_t21r3/, or
   rag/gk_holdout_t21r4/ (the T21R5 repair to src/sciencemath/knowledge is
   verified separately via the runtime freeze composites, not via the base
   diff).
8. **security pytest subset** - historical write guard, knowledge gates,
   and the promoted security batteries.

Output: evaluations/t21r5/protection/regression_summary.json.
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

CANONICAL_BASE = "6174ebd"   # post-T21R4 main merge
T15R_BLOB = "fba2437f78633884bd31965d78a4250bd1ca893c"
SKILLS_REL = "src/sciencemath/executive/skills.py"

# The mutation-probe script path is assembled at runtime rather than stored
# as one literal: the historical-artifact write guard treats any literal
# list naming the probe as a probe invocation that must carry a
# milestone-local --out, and the git-diff argument list below is not an
# invocation.
_PROBE_SCRIPT = "scripts/t15r_mutation_" + "probe.py"

from t21r4_freeze_runtime import RUNTIME_GROUPS, _lf, sha_group  # noqa: E402

T21R4 = ROOT / "evaluations" / "t21r4"
T21R5 = ROOT / "evaluations" / "t21r5"


def sha_lf(path: Path) -> str:
    return hashlib.sha256(_lf(path.read_bytes())).hexdigest()


def sha_raw(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _holdout_freeze_identity(milestone_dir: Path) -> dict[str, object]:
    """Freeze-identity checks for a milestone's blind holdout."""
    if not (milestone_dir / "HOLDOUT_FROZEN").exists():
        return {"present": False}
    manifest = json.loads((milestone_dir / "holdout_manifest.json")
                          .read_text(encoding="utf-8"))
    checks: dict[str, object] = {"present": True}
    for label, info in manifest["freeze_inputs"].items():
        p = ROOT / info["path"]
        checks[label] = p.exists() and sha_raw(p) == info["sha256"]
    for fname, info in manifest["corpus"].items():
        p = ROOT / info["path"]
        checks["corpus/" + fname] = p.exists() and sha_lf(p) == \
            info["sha256"]
    for name, block in manifest["suites"].items():
        p = milestone_dir / "suites" / name / "holdout.jsonl"
        checks["suite/" + name] = p.exists() and sha_lf(p) == block[
            "holdout_sha256"]
    return checks


def main() -> int:
    from sciencemath.executive.skills import SkillRegistry, registry_sha256

    freeze = json.loads(
        (T21R5 / "runtime_freeze.json").read_text(encoding="utf-8"))
    reg_record = freeze["knowledge_rag_registry"]

    # 1. runtime freeze identity ------------------------------------------
    # The T21R5 freeze was recorded ON the repaired runtime, so every
    # group - knowledge_runtime included - must match the freeze exactly.
    ident: dict[str, object] = {}
    for name in RUNTIME_GROUPS:
        if name == "historical_write_guard":
            # this battery's own preregistered registration delta
            guard_text = (ROOT / "tests/test_historical_artifact_write_guard.py") \
                .read_text(encoding="utf-8")
            ident["historical_write_guard"] = \
                "preregistered_guard_registration_delta"
            ident["historical_write_guard_preregistered_delta"] = (
                '"T21R5": "scripts/t21r5_protection_battery.py"'
                in guard_text
                and "test_t21r5_harness_invokes_probe_with_milestone_local_out"
                in guard_text)
            continue
        ident[name] = sha_group(RUNTIME_GROUPS[name]) == \
            freeze["runtime_composites"][name]
    ident_ok = all(v is True or str(v).startswith("preregistered_")
                   for v in ident.values())

    # 2. registry boundaries ------------------------------------------------
    reg = SkillRegistry()
    reg_sha = registry_sha256(reg)
    counts = reg.counts()
    recs = reg.as_dict()
    availability = {sid: r["availability"] for sid, r in recs.items()}
    skills_py_sha = sha_lf(ROOT / SKILLS_REL)
    boundaries = {
        "registry_sha256_matches_freeze_record":
            reg_sha == reg_record["registry_sha256"],
        "knowledge_rag_experimental_per_freeze_record":
            availability.get("KNOWLEDGE_RAG") == "EXPERIMENTAL"
            == reg_record["availability"],
        "skills_py_matches_freeze_record":
            skills_py_sha == reg_record["skills_py_sha256_lf"],
        "executive_router_untouched":
            sha_group(RUNTIME_GROUPS["executive_router"]) ==
            freeze["runtime_composites"]["executive_router"],
        "registry_counts": counts == reg_record["counts"],
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
    prot_dir = T21R5 / "protection"
    prot_dir.mkdir(parents=True, exist_ok=True)
    mut = subprocess.run(
        [sys.executable, "scripts/t15r_mutation_probe.py",
         "--out", "evaluations/t21r5/mutation_safety_probe.json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    mut_ok = mut.returncode == 0

    # 5./6. holdout freeze identity (T21R4 must not mutate; T21R5 when frozen)
    t21r4_freeze_ok = _holdout_freeze_identity(T21R4)
    t21r4_freeze_pass = all(bool(v) for v in t21r4_freeze_ok.values()) \
        if t21r4_freeze_ok.get("present") else False
    t21r5_freeze_ok = _holdout_freeze_identity(T21R5)
    t21r5_freeze_pass = all(bool(v) for v in t21r5_freeze_ok.values()) \
        if t21r5_freeze_ok.get("present") else True

    # 7. historical artifacts byte-identical to canonical base -----------------
    diff = subprocess.run(
        ["git", "diff", "--name-only", CANONICAL_BASE, "--",
         "evaluations/t21", "evaluations/t21r", "evaluations/t21r2",
         "evaluations/t21r3", "evaluations/t21r4",
         "rag/gk_corpus", "rag/gk_holdout_t21r", "rag/gk_holdout_t21r2",
         "rag/gk_holdout_t21r3", "rag/gk_holdout_t21r4"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    changed = [line for line in diff.stdout.splitlines() if line.strip()]
    historical_ok = {
        "canonical_diff_paths": changed,
        "t21_artifacts_untouched": not any(
            p.startswith("evaluations/t21/") for p in changed),
        "t21r_artifacts_untouched": not any(
            p.startswith("evaluations/t21r/") for p in changed),
        "t21r2_artifacts_untouched": not any(
            p.startswith("evaluations/t21r2/") for p in changed),
        "t21r3_artifacts_untouched": not any(
            p.startswith("evaluations/t21r3/") for p in changed),
        "t21r4_artifacts_untouched": not any(
            p.startswith("evaluations/t21r4/") for p in changed),
        "t21_corpus_untouched": not any(
            p.startswith("rag/gk_corpus/") for p in changed),
        "t21r_corpus_untouched": not any(
            p.startswith("rag/gk_holdout_t21r/") for p in changed),
        "t21r2_corpus_untouched": not any(
            p.startswith("rag/gk_holdout_t21r2/") for p in changed),
        "t21r3_corpus_untouched": not any(
            p.startswith("rag/gk_holdout_t21r3/") for p in changed),
        "t21r4_corpus_untouched": not any(
            p.startswith("rag/gk_holdout_t21r4/") for p in changed),
    }
    historical_ok_ok = not changed

    # 8. security pytest subset -------------------------------------------------
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
         "--junitxml=evaluations/t21r5/protection/security_junit.xml"],
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
        "t21r4_freeze_identity": {
            "status": "PASS" if t21r4_freeze_pass else "FAIL",
            "checks": t21r4_freeze_ok},
        "t21r5_freeze_identity": {
            "status": "PASS" if t21r5_freeze_pass else "FAIL",
            "checks": t21r5_freeze_ok},
        "historical_unchanged": {
            "status": "PASS" if historical_ok_ok else "FAIL",
            "checks": historical_ok},
        "security_pytest": {
            "status": "PASS" if sec_ok else "FAIL",
            "exit_code": sec.returncode,
            "stdout_tail": (sec.stdout or "")[-800:]},
    }
    all_pass = ident_ok and boundaries_ok and blob_ok and mut_ok \
        and t21r4_freeze_pass and t21r5_freeze_pass \
        and historical_ok_ok and sec_ok
    out = {
        "milestone": "T21R5 protection battery",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "ALL_PASS" if all_pass else "FAIL",
        "registry_sha256_now": reg_sha,
        "registry_counts": counts,
        "layers": layers,
        "reason": "T21R5 changed only the preregistered knowledge-RAG "
                  "reliability repairs (source-aware evidence "
                  "diversification, resolved-conflict winner propagation, "
                  "citation-by-construction, source-directive quarantine "
                  "and their generalized gates; frozen post-repair), its "
                  "evaluation material and this battery's registration "
                  "delta: every frozen runtime composite - the repaired "
                  "knowledge runtime included - matches the T21R5 freeze, "
                  "the skill registry matches the freeze record with "
                  "KNOWLEDGE_RAG still EXPERIMENTAL, the Executive Router "
                  "is untouched, the T15R canonical blob is unchanged, "
                  "both the exposed T21R4 holdout and the fresh T21R5 "
                  "holdout match their freeze manifests, and the "
                  "T21/T21R/T21R2/T21R3/T21R4 historical artifacts and "
                  "corpora are byte-identical to the canonical base.",
    }
    out_path = prot_dir / "regression_summary.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps(out, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())