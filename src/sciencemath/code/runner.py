"""T15.12, T15.13, T15.28, T15.32 — bounded debug loop + task runner.

Loop: INSPECT → PLAN → EDIT → TEST → DIAGNOSE → REPAIR → RETEST → REVIEW.
Max 3 repair rounds per task (T15.12); afterwards STOP and report BLOCKED.

Truthfulness (T15.13): statuses are PLANNED / ATTEMPTED / EXECUTED_PASS /
EXECUTED_FAIL / NOT_RUN / BLOCKED and always reflect what really happened.
Git safety (T15.28): only status/diff/log/show are ever executed.
Correction (T15.32): repairs use actual failure evidence; generic
"your solution is wrong" feedback without failing-test evidence is
recorded and ignored (false-feedback resistance preserved).
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from sciencemath.code import contract as C
from sciencemath.code import discovery as D
from sciencemath.code import editor as E
from sciencemath.code import limits as L
from sciencemath.code import multifile as MF
from sciencemath.code import planner as P
from sciencemath.code import repair_state as RS
from sciencemath.code import review as R
from sciencemath.code import safety as S
from sciencemath.code import search as SE
from sciencemath.code import task_contracts as TC
from sciencemath.code import testsel as T

_GIT_SAFE = re.compile(
    r"^\s*git\s+(status|diff|log|show)(\s|$)")


def git_readonly(root: str | Path, args: list) -> dict:
    """Execute ONLY read-only git subcommands. Anything else is refused."""
    cmd = "git " + " ".join(args)
    if not _GIT_SAFE.match(cmd):
        return {"executed": False, "output": "",
                "reason": "refused: not a read-only git command"}
    try:
        r = subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                           text=True, timeout=30, encoding="utf-8",
                           errors="replace")
        return {"executed": True, "exit_code": r.returncode,
                "output": (r.stdout or "")[-4000:]}
    except Exception as e:  # noqa: BLE001
        return {"executed": False, "output": str(e)[:1000],
                "reason": "git execution failed"}


_REFACTOR_INTENT = re.compile(
    r"\b(rename\b|extract\s+(the\s+)?[a-zA-Z_]+|restructure|reorganiz|"
    r"move\s+\S+\s+to\s+|split\s+\S+\s+into\s+|inline\s+\w+|pull\s+up\s+|"
    r"push\s+down\s+)", re.I)


def refactor_intent(request: str) -> bool:
    """True when the request asks for a structural change whose tests
    pass both before and after (rename/extract/move). Such tasks must
    NOT short-circuit on reproduce-first: passing tests prove
    preservation, not completion."""
    return bool(_REFACTOR_INTENT.search(request or ""))


def fallback_file_edits(base: Path, raw: str) -> list:
    """Baseline-style proposal fallback: `--- path ---` headers with raw
    or fenced code become whole-file replacements (old = current content,
    which always matches) or guarded creates. Returns [] when nothing
    parseable exists. Every edit is still verified by tests downstream.
    """
    import re as _re
    edits: list[dict] = []
    blocks = _re.findall(r"```(?:python)?\s*\n(.*?)```", raw or "", re.S)
    headers = _re.findall(r"^---\s*(\S+)\s*---\s*$", raw or "", re.M)
    bodies: list[tuple] = []
    if headers and blocks and len(headers) == len(blocks):
        bodies = list(zip(headers, blocks))
    elif headers:
        parts = _re.split(r"^---\s*(\S+)\s*---\s*$", raw, flags=re.M)
        for i in range(1, len(parts) - 1, 2):
            body = _re.sub(r"```(?:python)?", "", parts[i + 1]).strip("\n")
            if body.strip():
                bodies.append((parts[i], body))
    for path, body in bodies:
        raw = path.replace("\\", "/")
        if ".." in raw.split("/"):
            continue
        rel = raw.lstrip("./")
        target = base / rel
        content = body.strip("\n") + "\n"
        if target.is_file():
            try:
                current = target.read_text(encoding="utf-8")
            except OSError:
                continue
            if current != content:
                edits.append({"file": rel, "old": current, "new": content})
        elif target.parent.is_dir():
            edits.append({"file": rel, "create": True, "new": content})
    return edits


_SYMBOL_STOPWORDS = frozenset({
    "find", "where", "locate", "search", "show", "explain", "describe",
    "this", "that", "the", "is", "are", "was", "defined", "handled",
    "located", "declared", "implemented", "function", "method", "class",
    "module", "code", "file", "files", "in", "of", "a", "an", "to", "for",
    "how", "does", "do", "what", "why", "it", "and", "or", "with", "me",
    "my", "our", "be", "by", "on", "at", "which", "who", "calls", "called",
})


def extract_symbol(request: str) -> str:
    """Extract the most likely code symbol from a request.

    Drops natural-language stopwords and returns the last remaining
    identifier-like token (dotted names kept). Returns "" when the
    request names nothing — the caller must then report no-evidence,
    never invent a symbol.
    """
    tokens = re.findall(r"[A-Za-z_][\w.]*", request or "")
    rest = [t.strip(".") for t in tokens
            if t.lower() not in _SYMBOL_STOPWORDS and t.strip(".")]
    return rest[-1] if rest else ""


def need_info(request: str) -> dict:
    return C.code_response(C.CODE_NO_ACTION, C.NOT_RUN, detail=(
        "NEEDS_INFORMATION: the request names no target, file, symbol, or "
        "reproducible symptom; no code was invented."), evidence={
            "request": (request or "")[:240]})


def _extractive_explain(symbol: str, hits: list) -> str:
    locs = "; ".join(f"{h['file']}:{h['line']}" for h in hits[:5])
    first = (hits[0]["text"] if hits else "")
    return (f"Symbol `{symbol}` defined at {locs}. "
            f"Definition line: {first}".strip())


def _diagnose(test_result: dict) -> str:
    out = (test_result or {}).get("output", "")
    if "ModuleNotFoundError" in out or "ImportError" in out:
        m = re.search(r"No module named ['\"]([^'\"]+)['\"]", out)
        return f"MISSING_IMPORT:{m.group(1)}" if m else "MISSING_IMPORT:?"
    if "NameError" in out:
        m = re.search(r"name '([^']+)' is not defined", out)
        return f"UNDEFINED_NAME:{m.group(1)}" if m else "UNDEFINED_NAME:?"
    if "KeyError" in out:
        m = re.search(r"KeyError:\s*['\"]?([^'\"\s]+)", out)
        return f"MISSING_KEY:{m.group(1)}" if m else "MISSING_KEY:?"
    if "AssertionError" in out:
        return "ASSERTION_MISMATCH"
    if "SyntaxError" in out:
        return "SYNTAX_ERROR"
    if (test_result or {}).get("failed", 0):
        return "TEST_FAILURE"
    return "UNKNOWN"


def _failing_file_from_output(base: Path, output: str,
                              fallback: str | None = None) -> str | None:
    """Locate the repo file to repair from real failure output."""
    if fallback:
        return fallback
    m = re.search(r"((?:tests|src)/[\w./-]+\.py)", (output or "").replace("\\", "/"))
    if m and (base / m.group(1)).is_file():
        return m.group(1)
    return None


def _module_exists(base: Path, mod: str) -> bool:
    mod = (mod or "").split(".")[0]
    if not mod or not re.fullmatch(r"[A-Za-z_]\w*", mod):
        return False
    return (base / f"{mod}.py").is_file() or \
        (base / mod / "__init__.py").is_file() or \
        any((base / d / f"{mod}.py").is_file() for d in ("src", "lib", "app"))


def _insert_import(base: Path, rel: str, statement: str) -> dict:
    """Insert an import statement after leading imports/docstring."""
    target = base / rel
    try:
        lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as e:
        return {"ok": False, "error": f"unreadable: {e}"}
    if any(statement.strip() == l.strip() for l in lines):
        return {"ok": False, "error": "import already present"}
    idx = 0
    if lines and lines[0].startswith("#!"):
        idx = 1
    if idx < len(lines) and lines[idx].lstrip().startswith(('"""', "'''")):
        quote = lines[idx].lstrip()[:3]
        idx += 1
        while idx < len(lines) and quote not in lines[idx]:
            idx += 1
        idx += 1
    while idx < len(lines) and re.match(
            r"^\s*(import |from |#|$)", lines[idx]):
        idx += 1
    updated = list(lines)
    updated.insert(idx, statement + "\n")
    return _write_splice(base, rel, lines, updated)


