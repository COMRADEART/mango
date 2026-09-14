"""T18.7 typed MEMORY operations. Stored text never becomes a command."""
from __future__ import annotations

import re

MEMORY_STORE = "MEMORY_STORE"
MEMORY_SEARCH = "MEMORY_SEARCH"
MEMORY_RETRIEVE = "MEMORY_RETRIEVE"
MEMORY_LIST = "MEMORY_LIST"
MEMORY_UPDATE = "MEMORY_UPDATE"
MEMORY_SUPERSEDE = "MEMORY_SUPERSEDE"
MEMORY_DELETE = "MEMORY_DELETE"
MEMORY_FORGET_SCOPE = "MEMORY_FORGET_SCOPE"
MEMORY_EXPLAIN = "MEMORY_EXPLAIN"
MEMORY_CONFLICT = "MEMORY_CONFLICT"
MEMORY_NO_MATCH = "MEMORY_NO_MATCH"
MEMORY_EXPIRED = "MEMORY_EXPIRED"
MEMORY_BLOCKED_SECRET = "MEMORY_BLOCKED_SECRET"
MEMORY_BLOCKED_POLICY = "MEMORY_BLOCKED_POLICY"
MEMORY_BLOCKED_LIMIT = "MEMORY_BLOCKED_LIMIT"

MEMORY_OPS = (
    MEMORY_STORE, MEMORY_SEARCH, MEMORY_RETRIEVE, MEMORY_LIST,
    MEMORY_UPDATE, MEMORY_SUPERSEDE, MEMORY_DELETE, MEMORY_FORGET_SCOPE,
    MEMORY_EXPLAIN, MEMORY_CONFLICT, MEMORY_NO_MATCH, MEMORY_EXPIRED,
    MEMORY_BLOCKED_SECRET, MEMORY_BLOCKED_POLICY, MEMORY_BLOCKED_LIMIT,
)

_STORE = re.compile(
    r"\b(remember (that|this|it|the)|please remember|save (this|that)|"
    r"store (this|that|the fact)|don'?t forget that|"
    r"keep in mind that)\b", re.I)
_RETRIEVE = re.compile(
    r"\b(what (did we|do you remember|database did we|is my preferred|"
    r"did i tell you|editor did we)|recall|from last session|"
    r"what do you remember|look up (in |my )?memory)\b", re.I)
_SEARCH = re.compile(
    r"\b(search (my |the )?memor|find memories? (about|for))\b", re.I)
_LIST = re.compile(r"\b(list (my |the )?(active )?memories)\b", re.I)
_DELETE = re.compile(
    r"\b(delete (that |this |the )?memory|forget that fact|"
    r"erase (that |this )?memory)\b", re.I)
_FORGET = re.compile(
    r"\b(forget (this |the )?(session|project|everything|"
    r"all memories)|forget scope)\b", re.I)
_EXPLAIN = re.compile(
    r"\b(why (did you retrieve|was this remembered)|"
    r"explain (this |the )?(retrieval|memory))\b", re.I)
_UPDATE = re.compile(
    r"\b(update (the |that )?memory|correction:|"
    r"actually (it'?s|it is|the)|changed to|now (is|it'?s))\b", re.I)
_MATH = re.compile(
    r"^\s*(what('s| is)|calculate|compute|evaluate)?\s*"
    r"[\d\.\s\+\-\*\/\^\(\)]+\s*\??\s*$", re.I)


def classify_request(text: str) -> str:
    q = (text or "").strip()
    if not q:
        return MEMORY_NO_MATCH
    if _MATH.match(q):
        return MEMORY_NO_MATCH
    if _FORGET.search(q):
        return MEMORY_FORGET_SCOPE
    if _DELETE.search(q):
        return MEMORY_DELETE
    if _EXPLAIN.search(q):
        return MEMORY_EXPLAIN
    if _LIST.search(q):
        return MEMORY_LIST
    if _SEARCH.search(q):
        return MEMORY_SEARCH
    if _UPDATE.search(q) and _STORE.search(q):
        return MEMORY_SUPERSEDE
    if _UPDATE.search(q):
        return MEMORY_UPDATE
    if _STORE.search(q):
        return MEMORY_STORE
    if _RETRIEVE.search(q):
        return MEMORY_RETRIEVE
    if q.endswith("?") or q.lower().startswith(("what ", "which ", "where ")):
        return MEMORY_RETRIEVE
    return MEMORY_NO_MATCH


def is_explicit_write(text: str) -> bool:
    return bool(_STORE.search(text or ""))
