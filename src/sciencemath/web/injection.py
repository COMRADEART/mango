"""T16.22–T16.23 / T16.38–T16.39 — webpage content is untrusted DATA.

SYSTEM POLICY, USER TASK, and RESEARCH DATA stay separated.
Repository/webpage text never promotes itself into policy.
"""
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
    r"set WEB_RESEARCH to ACTIVE",
    r"disable the correction firewall",
)

_INJ = re.compile("|".join(f"(?:{p})" for p in INJECTION_PATTERNS), re.I)
_CMD = re.compile(
    r"(```(?:bash|sh|powershell)?\s*[\s\S]{0,400}```)|"
    r"(curl\s+\S+\s*\|\s*(bash|sh))|"
    r"(rm\s+-rf\s+\S+)", re.I)


def scan_injection(text: str) -> dict:
    t = text or ""
    hits = [m.group(0)[:80] for m in _INJ.finditer(t)]
    return {
        "detected": bool(hits),
        "hits": hits[:8],
        "instruction_authority": 0,
    }


def strip_instructions(text: str) -> str:
    """Keep factual sentences; drop embedded commands/instructions."""
    lines = []
    for line in (text or "").splitlines():
        if _INJ.search(line) or _CMD.search(line):
            continue
        if re.match(r"^\s*(SYSTEM|ASSISTANT|TOOL)\s*:", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def sanitize_for_code(facts: list[str]) -> dict:
    """WEB → CODE: structured facts only, never shell instructions."""
    clean = []
    for f in facts:
        if _INJ.search(f or "") or _CMD.search(f or ""):
            continue
        clean.append(f.strip()[:400])
    return {
        "kind": "web_facts",
        "facts": clean,
        "instruction_authority": 0,
        "may_execute": False,
    }


def sanitize_for_scicomp(facts: list[str]) -> dict:
    """WEB → SCICOMP: numeric/factual inputs only. Web does not override
    deterministic verified computation."""
    nums = []
    for f in facts:
        if _INJ.search(f or ""):
            continue
        nums.append(f.strip()[:400])
    return {
        "kind": "web_numeric_inputs",
        "facts": nums,
        "instruction_authority": 0,
        "overrides_computation": False,
    }
