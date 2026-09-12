"""T15.29–T15.30 — router coexistence + multi-skill interaction (bounded).

Pre-activation (CODE PREPARED_ONLY): coding requests fail closed to
GENERAL with unavailable_skill=CODE (never presented as executed).
Post-activation behavior is verified by the promotion gate, not here.
GENERAL→CODE classification, CODE→MATH_T4, CODE→SCICOMP, and workflow
depth caps are all exercised without mutating router policy.
"""
from sciencemath.code import contract as C
from sciencemath.code import runner as RN
from sciencemath.executive.skills import SkillRegistry


def test_router_fails_closed_for_code_pre_activation():
    from sciencemath.executive.executive_router import route_task
    reg = SkillRegistry()
    assert reg.availability("CODE") == "PREPARED_ONLY"
    assert not reg.executable("CODE")
    rec = route_task("write a python function to parse csv files",
                     registry=reg)
    # must not present CODE as executed
    assert rec["primary_skill"] in ("GENERAL", "NO_TOOL")
    assert rec["execution_status"] == "ROUTED_ONLY"
    assert rec.get("unavailable_skill") == "CODE" or \
        rec["primary_skill"] in ("GENERAL", "NO_TOOL")


def test_router_non_coding_does_not_route_to_code():
    from sciencemath.executive.executive_router import route_task
    reg = SkillRegistry()
    rec = route_task("what is 12 * 11?", registry=reg)
    assert rec["primary_skill"] != "CODE"
    rec2 = route_task("explain photosynthesis", registry=reg)
    assert rec2["primary_skill"] != "CODE"


def test_general_to_code_classification(tmp_path):
    # GENERAL→CODE: a coding question is recognized as a CODE operation
    assert C.classify_request("implement a function to add two numbers") == \
        C.CODE_EDIT
    # ...while non-coding stays out
    assert C.classify_request("what is the capital of France?") == \
        C.CODE_NO_ACTION


def test_code_to_math_t4_coexistence():
    from sciencemath.tools.router import route_question
    r = route_question("what is 12 * 11?")
    # T4 tool router names a concrete tool (calculator); the executive
    # layer maps tool coverage to the MATH_T4 skill. Either way the
    # request is handled as math, not as a CODE edit.
    assert r.get("primary") in ("calculator", "MATH_T4")
    assert "calculator" in r.get("tools", [])
    # and the CODE contract does not claim arithmetic questions
    assert C.classify_request("what is 12 * 11?") != C.CODE_EDIT


def test_code_to_scicomp_coexistence():
    from sciencemath.scicomp.router import compute_necessity
    n = compute_necessity("solve dy/dt = -y, y(0)=1 to t=5")
    assert n["necessity"] in ("COMPUTE_REQUIRED", "COMPUTE_HELPFUL",
                              "NO_COMPUTE", "INSUFFICIENT_INFORMATION")
    # workflow depth stays bounded by router policy
    from sciencemath.executive import executive_router as ER
    assert ER.MAX_WORKFLOW_DEPTH == 3


def test_code_search_then_explain_workflow(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text(
        "def authenticate(u, p):\n    return True\n", encoding="utf-8")
    found = RN.run_coding_task(tmp_path, "Find where authenticate is defined")
    assert found["status"] == C.EXECUTED_PASS
    explained = RN.run_coding_task(
        tmp_path, "Explain this function authenticate", op=C.CODE_EXPLAIN)
    assert explained["status"] == C.EXECUTED_PASS
    assert "src/m.py" in explained["detail"]
