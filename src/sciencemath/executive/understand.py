"""T7.4/T7.5 — Understanding phase + distractor filter.

T7.4: a COMPACT structured understanding (knowns / unknowns /
constraints / distractors / missing information). No hidden chain of
thought — everything recorded is an extractive span or a typed fact,
never free-form model reasoning. Deterministic extraction first
(numbers+units, question target); the model is never the sole source.

T7.5: candidate facts are labelled REQUIRED / SUPPORTING / IRRELEVANT /
CONFLICTING / UNKNOWN. Distractors are recorded and EXCLUDED from step
context (ablation F measures the cost of disabling this filter).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

FACT_LABELS = ("REQUIRED", "SUPPORTING", "IRRELEVANT", "CONFLICTING",
               "UNKNOWN")

# quantity+unit spans (numbers with optional units)
_NUM_UNIT_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(m/s|km/h|kg|g|mg|m|cm|km|s|ms|min|h|hr|hour"
    r"|J|kJ|N|K|°C|mol|mol/L|M|L|mL|%|degrees?|radians?|eV|Hz|W|kW|Pa|atm)?",
    re.IGNORECASE,
)
_ASSENT_RE = re.compile(
    r"\b(given|provided|supplied|using|of)\b", re.IGNORECASE)


@dataclass
class Understanding:
    question_target: str = ""
    knowns: list = field(default_factory=list)
    unknowns: list = field(default_factory=list)
    constraints: list = field(default_factory=list)
    missing_information: list = field(default_factory=list)
    source: str = "deterministic"   # deterministic | model_assisted

    def to_dict(self) -> dict:
        return asdict(self)


# -- deterministic understanding --------------------------------------------
_TARGET_PAT = re.compile(
    r"\b(what|how much|how many|calculate|compute|find|determine|"
    r"explain|describe|why|who|when)\b(.{0,120})", re.IGNORECASE)


def extract_understanding(question: str) -> Understanding:
    """Deterministic extraction. knowns = quantity spans; unknowns =
    the asked-for target; missing_information starts empty and is filled
    by downstream phases (retrieval-empty, contradiction)."""
    u = Understanding()
    m = _TARGET_PAT.search(question)
    if m:
        target = m.group(0).strip()
        # trim trailing junk at punctuation
        target = re.split(r"[.?!\n]", target)[0].strip()
        u.question_target = target[:160]
    else:
        u.question_target = question[:160]

    for num, unit in _NUM_UNIT_RE.findall(question):
        span = f"{num}{' ' + unit if unit else ''}"
        if span not in u.knowns:
            u.knowns.append(span)
    u.unknowns = [u.question_target] if u.question_target else []
    return u


# -- distractor filter (T7.5) -------------------------------------------------
@dataclass
class FactLabel:
    text: str
    label: str            # one of FACT_LABELS
    reason: str = ""
    source: str = "deterministic"

    def to_dict(self) -> dict:
        return asdict(self)


_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text or "") if s.strip()]


def _sentence_has_quantity(sent: str) -> bool:
    return bool(re.search(r"\d", sent))


def label_facts(question: str, sentences: list[str] | None = None,
                model_labels: dict | None = None,
                filter_enabled: bool = True) -> list[FactLabel]:
    """Label each candidate fact sentence. Deterministic rules:
    - sentence containing the asked-for quantity pattern and numbers
      -> REQUIRED
    - numeric sentence not about the target -> SUPPORTING
    - non-numeric sentence with unrelated-domain markers -> IRRELEVANT
    - model_labels (from the optional model-assisted pass, ablation F)
      override SUPPORTING/IRRELEVANT only; CONFLICTING is decided
      downstream by the contradiction detector, never here.
    """
    if sentences is None:
        sentences = _split_sentences(question)
    target = extract_understanding(question).question_target.lower()
    target_tokens = set(re.findall(r"[a-z]{3,}", target))

    labels: list[FactLabel] = []
    for sent in sentences:
        low = sent.lower()
        tokens = set(re.findall(r"[a-z]{3,}", low))
        numeric = _sentence_has_quantity(sent)
        overlap = tokens & target_tokens

        if numeric and overlap:
            label, reason = "REQUIRED", "quantity tied to question target"
        elif numeric and not overlap and len(sentences) > 1:
            label, reason = "SUPPORTING", "numeric, weak target overlap"
        elif not numeric and not overlap and len(sentences) > 1:
            label, reason = "IRRELEVANT", "no numbers, no target overlap"
        else:
            label, reason = "REQUIRED" if numeric else "SUPPORTING", \
                "single-fact context"

        if model_labels is not None and sent in model_labels:
            ml = str(model_labels[sent]).upper()
            if ml in ("IRRELEVANT", "SUPPORTING") and label != "REQUIRED":
                label, reason = ml, f"model-assisted override ({ml.lower()})"
            elif ml == "CONFLICTING":
                # recorded but not trusted here; verify.py decides
                label, reason = "UNKNOWN", "model flagged conflict; deferred"

        if not filter_enabled and label == "IRRELEVANT":
            label, reason = "UNKNOWN", "distractor filter disabled (ablation F)"
        labels.append(FactLabel(text=sent, label=label, reason=reason))
    return labels


def filter_context(sentences: list[str], labels: list[FactLabel]) -> dict:
    """Split candidate sentences into included (REQUIRED+SUPPORTING) and
    excluded (IRRELEVANT/UNKNOWN/CONFLICTING) context for step prompts."""
    by_text = {l.text: l for l in labels}
    included, excluded = [], []
    for s in sentences:
        lab = by_text.get(s)
        if lab is None or lab.label in ("REQUIRED", "SUPPORTING"):
            included.append(s)
        else:
            excluded.append(s)
    return {"included": included, "excluded": excluded}


def extract_conflicts(question: str, sentences: list[str]) -> list[dict]:
    """Deterministic contradiction candidates. A conflict requires the
    SAME unit carrying two DIFFERENT values for the SAME entity — two
    legitimate quantities that merely share a unit (speed 30 m/s here,
    speed 20 m/s for another object) are NOT a conflict. Precision
    rules:
      - the two value statements must share a content word (the entity
        they describe), AND
      - carry an explicit same-entity or contrast cue ("the same",
        "revised", "however", ...), OR
      - use an explicit quantity-name pattern ("X of/is/= N unit" with
        the same X).
    """
    conflicts = []
    if len(sentences) < 2:
        return conflicts
    # unit vocabulary mirrors the suite's phrasing: spelled-out units
    # (liters, minutes, ohms), prefixed forms (kJ, kW) and currency.
    # Aliases canonicalize so "3 liters" and "3 L" compare equal.
    _UNIT_RE = re.compile(
        r"(\d+(?:\.\d+)?)\s*("
        r"m/s|km/h|km|cm|mm|m|kg|mg|g|kJ|J|kW|W|mol/L|mol|mL|kL|L|"
        r"ms|minutes?|hours?|hr|h|min|s|°C|°F|degrees?|%|ohms?|Ω|"
        r"liters?|litres?|dollars?|cents?|eV|Hz|K)\b",
        re.IGNORECASE)
    _ALIAS = {
        "liters": "l", "liter": "l", "litres": "l", "litre": "l",
        "minutes": "min", "minute": "min", "hours": "h", "hour": "h",
        "hr": "h", "dollars": "$", "dollar": "$", "ohms": "ohm",
        "ohm": "ohm", "degrees": "deg", "degree": "deg", "°c": "deg",
        "°f": "degf",
    }
    by_unit: dict[str, list[tuple[str, float]]] = {}
    _INTERROG_RE = re.compile(
        r"^(what|how|why|when|who|which|where|calculate|compute|find|"
        r"determine)\b|\?", re.IGNORECASE)
    for sent in sentences:
        # a question sentence states the ask, not a fact — "how far does
        # it travel in 4.5 hours" is a hypothetical duration, not a
        # second value attributed to the same quantity
        if _INTERROG_RE.search(sent):
            continue
        for m in _UNIT_RE.finditer(sent):
            unit = _ALIAS.get(m.group(2).lower(), m.group(2).lower())
            by_unit.setdefault(unit, []).append((sent, float(m.group(1))))
        for m in re.finditer(r"\$\s*(\d+(?:\.\d+)?)", sent):
            by_unit.setdefault("$", []).append((sent, float(m.group(1))))

    _STOP = {"the", "a", "an", "and", "or", "of", "is", "are", "was",
             "were", "at", "to", "for", "with", "in", "on", "its",
             "his", "her", "their", "same", "per", "each", "then",
             "than", "has", "have", "had", "that", "this", "from",
             "by", "as", "later", "earlier", "first", "says", "stated",
             "states", "listed", "described", "however", "but",
             "actually", "revised", "revision", "corrected"}
    _CUE_RE = re.compile(
        r"\b(same|revised|revision|corrected|erratum|contradict\w*|"
        r"however|instead)\b", re.IGNORECASE)

    def _content_words(sent: str) -> set[str]:
        # light plural-stemming so "cupcakes"/"cupcake" count as the
        # shared entity word
        return {w[:-1] if w.endswith("s") and len(w) > 4 else w
                for w in re.findall(r"[A-Za-z-]{3,}", sent.lower())
                if w not in _STOP}

    def _quantity_names(sent: str) -> set[str]:
        names = set()
        for m in re.finditer(
                r"([A-Za-z][A-Za-z-]{2,20})\s+(?:of|=|:|is)\s*"
                r"(\d+(?:\.\d+)?)", sent, re.IGNORECASE):
            names.add(m.group(1).lower())
        return names

    for unit, pairs in by_unit.items():
        values = sorted({v for _, v in pairs})
        if len(values) < 2:
            continue
        sents = sorted({s for s, _ in pairs})
        flagged = False
        for i in range(len(sents)):
            for j in range(i + 1, len(sents)):
                a, b = sents[i], sents[j]
                shared = _content_words(a) & _content_words(b)
                cue = bool(_CUE_RE.search(a) or _CUE_RE.search(b))
                name_match = bool(_quantity_names(a) & _quantity_names(b))
                if shared and (cue or name_match):
                    flagged = True
        if flagged:
            conflicts.append({
                "unit": unit,
                "values": values,
                "sentences": sents,
            })
    return conflicts