"""scicomp ode_intent — T14R2 deterministic ODE initial-value operation
selection and request construction.

T14R forensics showed the dominant remaining numeric bottleneck is the
planner selecting the WRONG OPERATION for ODE initial-value problems
(6 of 25 incorrect numeric rows in the frozen recheck: IVPs routed to
``definite_integral`` / ``minimize`` instead of ``solve_ode`` — the
engine then faithfully computes the accumulated change, not the
solution y(t), and the now-disciplined adopter adopts the verified-but-
wrong-quantity value).

This module is the T14R2 primary-editable component: a DETERMINISTIC
planner layer that

1. recognizes an initial-value problem from the question text when ALL
   required IVP information is present (differential equation /
   derivative rule, dependent state variable(s), initial condition(s),
   integration time, requested numerical outcome) — T14R2.4;
2. separates ODE_IVP from other operations (integration, root finding,
   optimization, sweeps, algebraic equations, boundary-value problems)
   by structure, not keywords — T14R2.5;
3. validates every required solve_ode request field before invocation;
   null, missing, and zero remain distinct — T14R2.6;
4. maps validated intent + schema to the solve_ode operation
   deterministically (the LLM may extract content; this layer decides
   the operation) — T14R2.7;
5. never invents a scientific value: every emitted value is
   USER_GIVEN (verbatim in the question), DETERMINISTIC_DERIVATION
   (AST-verified rename / literal evaluation / stated rate law), or
   refused — never MODEL_INVENTED — T14R2.8;
6. preserves explicit state ordering for multi-state systems and fails
   closed on length/dimensionality/ordering ambiguity — T14R2.9;
7. supports second-order scalar equations ONLY through deterministic
   first-order-system conversion (y0 = x, y1 = dx/dt), which the frozen
   engine natively executes; anything beyond that shape is refused —
   T14R2.10.

Fail-closed: when recognition is incomplete or ambiguous the layer
returns None and the existing planner path (including its fail-closed
gates) is followed unchanged. Nothing here touches the frozen necessity
router, fidelity rules, engine, adopter, or rounding policy.
"""
from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import dataclass, field as dc_field

# NOTE: planner_repair._eval_scalar_literal is FROZEN and accepts only
# bare numeric constants (its AST whitelist rejects the operator and
# Load nodes ast.walk yields, so "pi/2" -> None). The layer therefore
# evaluates non-trivial time literals with its own equally-bounded
# evaluator below — inside the T14R2 primary-editable area, same
# restriction class (numbers, + - * / ** ( ), pi, e, tau), never a
# model-invented value.

