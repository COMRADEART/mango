"""T31.6 Scoring — content validity, kept permanently separate from format.

The brief's rule is stated as an absolute: "T31 must permanently separate
``schema_valid`` and ``content_valid``." That separation is the reason this
module exists as its own layer rather than as a boolean on the extraction.

``schema_valid``
    Did the generation honour the output contract the prompt asked for — the
    ``####`` marker, a ``\\boxed{}`` answer, a single unambiguous option
    letter? This is protocol compliance.

``content_valid``
    Is the answer, once read, *correct*? This is the capability metric. The
    brief is explicit that it is the primary one, and equally explicit that
    protocol compliance "must never automatically count as reasoning success".

A model that emits a flawlessly formatted wrong answer has
``schema_valid=True, content_valid=False``. That is a content failure, and
nothing in this module lets it be counted as anything else. The pairing is
carried onto every row so the report can show the cross-tabulation instead of
a single number that hides it.

Scoring is deterministic and layered, and each layer is named on the row. For
multiple choice it is label equality; for GSM8K it is exact decimal equality;
for MATH-500 it is normalised string equality, then numeric equality, then
symbolic equivalence restricted to a whitelist of constructs. The layered
MATH score is the only place where equivalence is attempted at all, and it is
bounded precisely so that it cannot become a source of nondeterminism.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from sciencemath.comparability.extractors import (
    Extraction, _normalize_option_text, normalize_number, strip_reasoning,
)

#: Generation ended because it hit the token budget.
FINISH_LENGTH: Final = "length"
FINISH_STOP: Final = "stop"

#: Refusal / abstention signals. Deterministic phrase matching only; a model
#: that declines is a fact about the generation, not a judgement about it.
_ABSTENTION: Final = re.compile(
    r"\b(i (?:cannot|can't|can not|am unable|don't know|do not know)"
    r"|unable to (?:determine|answer|solve)"
    r"|insufficient information"
    r"|cannot be determined"
    r"|no (?:correct|valid) (?:answer|option)"
    r"|not enough information)\b", re.IGNORECASE)

#: The commands symbolic comparison will accept. Anything outside this set
#: falls back to string comparison, which keeps the tier bounded and
#: deterministic instead of handing arbitrary LaTeX to a symbolic engine.
_SAFE_SYMBOLS: Final = frozenset({
    "frac", "dfrac", "tfrac", "sqrt", "pi", "cdot", "times", "div", "left",
    "right", "text", "mathrm", "operatorname", "sin", "cos", "tan", "log",
    "ln", "exp", "pm", "infty", "degree", "circ", "quad", "qquad", "!",
})

_LATEX_SUBSTITUTIONS: Final = (
    (r"\\left", ""), (r"\\right", ""), (r"\\!", ""), (r"\\,", ""),
    (r"\\;", ""), (r"\\ ", " "),
    (r"\\dfrac", r"\\frac"), (r"\\tfrac", r"\\frac"),
    (r"\\cdot", "*"), (r"\\times", "*"), (r"\\div", "/"),
    (r"\\pi", "pi"), (r"\\infty", "oo"), (r"\\degree", ""), (r"\\circ", ""),
    (r"\\text\{([^{}]*)\}", r"\1"), (r"\\mathrm\{([^{}]*)\}", r"\1"),
    (r"\\operatorname\{([^{}]*)\}", r"\1"),
    # Unbraced exponents only. ``^{...}`` is rewritten before this runs, by a
    # scanner, because a regex cannot match its closing brace — see
    # ``_rewrite_superscripts``.
    (r"\^", "**"),
    (r"\\%", "/100"), (r"%", "/100"),
    (r"\$", ""), (r"\\\$", ""),
    (r"\\sqrt\{([^{}]*)\}", r"sqrt(\1)"),
    (r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"((\1)/(\2))"),
)

#: LaTeX writes multiplication by juxtaposition, Python requires the operator.
#: ``2\pi`` becomes ``2pi``, which sympy cannot parse at all, so a gold answer
#: of ``2\pi`` fell to string comparison and a model answering ``2\cdot\pi``
#: was marked wrong. Both spellings name the same number. The lookarounds keep
#: this to the cases that are unambiguous in LaTeX: a number before a name or
#: a parenthesis, and a closing parenthesis before another factor.
_IMPLICIT_MULTIPLICATION: Final = (
    (r"(?<=[0-9])(?=[A-Za-z(])", "*"),
    (r"(?<=\))(?=[A-Za-z0-9(])", "*"),
)

_MATH_TIER_ORDER: Final = ("exact_normalized", "numeric", "symbolic",
                           "string_fallback")


class ScoringError(RuntimeError):
    """An item could not be scored."""


@dataclass(frozen=True)
class Score:
    """The scored outcome of one row.

    ``scorer_tier`` names the rule that decided the row, mirroring the
    extraction tier. Together they answer "how was this number produced?"
    without anyone having to re-derive it from the code.
    """

    content_valid: bool
    schema_valid: bool
    error_category: str
    scorer_tier: str
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"content_valid": self.content_valid,
                "schema_valid": self.schema_valid,
                "error_category": self.error_category,
                "scorer_tier": self.scorer_tier,
                "notes": list(self.notes)}


# ---------------------------------------------------------------------------
# MATH-500 normalisation and equivalence
# ---------------------------------------------------------------------------
def normalize_math_answer(text: str) -> str:
    """Canonical form of a mathematical answer, for string comparison.

    Whitespace, ``$`` delimiters, ``\\left``/``\\right`` and trailing periods
    are all presentation, not mathematics, so they are removed before the
    first comparison. Everything removed here is removed for both arms.
    """
    value = text.strip()
    value = value.replace("\\$", "").replace("$", "")
    value = re.sub(r"\\left|\\right", "", value)
    value = re.sub(r"\s+", "", value)
    value = value.rstrip(".").strip()
    value = value.replace("\\\\", "\\")
    return value


def _rewrite_superscripts(text: str) -> str:
    """``^{...}`` -> ``**(...)``, with the closing brace actually closed.

    A regex cannot match balanced braces, and the obvious substitution
    ``(r"\\^\\{", "**(")`` — which this replaces — opens a parenthesis that
    nothing ever closes: ``x^{2}+1`` became ``x**(2}+1``. Measured before the
    repair, every braced exponent in a probe was scored WRONG, including
    ``3^{4}`` against a gold of ``81`` and ``x^{2}+1`` against ``x^2+1``.

    That is a scorer artefact wearing the costume of a capability difference:
    on MATH-500, where braced exponents are everywhere, it penalised whichever
    arm happened to brace them. Both arms share one scorer, so the repair is
    symmetric by construction, and the recursion means the inner expression is
    still handed to the rest of the substitutions (``2^{\\frac{1}{2}}`` becomes
    ``2**(((1)/(2)))``).

    An unclosed brace is left exactly as written rather than being given a
    parenthesis that closes nothing; the answer then falls back to string
    comparison, which is what an unparseable answer should do.
    """
    out: list[str] = []
    index = 0
    while index < len(text):
        if text.startswith("^{", index):
            depth = 0
            for position in range(index + 1, len(text)):
                char = text[position]
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        inner = text[index + 2:position]
                        out.append("**(" + _rewrite_superscripts(inner) + ")")
                        index = position + 1
                        break
            else:
                out.append(text[index])
                index += 1
            continue
        out.append(text[index])
        index += 1
    return "".join(out)


def _to_python_expression(text: str) -> str | None:
    """Translate a whitelisted LaTeX subset into a Python expression.

    Returns ``None`` when the answer uses any construct outside the whitelist.
    Refusing is deliberate: an answer using an integral or a limit is not
    something this scorer can compare safely, and guessing would be worse than
    falling back to string equality and saying so.
    """
    value = _rewrite_superscripts(text.strip())
    for pattern, replacement in _LATEX_SUBSTITUTIONS:
        value = re.sub(pattern, replacement, value)
    for pattern, replacement in _IMPLICIT_MULTIPLICATION:
        value = re.sub(pattern, replacement, value)
    commands = set(re.findall(r"\\([A-Za-z]+)", value))
    if commands - _SAFE_SYMBOLS:
        return None
    if re.search(r"[^0-9A-Za-z_+\-*/^().,\s=<>!\[\]{}]", value):
        return None
    return value


def math_equivalent(predicted: str, gold: str) -> tuple[bool, str]:
    """Decide whether two mathematical answers are the same answer.

    Returns ``(equivalent, tier)``. The tiers are tried in a fixed order and
    the first decisive one is reported, so the same pair always resolves the
    same way.
    """
    left = normalize_math_answer(predicted)
    right = normalize_math_answer(gold)
    if not left or not right:
        return False, "empty"
    if left == right:
        return True, "exact_normalized"

    left_number = normalize_number(left)
    right_number = normalize_number(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number, "numeric"

    left_expression = _to_python_expression(left)
    right_expression = _to_python_expression(right)
    if left_expression and right_expression:
        verdict = _symbolic_equal(left_expression, right_expression)
        if verdict is not None:
            return verdict, "symbolic"

    return False, "string_fallback"


def _symbolic_equal(left: str, right: str) -> bool | None:
    """Symbolic equivalence, or ``None`` if sympy is unavailable or refuses."""
    try:
        import sympy
    except ImportError:                            # pragma: no cover
        return None
    try:
        first = sympy.sympify(left, evaluate=True)
        second = sympy.sympify(right, evaluate=True)
    except Exception:                              # noqa: BLE001
        return None
    try:
        same = first == second
    except Exception:                              # noqa: BLE001 - sympy's own
        return None                                 # __eq__ raises when one
        #                                            side is a class object
        #                                            (e.g. bare-word sympify
        #                                            resolving to an entity
        #                                            class); an engine that
        #                                            cannot compare is an
        #                                            engine that cannot decide.
    if same:
        return True
    try:
        return bool(sympy.simplify(first - second) == 0)
    except Exception:                              # noqa: BLE001 - a symbolic
        return None                                # engine that raises is an
        #                                            engine that cannot decide


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
def _gold_in_working(raw: str, gold: str, kind: str) -> bool:
    """Deterministic signal: does the gold value appear in the working?

    Not an error category. It is recorded as a boolean because it separates
    "reached the right value and reported something else" from "never got
    there", which is genuinely useful when the T32 handoff is built — and
    which no amount of category design would make a *correct* answer wrong.

    Restricted to the free-form benchmarks. For a multiple-choice item the
    "gold" is a letter, and a letter appears in ordinary prose constantly —
    asking whether "C" occurs in a paragraph is not a question with an
    answer, so it is not asked.
    """
    if kind == "multiple_choice":
        return False
    text = strip_reasoning(raw)
    gold_number = normalize_number(gold)
    if gold_number is not None:
        return any(normalize_number(found) == gold_number
                   for found in re.findall(r"-?\d[\d,]*\.?\d*", text))
    return bool(gold) and normalize_math_answer(gold) in \
        normalize_math_answer(text)


def score(item, kind: str, extraction: Extraction, raw: str, *,
          finish_reason: str = FINISH_STOP) -> Score:
    """Score one generation. Deterministic; no model judges another model."""
    notes: list[str] = []
    schema_valid = extraction.status != "FAILED" and \
        extraction.tier in _PRIMARY_TIERS[kind]

    if extraction.status == "FAILED":
        truncated = finish_reason == FINISH_LENGTH
        if truncated:
            return Score(False, False, "truncated_generation",
                         "no_answer", ("generation hit the token budget",))
        if _ABSTENTION.search(raw):
            return Score(False, False, "abstention", "no_answer",
                         ("model declined to answer",))
        return Score(False, False, "answer_extraction_failure", "no_answer",
                     ("no answer could be read from the generation",))

    if extraction.status == "AMBIGUOUS":
        category = "invalid_option" if kind == "multiple_choice" else "other"
        return Score(False, schema_valid, category, extraction.tier,
                     (extraction.note or "more than one answer offered",))

    if kind == "multiple_choice":
        correct = extraction.label is not None and \
            extraction.label.upper() == (item.gold_label or "").upper()
        if not correct and _twin_option_agrees(item, extraction):
            # SciQ ships items whose distractor repeats the correct answer's
            # text verbatim (measured: 9 of 1,000 items carry
            # duplicate_option_text). Writing out the right answer and having
            # it read as the identical twin is a defect in the benchmark's
            # presentation, not a wrong answer, and the brief requires a
            # discovered benchmark bug to be repaired for both arms. The
            # repair is item-level, so it is applied to both arms by
            # construction, and it never fires for a letter the model chose
            # itself — only for a text tier, where the label is inferred.
            correct = True
            notes.append("accepted a duplicate-text twin of the gold option")
        tier = "label_equality"
    elif kind == "numeric":
        predicted = normalize_number(extraction.answer or "")
        gold = normalize_number(item.gold)
        correct = predicted is not None and gold is not None and \
            predicted == gold
        tier = "decimal_equality"
    elif kind == "math":
        correct, tier = math_equivalent(extraction.answer or "", item.gold)
    else:                                          # pragma: no cover
        raise ScoringError(f"no scorer for kind {kind!r}")

    if extraction.tier.endswith("fallback") or \
            extraction.tier == "option_text_longest":
        notes.append(f"read by {extraction.tier}")

    if correct:
        return Score(True, schema_valid, "correct", tier, tuple(notes))

    if _ABSTENTION.search(raw):
        return Score(False, schema_valid, "abstention", tier, tuple(notes))

    if _gold_in_working(raw, item.gold, kind):
        notes.append("gold value present in the working but not reported")

    return Score(False, schema_valid, "wrong_final_answer", tier, tuple(notes))


#: Tiers where the label was *inferred from the option's text* rather than
#: chosen by the model. Only these can be rescued by the duplicate-text
#: repair; a model that writes "C" when the gold is "A" has made a choice.
_TEXT_TIERS: Final = frozenset({"option_text", "option_text_longest"})


def _twin_option_agrees(item, extraction) -> bool:
    """True when the model's answer names the gold option *by its text*.

    Restricted to text tiers and to a genuine text match, so it cannot turn a
    wrong answer into a right one: the model must have written out an option's
    text, and that text must be the same string the gold label points at.
    On an item with no duplicate option text this is a no-op — the chosen
    label already is the gold label. It fires exactly when the extractor
    mapped the written answer onto a twin of the gold option.
    """
    if extraction.tier not in _TEXT_TIERS or extraction.label is None:
        return False
    if not item.gold_label:
        return False
    texts = {str(label).upper(): _normalize_option_text(option)
             for label, option in item.choices}
    gold_text = texts.get(str(item.gold_label).upper(), "")
    chosen_text = texts.get(str(extraction.label).upper(), "")
    return bool(gold_text) and gold_text == chosen_text


#: Tiers that count as honouring the requested output contract. Reading an
#: answer by a fallback rule means the model answered without following the
#: format it was asked for — correct content, failed schema — and the two
#: facts are reported separately rather than collapsed.
_PRIMARY_TIERS: Final = {
    "numeric": frozenset({"hash_marker"}),
    "math": frozenset({"boxed", "fbox"}),
    "multiple_choice": frozenset({"answer_cue", "boxed_letter", "bare_line",
                                  "bare_letter"}),
}