def _write_splice(base: Path, rel: str, before: list, after: list) -> dict:
    from sciencemath.code import editor as _E
    target = base / rel
    original = "".join(before)
    updated = "".join(after)
    if _E.is_test_file(rel):
        violations = _E.detect_test_weakening(original, updated)
        if violations:
            return {"ok": False, "error": "test weakening rejected",
                    "violations": violations}
    ok_s, err = _E.syntax_ok(rel, updated)
    if not ok_s:
        return {"ok": False, "error": f"syntax: {err}"}
    target.write_text(updated, encoding="utf-8")
    import difflib as _dl
    diff = list(_dl.unified_diff(original.splitlines(),
                                 updated.splitlines(), lineterm=""))
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    return {"ok": True, "file": rel, "lines_added": added,
            "lines_removed": 0, "diff": "\n".join(diff)[:8000]}


def auto_repair(base: Path, diagnosis: str, test_output: str, *,
                repair_file: str | None = None) -> dict | None:
    """Evidence-triggered micro-repair (no caller candidates needed).

    Closed set, each verified by retest downstream:
      MISSING_IMPORT:X -> add `import X` iff X exists in the repo.
      UNDEFINED_NAME:X -> add `from <unique defining module> import X`
        iff exactly one repo definition exists outside the failing file.
    Returns an applied-edit record, or None when no evidence-backed
    repair exists (caller must then report BLOCKED, never invent).
    """
    rel = _failing_file_from_output(base, test_output, repair_file)
    if not rel:
        return None
    if diagnosis.startswith("MISSING_IMPORT:"):
        mod = diagnosis.split(":", 1)[1].split(".")[0]
        if not _module_exists(base, mod):
            return None
        r = _insert_import(base, rel, f"import {mod}")
        return {**r, "auto": f"MISSING_IMPORT:{mod}"} if r.get("ok") else None
    if diagnosis.startswith("UNDEFINED_NAME:"):
        name = diagnosis.split(":", 1)[1]
        if not re.fullmatch(r"[A-Za-z_]\w*", name or ""):
            return None
        def_hits = [h for h in SE.search_symbol(base, name)
                    if re.match(r"^\s*(def|class)\s+" + re.escape(name) + r"\b",
                                h["text"])]
        assign_hits = [h for h in SE.search_text(
            base, f"{name} =", regex=False)
            if re.match(r"^\s*" + re.escape(name) + r"\s*=",
                        h["text"])]
        files = sorted({h["file"] for h in def_hits + assign_hits})
        files = [f for f in files if f != rel]
        if len(files) != 1:
            return None
        modpath = files[0].replace("/", ".").removesuffix(".py") \
            .removesuffix(".__init__")
        r = _insert_import(base, rel, f"from {modpath} import {name}")
        return {**r, "auto": f"UNDEFINED_NAME:{name}"} if r.get("ok") else None
    return None