# --------------------------------------------------------------------------
# question-shape patterns (deterministic; every match is re-verified by
# AST before anything is constructed)
# --------------------------------------------------------------------------
# dX/dt = RHS   (first order). X is a single dependent-variable name.
_ODE1_EQ_RE = re.compile(r"\bd([A-Za-z][A-Za-z_0-9]*)\s*/\s*dt\s*=")
# d2X/dt2 = RHS (second order, x''-style notation)
_ODE2_EQ_RE = re.compile(r"\bd2([A-Za-z][A-Za-z_0-9]*)\s*/\s*dt2\s*=")
# X(t0) = value initial condition; the lookbehind refuses names that are
# part of derivative notation (dx/dt(0) would otherwise match "dt(0)").
_IC_RE = re.compile(
    r"(?<![A-Za-z0-9_/])([A-Za-z][A-Za-z_0-9]*)\s*\(\s*"
    r"([-+]?\d+(?:\.\d+)?)\s*\)\s*=\s*"
    r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")
# dX/dt(t0) = value  (initial condition on the first derivative)
_DIC_RE = re.compile(
    r"\bd([A-Za-z][A-Za-z_0-9]*)\s*/\s*dt\s*\(\s*"
    r"([-+]?\d+(?:\.\d+)?)\s*\)\s*=\s*"
    r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")
# X'(t0) = value
_PRIME_IC_RE = re.compile(
    r"\b([A-Za-z][A-Za-z_0-9]*)\s*'\s*\(\s*([-+]?\d+(?:\.\d+)?)\s*\)"
    r"\s*=\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")

_NUM_TOKEN = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
_EVAL_TOKEN = r"[-+]?[A-Za-z0-9_./()*]+"
# evaluation time, most specific pattern first
_EVAL_TIME_RES = [
    re.compile(rf"\bat\s+t\s*=\s*({_EVAL_TOKEN})"),
    re.compile(rf"\bup\s+to\s+t\s*=\s*({_EVAL_TOKEN})"),
    re.compile(rf"\bto\s+t\s*=\s*({_EVAL_TOKEN})"),
    re.compile(rf"\bafter\s+({_NUM_TOKEN})\s*"
               r"(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?|"
               r"s\b|min\b|h\b|yrs?\b)", re.I),
]

# verbal first-order rate laws (only when no derivative notation exists)
_VERBAL_DECAY_RE = re.compile(
    r"\b(decays?|decayed|decaying|radioactive|discharges?|discharging)\b",
    re.I)
_VERBAL_GROWTH_RE = re.compile(r"\b(grows?|growth)\b", re.I)
_VERBAL_RATE_RE = re.compile(
    rf"\brate\s+(?:constant|coefficient)\s*(?:of|is)?\s*({_NUM_TOKEN})",
    re.I)
_VERBAL_START_RE = re.compile(
    rf"\b(?:starting\s+from|starts?\s+(?:from|at)|initially|"
    r"initial\s+(?:amount|mass|population|concentration)\s+(?:of)?)\s+"
    rf"({_NUM_TOKEN})", re.I)
_VERBAL_SPAN_RE = re.compile(
    rf"\bafter\s+({_NUM_TOKEN})\s*"
    r"(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\b", re.I)

# cut the right-hand side at paren-depth-0 stop tokens
_STOP_TOKENS = (" with ", " where ", " and ", " when ", " given ",
                " for ", " so ", " then ", ";", ",")
_FORMULA_MAX = 400


@dataclass
class OdeIvp:
    """A deterministically validated initial-value problem."""

    order: int                                   # 1 or 2
    dep_vars: list[str]                          # appearance order
    equations_src: list[str]                     # RHS as the question writes it
    equations: list[str]                         # RHS in y0..y{n-1} form
    initial_state: list[float]
    t_start: float
    t_start_provenance: str                      # USER_GIVEN | DETERMINISTIC_DERIVATION
    t_end: float
    t_end_provenance: str
    parameters: dict[str, float] = dc_field(default_factory=dict)
    source_kind: str = "derivative_notation"     # | verbal_rate_law
    rate_law_note: str | None = None

    @property
    def n(self) -> int:
        return len(self.equations)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _free_names(expr: str) -> set[str] | None:
    """Non-function identifiers of an expression (None when it does not
    parse). Constants (pi, e, tau) are INCLUDED: a question may declare
    one as a parameter (e.g. 'tau = 0.5'), and undeclared ones stay
    sandbox math constants handled by the frozen engine."""
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    from sciencemath.scicomp.sandbox import _ALLOWED_FUNC_NAMES
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in _ALLOWED_FUNC_NAMES:
            names.add(node.id)
    return names


def _rename(expr: str, mapping: dict[str, str]) -> str | None:
    """AST-verified alpha-rename (word-boundary, never a call target).
    None only when parsing fails or the rewrite is not shape-equal."""
    out = expr
    for old, new in mapping.items():
        out = re.sub(r"\b" + re.escape(old) + r"\b(?!\s*\()", new, out)
    try:
        a = ast.parse(expr, mode="eval")
        b = ast.parse(out, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    dump_b = ast.dump(b)
    for old, new in mapping.items():
        dump_b = dump_b.replace(f"Name(id='{new}'", f"Name(id='{old}'")
    if ast.dump(a) != dump_b:
        return None
    return out


def _cut_rhs(text: str, start: int) -> str:
    """Scan from `start` and cut the RHS at the first paren-depth-0 stop
    token (so '(T - 20) with ...' keeps its parentheses intact)."""
    depth = 0
    i = start
    low = text.lower()
    while i < len(text):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0:
            if c == ";" or c == ",":
                return text[start:i].strip()
            if c == "." and (i + 1 == len(text) or text[i + 1] == " "):
                return text[start:i].strip()
            if c == " ":
                for tok in _STOP_TOKENS:
                    if low.startswith(tok, i):
                        return text[start:i].strip()
        i += 1
    return text[start:].strip()


_EVAL_CONST_NAMES = {"pi": math.pi, "e": math.e, "tau": math.tau}
_EVAL_NODE_TYPES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Load,
                    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
                    ast.FloorDiv, ast.Mod, ast.USub, ast.UAdd)


def _eval_literal(text: str) -> float | None:
    """Bounded deterministic scalar-literal evaluation: numbers,
    ``+ - * / // % ** ( )``, and the constants pi, e, tau. Returns None
    when the expression is not safely derivable (fail-closed)."""
    if not text or len(text) > 64:
        return None
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, _EVAL_NODE_TYPES):
            continue
        if isinstance(node, ast.Constant) \
                and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.Name) \
                and node.id in _EVAL_CONST_NAMES:
            continue
        return None
    try:
        result = eval(compile(tree, "<literal>", "eval"),  # noqa: S307
                      {"__builtins__": {}}, dict(_EVAL_CONST_NAMES))
    except Exception:
        return None
    if isinstance(result, (int, float)) and math.isfinite(result) \
            and not isinstance(result, bool):
        return float(result)
    return None


