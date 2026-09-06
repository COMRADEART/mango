"""Safe expression parsing: LaTeX normalization + AST whitelist gate.

Security contract (T4 requirement): **no `eval()` on untrusted
expressions**. Every expression string entering any tool passes through:

1. `normalize_input()` — deterministic text cleanup (LaTeX -> Python-ish,
   `^` -> `**`, whitespace), no parsing.
2. `lenient_expression()` — token-based implicit-multiplication insertion
   (`2x` -> `2*x`, `)(` -> `)*(`) using Python's tokenizer, so downstream
   parsing sees valid syntax.
3. `validate_ast()` — a strict whitelist over the Python AST: allowed
   operators, allowed calls (by name), allowed names, no attribute access,
   no subscripts, no strings, no lambdas, no comprehensions, bounded
   expression depth. Anything not explicitly allowed raises ToolError
   with code DISALLOWED_EXPRESSION.

Only after this gate may sympy's parse_expr touch the string, and even
then with a restricted namespace. The calculator never evals at all — it
walks the validated AST itself.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize

from sciencemath.tools.base import ToolError

MAX_AST_DEPTH = 64
# Parens do not add AST depth ("(((1)))" is Constant 1), so depth alone
# does not bound input size; cap the raw string too.
MAX_EXPRESSION_LENGTH = 10_000
# Resource caps enforced at the AST gate (BEFORE any eager evaluation):
# sympy evaluates integer arithmetic eagerly at parse time, so
# factorial(10**9) or 2**(10**8) would burn CPU for days unless rejected
# up front. These mirror the calculator's own runtime limits.
MAX_INT_LITERAL = 10**100        # no thousand-digit literals
MAX_STATIC_EXPONENT = 10_000     # integer exponent bound (calc limit)
MAX_FACTORIAL_ARG = 10**6        # factorial/binomial/gamma argument bound

# ---------------------------------------------------------------------------
# 1. Text normalization
# ---------------------------------------------------------------------------

_LATEX_REPLACEMENTS = [
    ("\\left", ""), ("\\right", ""), ("\\!", ""), ("\\,", ""), ("\\;", ""),
    ("\\cdot", "*"), ("\\times", "*"), ("\\div", "/"),
    ("\\pi", "pi"), ("\\tau", "tau"),
    ("\\$", ""), ("$", ""),
]

_LATEX_FRAC_RE = re.compile(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}")
_LATEX_SQRT_RE = re.compile(r"\\sqrt\[(\d+)\]\{([^{}]*)\}")
_LATEX_SQRT2_RE = re.compile(r"\\sqrt\{([^{}]*)\}")
_LATEX_BRACE_EXP_RE = re.compile(r"\^\{([^{}]*)\}")
_LATEX_CMD_RE = re.compile(r"\\([a-zA-Z]+)")
_LATEX_DEG_RE = re.compile(r"\^\{?\\?circ\}?|\^\{?o\}?(?![a-zA-Z_])")


def normalize_input(expression: str) -> str:
    """Deterministically convert common LaTeX math to Python-ish syntax.

    Handles \\\\frac{a}{b}, \\\\sqrt{x}, \\\\sqrt[n]{x}, \\\\cdot, \\\\times,
    \\\\div, \\\\pi, \\\\left/\\\\right, degree markers, `^` powers, and strips
    `$`. Unknown \\\\commands raise DISALLOWED_EXPRESSION (fail loud —
    silently dropping a command once produced wrong-but-plausible answers).
    """
    s = (expression or "").strip()
    for _ in range(6):                       # nested fracs
        nxt = _LATEX_FRAC_RE.sub(r"((\1)/(\2))", s)
        if nxt == s:
            break
        s = nxt
    s = _LATEX_SQRT_RE.sub(r"((\2)**(1/\1))", s)
    s = _LATEX_SQRT2_RE.sub(r"sqrt(\1)", s)
    for old, new in _LATEX_REPLACEMENTS:
        s = s.replace(old, new)
    s = _LATEX_DEG_RE.sub("", s)             # 45^{\circ} -> 45
    s = _LATEX_BRACE_EXP_RE.sub(r"**(\1)", s)  # 2^{10} -> 2**(10) (a bare
    #   {10} would parse as a Python set literal, which the gate rejects)
    s = _LATEX_CMD_RE.sub(_unknown_latex_cmd, s)
    s = s.replace("^", "**")
    return s.strip()


def _unknown_latex_cmd(m: re.Match) -> str:
    cmd = m.group(1)
    if cmd in {"theta", "alpha", "beta", "gamma", "lambda", "mu", "phi",
               "omega", "rho", "sigma", "Delta", "delta"}:
        return cmd                            # plain symbol names
    raise ToolError("DISALLOWED_EXPRESSION",
                    f"unsupported LaTeX command \\{cmd}")


# ---------------------------------------------------------------------------
# 2. Lenient implicit multiplication (token-based, no regex on code)
# ---------------------------------------------------------------------------

def lenient_expression(expr: str) -> str:
    """Insert `*` where Python's tokenizer allows juxtaposition:
    `2x` -> `2*x`, `2(` -> `2*(`, `)(` -> `)*(`, `)2` -> `)*2`,
    `x(` -> `x*(` when x is not a known function name.

    Uses tokenize so string literals / comments can't smuggle edits. Raises
    ToolError(PARSE_ERROR) on malformed input (matching Python's tokenizer).
    """
    allowed_functions = ALLOWED_FUNCTIONS
    try:
        tokens = list(tokenize.generate_tokens(
            io.StringIO(expr).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError) as e:
        raise ToolError("PARSE_ERROR", f"cannot tokenize expression: {e}")
    out: list[tuple[str, str]] = []
    prev: tuple[str, str] | None = None
    # A newline INSIDE an expression is ambiguous ("2\n3" would silently
    # become 2*3): only trailing newlines are allowed.
    first_content = next((i for i, t in enumerate(tokens)
                          if t.type not in (tokenize.NEWLINE, tokenize.NL,
                                            tokenize.INDENT,
                                            tokenize.DEDENT)), None)
    if first_content is not None:
        for i, tok in enumerate(tokens):
            if tok.type in (tokenize.NEWLINE, tokenize.NL) and i > first_content \
                    and any(t.type not in (tokenize.NEWLINE, tokenize.NL,
                                           tokenize.INDENT, tokenize.DEDENT,
                                           tokenize.ENDMARKER)
                            for t in tokens[i + 1:]):
                raise ToolError("PARSE_ERROR",
                                "newline inside expression is ambiguous")
    for tok in tokens:
        kind, text = tok.type, tok.string
        if kind in (tokenize.NEWLINE, tokenize.NL, tokenize.INDENT,
                    tokenize.DEDENT, tokenize.ENDMARKER):
            continue
        if prev is not None and _needs_star(prev, (kind, text),
                                            allowed_functions):
            out.append((tokenize.OP, "*"))
        out.append((kind, text))
        prev = (kind, text)
    return tokenize.untokenize(out).strip()


def _is_name(kind: int, text: str) -> bool:
    return kind == tokenize.NAME and text not in ("and", "or", "not", "in",
                                                  "is", "if", "else", "lambda")


def _needs_star(prev: tuple[int, str], cur: tuple[int, str],
                allowed_functions: frozenset) -> bool:
    pk, pt = prev
    ck, ct = cur
    prev_operand = _is_name(pk, pt) or pk == tokenize.NUMBER or (
        pk == tokenize.OP and pt in {")", "]"})
    cur_operand = _is_name(ck, ct) or ck == tokenize.NUMBER or (
        ck == tokenize.OP and ct in {"(", "["})
    if not (prev_operand and cur_operand):
        return False
    # `name(` is a call when name is an allowed function; otherwise 2*(x+y)
    if pk == tokenize.OP and pt == ")" and ck == tokenize.OP and ct == "(":
        return True
    if pk == tokenize.OP and pt in {")", "]"}:
        return True
    if pk == tokenize.NUMBER:
        return True
    if _is_name(pk, pt):
        # x( — multiplication unless x is an allowed function (a call)
        if ck == tokenize.OP and ct == "(" and pt in allowed_functions:
            return False
        # juxtaposed names: x y stays two symbols? invalid python; treat as
        # product of symbols only if cur is a name and prev is a lone symbol
        return ck == tokenize.OP and ct == "("
    return False


# ---------------------------------------------------------------------------
# 3. AST whitelist gate
# ---------------------------------------------------------------------------

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
                   ast.FloorDiv)
_ALLOWED_UNARY = (ast.UAdd, ast.USub)
_ALLOWED_CONST_TYPES = (int, float)

_ALLOWED_FUNCTIONS: frozenset = frozenset({
    "sqrt", "cbrt", "abs", "exp", "log", "log2", "log10",
    "sin", "cos", "tan", "asin", "acos", "atan",
    "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
    "floor", "ceil", "round", "sign", "factorial", "gcd", "lcm",
    "min", "max", "binomial", "gamma",
})

_ALLOWED_CONSTANTS: frozenset = frozenset({
    "pi", "e", "tau", "E", "inf", "oo",
})


def validate_ast(source: str, *, allow_calls: bool = True) -> ast.Expression:
    """Whitelist-validate a Python-arithmetic expression string.

    Raises ToolError(DISALLOWED_EXPRESSION) for anything outside: numeric
    literals, the 7 arithmetic binary operators, unary +/-, whitelisted
    function calls, whitelisted constants and plain symbol names. No
    attribute access, subscripts, strings, lambdas, comprehensions, or
    walrus operators can ever pass. Depth and input length are bounded.
    """
    if len(source) > MAX_EXPRESSION_LENGTH:
        raise ToolError("DISALLOWED_EXPRESSION",
                        f"expression exceeds {MAX_EXPRESSION_LENGTH} chars")
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError) as e:
        raise ToolError("PARSE_ERROR", f"invalid expression: {e}")
    _walk(tree.body, depth=0, allow_calls=allow_calls)
    return tree


def _walk(node: ast.AST, depth: int, allow_calls: bool) -> None:
    if depth > MAX_AST_DEPTH:
        raise ToolError("DISALLOWED_EXPRESSION",
                        f"expression nesting exceeds {MAX_AST_DEPTH}")
    if isinstance(node, ast.Expression):
        return _walk(node.body, depth, allow_calls)
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise ToolError("DISALLOWED_EXPRESSION",
                            f"operator {type(node.op).__name__} not allowed")
        if isinstance(node.op, ast.Pow):
            exp = _static_int(node.right)
            if exp is not None and abs(exp) > MAX_STATIC_EXPONENT:
                raise ToolError("DISALLOWED_EXPRESSION",
                                f"integer exponent {exp} exceeds "
                                f"{MAX_STATIC_EXPONENT}")
        return _walk_both(node.left, node.right, depth, allow_calls)
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARY):
            raise ToolError("DISALLOWED_EXPRESSION",
                            f"operator {type(node.op).__name__} not allowed")
        return _walk(node.operand, depth + 1, allow_calls)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or \
                not isinstance(node.value, _ALLOWED_CONST_TYPES):
            raise ToolError("DISALLOWED_EXPRESSION",
                            f"literal {node.value!r} not allowed")
        if isinstance(node.value, int) and abs(node.value) > MAX_INT_LITERAL:
            raise ToolError("DISALLOWED_EXPRESSION",
                            f"integer literal exceeds {MAX_INT_LITERAL}")
        return
    if isinstance(node, ast.Name):
        name = node.id
        if name in _ALLOWED_CONSTANTS:
            return
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z_0-9]*", name):
            raise ToolError("DISALLOWED_EXPRESSION",
                            f"identifier {name!r} not allowed")
        return
    if isinstance(node, ast.Call) and allow_calls:
        func = node.func
        if not isinstance(func, ast.Name) or func.id not in _ALLOWED_FUNCTIONS:
            raise ToolError("DISALLOWED_EXPRESSION",
                            "only whitelisted functions may be called")
        if node.keywords:
            raise ToolError("DISALLOWED_EXPRESSION", "keyword args not allowed")
        # Slowly-evaluated functions: bound integer arguments statically
        # (factorial(10**9) would be computed eagerly by sympy at parse
        # time and burn CPU for days before any timeout could fire).
        if func.id in {"factorial", "binomial", "gamma"}:
            for arg in node.args:
                v = _static_int(arg)
                if v is not None and abs(v) > MAX_FACTORIAL_ARG:
                    raise ToolError(
                        "DISALLOWED_EXPRESSION",
                        f"{func.id} argument {v} exceeds {MAX_FACTORIAL_ARG}")
        for arg in node.args:
            _walk(arg, depth + 1, allow_calls)
        return
    if isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            _walk(elt, depth + 1, allow_calls)
        return
    raise ToolError("DISALLOWED_EXPRESSION",
                    f"construct {type(node).__name__} not allowed")


def _walk_both(a: ast.AST, b: ast.AST, depth: int, allow_calls: bool) -> None:
    _walk(a, depth + 1, allow_calls)
    _walk(b, depth + 1, allow_calls)


def _static_int(node: ast.AST) -> int | None:
    """Statically evaluate an integer-only subtree (literals + int ops),
    or return None if any part is not statically computable."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd,
                                                              ast.USub)):
        v = _static_int(node.operand)
        return v if v is None else (-v if isinstance(node.op, ast.USub) else v)
    if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Pow, ast.FloorDiv,
                      ast.Mod)):
        a, b = _static_int(node.left), _static_int(node.right)
        if a is None or b is None:
            return None
        try:
            if b == 0 and isinstance(node.op, (ast.FloorDiv, ast.Mod)):
                return None
            if isinstance(node.op, ast.Pow) and (abs(a) > 10**20 or
                                                 abs(b) > MAX_STATIC_EXPONENT):
                return None
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Pow):
                return a ** b
            if isinstance(node.op, ast.FloorDiv):
                return a // b
            return a % b
        except (ValueError, OverflowError, MemoryError, ZeroDivisionError):
            return None
    return None


ALLOWED_FUNCTIONS = _ALLOWED_FUNCTIONS