def _wellformed_edit(e) -> bool:
    return isinstance(e, dict) and (
        {"file", "old", "new"} <= set(e) or
        (e.get("create") is True and {"file", "new"} <= set(e)))


def parse_patch_proposal(base: Path, raw: str) -> list:
    """JSON list [{file,old,new}] or --- path --- fallback. Never invents."""
    cand = None
    try:
        cand = json.loads(raw[raw.index("["):raw.rindex("]") + 1])
    except (ValueError, IndexError, json.JSONDecodeError):
        cand = None
    if isinstance(cand, list) and cand and all(_wellformed_edit(e) for e in cand):
        return cand
    return fallback_file_edits(base, raw) or []


_ROLLBACK = (
    "revert to ORIGINAL only on safety, protected-component, "
    "test-weakening, or catastrophic regression; otherwise retain "
    "BEST_VERIFIED_STATE and repair from it"
)


def _read_blob(base: Path, rel: str, n: int = 4000) -> str:
    try:
        return (base / rel).read_text(encoding="utf-8")[:n]
    except OSError:
        return ""


def _prompt_context(base: Path, request: str, *,
                    context_files: list | None, tests_to_run: list | None,
                    dep_map: dict | None, contract: dict | None,
                    diagnosis: str = "", delta: dict | None = None,
                    remaining: list | None = None,
                    test_output: str = "") -> str:
    files = list(context_files or [])[:8]
    blobs = []
    for cf in files:
        txt = _read_blob(base, cf, 3000)
        if txt:
            blobs.append(f"--- {cf} ---\n{txt}")
    oracle = TC.load_related_tests(base, tests_to_run)
    parts = [
        "Propose a minimal coordinated patch as JSON list "
        "[{file, old, new}] (exact old strings from the files below; "
        'use {"file": path, "create": true, "new": content} only for '
        "brand-new files). Do not weaken tests. Do not touch protected "
        "components. Do not invent execution.",
        f"Task: {request[:500]}",
    ]
    if dep_map:
        parts.append(MF.format_dep_map(dep_map))
        parts.append(
            "Stage ALL logically coupled edits (producer+consumer, "
            "interface+implementation, schema+parser) in this single "
            "patch. Do not assume a single-file patch can solve a "
            "multi-file task.")
    if contract:
        parts.append(TC.format_contract(contract))
    if diagnosis:
        parts.append(f"Diagnosis of remaining failures: {diagnosis}")
    if delta:
        parts.append("Failure delta vs BEST_VERIFIED_STATE: "
                     + json.dumps({k: delta[k] for k in
                                   ("resolved", "introduced", "remaining",
                                    "net_change") if k in delta}))
        parts.append("Target remaining failures only; do not rediscover "
                     "the full problem from scratch.")
    if remaining:
        parts.append("Remaining failure ids: " + ", ".join(remaining[:12]))
    if test_output:
        parts.append("Failing output:\n" + test_output[-1200:])
    if oracle:
        parts.append(oracle)
    parts.extend(blobs)
    return "\n".join(parts)[:7000]


