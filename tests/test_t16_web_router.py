"""T16.41 — routing tests with WEB_RESEARCH availability integration."""
from copy import deepcopy

from sciencemath.executive.executive_router import route_task
from sciencemath.executive.skills import (
    ACTIVE, EXPERIMENTAL, PREPARED_ONLY, SkillRegistry, default_registry,
)


def _reg(*, web="EXPERIMENTAL"):
    d = default_registry()
    d["WEB_RESEARCH"]["availability"] = web
    d["WEB_RESEARCH"]["executable"] = web in (ACTIVE, EXPERIMENTAL)
    d["WEB_RESEARCH"]["cost_class"] = "ONLINE_FREE"
    return SkillRegistry(d)


def test_default_registry_web_availability_is_recorded():
    reg = SkillRegistry()
    av = reg.availability("WEB_RESEARCH")
    assert av in (PREPARED_ONLY, ACTIVE, EXPERIMENTAL)
    if av == PREPARED_ONLY:
        assert not reg.executable("WEB_RESEARCH")
    else:
        assert reg.executable("WEB_RESEARCH")


def test_current_events_route_to_web_when_executable():
    rec = route_task("Search the web for the latest news on Mars.",
                     registry=_reg())
    assert rec["primary_skill"] == "WEB_RESEARCH"
    assert rec["execution_status"] == "ROUTED_ONLY"


def test_math_does_not_route_to_web():
    rec = route_task("What is 12 * 11?", registry=_reg())
    assert rec["primary_skill"] == "MATH_T4"
    assert rec["primary_skill"] != "WEB_RESEARCH"


def test_scicomp_not_web():
    rec = route_task(
        "Find the root of f(x) = x**2 - 2 in the interval [0, 5].",
        registry=_reg())
    assert rec["primary_skill"] == "SCICOMP"


def test_research_then_scicomp():
    rec = route_task(
        "Look up the official Planck constant then find the root of "
        "f(x) = x**2 - 2 in [0, 2].",
        registry=_reg())
    assert rec["primary_skill"] == "WEB_RESEARCH"
    assert "SCICOMP" in rec["secondary_skills"]


def test_research_then_code():
    rec = route_task(
        "Look up official mango-http documentation then write a python "
        "function and run this code.",
        registry=_reg())
    assert rec["primary_skill"] == "WEB_RESEARCH"
    assert "CODE" in rec["secondary_skills"]


def test_does_not_hallucinate_document_or_memory():
    rec = route_task("Remember this conversation forever", registry=_reg())
    assert rec["primary_skill"] != "MEMORY"
    rec2 = route_task("Parse this pdf spreadsheet csv file", registry=_reg())
    assert rec2["primary_skill"] != "DOCUMENT"


def test_web_fail_closed_when_prepared_only():
    rec = route_task("Search the web for the latest news on Mars.",
                     registry=_reg(web=PREPARED_ONLY))
    assert rec["primary_skill"] in ("GENERAL", "NO_TOOL")
    assert rec.get("unavailable_skill") == "WEB_RESEARCH"


def test_default_registry_routes_web_only_when_executable():
    rec = route_task("Search the web for the latest news on Mars.")
    if SkillRegistry().executable("WEB_RESEARCH"):
        assert rec["primary_skill"] == "WEB_RESEARCH"
        assert rec["execution_status"] == "ROUTED_ONLY"
    else:
        assert rec["primary_skill"] in ("GENERAL", "NO_TOOL")
        assert rec.get("unavailable_skill") == "WEB_RESEARCH"
