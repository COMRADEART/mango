"""T15.2 — strict typed CODE skill contract.

The CODE skill distinguishes (minimum):
  CODE_EXPLAIN, CODE_INSPECT, CODE_SEARCH, CODE_PLAN, CODE_EDIT, CODE_TEST,
  CODE_DEBUG, CODE_REVIEW, CODE_BUILD, CODE_NO_ACTION, CODE_NEEDS_PERMISSION.

Routing rule: never route every programming question into repository
modification. Explanations, searches, and reviews are read-only operations.

Execution truthfulness (T15.13): every operation ends in exactly one of
  PLANNED, ATTEMPTED, EXECUTED_PASS, EXECUTED_FAIL, NOT_RUN, BLOCKED.
"""
from __future__ import annotations

import re

CODE_EXPLAIN = "CODE_EXPLAIN"
CODE_INSPECT = "CODE_INSPECT"
CODE_SEARCH = "CODE_SEARCH"
CODE_PLAN = "CODE_PLAN"
CODE_EDIT = "CODE_EDIT"
CODE_TEST = "CODE_TEST"
CODE_DEBUG = "CODE_DEBUG"
CODE_REVIEW = "CODE_REVIEW"
CODE_BUILD = "CODE_BUILD"
CODE_NO_ACTION = "CODE_NO_ACTION"
CODE_NEEDS_PERMISSION = "CODE_NEEDS_PERMISSION"

CODE_OPS = (
    CODE_EXPLAIN, CODE_INSPECT, CODE_SEARCH, CODE_PLAN, CODE_EDIT,
    CODE_TEST, CODE_DEBUG, CODE_REVIEW, CODE_BUILD, CODE_NO_ACTION,
    CODE_NEEDS_PERMISSION,
)

PLANNED = "PLANNED"
ATTEMPTED = "ATTEMPTED"
EXECUTED_PASS = "EXECUTED_PASS"
EXECUTED_FAIL = "EXECUTED_FAIL"
NOT_RUN = "NOT_RUN"
BLOCKED = "BLOCKED"

EXECUTION_STATUSES = (
    PLANNED, ATTEMPTED, EXECUTED_PASS, EXECUTED_FAIL, NOT_RUN, BLOCKED,
)

# Operations that may mutate the repository (require an explicit plan and
# patch validation). Everything else is read-only or terminal.
READ_ONLY_OPS = frozenset({
    CODE_EXPLAIN, CODE_INSPECT, CODE_SEARCH, CODE_PLAN, CODE_REVIEW,
})
MUTATING_OPS = frozenset({CODE_EDIT, CODE_TEST, CODE_DEBUG, CODE_BUILD})
TERMINAL_OPS = frozenset({CODE_NO_ACTION, CODE_NEEDS_PERMISSION})

# --- destructive / privileged request detection (T15.15) -------------------
_DESTRUCTIVE = re.compile(
    r"\b(delete (the |this )?(entire |whole )?(project|repository|repo|"
    r"database|filesystem|drive)|delete .*branch|rm\s+-rf|"
    r"remove-item|format (the |this )?.*(disk|drive)|"
    r"drop (the |this )?.*(table|database)|force[ -]?push|reset\s+--hard|"
    r"clean\s+-fdx|rewrite (the )?(git )?history|"
    r"publish (the |this )?(package|release)|"
    r"rotate .*credentials?|reveal (the |my )?(api[ _-]?key|password|token|secret)|"
    r"destroy .*data|wipe (the |this |my ).+|"
    r"run .*curl.*\|\s*(bash|sh)|download and (run|execute))\b", re.I)

# --- insufficient-context detection (T15.25) --------------------------------
# NOTE: "fix this <named thing>" names a target and must NOT be vague; only
# target-less phrasings ("fix it", "fix the thing") count as vague.
_VAGUE = re.compile(
    r"(^\s*fix\s*$|\b(fix (it|the thing|that thing)|"
    r"repair (it|that thing|this thing|the thing)|make it work|"
    r"do the (right |needed )?thing|you know what I mean|"
    r"whatever is broken|stuff)\b)", re.I)

