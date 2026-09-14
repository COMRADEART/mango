"""T18.16 — MEMORY is not a credential vault."""
from __future__ import annotations

import re

SECRET_PATTERNS = (
    r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----",
    r"\bsk-[A-Za-z0-9]{20,}\b",
    r"\bghp_[A-Za-z0-9]{20,}\b",
    r"\bgithub_pat_[A-Za-z0-9_]{20,}\b",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bxox[bpsar]-[A-Za-z0-9-]{10,}\b",
    r"\bapi[_-]?key\s*[:=]\s*\S+",
    r"\b(?:password|passwd|pwd)\s*[:=]\s*\S+",
    r"\bsecret\s*[:=]\s*\S+",
    r"\bauth[_-]?token\s*[:=]\s*\S+",
    r"\bbearer\s+[A-Za-z0-9\-_\.]{16,}\b",
    r"\beyJ[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_\.]{10,}\b",
    r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://\S+:\S+@",
    r"Cookie:\s*\S+=\S+",
    r"\bAIza[0-9A-Za-z\-_]{20,}\b",
)

_SEC = re.compile("|".join(f"(?:{p})" for p in SECRET_PATTERNS), re.I)


def classify_sensitivity(text: str) -> str:
    if looks_like_secret(text):
        return "SECRET_LIKE"
    t = (text or "").lower()
    if any(k in t for k in ("ssn", "social security", "date of birth",
                             "home address", "medical record")):
        return "PERSONAL"
    if any(k in t for k in ("confidential", "internal only", "ndas")):
        return "CONFIDENTIAL"
    return "GENERAL"


def looks_like_secret(text: str) -> bool:
    return bool(_SEC.search(text or ""))


def secret_hits(text: str) -> list[str]:
    return [m.group(0)[:24] + "…" for m in _SEC.finditer(text or "")][:6]
