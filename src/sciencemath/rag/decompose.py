"""decompose — multi-hop decomposition + mixed math/science planning
(T5R.4/T5R.5).

T5.19 showed that a single broad prompt (premise + question + raw evidence
+ tool protocol) distracts the 1.7B model: it quotes retrieved prose
instead of computing, or hops straight to an answer. This module plans
the answer as EXPLICIT steps instead:

  * multi-hop (T5R.5): the question is split into subquestions, each hop
    gets its own retrieval query and a structured intermediate answer —
    no hidden chain-of-thought, no single broad blob. Decomposition is
    deterministic (sentence/regex based) so it is auditable and cheap.

  * mixed (T5R.4): constants/formulas already supplied in the question
    are extracted deterministically; arithmetic is delegated to the T4
    tools (the harness executes the tool call); retrieval only runs for
    the science side of the question. The final answer cites a source
    only if retrieval materially contributed (citation attachment is
    deterministic — citations.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sciencemath.rag.compression import split_sentences
from sciencemath.rag.route import (_MULTI_HOP_RE, _SUPPLIED_CONSTANTS_RE,
                                   _QUANTITY_UNIT_RE)
from sciencemath.tools.router import route_question

# name = value unit   |   name is value unit   |   value unit per unit.
# Value accepts scientific notation: 4.18e3, 4.18 x 10^3, 6,67 x 10^-11 —
# the whole magnitude belongs to the value, never the unit
_CONST_ASSIGN_RE = re.compile(
    r"(?:\b([a-z][a-z ()/-]{2,40})\s*(?:=|\bis\b|:\s*)\s*"
    r"(-?\d[\d,]*(?:\.\d+)?"
    r"(?:\s*[eE][+-]?\d+|\s*[×x*]\s*10\^?\s*-?\d+)?)\s*"
    r"([A-Za-z°Ωμ/()·*^0-9.\-]{1,20}))", re.IGNORECASE)
_VALUE_UNIT_RE = re.compile(
    r"(-?\d[\d,]*(?:\.\d+)?)\s*(km/h|km/h²|m/s²|m/s|kJ|kcal|kPa|MJ|MeV|"
    r"kW|kg|km|cm|mm|cal|atm|mol|°C|°F|eV|mph|ms|Pa|L|mL|Hz|h|g|s|m|N|"
    r"J|W|V|A|Ω|K)\b")

# the sentence that asks for arithmetic (T5R.4 step 2)
_COMPUTE_REQUEST_RE = re.compile(
    r"\b(?:calculate|compute|how\s+much|how\s+many|how\s+long|how\s+far|"
    r"how\s+fast|what\s+is\s+the\s+(?:value|energy|force|speed|mass|"
    r"volume|power|current|work|heat)|find\s+the\s+(?:value|energy|"
    r"force|speed|mass|volume|power|current|work|heat))\b", re.IGNORECASE)


@dataclass
class Hop:
    """One explicit subquestion (T5R.5)."""
    hop_id: int
    subquestion: str
    kind: str                 # "fact" | "compute"
    needs_retrieval: bool

    def to_dict(self) -> dict:
        return {"hop_id": self.hop_id, "subquestion": self.subquestion,
                "kind": self.kind, "needs_retrieval": self.needs_retrieval}


@dataclass
class MultiHopPlan:
    subquestions: list[Hop] = field(default_factory=list)
    decomposed: bool = False
    method: str = "single"          # single | premise_split | two_questions

    @property
    def n_hops(self) -> int:
        return len(self.subquestions)

    def to_dict(self) -> dict:
        return {"decomposed": self.decomposed, "method": self.method,
                "n_hops": self.n_hops,
                "subquestions": [h.to_dict() for h in self.subquestions]}


@dataclass
class MixedPlan:
    """Explicit MIXED execution plan (T5R.4)."""
    constants: list[dict] = field(default_factory=list)   # {name,value,unit}
    computation: str | None = None                        # compute request text
    science_query: str | None = None                      # retrieval query
    tools: list[str] = field(default_factory=list)        # recommended T4 tools
    retrieve: bool = True
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"constants": self.constants,
                "computation": self.computation,
                "science_query": self.science_query, "tools": self.tools,
                "retrieve": self.retrieve, "signals": self.signals}


def _is_interrogative(sentence: str) -> bool:
    return sentence.strip().endswith("?")


def decompose_multi_hop(question: str) -> MultiHopPlan:
    """T5R.5: split a multi-hop question into explicit subquestions.

    Shapes seen in the frozen suite:
      * premise statement + dependent question  -> [premise-as-fact hop,
        final question hop]
      * two linked questions ("..., and ...?")   -> one hop per question
    Otherwise: single hop, decomposed=False (MATH/MIXED keep using the
    whole question)."""
    sentences = split_sentences(question)
    plan = MultiHopPlan()

    # single-sentence two-hop shape: "How is X, and how does Y?" — split
    # the question clause at the conjunction (deterministic)
    expanded: list[str] = []
    for s in sentences:
        parts = re.split(
            r",?\s+and\s+(?=(?:how|why|what|which|when)\b)",
            s, flags=re.IGNORECASE)
        if len(parts) > 1 and _is_interrogative(s):
            head = parts[0].strip()
            if not head.endswith("?"):
                head += "?"
            expanded.append(head)
            for p in parts[1:]:
                p = p.strip()
                expanded.append(p if p.endswith("?") else p + "?")
        else:
            expanded.append(s)
    sentences = expanded

    questions = [s for s in sentences if _is_interrogative(s)]
    premises = [s for s in sentences if not _is_interrogative(s)]

    def kind_of(text: str) -> str:
        routing = route_question(text)
        if routing["tools"] or _COMPUTE_REQUEST_RE.search(text):
            return "compute"
        return "fact"

    if len(questions) >= 2:
        for i, q in enumerate(questions, 1):
            kind = kind_of(q)
            plan.subquestions.append(
                Hop(hop_id=i, subquestion=q.strip(), kind=kind,
                    needs_retrieval=kind == "fact"))
        plan.decomposed = True
        plan.method = "two_questions"
        return plan

    if len(premises) >= 1 and len(questions) == 1:
        premise = " ".join(premises).strip()
        q = questions[0].strip()
        plan.subquestions.append(
            Hop(hop_id=1, subquestion=premise, kind="fact",
                needs_retrieval=False))
        kind = kind_of(q)
        plan.subquestions.append(
            Hop(hop_id=2, subquestion=q, kind=kind,
                needs_retrieval=kind == "fact"))
        plan.decomposed = True
        plan.method = "premise_split"
        return plan

    kind = kind_of(question)
    plan.subquestions.append(
        Hop(hop_id=1, subquestion=question.strip(), kind=kind,
            needs_retrieval=kind == "fact"))
    return plan


def extract_constants(question: str) -> list[dict]:
    """T5R.4: constants/formulas the question itself supplies, extracted
    deterministically: "specific heat of water = 4180 J/(kg*K)" ->
    {"name": "specific heat of water", "value": "4180",
     "unit": "J/(kg*K)"}. Values are copied verbatim, never converted."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for m in _CONST_ASSIGN_RE.finditer(question):
        name, value, unit = m.group(1).strip().rstrip(",;. "), \
            m.group(2).replace(",", ""), m.group(3)
        name = re.sub(r"^(?:a|an|the)\s+", "", name,
                      flags=re.IGNORECASE).strip()
        if not name or len(name.split()) < 1:
            continue
        key = (name.lower(), value)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "value": value, "unit": unit})
    if not out:
        for m in _VALUE_UNIT_RE.finditer(question):
            key = ("__value__", m.group(1))
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": "value", "value": m.group(1),
                        "unit": m.group(2)})
    return out


