"""T17.41 — routing tests with DOCUMENT availability integration."""
from copy import deepcopy

from sciencemath.executive.executive_router import route_task
from sciencemath.executive.skills import (
    ACTIVE, EXPERIMENTAL, PREPARED_ONLY, SkillRegistry, default_registry,
)


def _reg(*, document="PREPARED_ONLY"):
    d = default_registry()
    d["DOCUMENT"]["availability"] = document
    d["DOCUMENT"]["executable"] = document in (ACTIVE, EXPERIMENTAL)
    return SkillRegistry(d)


def test_default_registry_document_availability_is_recorded():
    reg = SkillRegistry()
    av = reg.availability("DOCUMENT")
    assert av in (PREPARED_ONLY, ACTIVE, EXPERIMENTAL)
    if av == PREPARED_ONLY:
        assert not reg.executable("DOCUMENT")
    else:
        assert reg.executable("DOCUMENT")


def test_document_fail_closed_when_prepared_only():
    rec = route_task("Parse this pdf spreadsheet csv file",
                     registry=_reg())
    assert rec["primary_skill"] in ("GENERAL", "NO_TOOL")
    assert rec.get("unavailable_skill") == "DOCUMENT"


def test_document_routes_when_executable():
    rec = route_task("Parse this pdf spreadsheet csv file",
                     registry=_reg(document=ACTIVE))
    assert rec["primary_skill"] == "DOCUMENT"
    assert rec["execution_status"] == "ROUTED_ONLY"


def test_math_does_not_route_to_document():
    rec = route_task("What is 12 * 11?", registry=_reg(document=ACTIVE))
    assert rec["primary_skill"] == "MATH_T4"


def test_memory_still_unavailable():
    rec = route_task("Remember this conversation forever",
                     registry=_reg(document=ACTIVE))
    assert rec["primary_skill"] != "MEMORY"


def test_web_still_active_not_stolen_by_document():
    rec = route_task("Search the web for the latest news on Mars.",
                     registry=_reg(document=ACTIVE))
    assert rec["primary_skill"] == "WEB_RESEARCH"