# --- no-change detection (T15.24): requests that assert correctness --------
_NO_CHANGE_HINT = re.compile(
    r"\b(already (correct|fixed|works|working|passes)|no change needed|"
    r"verify (that |this |it )?(still |already )?(works|passes|is correct)|"
    r"confirm (that |this |it )?(still |already )?(works|passes))\b", re.I)

# --- operation classifiers (order matters: permission first, then narrow) --
_EXPLAIN = re.compile(
    r"\b(explain|what does|how does|describe|walk me through|why does)\b"
    r".*\b(function|method|class|module|code|this|that|it)\b|\b(explain this)\b",
    re.I)
_SEARCH = re.compile(
    r"\b(find|locate|where is|where are|search (for )?|who calls|"
    r"callers of|references to|grep)\b", re.I)
_REVIEW = re.compile(
    r"\b(review|audit|critique|give feedback|look over|check over)\b"
    r".*\b(pr|pull request|diff|patch|change|code)\b", re.I)
_PLAN = re.compile(
    r"\b(plan|outline|design|propose|strategy|steps to|how (should|would) "
    r"(we|you|I))\b", re.I)
_TEST = re.compile(
    r"\b(run|execute) (the )?tests?\b|\bpytest\b|\btest (this|that|the)\b", re.I)
_DEBUG = re.compile(
    r"\b(debug|diagnose|why (is|does).*(fail|error|crash|broken)|"
    r"traceback|stack trace|fix the failure)\b", re.I)
_BUILD = re.compile(
    r"\b(build|compile|package|bundle|make (the )?(binary|dist|release))\b",
    re.I)
_EDIT = re.compile(
    r"\b(fix|repair|implement|add|change|modify|update|refactor|edit|"
    r"patch|rename|remove|delete (this|that|the) (line|function|file)|"
    r"correct)\b", re.I)
_INSPECT = re.compile(
    r"\b(show|display|list|print|open|read|view|inspect|structure of|"
    r"layout of|tree of|contents of)\b", re.I)


def classify_request(text: str) -> str:
    """Map a natural-language coding request to exactly one CODE operation.

    Fail-closed: empty input -> CODE_NO_ACTION; destructive input ->
    CODE_NEEDS_PERMISSION (never silently downgraded); vague requests that
    name no target -> CODE_NO_ACTION with needs-information semantics left
    to the caller (see runner.need_info()).
    """
    q = (text or "").strip()
    if not q:
        return CODE_NO_ACTION
    if _DESTRUCTIVE.search(q):
        return CODE_NEEDS_PERMISSION
    if _NO_CHANGE_HINT.search(q):
        # "Verify X still works" is inspection, not modification.
        return CODE_INSPECT
    if _REVIEW.search(q):
        return CODE_REVIEW
    if _SEARCH.search(q):
        return CODE_SEARCH
    if _EXPLAIN.search(q):
        return CODE_EXPLAIN
    if _DEBUG.search(q):
        return CODE_DEBUG
    if _TEST.search(q):
        return CODE_TEST
    if _BUILD.search(q):
        return CODE_BUILD
    if _PLAN.search(q):
        return CODE_PLAN
    if _VAGUE.search(q):
        return CODE_NO_ACTION
    if _EDIT.search(q):
        return CODE_EDIT
    if _INSPECT.search(q):
        return CODE_INSPECT
    return CODE_NO_ACTION


def is_read_only(op: str) -> bool:
    return op in READ_ONLY_OPS


def is_mutating(op: str) -> bool:
    return op in MUTATING_OPS


def validate_op(op: str) -> str:
    if op not in CODE_OPS:
        raise ValueError(f"unknown CODE operation {op!r}")
    return op


def code_response(op: str, status: str, *, evidence=None, detail: str = "",
                  files_touched: tuple = ()) -> dict:
    """Build a contract-conformant CODE response. Status must be real."""
    validate_op(op)
    if status not in EXECUTION_STATUSES:
        raise ValueError(f"unknown execution status {status!r}")
    return {
        "op": op,
        "status": status,
        "evidence": evidence if evidence is not None else {},
        "detail": detail[:2000],
        "files_touched": list(files_touched),
    }
