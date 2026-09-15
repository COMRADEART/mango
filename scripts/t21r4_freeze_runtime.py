"""T21R4.B1 — freeze the repaired KNOWLEDGE_RAG runtime BEFORE holdout data.

Records composite SHA-256 hashes over every frozen runtime group after the
T21R4 repair commit (query-relevant conflict scoping). KNOWLEDGE_RAG
remains EXPERIMENTAL at freeze time; the Executive Router remains
EXPERIMENTAL and unchanged.

Ordering: T21R3 merge -> T21R4 repair commit -> runtime freeze ->
evaluator freeze -> holdout construction -> HOLDOUT_FROZEN -> one-shot
evaluation.

Usage: python scripts/t21r4_freeze_runtime.py
       python scripts/t21r4_freeze_runtime.py --re-record-post-registration

Re-record mode: the T21R4 protection battery registration in the write
guard test is the preregistered registration delta every post-T15R battery
applied (T16..T21R3); it changed the historical_write_guard composite AFTER
the original B1 freeze. Re-recording is allowed ONLY because every OTHER
group is first proven byte-identical to the existing freeze record (zero
runtime drift) and the holdout data is proven untouched against its own
HOLDOUT_FROZEN manifest. The re-record is marked in the freeze document.
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

_GUARD_TEST = "tests/test_historical_artifact_write_guard.py"
_PROBE_SCRIPT = "scripts/t15r_mutation_" + "probe.py"

RUNTIME_GROUPS = {
    "knowledge_runtime": ["src/sciencemath/knowledge/"],
    "executive_skills": ["src/sciencemath/executive/skills.py"],
    "executive_router": ["src/sciencemath/executive/executive_router.py"],
    "science_rag_runtime": ["src/sciencemath/rag/"],
    "web_research_runtime": ["src/sciencemath/web/"],
    "document_runtime": ["src/sciencemath/document/"],
    "memory_runtime": ["src/sciencemath/memory/"],
    "planning_runtime": ["src/sciencemath/planning/"],
    "orchestration_runtime": ["src/sciencemath/orchestration/"],
    "scicomp_runtime": ["src/sciencemath/scicomp/"],
    "code_runtime": ["src/sciencemath/code/"],
    "correction_firewall": [
        "src/sciencemath/executive/correction.py",
        "src/sciencemath/executive/verify.py",
        "src/sciencemath/executive/repair.py",
        "src/sciencemath/executive/replan.py",
    ],
    "security_layer": [
        "src/sciencemath/knowledge/injection.py",
        "src/sciencemath/knowledge/provenance_spoof.py",
        "src/sciencemath/executive/state.py",
    ],
    "historical_write_guard": [_GUARD_TEST, _PROBE_SCRIPT],
}

OUT_DIR = ROOT / "evaluations" / "t21r4"
T21R3_MERGE_SHA = "9932fee0b3bfe01797b743e0e829aaca404f5ba7"
T21R4_REPAIR_COMMIT = "c1227ab789bdc50b9c2a8c0a2da0c991fda01f78"
T15R_BLOB = "fba2437f78633884bd31965d78a4250bd1ca893c"


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def sha_group(rel_specs: list[str]) -> str:
    paths: list[Path] = []
    for spec in rel_specs:
        if spec.endswith("/"):
            base = ROOT / spec
            paths.extend(sorted(p for p in base.rglob("*.py")
                                if "__pycache__" not in p.parts))
        else:
            paths.append(ROOT / spec)
    h = hashlib.sha256()
    for p in sorted(paths):
        rel = p.relative_to(ROOT).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(_lf(p.read_bytes()) if p.exists() else b"")
        h.update(b"\0")
    return h.hexdigest()


def sha_lf(path: Path) -> str:
    return hashlib.sha256(_lf(path.read_bytes())).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


def main() -> int:
    re_record = "--re-record-post-registration" in sys.argv
    head = _git("rev-parse", "HEAD")
    log = _git("log", "--pretty=%H", "-50").splitlines()
    if T21R3_MERGE_SHA not in log and head != T21R3_MERGE_SHA:
        raise SystemExit("T21R3 merge commit 9932fee not in ancestry")
    if T21R4_REPAIR_COMMIT not in log and head != T21R4_REPAIR_COMMIT:
        raise SystemExit(
            f"repair commit {T21R4_REPAIR_COMMIT} not in ancestry")

    if (ROOT / "evaluations" / "t22").exists():
        raise SystemExit("T22 must not have started")
    if (ROOT / "rag" / "gk_holdout_t21r4" / "world.jsonl").exists():
        if not re_record:
            raise SystemExit(
                "holdout world already exists: runtime must freeze BEFORE "
                "holdout construction")
        # re-record mode: every group EXCEPT the preregistered
        # historical_write_guard registration delta must be byte-identical
        # to the existing freeze, and the holdout data must be untouched
        # against its own HOLDOUT_FROZEN manifest.
        prev_path = OUT_DIR / "runtime_freeze.json"
        if not prev_path.exists():
            raise SystemExit("re-record: no existing runtime_freeze.json")
        prev = json.loads(prev_path.read_text(encoding="utf-8"))
        drift = [name for name, spec in RUNTIME_GROUPS.items()
                 if name != "historical_write_guard"
                 and sha_group(spec) != prev["runtime_composites"][name]]
        if drift:
            raise SystemExit(
                f"re-record refused: runtime groups drifted since B1: "
                f"{drift}")
        from t21r4_freeze import CORPUS_FILES, SUITES, sha256_lf  # noqa: E402
        manifest_path = OUT_DIR / "holdout_manifest.json"
        if not (OUT_DIR / "HOLDOUT_FROZEN").exists() or \
                not manifest_path.exists():
            raise SystemExit("re-record: holdout freeze missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for fname in CORPUS_FILES:
            p = ROOT / "rag" / "gk_holdout_t21r4" / fname
            if sha256_lf(p) != manifest["corpus"][fname]["sha256"]:
                raise SystemExit(
                    f"re-record refused: holdout corpus changed: {fname}")
        for name in SUITES:
            p = OUT_DIR / "suites" / name / "holdout.jsonl"
            if sha256_lf(p) != manifest["suites"][name]["holdout_sha256"]:
                raise SystemExit(
                    f"re-record refused: gold suite changed: {name}")

    composites = {name: sha_group(spec)
                  for name, spec in RUNTIME_GROUPS.items()}

    from sciencemath.executive.skills import SkillRegistry, registry_sha256
    reg = SkillRegistry()
    registry_record = {
        "availability": reg.availability("KNOWLEDGE_RAG"),
        "registry_sha256": registry_sha256(reg),
        "skills_py_sha256_lf": sha_lf(
            ROOT / "src/sciencemath/executive/skills.py"),
        "counts": reg.counts(),
    }
    if registry_record["availability"] != "EXPERIMENTAL":
        raise SystemExit(
            "KNOWLEDGE_RAG must be EXPERIMENTAL at T21R4 runtime freeze")

    t15r = ROOT / "evaluations/t15r/mutation_safety_probe.json"
    blob = _git("hash-object", str(t15r))
    if blob != T15R_BLOB:
        raise SystemExit(f"T15R blob drifted: {blob}")

    doc = {
        "milestone": "T21R4.B1 runtime freeze (repaired runtime, before holdout)",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "re_record_post_registration": (
            "historical_write_guard re-recorded after the preregistered "
            "protection-battery registration delta; every other group "
            "proven byte-identical to the original B1 freeze and the "
            "holdout data proven untouched against its HOLDOUT_FROZEN "
            "manifest" if re_record else None),
        "t21r3_merge_sha": T21R3_MERGE_SHA,
        "repair_commit": T21R4_REPAIR_COMMIT,
        "git_head": head,
        "git_tree_sha": _git("rev-parse", "HEAD^{tree}"),
        "t15r_canonical_blob": T15R_BLOB,
        "runtime_composites": composites,
        "knowledge_rag_registry": registry_record,
        "executive_router_status": "EXPERIMENTAL (unchanged)",
        "promotion_policy": ("KNOWLEDGE_RAG may move to ACTIVE only after "
                             "the one-shot T21R4 blind holdout passes every "
                             "preregistered floor."),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "runtime_freeze.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_DIR / 'runtime_freeze.json'}")
    print(f"knowledge_rag={registry_record['availability']} "
          f"composites={len(composites)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())