"""SciComp registry consistency: canonical ACTIVE, invariants unchanged."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sciencemath.executive.skills import (
    ACTIVE, LOCAL_FREE, SkillRegistry, registry_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
SCICOMP_IMPL = "5be66a3afb5f17f6b07ec995938ee783cb9adee8f85c268c52562a258f8e22c8"
CODE_IMPL = "cf9dc3c640d9410ee147e2ba8ca5ce42a2feeb36155d5ba61b462c94a988e627"
WEB_IMPL = "5ec760efb9d0420de3f1ca6c49e8481c151efeef027611683bfb1f1909140aa4"
DOCUMENT_IMPL = "d14232aeaa62d9ddead8fb84e5c95a4df93554da7159e2c610191f30cec4059d"
MEMORY_IMPL = "ac77f2d448345b4fb489911d6f9cd3c98dec06f4528ddf0e47e54852ccc4002d"
PLANNING_IMPL = "d045885cefcd097ceffc6588b5e6b00a1072cfaa08526ba9e4070bbdc041528c"
T4_IMPL = "3dadd23df1cf9bb10421a9abe316edcfca9e553f714980aca1764e5f53855da7"
T5R_IMPL = "350f023bcfccf370761963704b96fe6aa60819f6dff8067064aa24348b697742"
ROUTER_FILE = "06c59027341e4ef9124a4b5c1610a470e77fd67cfe8133446b380fcf9866af8e"
REGISTRY_SHA_BEFORE = (
    "06800bc0dee39ae1865e1b39aee3f612645a79e12eaa53256a6c64f13b6951e9"
)
PRECONDITIONS = [
    "compute_necessity_COMPUTE_REQUIRED",
    "parameter_fidelity_gate",
    "correction_firewall",
]


def _sha_group(rel_dir: str) -> str:
    h = hashlib.sha256()
    for p in sorted((ROOT / rel_dir).glob("*.py")):
        rel = (rel_dir + "/" + p.name).replace("\\", "/")
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return h.hexdigest()


def _sha_file(rel: str) -> str:
    data = (ROOT / rel).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_scicomp_availability_active_and_executable():
    reg = SkillRegistry()
    rec = reg.get("SCICOMP")
    assert rec is not None
    assert rec["availability"] == ACTIVE
    assert reg.availability("SCICOMP") == ACTIVE
    assert reg.executable("SCICOMP") is True
    assert "Experimental until a T14A" not in rec["description"]
    assert "T14R2" in rec["description"]
    assert registry_sha256() != REGISTRY_SHA_BEFORE


def test_scicomp_invariants_unchanged():
    rec = SkillRegistry().get("SCICOMP")
    assert rec["cost_class"] == LOCAL_FREE
    assert rec["required_permissions"] == []
    assert rec["preconditions"] == PRECONDITIONS
    assert rec["verification_method"] == "scicomp_envelope"
    assert rec["fallback_behavior"] == "MATH_T4"
    assert rec["offline"] is True
    assert rec["online"] is False


def test_promoted_capability_stack_active():
    reg = SkillRegistry()
    for skill in ("SCICOMP", "CODE", "WEB_RESEARCH", "DOCUMENT",
                  "MEMORY", "PLANNING"):
        assert reg.availability(skill) == ACTIVE, skill
        assert reg.executable(skill) is True, skill
    # Executive Router promotion is not inferred from skill availability.


def test_scicomp_implementation_hash_unchanged():
    freeze = _json("evaluations/t19/frozen_components.json")
    assert _sha_group("src/sciencemath/scicomp") == SCICOMP_IMPL
    assert freeze["composites"]["scicomp"] == SCICOMP_IMPL
    assert _sha_group("src/sciencemath/code") == CODE_IMPL
    assert _sha_group("src/sciencemath/web") == WEB_IMPL
    assert _sha_group("src/sciencemath/document") == DOCUMENT_IMPL
    assert _sha_group("src/sciencemath/memory") == MEMORY_IMPL
    assert _sha_group("src/sciencemath/planning") == PLANNING_IMPL
    assert _sha_group("src/sciencemath/tools") == T4_IMPL
    assert _sha_group("src/sciencemath/rag") == T5R_IMPL
    assert _sha_file("src/sciencemath/executive/executive_router.py") == ROUTER_FILE


def test_protection_historical_floors_preserved():
    d14 = _json("evaluations/t14r2/scicomp_decision.json")
    assert d14["decision"] == "PROMOTE_SCICOMP_LAB"
    assert d14["numeric_accuracy"] >= 0.848
    assert d14["gates"]["silent_mutations"]["measured"] == 0
    assert d14["gates"]["pipeline_exceptions"]["measured"] == 0
    t18 = _json("evaluations/t18/protection/regression_summary.json")
    assert t18["layers"]["t4"]["false_pass_rate"] == 0.0
    assert t18["layers"]["t5r"]["fabricated"] == 0
    assert t18["layers"]["t5r"]["unsupported"] == 0
    assert t18["layers"]["t5r"]["invalid"] == 0
    assert t18["layers"]["scicomp"]["numeric_accuracy"] >= 0.848
    t19 = _json("evaluations/t19/protection/regression_summary.json")
    assert t19["status"] == "ALL_PASS"
    assert t19["identity"]["scicomp"] is True
    assert t19["identity"]["executive_router"] is True
    trans = _json("evaluations/t19/planning_transition.json")
    assert trans["decision"] == "PROMOTE_PLANNING_SKILL"
    assert trans["after"] == "ACTIVE"
    assert "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL" in trans["executive_router"]
    cleanup = _json("evaluations/t19/post_merge_audit_cleanup.json")
    assert cleanup["scicomp_status_cleanup"]["canonical_value"] == "ACTIVE"
    floors = _json("evaluations/t19/promotion_floors.json")
    assert floors["quality"]["goal_capture_accuracy"] == 0.98
    mem = t19["layers"]["memory"]
    assert mem["owner_isolation"] == 1.0
    assert mem["fabricated_memory_claim"] == 0
