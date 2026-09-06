"""T6.17 — Deterministic counterfactual / perturbation testing.

Given a base question record with a declared perturbation spec, produce a
controlled variant whose answer the SAME deterministic ground-truth
generator recomputes. Purposes: detect memorization (surface wording
changes, structure held) and confirm the answer tracks the changed fact.

Perturbation kinds (fixed, closed set — generation rules are stored in the
suite manifest so any variant is reproducible):

  change_value     swap a number; recomputed answer expected to change
  reverse_relation flip a stated relation ("twice" <-> "half")
  remove_fact      delete the key fact; expected behavior = uncertainty
  add_distractor   append an irrelevant fact; answer must NOT change
  alter_unit       change the unit; recomputed answer expected to change
  swap_variables   rename variables consistently; answer must NOT change

Spec schema (stored per base item):
  {"kind": "change_value", "find": "12", "replace": "18"}
  {"kind": "remove_fact", "sentence_contains": "frictionless"}
  {"kind": "alter_unit", "find": "km/h", "replace": "m/s",
   "answer_factor": 3.6}
"""
from __future__ import annotations

KINDS = ("change_value", "reverse_relation", "remove_fact", "add_distractor",
         "alter_unit", "swap_variables")

# kinds whose answer must NOT change vs kinds whose answer must change
ANSWER_UNCHANGED = ("add_distractor", "swap_variables")
ANSWER_CHANGES = ("change_value", "reverse_relation", "alter_unit")
ANSWER_INSUFFICIENT = ("remove_fact",)


def validate_spec(spec: dict) -> list[str]:
    errors = []
    kind = spec.get("kind")
    if kind not in KINDS:
        errors.append(f"kind {kind!r} not in {KINDS}")
        return errors
    if kind in ("change_value", "alter_unit", "swap_variables"):
        if not spec.get("find"):
            errors.append(f"{kind}: 'find' required")
    if kind in ("change_value", "alter_unit"):
        if not spec.get("replace"):
            errors.append(f"{kind}: 'replace' required")
    if kind == "remove_fact" and not spec.get("sentence_contains"):
        errors.append("remove_fact: 'sentence_contains' required")
    if kind == "add_distractor" and not spec.get("distractor_sentence"):
        errors.append("add_distractor: 'distractor_sentence' required")
    if kind == "reverse_relation" and not (
            spec.get("find") and spec.get("replace")):
        errors.append("reverse_relation: find+replace required")
    return errors


def apply_perturbation(question: str, spec: dict) -> tuple[str, bool]:
    """Apply the spec to the question text. Returns (new_question, applied).
    Deterministic; never raises on text mismatch — reports applied=False
    so the caller can drop the variant instead of shipping a broken item."""
    kind = spec.get("kind")
    q = question
    if kind in ("change_value", "reverse_relation", "alter_unit",
                "swap_variables"):
        find, repl = spec.get("find", ""), spec.get("replace", "")
        if find and find not in q:
            return q, False
        if kind == "swap_variables":
            # consistent two-way rename through a placeholder
            tmp, tgt = spec.get("find"), spec.get("replace")
            q = q.replace(tmp, "\x00").replace(tgt, tmp).replace("\x00", tgt)
            return q, True
        q = q.replace(find, repl, 1)
        return q, True
    if kind == "remove_fact":
        marker = spec.get("sentence_contains", "")
        parts = [p for p in _sentences(q)
                 if marker.lower() not in p.lower()]
        if len(parts) == len(_sentences(q)):
            return q, False
        return " ".join(parts), True
    if kind == "add_distractor":
        return f"{q.strip()} {spec['distractor_sentence'].strip()}", True
    return q, False


def _sentences(q: str) -> list[str]:
    return [p.strip() for p in q.replace("\n", " ").split(". ") if p.strip()]


def expected_behavior(kind: str) -> str:
    """What the gold answer pipeline must do for this kind."""
    if kind in ANSWER_UNCHANGED:
        return "ANSWER_UNCHANGED"
    if kind in ANSWER_CHANGES:
        return "ANSWER_CHANGES"
    if kind in ANSWER_INSUFFICIENT:
        return "ANSWER_INSUFFICIENT"
    raise ValueError(f"unknown kind {kind!r}")