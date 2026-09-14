"""T18.47 / T18.71 router availability tests."""
from sciencemath.executive.executive_router import route_task
from sciencemath.executive.skills import (
    ACTIVE, EXPERIMENTAL, PREPARED_ONLY, SkillRegistry, default_registry,
)


def _reg(*, memory="PREPARED_ONLY"):
    d = default_registry()
    d["MEMORY"]["availability"] = memory
    d["MEMORY"]["executable"] = memory in (ACTIVE, EXPERIMENTAL)
    return SkillRegistry(d)


def test_default_memory_prepared_only_or_active():
    reg = SkillRegistry()
    av = reg.availability("MEMORY")
    assert av in (PREPARED_ONLY, ACTIVE, EXPERIMENTAL)
    if av == PREPARED_ONLY:
        assert not reg.executable("MEMORY")
    else:
        assert reg.executable("MEMORY")


def test_memory_fail_closed_when_prepared_only():
    rec = route_task("Remember that project X uses PostgreSQL.",
                     registry=_reg())
    assert rec["primary_skill"] in ("GENERAL", "NO_TOOL")
    assert rec.get("unavailable_skill") == "MEMORY"


def test_memory_store_routes_when_executable():
    rec = route_task("Remember that project X uses PostgreSQL.",
                     registry=_reg(memory=ACTIVE))
    assert rec["primary_skill"] == "MEMORY"


def test_memory_retrieve_routes_when_executable():
    rec = route_task("What database did we choose for project X?",
                     registry=_reg(memory=ACTIVE))
    assert rec["primary_skill"] == "MEMORY"


def test_web_not_stolen_by_memory():
    rec = route_task("What happened in the market today? Search the web.",
                     registry=_reg(memory=ACTIVE))
    assert rec["primary_skill"] == "WEB_RESEARCH"


def test_document_not_stolen_by_memory():
    rec = route_task("Summarize this PDF document please.",
                     registry=_reg(memory=ACTIVE))
    assert rec["primary_skill"] == "DOCUMENT"


def test_code_not_stolen_by_memory():
    rec = route_task("Write a python function and run this code to fix the bug.",
                     registry=_reg(memory=ACTIVE))
    assert rec["primary_skill"] != "MEMORY"


def test_scicomp_not_stolen_by_memory():
    rec = route_task(
        "Calculate the confidence interval. Find the root of f(x)=x**2-2 "
        "in [0, 2].",
        registry=_reg(memory=ACTIVE))
    assert rec["primary_skill"] == "SCICOMP"


def test_math_not_memory():
    rec = route_task("What is 12 * 11?", registry=_reg(memory=ACTIVE))
    assert rec["primary_skill"] == "MATH_T4"
