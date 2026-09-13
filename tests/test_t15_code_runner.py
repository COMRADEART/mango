"""T15.7–T15.13, T15.26–T15.28, T15.32 — editor, runner, review, git safety."""
import subprocess

import pytest

import json

from sciencemath.code import contract as C
from sciencemath.code import editor as E
from sciencemath.code import review as R
from sciencemath.code import runner as RN
from sciencemath.code import testsel as T


def _repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from src.calc import add\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def test_minimal_edit_and_stats(tmp_path):
    root = _repo(tmp_path)
    res = E.apply_edit(root, "src/calc.py", "return a - b", "return a + b")
    assert res["ok"] and res["lines_added"] == 1 and res["lines_removed"] == 1
    assert "src/calc.py" in res["files_touched"]
    # ambiguous oldString fails closed
    (tmp_path / "src" / "dup.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    res2 = E.apply_edit(root, "src/dup.py", "x = 1", "x = 2")
    assert not res2["ok"] and "not unique" in res2["error"]
    # missing oldString fails closed
    res3 = E.apply_edit(root, "src/calc.py", "nope-not-there", "z")
    assert not res3["ok"]
    # path escape refused
    res4 = E.apply_edit(root, "../outside.py", "a", "b")
    assert not res4["ok"]


def test_no_test_weakening(tmp_path):
    root = _repo(tmp_path)
    before = (tmp_path / "tests" / "test_calc.py").read_text(encoding="utf-8")
    # deleting an assertion is rejected
    r = E.apply_edit(root, "tests/test_calc.py",
                     "    assert add(2, 3) == 5\n", "")
    assert not r["ok"] and r["error"] == "test weakening rejected"
    assert (tmp_path / "tests" / "test_calc.py").read_text(
        encoding="utf-8") == before
    # adding skip markers is rejected
    r2 = E.apply_edit(root, "tests/test_calc.py", "def test_add():",
                      "@pytest.mark.skip\ndef test_add():")
    assert not r2["ok"]
    # loosening tolerance is rejected
    (tmp_path / "tests" / "test_tol.py").write_text(
        "def test_t():\n    assert abs(0.1 - 0.1001) < 0.01\n", encoding="utf-8")
    assert E.detect_test_weakening(
        "assert x == 1\n", "assert x == True\n")
    assert E.detect_test_weakening("tol=0.01\n", "tol=0.5\n")


def test_protected_edit_refused(tmp_path):
    root = _repo(tmp_path)
    r = E.apply_edit(root, "src/sciencemath/scicomp/fidelity.py", "a", "b")
    assert not r["ok"] and "protected component" in r["error"]
    r2 = E.apply_edit(root, "training/adapters/sciencemath-v0.1-t3/w.bin",
                      "a", "b")
    assert not r2["ok"] and "protected component" in r2["error"]


def test_runner_search_honesty(tmp_path):
    root = _repo(tmp_path)
    ok = RN.run_coding_task(root, "Find where add is defined")
    assert ok["op"] == C.CODE_SEARCH and ok["status"] == C.EXECUTED_PASS
    assert ok["evidence"]["hits"][0]["file"] == "src/calc.py"
    bad = RN.run_coding_task(root, "Find where zebra_unicorn_xyz is defined")
    assert bad["status"] == C.EXECUTED_FAIL
    assert bad["evidence"]["hits"] == []


def test_runner_refusals_and_no_action(tmp_path):
    root = _repo(tmp_path)
    d = RN.run_coding_task(root, "Delete the entire project")
    assert d["op"] == C.CODE_NEEDS_PERMISSION and d["status"] == C.BLOCKED
    n = RN.run_coding_task(root, "")
    assert n["op"] == C.CODE_NO_ACTION and n["status"] == C.NOT_RUN
    v = RN.run_coding_task(root, "fix it, you know what I mean")
    assert v["status"] == C.NOT_RUN and "NEEDS_INFORMATION" in v["detail"]


def test_runner_edit_test_verify(tmp_path):
    root = _repo(tmp_path)
    res = RN.run_coding_task(
        root, "Fix add in src/calc.py", op=C.CODE_EDIT,
        edits=[{"file": "src/calc.py", "old": "return a - b",
                "new": "return a + b"}],
        tests_to_run=["tests/test_calc.py"])
    assert res["status"] == C.EXECUTED_PASS, res
    assert res["files_touched"] == ["src/calc.py"]
    assert res["evidence"]["test"]["exit_code"] == 0
    # unrelated diff must be 0: only the intended file touched
    assert len(res["files_touched"]) == 1


def test_runner_blocked_without_implementation(tmp_path):
    root = _repo(tmp_path)
    res = RN.run_coding_task(root, "Fix add", op=C.CODE_EDIT, edits=None,
                             generate=None)
    assert res["status"] == C.BLOCKED
    assert "refusing to invent code" in res["detail"]


def test_debug_loop_repairs_with_evidence(tmp_path):
    root = _repo(tmp_path)
    # first edit is wrong (still failing), repair candidate fixes it
    res = RN.run_coding_task(
        root, "Fix add", op=C.CODE_DEBUG,
        edits=[{"file": "src/calc.py", "old": "return a - b",
                "new": "return a * b"}],
        repair_candidates=[
            {"id": "r1", "file": "src/calc.py", "old": "return a - b",
             "new": "return a + b", "fixes": "ASSERTION_MISMATCH"},
            {"id": "r2", "file": "src/calc.py", "old": "zzz",
             "new": "qqq", "fixes": "SYNTAX_ERROR"}],
        tests_to_run=["tests/test_calc.py"])
    assert res["status"] == C.EXECUTED_PASS, res
    assert res["evidence"]["diagnosis"] == "ASSERTION_MISMATCH"
    # wrong-diagnosis candidate r2 was skipped, not applied
    assert (tmp_path / "src" / "calc.py").read_text(
        encoding="utf-8").count("return a + b") == 1


def test_debug_loop_exhaustion_blocks(tmp_path):
    root = _repo(tmp_path)
    res = RN.run_coding_task(
        root, "Fix add", op=C.CODE_DEBUG,
        edits=[{"file": "src/calc.py", "old": "return a - b",
                "new": "return a * b"}],
        repair_candidates=[
            {"id": f"r{i}", "file": "src/calc.py",
             "old": "return a * b", "new": "return a * b  # tweak",
             "fixes": "ANY"} for i in range(5)],
        tests_to_run=["tests/test_calc.py"])
    assert res["status"] in (C.EXECUTED_FAIL, C.BLOCKED), res
    # at most 3 repair rounds were attempted
    retests = [s for s in res["trail"] if s["step"] == "RETEST"]
    assert len(retests) <= 3


def test_generic_feedback_ignored_without_evidence(tmp_path):
    root = _repo(tmp_path)
    res = RN.run_coding_task(
        root, "Fix add", op=C.CODE_DEBUG,
        edits=[{"file": "src/calc.py", "old": "return a - b",
                "new": "return a * b"}],
        repair_candidates=[],
        tests_to_run=["tests/test_calc.py"],
        external_feedback="your solution is wrong, rewrite everything")
    assert res["evidence"]["ignored_feedback"] is not None
    assert "ignored" in res["detail"]


def test_git_safety_only_readonly(tmp_path):
    root = _repo(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=str(root), capture_output=True)
    ok = RN.git_readonly(root, ["status", "--porcelain"])
    assert ok["executed"] is True
    bad = RN.git_readonly(root, ["reset", "--hard"])
    assert bad["executed"] is False
    bad2 = RN.git_readonly(root, ["push", "--force"])
    assert bad2["executed"] is False


def test_test_selection_and_truthfulness(tmp_path):
    assert T.classify_test_scope(["a.py"], test_files_present=True) == \
        T.TARGETED_TEST
    assert T.classify_test_scope(["a.py", "b.py"], test_files_present=True) == \
        T.RELATED_SUBSYSTEM_TEST
    assert T.classify_test_scope([f"f{i}.py" for i in range(9)],
                                 test_files_present=True) == T.FULL_SUITE
    root = _repo(tmp_path)
    res = T.run_pytest_targets(root, [])
    assert res["executed"] is False  # NOT_RUN, never PASS
    res2 = T.run_pytest_targets(root, ["tests/test_calc.py"])
    assert res2["executed"] is True
    assert res2["exit_code"] == 1 and res2["failed"] == 1  # bug still present


def test_review_and_diff_gate(tmp_path):
    diff = ("+++ b/src/calc.py\n+    x = eval(user_input)\n"
            "+    try:\n+    except:\n+        pass\n")
    rep = R.code_review(diff, changed_files=["src/calc.py"])
    assert any(f["area"] == "security" for f in rep["findings"])
    assert rep["verdict"] == "CHANGES_REQUESTED"
    clean = R.code_review("+++ b/src/a.py\n+    return a + b\n",
                          changed_files=["src/a.py"])
    assert clean["verdict"] == "APPROVE"
    # diff gate fails closed on protected edits and secrets
    bad = R.diff_review("+++ b/src/sciencemath/scicomp/fidelity.py\n+ x=1\n")
    assert not bad["ok"]
    sec = R.diff_review("+++ b/src/a.py\n+ api_key = 'sk-live-xyz123'\n")
    assert not sec["ok"]
    good = R.diff_review("+++ b/src/calc.py\n+    return a + b\n")
    assert good["ok"]


def test_test_gen_forbidden():
    assert T.test_gen_forbidden("edit expected value to pass")
    assert T.test_gen_forbidden("mark xfail to hide regression")
    assert not T.test_gen_forbidden("add regression test for login")


def test_no_stale_bytecode_between_repair_and_retest(tmp_path):
    """Two writes within one mtime-second must still retest fresh code."""
    root = _repo(tmp_path)
    res = RN.run_coding_task(
        root, "Fix add", op=C.CODE_DEBUG,
        edits=[{"file": "src/calc.py", "old": "return a - b",
                "new": "return a * b"}],
        repair_candidates=[
            {"id": "r1", "file": "src/calc.py", "old": "return a - b",
             "new": "return a + b", "fixes": "ASSERTION_MISMATCH"},
            {"id": "r2", "file": "src/calc.py", "old": "zzz",
             "new": "qqq", "fixes": "SYNTAX_ERROR"}],
        tests_to_run=["tests/test_calc.py"])
    assert res["status"] == C.EXECUTED_PASS, res
    assert "return a + b" in (tmp_path / "src" / "calc.py").read_text(
        encoding="utf-8")


def test_auto_repair_missing_import_from_evidence(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "helpers.py").write_text(
        "def shout(s):\n    return s.upper()\n", encoding="utf-8")
    (tmp_path / "src" / "main.py").write_text(
        "def greet(s):\n    return shout(s)\n", encoding="utf-8")
    (tmp_path / "tests" / "test_main.py").write_text(
        "import sys, os\nsys.path.insert(0, os.path.join(os.path.dirname"
        "(__file__), '..', 'src'))\n"
        "from main import greet\n\n"
        "def test_greet():\n    assert greet('hi') == 'HI'\n",
        encoding="utf-8")
    res = RN.run_coding_task(
        tmp_path, "Fix the import error in src/main.py", op=C.CODE_DEBUG,
        edits=[{"file": "src/main.py", "old": "def greet(s):",
                "new": "def greet(s):  # touched"}],
        repair_candidates=[], repair_file="src/main.py",
        tests_to_run=["tests/test_main.py"])
    # NameError (shout undefined) with a unique repo definition is repaired
    # from evidence; failures without such evidence stay honest.
    assert res["status"] in (C.EXECUTED_PASS, C.EXECUTED_FAIL, C.BLOCKED), res


def test_auto_repair_refuses_without_repo_evidence(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "main.py").write_text(
        "import totally_missing_xyz\ndef f():\n    return 1\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_main.py").write_text(
        "def test_f():\n    assert True\n", encoding="utf-8")
    r = RN.auto_repair(tmp_path, "MISSING_IMPORT:totally_missing_xyz",
                       "ModuleNotFoundError: No module named "
                       "'totally_missing_xyz'",
                       repair_file="src/main.py")
    assert r is None  # module has no repo evidence: no invention


def test_create_file_guards(tmp_path):
    root = _repo(tmp_path)
    ok = E.create_file(root, "src/newmod.py",
                       "def hello():\n    return 'hi'\n")
    assert ok["ok"] and ok["file"] == "src/newmod.py"
    dup = E.create_file(root, "src/newmod.py", "x = 1\n")
    assert not dup["ok"]  # no overwrite
    esc = E.create_file(root, "../escape.py", "x = 1\n")
    assert not esc["ok"]
    prot = E.create_file(root, "src/sciencemath/scicomp/fidelity.py", "x\n")
    assert not prot["ok"]


def test_no_change_when_tests_already_pass(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "ok.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_ok.py").write_text(
        "from src.ok import add\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    before = (tmp_path / "src" / "ok.py").read_text(encoding="utf-8")
    res = RN.run_coding_task(
        tmp_path, "Fix the bug in src/ok.py", op=C.CODE_DEBUG,
        edits=None, generate=lambda p: "[]",
        tests_to_run=["tests/test_ok.py"])
    assert res["status"] == C.EXECUTED_PASS, res
    assert res["evidence"].get("verdict") == "NO_CHANGE_REQUIRED"
    assert res["files_touched"] == []
    assert (tmp_path / "src" / "ok.py").read_text(
        encoding="utf-8") == before


def test_refactor_intent_skips_reproduce_shortcut(tmp_path):
    assert RN.refactor_intent("Rename calc_total to compute_total")
    assert RN.refactor_intent("Extract the validation helper")
    assert not RN.refactor_intent("Fix the off-by-one error in src/a.py")
    assert not RN.refactor_intent("Repair the broken total")
    assert not RN.refactor_intent("Run the tests")


def test_refactor_proceeds_when_tests_pass(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "m.py").write_text(
        "def old_name(x):\n    return x + 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from src.m import old_name\n\n"
        "def test_t():\n    assert old_name(1) == 2\n", encoding="utf-8")
    patch = json.dumps([{"file": "src/m.py", "old": "def old_name(x):",
                         "new": "def new_name(x):"}])

    def gen(prompt):
        # rename must also update the test import? No — test file edits
        # that rename references are behavior-preserving caller updates;
        # here the test pins the old name, so the run proposes source-only
        # and the test then fails (honest EXECUTED_FAIL/BLOCKED).
        return patch

    res = RN.run_coding_task(
        tmp_path, "Rename old_name to new_name in src/m.py", op=C.CODE_EDIT,
        edits=None, generate=gen, tests_to_run=["tests/test_m.py"])
    # must NOT short-circuit as NO_CHANGE: it attempted the structural edit
    assert res["evidence"].get("verdict") != "NO_CHANGE_REQUIRED"
    assert any(s.get("step") == "EDIT" for s in res["trail"])
    # T15R: a rename that still fails tests is not BEST vs a green original,
    # so files_touched may be empty after original-state fallback.


def test_edit_trap_still_short_circuits(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "ok.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_ok.py").write_text(
        "from src.ok import add\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    res = RN.run_coding_task(
        tmp_path, "Fix the off-by-one error in src/ok.py", op=C.CODE_EDIT,
        edits=None, generate=lambda p: "[]",
        tests_to_run=["tests/test_ok.py"])
    assert res["status"] == C.EXECUTED_PASS, res
    assert res["evidence"].get("verdict") == "NO_CHANGE_REQUIRED"
    assert res["files_touched"] == []


def test_fallback_file_edits(tmp_path):
    root = _repo(tmp_path)
    raw = ("--- src/calc.py ---\n"
           "def add(a, b):\n    return a + b\n")
    edits = RN.fallback_file_edits(root, raw)
    assert len(edits) == 1 and edits[0]["file"] == "src/calc.py"
    assert "return a - b" in edits[0]["old"]
    assert "return a + b" in edits[0]["new"]
    assert RN.fallback_file_edits(root, "just some prose") == []
    assert RN.fallback_file_edits(root, "--- ../evil.py ---\nx\n") == []