def plan_mixed(question: str) -> MixedPlan:
    """Build the explicit MIXED plan (T5R.4):

    1. extract constants the question supplies,
    2. identify the computation request (which sentence wants arithmetic),
    3. recommend T4 tools via the frozen T4 router (never executed here),
    4. decide retrieval: only when the science side needs facts the
       question does not already supply (T5R.6)."""
    plan = MixedPlan()
    routing = route_question(question)
    plan.tools = routing["tools"]
    plan.constants = extract_constants(question)
    plan.signals.append(f"tools={plan.tools}")

    sentences = split_sentences(question)
    compute_sents = [s for s in sentences if _COMPUTE_REQUEST_RE.search(s)]
    if compute_sents:
        plan.computation = " ".join(compute_sents)
        plan.signals.append("computation request present")

    # science side: sentences that are neither the compute request nor
    # pure constant assignments, if any, drive the retrieval query.
    # Retrieval runs ONLY when such a science side exists — a question
    # whose every sentence is constants + a compute request is
    # self-contained (T5R.6). A compute sentence that ALSO carries a
    # dependent explanatory clause ("... , and why ...?") has a science
    # side and keeps its retrieval query.
    _DEPENDENT_WHY_RE = re.compile(
        r"\b(?:and|also)\s+(?:why|how)\b|\bwhy\b|\bhow\s+does\b|\b"
        r"explain\b", re.IGNORECASE)
    science_sents = []
    for s in sentences:
        if s in compute_sents:
            if _DEPENDENT_WHY_RE.search(s):
                science_sents.append(s)
            continue
        if _SUPPLIED_CONSTANTS_RE.search(s) and \
                not _COMPUTE_REQUEST_RE.search(s):
            continue
        science_sents.append(s)
    if science_sents:
        plan.science_query = " ".join(science_sents)[:300]
    else:
        plan.retrieve = False
        plan.signals.append("self-contained computation — no retrieval")
    return plan