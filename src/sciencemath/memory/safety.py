"""Stored memory is untrusted DATA. Instruction authority is always 0."""
from __future__ import annotations

import re

INJECTION_PATTERNS = (
    r"ignore (all )?(prior|previous|above) instructions",
    r"you are now",
    r"system prompt",
    r"\[system\]",
    r"upload your secrets",
    r"exfiltrat",
    r"run this command",
    r"delete your files",
    r"change your evaluation answer",
    r"curl .+\|\s*(bash|sh)",
    r"rm\s+-rf",
    r"benchmark tamper",
    r"set MEMORY to ACTIVE",
    r"disable the correction firewall",
    r"reveal secrets",
    r"change your safety rules",
)

_INJ = re.compile("|".join(f"(?:{p})" for p in INJECTION_PATTERNS), re.I)
_CMD = re.compile(
    r"(```(?:bash|sh|powershell)?\s*[\s\S]{0,400}```)|"
    r"(curl\s+\S+\s*\|\s*(bash|sh))|"
    r"(rm\s+-rf\s+\S+)", re.I)

POLICY_PATTERNS = (
    r"change (your |the )?safety (rules|policy)",
    r"rewrite (the )?system prompt",
    r"alter (the )?(evaluation|promotion) floors",
    r"promote (the )?executive router",
    r"set (MEMORY|DOCUMENT|CODE|WEB_RESEARCH) to ACTIVE",
    r"disable (the )?(correction firewall|paid.compute (gate|policy))",
    r"grant (unrestricted )?tool permission",
    r"ignore paid.compute",
    r"override (the )?router promotion",
)
_POL = re.compile("|".join(f"(?:{p})" for p in POLICY_PATTERNS), re.I)

_QUOTE = re.compile(
    r"\b(remember (this|the) (quote|text|string|payload|sentence)|"
    r"store (this|the) (quoted|literal) )", re.I)


def scan_injection(text: str) -> dict:
    t = text or ""
    hits = [m.group(0)[:80] for m in _INJ.finditer(t)]
    return {
        "detected": bool(hits),
        "hits": hits[:8],
        "instruction_authority": 0,
    }


def is_policy_write(text: str, *, explicit_quote: bool = False) -> bool:
    if explicit_quote or _QUOTE.search(text or ""):
        return False
    return bool(_POL.search(text or ""))


def strip_instructions(text: str) -> str:
    lines = []
    for line in (text or "").splitlines():
        if _INJ.search(line) or _CMD.search(line):
            continue
        if re.match(r"^\s*(SYSTEM|ASSISTANT|TOOL)\s*:", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def sanitize_facts(facts: list[str], *, kind: str) -> dict:
    clean = []
    for f in facts:
        if _INJ.search(f or "") or _CMD.search(f or ""):
            continue
        clean.append((f or "").strip()[:400])
    return {
        "kind": kind,
        "facts": clean,
        "instruction_authority": 0,
        "may_execute": False,
        "may_override_policy": False,
        "may_override_tools": False,
    }
