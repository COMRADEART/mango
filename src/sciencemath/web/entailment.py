"""T16.14 — evidence entailment.

Do not cite a source merely because it shares keywords.
"""
from __future__ import annotations

import re

ENTAILS = "ENTAILS"
PARTIALLY_ENTAILS = "PARTIALLY_ENTAILS"
DOES_NOT_ENTAIL = "DOES_NOT_ENTAIL"
CONTRADICTS = "CONTRADICTS"
UNCLEAR = "UNCLEAR"

ENTAILMENT_STATUSES = (
    ENTAILS, PARTIALLY_ENTAILS, DOES_NOT_ENTAIL, CONTRADICTS, UNCLEAR,
)

_TOKEN = re.compile(r"[a-z0-9]{3,}", re.I)
_NUM = re.compile(
    r"(?<![A-Za-z])(?:\d+\.\d+(?:e[+\-]?\d+)?|\d{2,}(?:e[+\-]?\d+)?)",
    re.I,
)
_PATH = re.compile(r"/[A-Za-z0-9._/-]+")
_PROPER = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
_NEG = re.compile(
    r"\b(not|no longer|never|false|incorrect|former|ex-|denied|"
    r"untrue|debunked|misinformation)\b", re.I)


def _tok(text: str) -> set[str]:
    t = {x.lower() for x in _TOKEN.findall(text or "")}
    t.update(p.lower().rstrip("/") for p in _PATH.findall(text or ""))
    return t


def _names(text: str) -> set[str]:
    out = set()
    for m in _PROPER.finditer(text or ""):
        parts = [p for p in m.group(1).split() if p]
        if parts and parts[0] in ("The", "A", "An"):
            parts = parts[1:]
        if len(parts) >= 2:
            out.add(" ".join(parts).lower())
    return out


_STOP = {
    "the", "a", "an", "of", "and", "or", "to", "for", "in", "on", "is",
    "are", "was", "were", "what", "who", "which", "this", "that", "with",
    "from", "look", "search", "tell", "does", "did",
}


def entailment(claim: str, evidence: str) -> str:
    c = (claim or "").strip()
    e = (evidence or "").strip()
    if not c or not e:
        return UNCLEAR
    ct, et = _tok(c), _tok(e)
    if not ct:
        return UNCLEAR
    cov = len(ct & et) / len(ct)
    distinctive = {t for t in ct if t not in _STOP and len(t) >= 3}
    dist_cov = (len(distinctive & et) / len(distinctive)) if distinctive else 0.0
    cnums = _NUM.findall(c)
    enums = set(_NUM.findall(e))
    nums_ok = all(n in enums for n in cnums) if cnums else True
    nums_conflict = bool(cnums) and not nums_ok and bool(enums)
    neg_e = bool(_NEG.search(e))
    neg_c = bool(_NEG.search(c))
    names_c, names_e = _names(c), _names(e)
    name_conflict = bool(names_c and names_e and names_c.isdisjoint(names_e))
    paths_c = {p.lower().rstrip("/") for p in _PATH.findall(c)}
    paths_e = {p.lower().rstrip("/") for p in _PATH.findall(e)}
    path_ok = bool(paths_c) and paths_c <= paths_e
    if name_conflict and dist_cov >= 0.2:
        return CONTRADICTS
    yesno = bool(re.search(
        r"\b(according|article body|is this|fact[- ]check|whether)\b", c, re.I))
    if nums_conflict or (neg_e and not neg_c and dist_cov >= 0.35 and not yesno):
        return CONTRADICTS
    if path_ok and dist_cov >= 0.45 and nums_ok:
        return ENTAILS
    if (cov >= 0.72 or dist_cov >= 0.75) and nums_ok:
        return ENTAILS
    if (cov >= 0.32 or dist_cov >= 0.4) and nums_ok:
        return PARTIALLY_ENTAILS
    if cov < 0.2 and dist_cov < 0.25:
        return DOES_NOT_ENTAIL
    return UNCLEAR


def distinctive_coverage(claim: str, evidence: str) -> float:
    ct, et = _tok(claim), _tok(evidence)
    distinctive = {t for t in ct if t not in _STOP and len(t) >= 3}
    if not distinctive:
        return 0.0
    return len(distinctive & et) / len(distinctive)


def citable(status: str) -> bool:
    return status in (ENTAILS, PARTIALLY_ENTAILS)