def _eval_time_token(token: str) -> tuple[float | None, str]:
    """Deterministically evaluate an evaluation-time token. Returns
    (value, provenance); (None, ...) when not determinable. A single
    trailing '.' is sentence punctuation in prose ("at t = 5.") and is
    stripped before classification."""
    t = token.strip()
    if t.endswith("."):
        t = t[:-1]
    if re.fullmatch(_NUM_TOKEN, t):
        return float(t), "USER_GIVEN"
    val = _eval_literal(t)
    if val is not None:
        return val, "DETERMINISTIC_DERIVATION"
    return None, "refused"


def _declared_parameter(name: str, question: str) -> float | None:
    m = re.search(rf"\b{re.escape(name)}\s*=\s*({_NUM_TOKEN})", question)
    if m:
        try:
            v = float(m.group(1))
        except ValueError:  # pragma: no cover
            return None
        if math.isfinite(v):
            return v
    return None


def _num(v: float) -> str:
    return repr(float(v))


def _eval_time_from_question(q: str, dep_vars: set[str]) \
        -> tuple[float | None, str]:
    """Evaluation time by pattern priority; bare 't = number' is used
    only when no more specific pattern matched (and never for the IC
    point, which the caller rejects separately)."""
    for rx in _EVAL_TIME_RES:
        m = rx.search(q)
        if m is None:
            continue
        val, prov = _eval_time_token(m.group(1))
        if val is not None:
            return val, prov
    for m in re.finditer(rf"\bt\s*=\s*({_NUM_TOKEN})", q):
        val, prov = _eval_time_token(m.group(1))
        return val, prov
    return None, "refused"


# --------------------------------------------------------------------------
# recognition
# --------------------------------------------------------------------------
def recognize_ode_ivp(question: str) -> OdeIvp | None:
    """Deterministically recognize an initial-value problem, or None.

    Fires ONLY when the question supplies every required IVP element:
    the derivative rule (first-order dX/dt = RHS, or a guarded
    second-order d2X/dt2 = RHS with both state ICs), initial
    condition(s) at a common t0, a determinable evaluation time, and —
    for every non-interface name in a right-hand side — a declared
    value. Anything missing or ambiguous refuses (fail-closed).
    """
    q = question if isinstance(question, str) else ""
    if not q:
        return None

    ivp = _recognize_notation(q)
    if ivp is None:
        ivp = _recognize_verbal(q)
    return ivp


