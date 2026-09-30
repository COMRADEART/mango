"""T31.5 Answer extraction — deterministic, layered, auditable.

Extraction is where an evaluation most easily lies to itself. A permissive
parser inflates accuracy; a brittle one converts correct answers into
extraction failures and depresses it. Both errors are invisible in the final
number, which is why every extraction here records *which rule* produced it.

Three principles shape this module.

**Deterministic only.** No model judges another model's output. Every rule
below is a string or numeric operation whose result is the same on every
machine and in every process.

**Failure is typed, not silent.** ``FAILED`` means no answer could be read;
``AMBIGUOUS`` means more than one plausible answer was offered. They are
different facts — a model that says two different things is not the same as a
model that says nothing — and the brief requires extraction failures to be
recorded separately from content failures. Keeping the distinction here is
what lets the report do that.

**Reasoning is not scored.** Extraction reads the *final* answer only. Wording
in the working is never evidence of correctness, and a correct number reached
by a wrong route scores as correct while being classified ``wrong_reasoning``
in the error taxonomy — the two questions are answered separately rather than
conflated.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final, Sequence

from sciencemath.comparability.contract import (
    EXTRACTION_AMBIGUOUS, EXTRACTION_FAILED, EXTRACTION_OK,
)

#: Reasoning blocks are not part of an answer. With ``enable_thinking=False``
#: the template pre-closes the block, so a well-behaved generation contains no
#: reasoning at all — this strips one defensively rather than assuming.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK = re.compile(r"^.*?</think>", re.DOTALL | re.IGNORECASE)

_GSM8K_MARKER = re.compile(r"####\s*(.+)")
_NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")

_BOXED = "\\boxed"
_FBOXED = "\\fbox"

#: Cues that introduce a final answer statement, most specific first.
_ANSWER_CUES: Final = (
    r"(?:final|correct)?\s*answer\s*(?:is|:)\s*",
    r"answer\s*[:=]\s*",
    r"the\s+correct\s+option\s+is\s*",
    r"option\s*[:=]?\s*",
    r"choice\s*[:=]?\s*",
)

#: A bare option letter, bounded so that "a" inside a word is not a match.
_LETTER_BOUNDED = r"(?<![A-Za-z0-9])([{letters}])(?![A-Za-z0-9])"


class ExtractionError(RuntimeError):
    """An item could not be handed to an extractor."""


@dataclass(frozen=True)
class Extraction:
    """The outcome of reading an answer out of a generation.

    ``tier`` names the rule that fired, so a run can report how much of its
    measurement rested on the primary rule and how much on a fallback. That
    distribution is itself evidence: a benchmark scored mostly by fallback
    rules is a benchmark whose parser needs looking at.
    """

    status: str
    answer: str | None
    tier: str
    label: str | None = None
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.status == EXTRACTION_OK

    def to_dict(self) -> dict:
        return {"status": self.status, "answer": self.answer, "tier": self.tier,
                "label": self.label, "note": self.note}


# ---------------------------------------------------------------------------
# shared normalisation
# ---------------------------------------------------------------------------
def strip_reasoning(text: str) -> str:
    """Remove any reasoning block, closed or (pathologically) unclosed."""
    cleaned = _THINK_BLOCK.sub(" ", text)
    if "</think>" in cleaned:
        cleaned = _UNCLOSED_THINK.sub(" ", cleaned)
    return cleaned


def normalize_number(text: str) -> str | None:
    """Canonical decimal form of a numeric answer, or ``None``.

    ``"1,000"``, ``"$1000"``, ``"1000."`` and ``"1000"`` all normalise to
    ``"1000"``; ``"0.50"`` normalises to ``"0.5"``. Decimal is used rather
    than float so that the comparison is exact — two answers that differ only
    at the fifteenth significant digit are the same answer for a grade-school
    word problem, and a float would occasionally say otherwise.
    """
    candidate = text.strip()
    if not candidate:
        return None
    candidate = candidate.replace(",", "").replace("$", "").replace("\\$", "")
    candidate = candidate.replace("%", "").replace("\\%", "").strip()
    candidate = candidate.rstrip(".").strip()
    if not candidate:
        return None
    try:
        value = Decimal(candidate)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def _match_last(pattern: str, text: str, flags: int = re.IGNORECASE):
    matches = list(re.finditer(pattern, text, flags))
    return matches[-1] if matches else None


# ---------------------------------------------------------------------------
# GSM8K — numeric
# ---------------------------------------------------------------------------
def extract_numeric(raw: str) -> Extraction:
    """GSM8K: the value after ``####``, else the last number in the text.

    The marker is GSM8K's own convention and is what the prompt asks for, so
    it is the primary rule. The fallback exists because a model that solves
    the problem and then writes "So she sells 18 eggs" without the marker has
    answered the question, and treating that as a measurement failure would
    understate accuracy for both arms equally — but it is recorded as a
    fallback so the reader can see how often it was needed.
    """
    text = strip_reasoning(raw).strip()
    if not text:
        return Extraction(EXTRACTION_FAILED, None, "empty")

    marker = None
    for match in _GSM8K_MARKER.finditer(text):
        marker = match
    if marker is not None:
        tail = marker.group(1).strip().splitlines()
        if tail:
            number = _NUMBER.search(tail[0])
            value = normalize_number(number.group(0)) if number else None
            if value is not None:
                return Extraction(EXTRACTION_OK, value, "hash_marker")

    # A model that answers inside \boxed{} has answered the question. It has
    # not followed the format the prompt asked for, and the schema flag says
    # so — but refusing to read the number would turn a format difference
    # into a capability difference, which is the one thing this layer must
    # never do.
    boxed = _last_braced(text, _BOXED)
    if boxed:
        number = _NUMBER.search(boxed)
        value = normalize_number(number.group(0)) if number else None
        if value is not None:
            return Extraction(EXTRACTION_OK, value, "boxed_fallback",
                              note="no #### marker; answer was boxed")

    numbers = _NUMBER.findall(text)
    if numbers:
        value = normalize_number(numbers[-1])
        if value is not None:
            return Extraction(EXTRACTION_OK, value, "last_number_fallback",
                              note="no #### marker in generation")

    return Extraction(EXTRACTION_FAILED, None, "no_number")


# ---------------------------------------------------------------------------
# MATH-500 — LaTeX
# ---------------------------------------------------------------------------
def _last_braced(text: str, command: str) -> str | None:
    """Contents of the last ``\\command{...}``, with balanced braces.

    A regex cannot match balanced braces, and mathematical answers nest them
    constantly (``\\boxed{\\frac{1}{2}}``), so this scans.
    """
    found: list[str] = []
    start = 0
    while True:
        index = text.find(command + "{", start)
        if index < 0:
            break
        depth = 0
        for position in range(index + len(command), len(text)):
            char = text[position]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    found.append(text[index + len(command) + 1:position])
                    start = position + 1
                    break
        else:
            break
    return found[-1].strip() if found else None


def extract_math(raw: str) -> Extraction:
    """MATH-500: the last ``\\boxed{...}``, else the last answer-like line."""
    text = strip_reasoning(raw).strip()
    if not text:
        return Extraction(EXTRACTION_FAILED, None, "empty")

    for command, tier in ((_BOXED, "boxed"), (_FBOXED, "fbox")):
        value = _last_braced(text, command)
        if value:
            return Extraction(EXTRACTION_OK, value, tier)

    for cue in _ANSWER_CUES:
        match = _match_last(cue + r"(.+)", text)
        if match:
            value = match.group(1).strip().strip(".$").rstrip(".").strip()
            if value:
                return Extraction(EXTRACTION_OK, value, "answer_cue_fallback",
                                  note="no \\boxed{} in generation")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        value = lines[-1].strip().strip(".$").rstrip(".").strip()
        if value:
            return Extraction(EXTRACTION_OK, value, "last_line_fallback",
                              note="no \\boxed{} or answer cue in generation")

    return Extraction(EXTRACTION_FAILED, None, "no_math_answer")


# ---------------------------------------------------------------------------
# multiple choice — ARC and SciQ
# ---------------------------------------------------------------------------
def _normalize_option_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().strip(".\"'").casefold()


def _binds(character: str) -> bool:
    """Whether a neighbouring character welds a letter into a unit or a code.

    ``20°C`` is a temperature, ``3D`` a shape, ``5V`` a voltage: the letter is
    part of the token, not a vote for an option. A digit or a symbol binds; a
    space, a bracket, a quote and other punctuation separate, so ``(C)``,
    ``"C"`` and ``**C**`` still read as option C.

    ``_LETTER_BOUNDED`` already excludes a neighbouring ASCII letter or digit.
    This adds the symbols a regex boundary cannot name — including the
    replacement character that a mis-decoded degree sign becomes, which is how
    a real ARC generation reading ``20°C`` was scored as an ambiguous answer.
    """
    if not character:
        return False
    return character.isdigit() or unicodedata.category(character)[0] == "S"


def _unbound(text: str, match: re.Match) -> bool:
    """A matched option letter that stands alone rather than inside a token."""
    start, end = match.span(1)
    return not (_binds(text[start - 1:start]) or _binds(text[end:end + 1]))


def _option(label: str, tier: str, note: str = "") -> Extraction:
    """A successful multiple-choice extraction.

    ``label`` and ``answer`` are both set to the option letter. The scorer
    reads ``label`` because that is what a choice item's answer *is*; ``answer``
    carries the same value so that a reader inspecting a raw row does not have
    to know which of the two fields a given benchmark populates.
    """
    return Extraction(EXTRACTION_OK, label, tier, label=label, note=note)


def extract_choice(raw: str, labels: Sequence[str],
                   choices: Sequence[tuple[str, str]] = ()) -> Extraction:
    """ARC / SciQ: one option label, in the item's own label vocabulary.

    Tiers, most explicit first: an answer cue or a boxed letter, then a
    stand-alone letter, then the *text* of an option. The text tier matters
    because a model that writes out the correct option instead of its letter
    has answered correctly; refusing to read it would be a parser artefact,
    not a capability result. It is applied identically to both arms.

    A generation offering two different options is ``AMBIGUOUS`` rather than
    silently resolved to whichever appeared last, because "the model was of
    two minds" is a fact worth keeping.
    """
    text = strip_reasoning(raw).strip()
    label_set = {str(label).strip().upper() for label in labels}
    if not text:
        return Extraction(EXTRACTION_FAILED, None, "empty")
    if not label_set:
        return Extraction(EXTRACTION_FAILED, None, "no_labels")

    letters = "".join(sorted(label_set))
    bounded = _LETTER_BOUNDED.format(letters=re.escape(letters))

    # Tier 1: an explicit answer statement.
    cued: list[str] = []
    for cue in _ANSWER_CUES:
        for match in re.finditer(cue + bounded, text, re.IGNORECASE):
            if _unbound(text, match):
                cued.append(match.group(1).upper())
    if cued:
        distinct = set(cued)
        if len(distinct) > 1:
            return Extraction(EXTRACTION_AMBIGUOUS, None, "answer_cue",
                              note=f"conflicting options {sorted(distinct)}")
        return _option(cued[-1], "answer_cue")

    # Tier 2: a boxed letter, e.g. \boxed{C}. The box must hold the letter, not
    # merely end in one: an inner "20°C" is a temperature whose last character
    # happens to be an option letter.
    boxed = _last_braced(text, _BOXED)
    if boxed:
        candidate = boxed.strip(" \t().:*_`{}").upper()
        if len(candidate) == 1 and candidate in label_set:
            return _option(candidate, "boxed_letter")

    # Tier 3: a line that is nothing but the letter. A whole line consisting
    # of one character is structurally an answer, so case is not decisive
    # here and "c" on its own is read as option C.
    for line in reversed([line.strip() for line in text.splitlines()
                          if line.strip()]):
        stripped = line.strip(" \t().:*_`")
        if 0 < len(stripped) <= 2 and stripped.isalpha() \
                and stripped.upper() in label_set:
            return _option(stripped.upper(), "bare_line")

    # Tier 4: a stand-alone letter *in the item's own alphabet*. This scan is
    # deliberately case-sensitive. Option labels are upper case, and a
    # case-insensitive scan would read the English article "a" — which
    # appears in almost every sentence of working — as a vote for option A,
    # manufacturing agreement out of grammar. Context-anchored cues above may
    # be case-insensitive because "the answer is c" really is an answer; a
    # bare letter floating in prose is not.
    standalone = [match.group(1) for match in re.finditer(bounded, text)
                  if _unbound(text, match)]
    if standalone:
        distinct = set(standalone)
        if len(distinct) == 1:
            return _option(standalone[-1], "bare_letter")
        return Extraction(EXTRACTION_AMBIGUOUS, None, "bare_letter",
                          note=f"conflicting options {sorted(distinct)}")

    # Tier 5: the option's text, written out in full.
    normalized = _normalize_option_text(text)
    hits = [(label, option) for label, option in choices
            if _normalize_option_text(option)
            and _normalize_option_text(option) in normalized]
    if hits:
        distinct = {label for label, _ in hits}
        if len(distinct) == 1:
            return _option(hits[0][0], "option_text")
        # Several option texts appear because they are quoted in the working.
        # The longest match is the one the model actually committed to.
        longest = max(hits, key=lambda pair: len(pair[1]))
        return _option(longest[0], "option_text_longest",
                       note="multiple options quoted; longest match taken")

    return Extraction(EXTRACTION_FAILED, None, "no_option")


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
def extract(item, kind: str, raw: str) -> Extraction:
    """Read an answer from a generation, using the benchmark's own rule."""
    if kind == "numeric":
        return extract_numeric(raw)
    if kind == "math":
        return extract_math(raw)
    if kind == "multiple_choice":
        return extract_choice(raw, [label for label, _ in item.choices],
                              item.choices)
    raise ExtractionError(f"no extractor for kind {kind!r}")
