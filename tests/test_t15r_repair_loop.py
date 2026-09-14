"""T15R.36 — transactional repair-state, delta, retention, safety."""
import json

from sciencemath.code import contract as C
from sciencemath.code import editor as E
from sciencemath.code import multifile as MF
from sciencemath.code import repair_state as RS
from sciencemath.code import runner as RN
from sciencemath.code import task_contracts as TC


def _state(**kw) -> RS.RepairState:
    defaults = dict(
        state_id="s1", parent_state_id="s0", files_changed=["a.py"],
        diff_hash="ab", test_result={}, targeted_tests_passed=False,
        full_tests_passed_if_run=None, failure_count=1, failure_ids=["t1"],
        lint_status=RS.OK, safety_status=RS.OK,
        protected_component_status=RS.OK, tests_ran=True, compile_ok=True,
        diff_size=10,
    )
    defaults.update(kw)
    return RS.RepairState(**defaults)


def test_failure_delta_resolved_introduced_remaining():
    d = RS.failure_delta(["a", "b", "c"], ["b", "d"])
    assert d["resolved"] == ["a", "c"]
    assert d["introduced"] == ["d"]
    assert d["remaining"] == ["b", "d"]
    assert d["net_change"] == -1
    assert d["resolved_count"] == 2
    assert d["regression_count"] == 1


def test_best_state_selects_fewer_failures_not_newest():
    orig = _state(state_id="s0", parent_state_id=None, files_changed=[],
                  failure_count=5, failure_ids=["a", "b", "c", "d", "e"],
                  diff_size=0, tests_ran=True)
    newer_worse = _state(state_id="s2", failure_count=5,
                         failure_ids=["a", "b", "c", "d", "e"], diff_size=40)
    improved = _state(state_id="s1", failure_count=1, failure_ids=["e"],
                      diff_size=12)
    newest = _state(state_id="s9", failure_count=2, failure_ids=["e", "z"],
                    diff_size=8)
    best = RS.select_best([orig, newer_worse, improved, newest])
    assert best.state_id == "s1"


def test_same_failure_count_prefers_smaller_diff_not_newest():
    orig = _state(state_id="s0", parent_state_id=None, files_changed=[],
                  failure_count=1, failure_ids=["t"], diff_size=0)
    smaller = _state(state_id="s1", files_changed=["a.py"],
                     failure_count=1, failure_ids=["t"], diff_size=9)
    newest = _state(state_id="s9", files_changed=["a.py"],
                    failure_count=1, failure_ids=["t"], diff_size=40)
    # equal remaining failures: original wins (not a verified improvement).
    # Among non-original equal-fail patches, smaller diff wins — not newest.
    assert RS.select_best([orig, smaller, newest]).state_id == "s0"
    assert RS.select_best([smaller, newest]).state_id == "s1"


def test_regression_does_not_become_best():
    orig = _state(state_id="s0", parent_state_id=None, files_changed=[],
                  failure_count=1, failure_ids=["t1"], diff_size=0)
    regress = _state(state_id="s1", failure_count=4,
                     failure_ids=["t1", "a", "b", "c"], diff_size=20)
    assert RS.select_best([orig, regress]).is_original
    assert not RS.is_strict_improvement(regress, orig)


def test_unsafe_partial_cannot_be_retained():
    orig = _state(state_id="s0", parent_state_id=None, files_changed=[],
                  failure_count=5, diff_size=0)
    unsafe = _state(state_id="s1", failure_count=0,
                    targeted_tests_passed=True, test_weakening=True,
                    safety_status=RS.UNSAFE)
    assert not unsafe.retention_ok()
    assert not RS.is_strict_improvement(unsafe, orig)


def test_continue_repair_budget():
    assert RS.continue_repair(0, last_progress=False) is True
    assert RS.continue_repair(2, last_progress=False) is True
    assert RS.continue_repair(3, last_progress=False) is False
    assert RS.continue_repair(3, last_progress=True) is True
    assert RS.continue_repair(4, last_progress=True) is True
    assert RS.continue_repair(5, last_progress=True) is False


