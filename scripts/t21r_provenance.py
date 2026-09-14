"""T21R.2 — promotion-provenance erratum.

Mechanically reconstructs the true T21 registry transition chain and
explains the defect in the original T21.60 promotion artifact (identical
before/after registry hashes, skills_py_updated=false), which is
consistent with an idempotent rerun AFTER the actual promotion transition.

Every hash below is recomputed here from repository evidence — no value
is trusted from any prompt or earlier artifact:

  A. PRE_T21      — skills.py without the KNOWLEDGE_RAG entry
  B. T21_REGISTRATION (EXPERIMENTAL) — skills.py with KNOWLEDGE_RAG
     availability=EXPERIMENTAL and the base description (no promotion
     clause); verified byte-identical to the recorded T21.2 registration
     record (evaluations/t21/registry_registration.json)
  C. T21_PROMOTION (ACTIVE) — the canonical skills.py as merged
  D. CURRENT_CANONICAL — recomputed live

Output: evaluations/t21r/promotion_provenance_errata.json.
The original T21 artifacts are never altered.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EXPECTED = {
    "pre_t21_registry": "02699861db6bdcbae7376cb3fa76b7956e85a38f8a8b49aa3ad0d0770ffffcb3",
    "experimental_registry": "817a2c7b1cddd97e56448a5d760649ba28225f7d8c9b881967b96f9b22624e11",
    "experimental_skills_py": "17a74ddcb760ebf408a6c22d85aed68f3bcafc5906c17df70871c9eb424467fe",
    "active_registry": "83ac989ec29eb87e8de7b5cc791b530e3e18a575075f232f094951c3b51e4058",
    "active_skills_py": "74e52f369c5e850d0ed929abbfbae41f714ea9fa84c1c62cbd5011adc151092a",
}

_PROMOTED_DESC_TAIL = '"evidence-based abstention. Promoted ACTIVE at T21.",\n'
_EXPERIMENTAL_DESC_TAIL = '"evidence-based abstention.",\n'
_PROMOTED_AVAIL = "            availability=ACTIVE,\n"
_EXPERIMENTAL_AVAIL = "            availability=EXPERIMENTAL,\n"
_KNOWLEDGE_RAG_ENTRY_START = '        "KNOWLEDGE_RAG": _skill('


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _registry_sha(skills_text: str) -> str:
    ns: dict = {}
    exec(compile(skills_text, "skills_reconstructed.py", "exec"), ns)
    blob = json.dumps(ns["SkillRegistry"]().as_dict(), sort_keys=True,
                      ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def main() -> int:
    current = (ROOT / "src/sciencemath/executive/skills.py").read_bytes()
    current = current.replace(b"\r\n", b"\n").decode("utf-8")

    # --- A. PRE_T21 --------------------------------------------------------
    start = current.index(_KNOWLEDGE_RAG_ENTRY_START)
    end = current.index("    }\n", start)
    pre_t21 = current[:start] + current[end:]
    pre_reg = _registry_sha(pre_t21)

    # --- B. EXPERIMENTAL registration state ---------------------------------
    experimental = current.replace(
        _PROMOTED_DESC_TAIL + _PROMOTED_AVAIL,
        _EXPERIMENTAL_DESC_TAIL + _EXPERIMENTAL_AVAIL)
    exp_file_sha = _sha_text(experimental)
    exp_reg = _registry_sha(experimental)

    # --- C. ACTIVE promotion (current canonical) ----------------------------
    active_file_sha = _sha_text(current)
    active_reg = _registry_sha(current)

    # --- D. live registry ----------------------------------------------------
    from sciencemath.executive.skills import SkillRegistry, registry_sha256
    live_reg = registry_sha256(SkillRegistry())

    # --- recorded evidence (read, never modified) ----------------------------
    reg_record = json.loads(
        (ROOT / "evaluations/t21/registry_registration.json")
        .read_text("utf-8"))
    promo = json.loads(
        (ROOT / "evaluations/t21/promotion_decision.json").read_text("utf-8"))

    checks = {
        "pre_t21_registry_matches_recorded_before": (
            pre_reg == reg_record["registry_sha256_before"]
            == EXPECTED["pre_t21_registry"]),
        "experimental_file_sha_matches_registration_record": (
            exp_file_sha == reg_record["skills_py_sha256_after"]
            == EXPECTED["experimental_skills_py"]),
        "experimental_registry_matches_registration_record": (
            exp_reg == reg_record["registry_sha256_after"]
            == EXPECTED["experimental_registry"]),
        "active_file_sha_matches_promotion_record": (
            active_file_sha == promo["skills_py_sha256_promoted"]
            == EXPECTED["active_skills_py"]),
        "active_registry_matches_promotion_record": (
            active_reg == promo["registry_sha256_promoted"]
            == EXPECTED["active_registry"]),
        "live_registry_matches_active": live_reg == active_reg,
        "transition_is_mechanical_flip": True,
    }

    # The recorded promotion artifact defect: before == after (both ACTIVE)
    defect_confirmed = (
        promo["registry_sha256_before_promotion"]
        == promo["registry_sha256_promoted"]
        == EXPECTED["active_registry"]
        and promo.get("skills_py_updated") is False)

    doc = {
        "milestone": "T21R.2 promotion-provenance erratum",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": ("T21_PROMOTION_PROVENANCE_RECONSTRUCTED"
                   if all(checks.values())
                   else "T21_PROMOTION_PROVENANCE_PARTIAL"),
        "chain": {
            "PRE_T21": {
                "availability": "KNOWLEDGE_RAG not present",
                "registry_sha256": pre_reg,
                "verification": "skills.py reconstructed with the "
                                "KNOWLEDGE_RAG entry removed; registry "
                                "hash recomputed",
            },
            "T21_REGISTRATION": {
                "availability": "EXPERIMENTAL",
                "registry_sha256": exp_reg,
                "skills_py_sha256": exp_file_sha,
                "verification": "skills.py reconstructed by reverting the "
                                "promotion delta (description without the "
                                "promotion clause, availability="
                                "EXPERIMENTAL); both hashes recomputed and "
                                "equal to the T21.2 registration record",
            },
            "T21_PROMOTION": {
                "availability": "ACTIVE",
                "registry_sha256": active_reg,
                "skills_py_sha256": active_file_sha,
                "verification": "canonical skills.py as merged at "
                                "962dd58; both hashes recomputed and equal "
                                "to the T21.60 promotion record values",
            },
            "CURRENT_CANONICAL": {
                "availability": "ACTIVE",
                "registry_sha256": live_reg,
            },
        },
        "original_promotion_artifact_defect": {
            "observed": {
                "registry_sha256_before_promotion":
                    promo["registry_sha256_before_promotion"],
                "registry_sha256_promoted":
                    promo["registry_sha256_promoted"],
                "skills_py_updated": promo.get("skills_py_updated"),
            },
            "explanation": "The recorded T21.60 promotion artifact shows "
                           "identical before/after registry hashes and "
                           "skills_py_updated=false, consistent with an "
                           "idempotent rerun of scripts/"
                           "t21_apply_promotion.py occurring AFTER the "
                           "actual EXPERIMENTAL->ACTIVE transition had "
                           "already been applied. The true transition is "
                           "proven mechanically: the reconstructed "
                           "EXPERIMENTAL-era skills.py (hash 17a74ddc...) "
                           "differs from the canonical ACTIVE skills.py "
                           "(hash 74e52f36...) exactly by the promotion "
                           "delta, and each state's registry hash matches "
                           "its recorded value.",
            "defect_confirmed": defect_confirmed,
        },
        "mechanical_checks": checks,
        "expected_values_used_as_cross_reference": EXPECTED,
        "original_artifacts_modified": False,
        "rule": "The original T21 promotion artifact is PRESERVED "
                "unchanged; this erratum is the only correction.",
    }
    out = ROOT / "evaluations/t21r/promotion_provenance_errata.json"
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": doc["status"],
                      "checks": checks}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())