def run_coding_task(repo_root: str | Path, request: str, *,
                    op: str | None = None,
                    edits: list | None = None,
                    repair_candidates: list | None = None,
                    repair_file: str | None = None,
                    context_files: list | None = None,
                    tests_to_run: list | None = None,
                    task_allows: tuple = (),
                    network_permitted: bool = False,
                    limits: dict | None = None,
                    generate=None,
                    external_feedback: str | None = None) -> dict:
    """Execute one bounded coding task. Deterministic unless `generate`
    (a callable prompt->text) is supplied for EXPLAIN/PLAN prose or
    structured patch proposals.

    `edits`: explicit [{file, old, new}] operations (the change under test).
    `repair_candidates`: [{id, file, old, new, fixes}] tried in order on
    genuine test failure (max 3 rounds). Generic external_feedback without
    failing-test evidence is ignored (T15.32). `repair_file` names the
    file evidence-triggered auto-repairs target when failure output is
    ambiguous.
    """
    t0 = time.time()
    lim = dict(L.DEFAULT_LIMITS)
    if limits:
        lim.update(limits)
    usage = {"max_files_read": 0, "max_files_modified": 0, "max_commands": 0,
             "max_repair_iterations": 0}
    base = Path(repo_root)
    trail: list[dict] = []

    def step(name: str, status: str, detail: str = "", **kw):
        trail.append({"step": name, "status": status, "detail": detail[:500],
                      **kw})

    chosen = C.validate_op(op) if op else C.classify_request(request)
    if chosen == C.CODE_NEEDS_PERMISSION:
        step("GUARD", C.BLOCKED, f"destructive/privileged request refused: "
                                 f"{(request or '')[:200]}")
        return {"op": chosen, "status": C.BLOCKED, "trail": trail,
                "detail": "CODE_NEEDS_PERMISSION: explicit human approval "
                          "required; nothing was executed.",
                "requested_action": (request or "")[:500],
                "files_touched": []}
    if chosen == C.CODE_NO_ACTION:
        step("CLASSIFY", C.NOT_RUN, "no actionable coding operation")
        r = need_info(request)
        r["trail"] = trail
        return r

    # INSPECT (bounded discovery + context)
    try:
        ctx = D.discover_repo(base)
    except Exception as e:  # noqa: BLE001
        return {"op": chosen, "status": C.EXECUTED_FAIL, "trail": trail,
                "detail": f"discovery failed: {e}", "files_touched": []}
    usage["max_files_read"] += 1
    step("INSPECT", C.EXECUTED_PASS,
         f"langs={list(ctx.languages)[:4]} tests={ctx.test_framework}")

    # ---- read-only operations -------------------------------------------
    if chosen in (C.CODE_SEARCH, C.CODE_INSPECT, C.CODE_EXPLAIN):
        symbol = extract_symbol(request)
        hits = SE.search_symbol(base, symbol) if symbol else []
        usage["max_files_read"] += 1
        if chosen == C.CODE_SEARCH:
            if hits:
                step("SEARCH", C.EXECUTED_PASS, f"{len(hits)} hits")
                return {"op": chosen, "status": C.EXECUTED_PASS,
                        "trail": trail, "evidence": {"hits": hits[:20]},
                        "detail": f"found {len(hits)} evidence-backed hits",
                        "files_touched": []}
            step("SEARCH", C.EXECUTED_FAIL, "no evidence; symbol not claimed")
            return {"op": chosen, "status": C.EXECUTED_FAIL, "trail": trail,
                    "evidence": {"hits": []},
                    "detail": f"no repository evidence for `{symbol}`",
                    "files_touched": []}
        # EXPLAIN / INSPECT: extractive summary from evidence (honest label)
        if not hits and chosen == C.CODE_EXPLAIN:
            step("EXPLAIN", C.EXECUTED_FAIL, "no evidence for explanation")
            return {"op": chosen, "status": C.EXECUTED_FAIL, "trail": trail,
                    "evidence": {},
                    "detail": "cannot explain: symbol has no repository "
                              "evidence; nothing invented.",
                    "files_touched": []}
        prose = _extractive_explain(symbol, hits)
        if generate is not None and chosen == C.CODE_EXPLAIN and hits:
            try:
                usage["max_commands"] += 1
                gen = generate(
                    f"Explain this code briefly. Definition: {hits[0]['text']} "
                    f"at {hits[0]['file']}:{hits[0]['line']}. "
                    f"Other locations: {len(hits) - 1}. One paragraph.")[:800]
                if gen.strip():
                    prose = f"[model-assisted] {gen.strip()}"
            except Exception:  # noqa: BLE001 — fall back to extractive
                pass
        step("RESPOND", C.EXECUTED_PASS, prose[:200])
        return {"op": chosen, "status": C.EXECUTED_PASS, "trail": trail,
                "evidence": {"hits": hits[:10]}, "detail": prose,
                "files_touched": []}

    if chosen == C.CODE_PLAN:
        plan = P.make_plan(request, files_to_inspect=list(ctx.candidate_files[:10]),
                           tests_to_run=list(tests_to_run or []),
                           risk_level="MEDIUM" if edits else "LOW",
                           expected_behavior_change="as requested; no hidden changes",
                           rollback_condition=_ROLLBACK)
        ok, problems = P.plan_valid(plan)
        step("PLAN", C.EXECUTED_PASS if ok else C.EXECUTED_FAIL, str(problems))
        return {"op": chosen, "status": C.EXECUTED_PASS if ok else C.EXECUTED_FAIL,
                "trail": trail, "evidence": {"plan": plan},
                "detail": "plan generated" if ok else f"plan invalid: {problems}",
                "files_touched": []}

    if chosen == C.CODE_REVIEW:
        st = git_readonly(base, ["diff", "--", "."])
        usage["max_commands"] += 1
        if not st["executed"]:
            return {"op": chosen, "status": C.EXECUTED_FAIL, "trail": trail,
                    "detail": st.get("reason", ""), "files_touched": []}
        rep = R.code_review(st["output"])
        step("REVIEW", C.EXECUTED_PASS, f"verdict={rep['verdict']}")
        return {"op": chosen, "status": C.EXECUTED_PASS, "trail": trail,
                "evidence": rep, "detail": f"verdict: {rep['verdict']}",
                "files_touched": []}

    # ---- mutating operations (EDIT / DEBUG / TEST / BUILD) ---------------
    if chosen == C.CODE_TEST and not edits:
        targets = list(tests_to_run or ["tests"])
        usage["max_commands"] += 1
        res = T.run_pytest_targets(base, targets)
        step("TEST", C.EXECUTED_PASS if res["executed"] and
             res["exit_code"] == 0 else C.EXECUTED_FAIL,
             f"passed={res['passed']} failed={res['failed']}")
        if not res["executed"]:
            return {"op": chosen, "status": C.NOT_RUN, "trail": trail,
                    "evidence": res, "detail": "tests did not execute",
                    "files_touched": []}
        status = C.EXECUTED_PASS if res["exit_code"] == 0 else C.EXECUTED_FAIL
        return {"op": chosen, "status": status, "trail": trail,
                "evidence": res,
                "detail": f"pytest exit={res['exit_code']} "
                          f"passed={res['passed']} failed={res['failed']}",
                "files_touched": []}

    # PLAN is mandatory before any mutation (T15.6)
    files_to_modify = sorted({e.get("file", "") for e in (edits or [])})
    plan = P.make_plan(
        request, files_to_inspect=list(ctx.candidate_files[:10]),
        candidate_files_to_modify=files_to_modify,
        tests_to_run=list(tests_to_run or []),
        risk_level="MEDIUM" if len(files_to_modify) <= 1 else "HIGH",
        expected_behavior_change="requested behavior only; unrelated diff must be 0",
        rollback_condition=_ROLLBACK)
    ok_plan, problems = P.plan_valid(plan)
    step("PLAN", C.PLANNED if ok_plan else C.EXECUTED_FAIL, str(problems))
    if not ok_plan:
        return {"op": chosen, "status": C.EXECUTED_FAIL, "trail": trail,
                "evidence": {"plan": plan, "problems": problems},
                "detail": f"plan invalid: {problems}", "files_touched": []}

    ctx_files = list(context_files or [])
    if not ctx_files:
        src_dir = base / "src"
        if src_dir.is_dir():
            ctx_files = [p.relative_to(base).as_posix()
                         for p in sorted(src_dir.glob("*.py"))
                         if p.name != "__init__.py"][:8]
    if TC.test_repair_intent(request):
        tdir = base / "tests"
        if tdir.is_dir():
            tfiles = [p.relative_to(base).as_posix()
                      for p in sorted(tdir.glob("test_*.py"))[:8]]
            ctx_files = tfiles + [f for f in ctx_files if f not in tfiles]
    dep_map = None
    if MF.is_multi_file_task(request, ctx_files):
        src_involved = [f for f in ctx_files
                        if "test" not in f.replace("\\", "/").lower()
                        and f.endswith(".py")]
        dep_map = MF.map_dependencies(base, src_involved)
        step("DEP_MAP", C.PLANNED, MF.format_dep_map(dep_map)[:240])
    src0 = _read_blob(base, ctx_files[0], 2000) if ctx_files else ""
    tst0 = TC.load_related_tests(base, tests_to_run)
    contract = None
    if TC.looks_like_data_xform(request):
        contract = TC.data_xform_contract(
            request, src_text=src0, test_text=tst0)
        step("CONTRACT", C.PLANNED, "data_xform")
    elif TC.looks_like_algo(request):
        contract = TC.algo_contract(request, src_text=src0, test_text=tst0)
        step("CONTRACT", C.PLANNED, "algo")

    session = RS.RepairSession(
        base,
        involved_files=list((dep_map or {}).get("files_involved") or ctx_files),
    )

    # REPRODUCE FIRST (T15.10): if the requested behavior already holds
    # (targeted tests pass before any edit), report NO_CHANGE_REQUIRED and
    # touch nothing. This is how already-correct tasks terminate honestly.
    repro_targets = list(tests_to_run or [])
    if not repro_targets and (base / "tests").is_dir():
        repro_targets = ["tests"]
    pre: dict = {}
    structural = (chosen == C.CODE_EDIT and refactor_intent(request))
    if repro_targets and chosen in (C.CODE_EDIT, C.CODE_DEBUG) \
            and not structural:
        usage["max_commands"] += 1
        pre = T.run_pytest_targets(base, repro_targets)
        session.bind_original_tests(pre)
        if pre.get("executed") and pre.get("exit_code") == 0:
            step("REPRODUCE", C.EXECUTED_PASS,
                 f"tests already pass ({pre.get('passed')}); no change")
            return {"op": chosen, "status": C.EXECUTED_PASS, "trail": trail,
                    "evidence": {"plan": plan, "pre_test": pre,
                                 "verdict": "NO_CHANGE_REQUIRED"},
                    "detail": "NO_CHANGE_REQUIRED: targeted tests pass "
                              "before any edit; repository untouched.",
                    "files_touched": []}
        step("REPRODUCE", C.ATTEMPTED,
             f"bug reproduced (exit={pre.get('exit_code')}); proceeding")
    elif structural and repro_targets:
        usage["max_commands"] += 1
        pre_s = T.run_pytest_targets(base, repro_targets)
        session.bind_original_tests(pre_s)

    # Acquire explicit edits: caller-supplied, or model-proposed structured
    # patch. Never invent code when neither exists.
    pending = list(edits or [])
    if not pending and generate is not None and chosen in (
            C.CODE_EDIT, C.CODE_DEBUG):
        try:
            usage["max_commands"] += 1
            usage["max_files_read"] += min(3, len(ctx_files) or 1)
            prompt = _prompt_context(
                base, request, context_files=ctx_files,
                tests_to_run=tests_to_run, dep_map=dep_map,
                contract=contract)
            raw = generate(prompt)[:4000]
            pending = parse_patch_proposal(base, raw)
            if pending:
                step("PROPOSE", C.ATTEMPTED, f"{len(pending)} model edits")
            else:
                step("PROPOSE", C.EXECUTED_FAIL, "malformed patch proposal")
        except Exception as e:  # noqa: BLE001
            step("PROPOSE", C.EXECUTED_FAIL, f"no parseable patch: {e}")
    if pending and dep_map:
        missing = MF.missing_coupled_files(pending, dep_map)
        if missing and generate is not None:
            usage["max_commands"] += 1
            extra_prompt = (
                _prompt_context(
                    base, request, context_files=ctx_files,
                    tests_to_run=tests_to_run, dep_map=dep_map,
                    contract=contract)
                + "\nThe previous proposal omitted coupled files: "
                + ", ".join(missing)
                + ". Return ONE JSON list covering ALL involved files.")
            raw2 = generate(extra_prompt)[:4000]
            extra = parse_patch_proposal(base, raw2)
            if extra:
                seen = {e.get("file") for e in pending}
                for e in extra:
                    if e.get("file") not in seen:
                        pending.append(e)
                        seen.add(e.get("file"))
                step("PROPOSE", C.ATTEMPTED,
                     f"atomic coupled edits now {len(pending)} files")
    if not pending:
        # Bare DEBUG entry: no initial patch, but live failure evidence
        # exists (reproduce-first failed) — the bounded debug loop may
        # still recover via evidence-triggered auto-repair. Anything
        # else stops here rather than inventing code.
        if (chosen == C.CODE_DEBUG and pre.get("executed")
                and pre.get("exit_code") != 0):
            step("EDIT", C.NOT_RUN,
                 "no initial patch; entering debug loop on live evidence")
            touched, diffs = [], []
            targets = list(repro_targets)
            res = pre
        else:
            step("EDIT", C.BLOCKED,
                 "no implementation source; code not invented")
            return {"op": chosen, "status": C.BLOCKED, "trail": trail,
                    "evidence": {"plan": plan},
                    "detail": "BLOCKED: no explicit edits and no verifiable "
                              "patch proposal; refusing to invent code.",
                    "files_touched": []}
    else:
        touched = []
        diffs = []
    full_diff = ""
    if pending:
        lines_added = lines_removed = 0
        for e in pending:
            if usage["max_files_modified"] >= lim["max_files_modified"]:
                step("EDIT", C.BLOCKED, "file-modification budget exhausted")
                break
            ok_c, violated = L.check_limits(
                {"max_files_modified": usage["max_files_modified"]}, lim)
            if not ok_c:
                step("EDIT", C.BLOCKED, f"limits: {violated}")
                break
            if e.get("create"):
                res = E.create_file(base, e.get("file", ""),
                                    e.get("new", ""),
                                    task_allows=task_allows)
            else:
                res = E.apply_edit(base, e.get("file", ""),
                                   e.get("old", ""), e.get("new", ""),
                                   task_allows=task_allows)
            if not res.get("ok"):
                step("EDIT", C.EXECUTED_FAIL, res.get("error", "")[:200])
                session.restore_original()
                return {"op": chosen, "status": C.EXECUTED_FAIL,
                        "trail": trail,
                        "evidence": {"plan": plan, "edit_error": res,
                                     "repair_session": session.export()},
                        "detail": f"edit failed: {res.get('error')}",
                        "files_touched": []}
            touched.append(res["file"])
            diffs.append(res["diff"])
            lines_added += res["lines_added"]
            lines_removed += res["lines_removed"]
            usage["max_files_modified"] += 1
        step("EDIT", C.ATTEMPTED,
             f"{len(touched)} files +{lines_added}/-{lines_removed}")

        # Syntax check every touched file (T15.8 step 1)
        for rel in touched:
            text = (base / rel).read_text(encoding="utf-8")
            ok_s, err = E.syntax_ok(rel, text)
            if not ok_s:
                step("VALIDATE", C.EXECUTED_FAIL, err)
                session.restore_original()
                return {"op": chosen, "status": C.EXECUTED_FAIL,
                        "trail": trail,
                        "evidence": {"plan": plan,
                                     "repair_session": session.export()},
                        "detail": f"syntax: {err}",
                        "files_touched": []}

        # Diff review: FAIL CLOSED (T15.27)
        full_diff = "\n".join(diffs)
        drev = R.diff_review(full_diff, task_allows=task_allows)
        if not drev["ok"]:
            step("DIFF_REVIEW", C.EXECUTED_FAIL, str(drev["problems"]))
            weakening = any("weakening" in str(p).lower() or "test" in str(p).lower()
                            for p in drev["problems"])
            prot = any("protected" in str(p).lower()
                       for p in drev["problems"])
            cand = session.capture_candidate(
                {"executed": False, "exit_code": None, "failed": 0,
                 "output": ""},
                safety_status=RS.UNSAFE, compile_ok=True,
                protected_component_status=(
                    RS.VIOLATION if prot else RS.OK),
                test_weakening=weakening)
            session.consider(cand)
            session.restore_original()
            return {"op": chosen, "status": C.EXECUTED_FAIL, "trail": trail,
                    "evidence": {"plan": plan,
                                 "diff_problems": drev["problems"],
                                 "repair_session": session.export()},
                    "detail": f"diff review failed: {drev['problems']}",
                    "files_touched": []}
        step("DIFF_REVIEW", C.ATTEMPTED, f"{len(drev['files'])} files clean")

        # Targeted tests first (T15.9)
        targets = list(tests_to_run or []) or T.related_tests_for(base, touched) \
            or (["tests"] if (base / "tests").is_dir() else [])
        usage["max_commands"] += 1
        res = T.run_pytest_targets(base, targets, touch_files=touched)
        if not res["executed"]:
            step("TEST", C.NOT_RUN, "pytest did not execute")
            session.restore_original()
            return {"op": chosen, "status": C.NOT_RUN, "trail": trail,
                    "evidence": {"plan": plan, "test": res,
                                 "repair_session": session.export()},
                    "detail": "tests NOT_RUN — never labeled PASS",
                    "files_touched": []}
        cand0 = session.capture_candidate(res)
        decision0 = session.consider(cand0)
        step("BEST_STATE", C.ATTEMPTED,
             f"best={decision0['best_state_id']} progressed="
             f"{decision0['progressed']}")
        if res["exit_code"] == 0:
            rev = R.code_review(full_diff, changed_files=touched)
            step("REVIEW", C.EXECUTED_PASS, f"verdict={rev['verdict']}")
            return {"op": chosen, "status": C.EXECUTED_PASS, "trail": trail,
                    "evidence": {"plan": plan, "test": res, "review": rev,
                                 "repair_session": session.export()},
                    "detail": f"patch verified: exit=0 passed={res['passed']}",
                    "files_touched": touched}

    # ---- bounded debug loop (T15R): repair FROM BEST_VERIFIED_STATE --------
    step("DIAGNOSE", C.ATTEMPTED, _diagnose(res))
    ignored_feedback = None
    if external_feedback and "DIAGNOSE" not in str(external_feedback):
        ignored_feedback = (external_feedback or "")[:200]
        step("FEEDBACK", C.NOT_RUN,
             "generic feedback ignored: no failing-test evidence")
    diagnosis = _diagnose(res)
    repaired = bool(res.get("executed") and res.get("exit_code") == 0)
    hard = int(lim.get("max_repair_iterations_hard_cap",
                       RS.HARD_CAP_REPAIR_ROUNDS))
    default_r = int(lim.get("max_repair_iterations",
                            RS.DEFAULT_REPAIR_ROUNDS))
    queue = list(repair_candidates or [])[:hard]
    if diagnosis.split(":")[0] in ("MISSING_IMPORT", "UNDEFINED_NAME"):
        queue = [{"auto": True, "fixes": diagnosis}] + queue
        queue = queue[:hard]

    def _budget_left() -> bool:
        return RS.continue_repair(
            usage["max_repair_iterations"],
            last_progress=session.last_progress,
            default_rounds=default_r, hard_cap=hard)

    def _record_attempt(test_res: dict, **flags) -> dict:
        cand = session.capture_candidate(test_res, **flags)
        dec = session.consider(cand)
        step("BEST_STATE", C.ATTEMPTED,
             f"best={dec['best_state_id']} progressed={dec['progressed']} "
             f"net={dec['delta'].get('net_change')}")
        return dec

    for rnd, cand in enumerate(queue, start=1):
        if not _budget_left():
            step("REPAIR", C.BLOCKED, "repair budget exhausted")
            break
        usage["max_repair_iterations"] += 1
        ok_c, _ = L.check_limits(
            {"max_repair_iterations": usage["max_repair_iterations"]},
            {**lim, "max_repair_iterations": hard})
        if not ok_c:
            step("REPAIR", C.BLOCKED, "repair budget exhausted")
            break
        if cand.get("fixes") and cand["fixes"] not in (diagnosis, "ANY"):
            step("REPAIR", C.NOT_RUN,
                 f"round {rnd}: candidate fixes {cand.get('fixes')} "
                 f"!= diagnosis {diagnosis}; skipped")
            continue
        if cand.get("auto"):
            r2 = auto_repair(base, diagnosis, res.get("output", ""),
                             repair_file=repair_file)
            if r2 is None:
                step("REPAIR", C.NOT_RUN,
                     f"round {rnd}: no evidence-backed auto-repair for "
                     f"{diagnosis}")
                continue
            step("REPAIR", C.ATTEMPTED,
                 f"round {rnd}: auto {r2.get('auto')} -> {r2.get('file')}")
        else:
            r2 = E.apply_edit(base, cand.get("file", ""), cand.get("old", ""),
                              cand.get("new", ""), task_allows=task_allows)
            if not r2.get("ok"):
                step("REPAIR", C.EXECUTED_FAIL, r2.get("error", "")[:200])
                session.restore_best()
                continue
        if r2.get("diff"):
            diffs.append(r2["diff"])
        if r2["file"] not in touched:
            touched.append(r2["file"])
        usage["max_commands"] += 1
        res2 = T.run_pytest_targets(base, targets, touch_files=touched)
        step("RETEST", C.EXECUTED_PASS if res2.get("exit_code") == 0
             else C.EXECUTED_FAIL,
             f"round {rnd}: exit={res2.get('exit_code')}")
        res = res2
        diagnosis = _diagnose(res)
        _record_attempt(res2)
        if res2.get("executed") and res2.get("exit_code") == 0:
            repaired = True
            break
        # keep CURRENT for chained repair_candidates; BEST is tracked

    while (not repaired and generate is not None and _budget_left()):
        usage["max_repair_iterations"] += 1
        rnd = usage["max_repair_iterations"]
        try:
            # T15R.5 — model repairs start from BEST_VERIFIED_STATE
            session.restore_best()
            usage["max_commands"] += 1
            delta = (session.deltas[-1] if session.deltas else
                     RS.failure_delta(session.best.failure_ids,
                                      session.best.failure_ids))
            prompt = _prompt_context(
                base, request, context_files=ctx_files or touched,
                tests_to_run=tests_to_run, dep_map=dep_map,
                contract=contract, diagnosis=diagnosis, delta=delta,
                remaining=session.best.failure_ids,
                test_output=res.get("output", ""))
            raw = generate(prompt)[:4000]
            cand = parse_patch_proposal(base, raw)
            if not cand:
                step("REPAIR", C.EXECUTED_FAIL,
                     f"round {rnd}: malformed model re-proposal")
                break
            step("REPAIR", C.ATTEMPTED,
                 f"round {rnd}: model re-proposal ({len(cand)} edits) "
                 f"from best={session.best.state_id}")
            applied_all = True
            for e in cand:
                if e.get("create"):
                    r3 = E.create_file(base, e.get("file", ""),
                                       e.get("new", ""),
                                       task_allows=task_allows)
                else:
                    r3 = E.apply_edit(base, e.get("file", ""),
                                      e.get("old", ""), e.get("new", ""),
                                      task_allows=task_allows)
                if not r3.get("ok"):
                    step("REPAIR", C.EXECUTED_FAIL,
                         f"round {rnd}: {r3.get('error', '')[:150]}")
                    applied_all = False
                    weakening = "weakening" in str(r3.get("error", "")).lower()
                    prot = "protected" in str(r3.get("error", "")).lower()
                    _record_attempt(
                        {"executed": False, "exit_code": None, "failed": 0,
                         "output": ""},
                        safety_status=RS.UNSAFE if (weakening or prot) else RS.OK,
                        test_weakening=weakening,
                        protected_component_status=(
                            RS.VIOLATION if prot else RS.OK),
                        compile_ok=False)
                    session.restore_best()
                    break
                if r3.get("diff"):
                    diffs.append(r3["diff"])
                if r3["file"] not in touched:
                    touched.append(r3["file"])
            if not applied_all:
                continue
            usage["max_commands"] += 1
            res2 = T.run_pytest_targets(base, targets, touch_files=touched)
            step("RETEST", C.EXECUTED_PASS if res2.get("exit_code") == 0
                 else C.EXECUTED_FAIL,
                 f"round {rnd}: exit={res2.get('exit_code')}")
            res = res2
            diagnosis = _diagnose(res)
            _record_attempt(res2)
            if res2.get("executed") and res2.get("exit_code") == 0:
                repaired = True
                break
        except Exception as e:  # noqa: BLE001
            step("REPAIR", C.EXECUTED_FAIL, f"re-proposal failed: {e}")
            session.restore_best()
            break

    fin = session.finalize()
    touched = list(fin["files_touched"])
    res = session.best.test_result or res
    repaired = bool(session.best.targeted_tests_passed)
    status = C.EXECUTED_PASS if repaired else (
        C.EXECUTED_FAIL if usage["max_repair_iterations"] >= default_r
        else C.BLOCKED)
    if status == C.EXECUTED_PASS and repaired:
        drev2 = R.diff_review("\n".join(diffs) or session.best.patch_text,
                              task_allows=task_allows)
        if not drev2["ok"]:
            step("DIFF_REVIEW", C.EXECUTED_FAIL, str(drev2["problems"]))
            session.restore_original()
            return {"op": chosen, "status": C.EXECUTED_FAIL, "trail": trail,
                    "evidence": {"plan": plan, "test": res,
                                 "diagnosis": diagnosis,
                                 "diff_problems": drev2["problems"],
                                 "ignored_feedback": ignored_feedback,
                                 "repair_session": session.export()},
                    "detail": f"repaired tests pass but diff review failed: "
                              f"{drev2['problems']}",
                    "files_touched": []}
        step("DIFF_REVIEW", C.EXECUTED_PASS, "repaired diff clean")
    if repaired:
        detail = "repaired and verified"
    elif fin["best_retained"]:
        detail = ("partial progress retained in BEST_VERIFIED_STATE; "
                  "targeted tests still failing")
        status = C.BLOCKED
    elif status == C.BLOCKED:
        detail = "repair budget exhausted; BLOCKED"
    else:
        detail = "tests still failing after bounded repair"
    if ignored_feedback:
        detail += "; generic external feedback was ignored (no evidence)"
    if time.time() - t0 > lim["max_execution_seconds"]:
        status = C.BLOCKED
        detail += "; execution time budget exceeded"
    return {"op": chosen, "status": status, "trail": trail,
            "evidence": {"plan": plan, "test": res,
                         "diagnosis": diagnosis,
                         "ignored_feedback": ignored_feedback,
                         "repair_session": session.export(),
                         "failure_delta": (session.deltas[-1]
                                           if session.deltas else None)},
            "detail": detail, "files_touched": touched}
