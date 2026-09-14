"""Document content is untrusted DATA. Instruction authority 0."""
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
    r"set DOCUMENT to ACTIVE",
    r"disable the correction firewall",
    r"execute (this )?(macro|vba|javascript)",
    r"overwrite (the )?source",
)

_INJ = re.compile("|".join(f"(?:{p})" for p in INJECTION_PATTERNS), re.I)
_CMD = re.compile(
    r"(```(?:bash|sh|powershell|vba|javascript)?\s*[\s\S]{0,400}```)|"
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
    lines = []
    for line in (text or "").splitlines():
        if _INJ.search(line) or _CMD.search(line):
            continue
        if re.match(r"^\s*(SYSTEM|ASSISTANT|TOOL)\s*:", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def sanitize_for_code(facts: list[str]) -> dict:
    clean = []
    for f in facts:
        if _INJ.search(f or "") or _CMD.search(f or ""):
            continue
        clean.append((f or "").strip()[:400])
    return {
        "kind": "document_facts",
        "facts": clean,
        "instruction_authority": 0,
        "may_execute": False,
    }


def sanitize_for_scicomp(values: list) -> dict:
    nums = []
    for v in values:
        if isinstance(v, str) and _INJ.search(v):
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            nums.append(float(v))
        elif isinstance(v, str):
            try:
                nums.append(float(v))
            except ValueError:
                continue
    return {
        "kind": "document_numeric_inputs",
        "values": nums,
        "instruction_authority": 0,
        "may_override_scicomp": False,
    }


def sanitize_for_web(text: str) -> dict:
    """Local documents are not auto-uploaded."""
    return {
        "kind": "document_web_gate",
        "may_upload": False,
        "text_released": False,
        "instruction_authority": 0,
        "excerpt": "",
        "reason": "local_by_default",
    }
