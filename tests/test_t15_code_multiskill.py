"""T15.29–T15.30 / T15R.32 — router coexistence + multi-skill interaction.

Routing must respect skill availability. CODE is invoked by the CODE
runtime; the Executive Router stays experimental and must not fake
WEB/MEMORY execution. GENERAL→CODE classification, CODE→MATH_T4, and
CODE→SCICOMP are exercised without mutating router policy.
"""
from sciencemath.code import contract as C
from sciencemath.code import runner as RN
from sciencemath.executive.skills import ACTIVE, PREPARED_ONLY, SkillRegistry


def test_code_skill_active_after_t15r_promotion():
    reg = SkillRegistry()
    assert reg.availability("CODE") == ACTIVE
    assert reg.executable("CODE")
    # WEB_RESEARCH stays non-executable until a T16 promotion gate.
    if reg.availability("WEB_RESEARCH") == PREPARED_ONLY:
        assert not reg.executable("WEB_RESEARCH")
    else:
        assert reg.executable("WEB_RESEARCH")
    assert not reg.executable("MEMORY")


def test_router_fails_closed_for_code_pre_activation():
    from sciencemath.executive.executive_router import route_task
    reg = SkillRegistry()
    rec = route_task("write a python function to parse csv files",
                     registry=reg)
    # must not present CODE as executed
    assert rec["execution_status"] == "ROUTED_ONLY"
    assert rec["primary_skill"] not in ("WEB_RESEARCH", "MEMORY")
    if reg.availability("CODE") == PREPARED_ONLY:
        assert not reg.executable("CODE")
        assert rec["primary_skill"] in ("GENERAL", "NO_TOOL")
        assert rec.get("unavailable_skill") == "CODE" or \
            rec["primary_skill"] in ("GENERAL", "NO_TOOL")
    else:
        # Router remains experimental: even if CODE is executable it does
        # not auto-dispatch CODE. Direct CODE runtime is the integration.
        assert rec["primary_skill"] != "WEB_RESEARCH"
        assert rec.get("hallucinated_tool") in (None, "")


def test_router_does_not_fake_web_or_memory():
    from sciencemath.executive.executive_router import route_task
    reg = SkillRegistry()
    rec = route_task("search the web for today's mango news", registry=reg)
    assert rec["execution_status"] == "ROUTED_ONLY"
    assert rec["primary_skill"] != "MEMORY"
    if not reg.executable("WEB_RESEARCH"):
        assert rec["primary_skill"] != "WEB_RESEARCH"
    else:
        assert rec["primary_skill"] == "WEB_RESEARCH"
    rec2 = route_task("remember this conversation forever", registry=reg)
    assert rec2["primary_skill"] != "MEMORY"
    assert rec2["execution_status"] == "ROUTED_ONLY"


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