def _recognize_notation(q: str) -> OdeIvp | None:
    eq2 = _ODE2_EQ_RE.search(q)
    if eq2 is not None:
        return _recognize_second_order(q, eq2)
    matches = list(_ODE1_EQ_RE.finditer(q))
    if not matches:
        return None
    if len(matches) > 2:
        return None  # larger systems: out of T14R2 scope, refuse
    entries: list[tuple[str, str]] = []
    for m in matches:
        dep = m.group(1)
        rhs = _cut_rhs(q, m.end())
        if not rhs or len(rhs) > _FORMULA_MAX:
            return None
        entries.append((dep, rhs))
    deps = [d for d, _ in entries]
    if len(set(deps)) != len(deps):
        return None  # duplicate equation for one variable: ambiguous

    # initial conditions at a common t0
    ics: dict[str, tuple[float, float, str]] = {}   # var -> (t0, value, raw)
    for m in _IC_RE.finditer(q):
        var, t0, val = m.group(1), float(m.group(2)), float(m.group(3))
        prev = ics.get(var)
        if prev is not None and prev[0] != t0:
            return None  # two-point conditions: boundary-value shape
        ics[var] = (t0, val, m.group(0))
    dic = _DIC_RE.search(q)
    prime = _PRIME_IC_RE.search(q)

    order = deps  # canonical state order: first appearance (T14R2.9)
    t0_values = {ics[d][0] for d in order if d in ics}
    if dic is not None:
        t0_values.add(float(dic.group(2)))
    if prime is not None:
        t0_values.add(float(prime.group(2)))
    if len(t0_values) > 1:
        return None  # conditions at mixed times: not an IVP we bind
    t0 = t0_values.pop() if t0_values else 0.0

    declared: dict[str, float] = {}
    dep_set = set(deps)
    for dep, rhs in entries:
        free = _free_names(rhs)
        if free is None:
            return None
        # any state variable of the system may appear in any RHS;
        # everything else must be a declared parameter (never invented);
        # undeclared sandbox math constants (pi, e, tau) are engine-
        # evaluated constants, not invented parameters
        free -= dep_set
        for name in sorted(free):
            v = _declared_parameter(name, q)
            if v is None and name in ("pi", "e", "tau"):
                continue
            if v is None:
                return None  # undeclared symbol: refuse, never invent
            declared[name] = v

    mapping = {dep: f"y{i}" for i, dep in enumerate(order)}
    equations_src = [rhs for _, rhs in entries]
    equations = []
    for dep, rhs in entries:
        renamed = _rename(rhs, mapping)
        if renamed is None:
            return None
        equations.append(renamed)

    if any(d not in ics for d in order):
        return None  # a state variable without an initial condition
    initial_state = [ics[d][1] for d in order]

    eval_val, eval_prov = _eval_time_from_question(q, set(order))
    if eval_val is None:
        return None
    if eval_val == t0:
        return None  # degenerate span; the engine would reject it

    return OdeIvp(order=1, dep_vars=order, equations_src=equations_src,
                  equations=equations, initial_state=initial_state,
                  t_start=t0, t_start_provenance="USER_GIVEN",
                  t_end=eval_val, t_end_provenance=eval_prov,
                  parameters=declared)


def _recognize_second_order(q: str, eq2: re.Match) -> OdeIvp | None:
    dep = eq2.group(1)
    rhs = _cut_rhs(q, eq2.end())
    if not rhs or len(rhs) > _FORMULA_MAX:
        return None
    free = _free_names(rhs)
    if free is None:
        return None
    free.discard(dep)
    if free:
        return None  # RHS referencing other symbols: refuse
    ic = _IC_RE.search(q)
    dic = _DIC_RE.search(q)
    prime = _PRIME_IC_RE.search(q)
    deriv_ic = dic or prime
    if ic is None or deriv_ic is None:
        return None  # a second-order IVP needs BOTH state ICs
    if ic.group(1) != dep or deriv_ic.group(1) != dep:
        return None
    t0 = float(ic.group(2))
    if float(deriv_ic.group(2)) != t0:
        return None

    renamed = _rename(rhs, {dep: "y0"})
    if renamed is None:
        return None
    eval_val, eval_prov = _eval_time_from_question(q, {dep})
    if eval_val is None or eval_val == t0:
        return None
    return OdeIvp(order=2, dep_vars=[dep], equations_src=[rhs],
                  equations=["y1", renamed],
                  initial_state=[float(ic.group(3)),
                                 float(deriv_ic.group(3))],
                  t_start=t0, t_start_provenance="USER_GIVEN",
                  t_end=eval_val, t_end_provenance=eval_prov)


def _recognize_verbal(q: str) -> OdeIvp | None:
    """Verbal linear rate law ("decays with rate constant 0.02 per
    year. Starting from 10 grams, ... after 100 years"). Fires only on
    the full conservative pattern: rate keyword + rate constant +
    starting amount + after-span. No parameter invention."""
    decay = _VERBAL_DECAY_RE.search(q) is not None
    growth = _VERBAL_GROWTH_RE.search(q) is not None
    if decay == growth:  # neither, or both: refuse
        return None
    rate = _VERBAL_RATE_RE.search(q)
    start = _VERBAL_START_RE.search(q)
    span = _VERBAL_SPAN_RE.search(q)
    if not (rate and start and span):
        return None
    try:
        k = float(rate.group(1))
        y_init = float(start.group(1))
        t_end = float(span.group(1))
    except ValueError:  # pragma: no cover
        return None
    if not all(math.isfinite(v) for v in (k, y_init, t_end)) or t_end <= 0:
        return None
    sign = "-" if decay else ""
    return OdeIvp(order=1, dep_vars=[], equations_src=[f"{_num(k)} * y0"],
                  equations=[f"{sign}{_num(k)}*y0"],
                  initial_state=[y_init], t_start=0.0,
                  t_start_provenance="DETERMINISTIC_DERIVATION",
                  t_end=t_end, t_end_provenance="USER_GIVEN",
                  source_kind="verbal_rate_law",
                  rate_law_note=("linear first-order rate law from the "
                                 "stated rate constant; sign fixed by "
                                 "the decay/growth wording"))