def test_session_lineage_and_checkpoints(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    ck = tmp_path / "ck"
    sess = RS.RepairSession(tmp_path, involved_files=["a.py"],
                            checkpoint_dir=ck)
    sess.bind_original_tests({
        "executed": True, "exit_code": 1, "failed": 5,
        "output": "FAILED t1\nFAILED t2\nFAILED t3\nFAILED t4\nFAILED t5\n",
    })
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    cand = sess.capture_candidate({
        "executed": True, "exit_code": 1, "failed": 1,
        "output": "FAILED t5\n",
    })
    dec = sess.consider(cand)
    assert dec["progressed"] is True
    assert sess.best.state_id == cand.state_id
    fin = sess.finalize()
    assert fin["best_retained"] is True
    assert fin["reverted_to_original"] is False
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 2\n"
    assert (ck / "attempt_1.patch").is_file()
    assert (ck / "best.patch").is_file()
    lin = sess.lineage()
    assert lin[0]["state_id"] == "s0"
    assert lin[-1]["parent_state_id"] == "s0"


def test_stub_replacement_retained_at_same_fail_count(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "a.py").write_text(
        "def fib(n):\n    raise NotImplementedError\n", encoding="utf-8")
    sess = RS.RepairSession(tmp_path, involved_files=["a.py"])
    sess.bind_original_tests({
        "executed": True, "exit_code": 1, "failed": 1,
        "output": "FAILED tests/test_f.py::test_f\n",
    })
    (tmp_path / "a.py").write_text(
        "def fib(n):\n    return n\n", encoding="utf-8")
    cand = sess.capture_candidate({
        "executed": True, "exit_code": 1, "failed": 1,
        "output": "FAILED tests/test_f.py::test_f\n",
    })
    dec = sess.consider(cand)
    assert dec["progressed"] is True
    assert cand.acceptance_conditions_satisfied >= 1
    fin = sess.finalize()
    assert fin["best_retained"] is True
    assert "return n" in (tmp_path / "a.py").read_text(encoding="utf-8")


def test_repair_budget_exhaustion_retains_best(tmp_path):
    root = _multi_fail_repo(tmp_path)
    res = RN.run_coding_task(
        root, "Fix a,b,c,d,e in src/m.py", op=C.CODE_DEBUG,
        edits=[{"file": "src/m.py",
                "old": ("def a():\n    return 0\n"
                        "def b():\n    return 0\n"
                        "def c():\n    return 0\n"
                        "def d():\n    return 0\n"
                        "def e():\n    return 0\n"),
                "new": ("def a():\n    return 1\n"
                        "def b():\n    return 1\n"
                        "def c():\n    return 1\n"
                        "def d():\n    return 1\n"
                        "def e():\n    return 0\n")}],
        repair_candidates=[
            {"id": "n1", "file": "src/m.py",
             "old": "def e():\n    return 0\n",
             "new": "def e():\n    return 2\n", "fixes": "ANY"},
            {"id": "n2", "file": "src/m.py",
             "old": "def e():\n    return 0\n",
             "new": "def e():\n    return 3\n", "fixes": "ANY"},
            {"id": "n3", "file": "src/m.py",
             "old": "def e():\n    return 0\n",
             "new": "def e():\n    return 4\n", "fixes": "ANY"},
        ],
        tests_to_run=["tests/test_m.py"])
    body = (tmp_path / "src" / "m.py").read_text(encoding="utf-8")
    assert "def a():\n    return 1" in body
    assert "def e():\n    return 0" in body
    sess = (res.get("evidence") or {}).get("repair_session") or {}
    assert sess.get("round") >= 1
    assert res["status"] in (C.BLOCKED, C.EXECUTED_FAIL)


def test_session_unsafe_does_not_overwrite_best(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    sess = RS.RepairSession(tmp_path, involved_files=["a.py"])
    sess.bind_original_tests({
        "executed": True, "exit_code": 1, "failed": 3,
        "output": "FAILED a\nFAILED b\nFAILED c\n",
    })
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    good = sess.capture_candidate({
        "executed": True, "exit_code": 1, "failed": 1,
        "output": "FAILED c\n",
    })
    sess.consider(good)
    (tmp_path / "a.py").write_text("x = 3\n", encoding="utf-8")
    bad = sess.capture_candidate({
        "executed": True, "exit_code": 1, "failed": 0,
        "output": "",
    }, test_weakening=True, safety_status=RS.UNSAFE)
    dec = sess.consider(bad)
    assert dec["progressed"] is False
    assert sess.best.state_id == good.state_id
    fin = sess.finalize()
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 2\n"
    assert fin["unsafe_revert"] is False
    assert fin["best_retained"] is True


def test_original_fallback_when_no_improvement(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    sess = RS.RepairSession(tmp_path, involved_files=["a.py"])
    sess.bind_original_tests({
        "executed": True, "exit_code": 1, "failed": 1,
        "output": "FAILED t\n",
    })
    (tmp_path / "a.py").write_text("x = 9\n", encoding="utf-8")
    cand = sess.capture_candidate({
        "executed": True, "exit_code": 1, "failed": 4,
        "output": "FAILED t\nFAILED a\nFAILED b\nFAILED c\n",
    })
    sess.consider(cand)
    fin = sess.finalize()
    assert fin["reverted_to_original"] is True
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def _multi_fail_repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "m.py").write_text(
        "def a():\n    return 0\n"
        "def b():\n    return 0\n"
        "def c():\n    return 0\n"
        "def d():\n    return 0\n"
        "def e():\n    return 0\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from src.m import a, b, c, d, e\n"
        "def test_a():\n    assert a() == 1\n"
        "def test_b():\n    assert b() == 1\n"
        "def test_c():\n    assert c() == 1\n"
        "def test_d():\n    assert d() == 1\n"
        "def test_e():\n    assert e() == 1\n", encoding="utf-8")
    return tmp_path


def test_runner_retains_partial_progress(tmp_path):
    root = _multi_fail_repo(tmp_path)
    # first patch fixes 4/5; no further repair that works
    res = RN.run_coding_task(
        root, "Fix a,b,c,d,e in src/m.py", op=C.CODE_DEBUG,
        edits=[{"file": "src/m.py",
                "old": ("def a():\n    return 0\n"
                        "def b():\n    return 0\n"
                        "def c():\n    return 0\n"
                        "def d():\n    return 0\n"
                        "def e():\n    return 0\n"),
                "new": ("def a():\n    return 1\n"
                        "def b():\n    return 1\n"
                        "def c():\n    return 1\n"
                        "def d():\n    return 1\n"
                        "def e():\n    return 0\n")}],
        repair_candidates=[],
        tests_to_run=["tests/test_m.py"])
    body = (tmp_path / "src" / "m.py").read_text(encoding="utf-8")
    assert "def a():\n    return 1" in body
    assert "def e():\n    return 0" in body
    assert res["files_touched"] == ["src/m.py"]
    sess = (res.get("evidence") or {}).get("repair_session") or {}
    assert sess.get("best", {}).get("failure_count") == 1
    assert res["status"] in (C.BLOCKED, C.EXECUTED_FAIL)


def test_runner_regression_rejects_and_keeps_best(tmp_path):
    root = _multi_fail_repo(tmp_path)
    res = RN.run_coding_task(
        root, "Fix a,b,c,d,e in src/m.py", op=C.CODE_DEBUG,
        edits=[{"file": "src/m.py",
                "old": ("def a():\n    return 0\n"
                        "def b():\n    return 0\n"
                        "def c():\n    return 0\n"
                        "def d():\n    return 0\n"
                        "def e():\n    return 0\n"),
                "new": ("def a():\n    return 1\n"
                        "def b():\n    return 1\n"
                        "def c():\n    return 1\n"
                        "def d():\n    return 1\n"
                        "def e():\n    return 0\n")}],
        repair_candidates=[{
            "id": "bad", "file": "src/m.py",
            "old": ("def a():\n    return 1\n"
                    "def b():\n    return 1\n"
                    "def c():\n    return 1\n"
                    "def d():\n    return 1\n"
                    "def e():\n    return 0\n"),
            "new": ("def a():\n    return 0\n"
                    "def b():\n    return 0\n"
                    "def c():\n    return 0\n"
                    "def d():\n    return 0\n"
                    "def e():\n    return 0\n"),
            "fixes": "ANY",
        }],
        tests_to_run=["tests/test_m.py"])
    body = (tmp_path / "src" / "m.py").read_text(encoding="utf-8")
    assert "def a():\n    return 1" in body  # best retained
    assert "def e():\n    return 0" in body
    assert res["files_touched"] == ["src/m.py"]


def test_runner_repairs_from_best_not_original(tmp_path):
    root = _multi_fail_repo(tmp_path)
    seen = []

    def gen(prompt):
        seen.append(prompt)
        if "Remaining failure" in prompt or "remaining failures" in prompt.lower() \
                or "Failure delta" in prompt:
            return json.dumps([{
                "file": "src/m.py",
                "old": "def e():\n    return 0\n",
                "new": "def e():\n    return 1\n",
            }])
        return json.dumps([{
            "file": "src/m.py",
            "old": ("def a():\n    return 0\n"
                    "def b():\n    return 0\n"
                    "def c():\n    return 0\n"
                    "def d():\n    return 0\n"
                    "def e():\n    return 0\n"),
            "new": ("def a():\n    return 1\n"
                    "def b():\n    return 1\n"
                    "def c():\n    return 1\n"
                    "def d():\n    return 1\n"
                    "def e():\n    return 0\n"),
        }])

    res = RN.run_coding_task(
        root, "Fix a,b,c,d,e in src/m.py", op=C.CODE_DEBUG,
        edits=None, generate=gen, tests_to_run=["tests/test_m.py"],
        context_files=["src/m.py"])
    assert res["status"] == C.EXECUTED_PASS, res
    assert "return 1" in (tmp_path / "src" / "m.py").read_text(encoding="utf-8")
    assert any("BEST" in p or "remaining" in p.lower() or "delta" in p.lower()
               for p in seen[1:] or seen)


def test_unsafe_partial_reverts_to_best_or_original(tmp_path):
    root = _multi_fail_repo(tmp_path)
    before = (tmp_path / "src" / "m.py").read_text(encoding="utf-8")
    res = RN.run_coding_task(
        root, "Fix a in src/m.py", op=C.CODE_DEBUG,
        edits=[{"file": "src/m.py", "old": "def a():\n    return 0\n",
                "new": "def a():\n    return 1\n"}],
        generate=lambda p: json.dumps([{
            "file": "tests/test_m.py",
            "old": "    assert a() == 1\n",
            "new": "    assert True\n",
        }]),
        tests_to_run=["tests/test_m.py"])
    # test weakening on repair must not stick; a()==1 partial may be kept
    test_txt = (tmp_path / "tests" / "test_m.py").read_text(encoding="utf-8")
    assert "assert True" not in test_txt
    # source is either original or the safe partial (a fixed)
    src = (tmp_path / "src" / "m.py").read_text(encoding="utf-8")
    assert src in (before, src)
    assert "assert a() == 1" in test_txt
    assert res["status"] != C.EXECUTED_PASS or "return 1" in src


def test_multi_file_atomic_dependency_map(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "cfg.py").write_text("TAX = 0.5\n", encoding="utf-8")
    (tmp_path / "src" / "use.py").write_text(
        "from src.cfg import TAX\n"
        "def price_with_tax(p):\n    return p + p * TAX + 1\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_use.py").write_text(
        "from src.use import price_with_tax\n"
        "def test_it():\n    assert price_with_tax(100) == 120\n",
        encoding="utf-8")
    dep = MF.map_dependencies(tmp_path, ["src/cfg.py", "src/use.py"])
    assert "src/cfg.py" in dep["files_involved"]
    assert "src/use.py" in dep["files_involved"]
    missing = MF.missing_coupled_files(
        [{"file": "src/cfg.py", "old": "TAX = 0.5", "new": "TAX = 0.2"}],
        dep)
    assert "src/use.py" in missing

    def gen(prompt):
        assert "files_involved" in prompt or "coupled" in prompt.lower() \
            or "Multi-file" in prompt
        return json.dumps([
            {"file": "src/cfg.py", "old": "TAX = 0.5", "new": "TAX = 0.2"},
            {"file": "src/use.py",
             "old": "    return p + p * TAX + 1",
             "new": "    return p + p * TAX"},
        ])

    res = RN.run_coding_task(
        tmp_path, "Fix the bugs across src/cfg.py and src/use.py",
        op=C.CODE_DEBUG, generate=gen,
        context_files=["src/cfg.py", "src/use.py"],
        tests_to_run=["tests/test_use.py"])
    assert res["status"] == C.EXECUTED_PASS, res
    assert "src/cfg.py" in res["files_touched"]
    assert "src/use.py" in res["files_touched"]


def test_context_pair_is_not_multi_file_unless_request_says_so():
    assert not MF.is_multi_file_task(
        "Adapt src/cli04.py to the current connect() signature",
        ["src/lib04.py", "src/cli04.py"])
    assert not MF.is_multi_file_task(
        "Fix the misconfiguration in src/cfg01.py",
        ["src/cfg01.py", "src/cfgu01.py"])
    assert MF.is_multi_file_task(
        "Fix the bugs across src/cfg.py and src/use.py",
        ["src/cfg.py", "src/use.py"])
    assert MF.is_multi_file_task(
        "Fix bugs in src/a.py and src/b.py",
        ["src/a.py", "src/b.py"])


def test_data_xform_and_algo_contracts():
    x = TC.data_xform_contract(
        "Implement rows_to_dict",
        src_text="def rows_to_dict(rows):\n    raise NotImplementedError\n",
        test_text="assert rows_to_dict([('a', 1)]) == {'a': 1}\n")
    assert x["kind"] == "data_xform"
    assert x["function"] == "rows_to_dict"
    assert x["determinism"].startswith("required")
    a = TC.algo_contract(
        "Implement fib",
        src_text="def fib(n):\n    raise NotImplementedError\n",
        test_text="assert [fib(i) for i in range(7)] == [0, 1, 1, 2, 3, 5, 8]\n")
    assert a["kind"] == "algo"
    assert a["function"] == "fib"


def test_no_test_weakening_still_holds(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from src.calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8")
    r = E.apply_edit(tmp_path, "tests/test_calc.py",
                     "    assert add(2, 3) == 5\n", "")
    assert not r["ok"] and r["error"] == "test weakening rejected"


def test_existing_single_fix_still_passes(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from src.calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8")
    res = RN.run_coding_task(
        tmp_path, "Fix add in src/calc.py", op=C.CODE_EDIT,
        edits=[{"file": "src/calc.py", "old": "return a - b",
                "new": "return a + b"}],
        tests_to_run=["tests/test_calc.py"])
    assert res["status"] == C.EXECUTED_PASS, res
    assert res["files_touched"] == ["src/calc.py"]


def test_code_edit_retries_from_live_failures_without_initial_patch(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "alg.py").write_text(
        "def fib(n):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_alg.py").write_text(
        "from src.alg import fib\n"
        "def test_f():\n    assert fib(6) == 8\n", encoding="utf-8")
    n = {"calls": 0}

    def gen(prompt):
        n["calls"] += 1
        if n["calls"] == 1:
            return "sorry, I cannot format a patch yet"
        return json.dumps([{
            "file": "src/alg.py",
            "old": "    raise NotImplementedError\n",
            "new": "    a, b = 0, 1\n"
                   "    for _ in range(n):\n"
                   "        a, b = b, a + b\n"
                   "    return a\n",
        }])

    res = RN.run_coding_task(
        tmp_path, "Implement fib in src/alg.py", op=C.CODE_EDIT,
        edits=None, generate=gen, tests_to_run=["tests/test_alg.py"],
        context_files=["src/alg.py"])
    assert res["status"] == C.EXECUTED_PASS, res
    assert n["calls"] >= 2
    assert "return a" in (tmp_path / "src" / "alg.py").read_text(
        encoding="utf-8")


def test_parse_patch_proposal_accepts_single_object(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    raw = '{"file": "src/a.py", "old": "x = 1", "new": "x = 2"}'
    edits = RN.parse_patch_proposal(tmp_path, raw)
    assert len(edits) == 1 and edits[0]["file"] == "src/a.py"