# --------------------------------------------------------------------------
# request construction
# --------------------------------------------------------------------------
def construct_solve_ode_request(ivp: OdeIvp, question: str) -> dict:
    """Build a complete, schema-valid solve_ode planner request.

    Every value is USER_GIVEN (verbatim in the question) or
    DETERMINISTIC_DERIVATION (AST-verified rename, literal evaluation,
    or the stated verbal rate law). Nothing is MODEL_INVENTED. The
    source_inputs mirror the parameters field-for-field (same keys,
    same values), which the frozen fidelity gate verifies by identity.
    """
    parameters: dict = {
        "equations": list(ivp.equations),
        "initial_state": list(ivp.initial_state),
        "t_start": ivp.t_start,
        "t_end": ivp.t_end,
    }
    if ivp.parameters:
        parameters["parameters"] = dict(ivp.parameters)

    provenance: dict = {
        "equations": "DETERMINISTIC_DERIVATION",
        "initial_state": "USER_GIVEN",
        "t_start": ivp.t_start_provenance,
        "t_end": ivp.t_end_provenance,
    }
    if ivp.parameters:
        provenance["parameters"] = "USER_GIVEN"

    n = ivp.n
    shape = "scalar" if n == 1 else "vector"
    names = ", ".join(ivp.dep_vars) if ivp.dep_vars else "the state"
    if ivp.order == 1:
        reason = (
            f"Initial-value problem: integrate the given derivative rule "
            f"for {names} from the stated initial condition(s) to the "
            f"requested evaluation time; solve_ode is the deterministic "
            f"operation for an initial-value problem.")
    else:
        reason = (
            f"Second-order initial-value problem converted deterministically "
            f"to a first-order system (y0={ivp.dep_vars[0]}, "
            f"y1=d{ivp.dep_vars[0]}/dt) as the frozen engine natively "
            f"supports; solve_ode is the deterministic operation.")

    return {
        "operation": "solve_ode",
        "compute_required": True,
        "parameters": parameters,
        "source_inputs": json.loads(json.dumps(parameters)),
        "parameter_provenance": provenance,
        "expected_result_type": shape,
        "reason_for_compute": reason,
        "preserve_verbatim": ["initial_state", "t_start", "t_end"],
    }


# --------------------------------------------------------------------------
# pipeline entry point
# --------------------------------------------------------------------------
def select_ode_operation(request: object, question: str) -> dict | None:
    """Deterministic operation selection for recognized ODE IVPs.

    Fires when the question is a fully-specified IVP and the planner did
    NOT already produce a well-formed first-order solve_ode request:
      * a wrong operation (definite_integral, minimize, ...) — the
        T14R2 dominant failure;
      * no parseable planner request at all;
      * a second-order IVP the planner sent in a non-RHS shape —
        converted to the first-order system the frozen engine executes.

    First-order solve_ode requests are left untouched (minimal
    intervention: the existing repair + gates path already handles
    them). Returns None when the layer does not fire.
    """
    ivp = recognize_ode_ivp(question)
    if ivp is None:
        return None

    prior = None
    if isinstance(request, dict):
        prior = request.get("operation")
        if prior == "solve_ode" and ivp.order == 1:
            return None  # existing path handles it; do not perturb

    constructed = construct_solve_ode_request(ivp, question)
    if prior == "solve_ode":
        reason = "SECOND_ORDER_SYSTEM_CONVERSION"
    elif not isinstance(request, dict):
        reason = "NO_PLANNER_REQUEST"
    else:
        reason = "WRONG_OPERATION_REMAPPED"

    return {
        "request": constructed,
        "meta": {
            "fired": True,
            "reason": reason,
            "prior_operation": prior if isinstance(request, dict) else None,
            "operation": "solve_ode",
            "order": ivp.order,
            "state_count": ivp.n,
            "dep_vars": list(ivp.dep_vars),
            "source_kind": ("verbal_rate_law" if ivp.rate_law_note
                            else "derivative_notation"),
        },
    }