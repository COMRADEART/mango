"""T15.14–T15.17, T15.33, T15.35 — command safety, secrets, network policy.

- Command-risk classifier: READ_ONLY / LOCAL_SAFE / REPO_MUTATION /
  DESTRUCTIVE / NETWORK / PRIVILEGED / PAID_EXTERNAL.
- Destructive-action guard: covered commands must yield CODE_NEEDS_PERMISSION.
- Secret handling: redaction only; secret contents never copied to evidence.
- Network policy: default offline; installs/publishes require permission.
- Protected components (T15.33): benchmark answers, frozen eval artifacts,
  T3 adapter, SciComp frozen engine, fidelity suites, correction firewall,
  release/provenance records.
- Repository prompt-injection defense (T15.35): repository text is DATA.
"""
from __future__ import annotations

import re

READ_ONLY = "READ_ONLY"
LOCAL_SAFE = "LOCAL_SAFE"
REPO_MUTATION = "REPO_MUTATION"
DESTRUCTIVE = "DESTRUCTIVE"
NETWORK = "NETWORK"
PRIVILEGED = "PRIVILEGED"
PAID_EXTERNAL = "PAID_EXTERNAL"

RISK_LEVELS = (READ_ONLY, LOCAL_SAFE, REPO_MUTATION, DESTRUCTIVE,
               NETWORK, PRIVILEGED, PAID_EXTERNAL)

# --- destructive command patterns (T15.15: must produce NEEDS_PERMISSION) ---
_DESTRUCTIVE_CMD = re.compile(
    r"(rm\s+-rf|Remove-Item\s+.*-Recurse|git\s+(reset\s+--hard|push\s+--force|"
    r"push\s+-f|branch\s+-D|rebase|filter-branch|clean\s+-fdx)|"
    r"format\s+[a-z]:|mkfs|dd\s+.*of=/dev|del\s+/[fs]|rd\s+/s|"
    r"revoke|credential|publish\s+-)", re.I)

_PRIVILEGED = re.compile(
    r"(^\s*sudo\b|runas|Start-Process\s+-Verb\s+RunAs|set-executionpolicy\s+"
    r"bypass|takeown|icacls.*\/grant)", re.I)

_PAID = re.compile(
    r"(rent (a |an )?(a100|h100|gpu)|launch paid|buy cloud gpu|"
    r"spin up a cluster|paid (gpu|api|compute)|--paid|billing)", re.I)

_NETWORK = re.compile(
    r"(curl|wget|Invoke-WebRequest|Invoke-RestMethod|pip\s+install|"
    r"npm\s+(install|publish)|conda\s+install|git\s+(push|fetch|pull|clone)|"
    r"ssh\s+|scp\s+|ftp\s+|http://|https://)", re.I)

# pip/pytest/git-read are local-safe developer commands.
_LOCAL_SAFE = re.compile(
    r"^\s*(pytest|python(\.exe)?\s+-m\s+pytest|python\s+\S+\.py|"
    r"node\s+--test|npm\s+test|go\s+test|cargo\s+test|"
    r"python\s+-c\s+)", re.I)

_READ_ONLY = re.compile(
    r"^\s*(git\s+(status|diff|log|show|branch(\s+--show-current)?)"
    r"|dir|ls|cat\s|type\s|Get-ChildItem|Select-String|findstr)\b", re.I)


def classify_command(cmd: str) -> str:
    """Classify a shell command into exactly one risk level.

    Precedence: PRIVILEGED > DESTRUCTIVE > PAID_EXTERNAL > NETWORK >
    REPO_MUTATION (handled by caller for file edits) > LOCAL_SAFE >
    READ_ONLY. Unknown commands default to REPO_MUTATION (fail closed:
    never assume a novel command is safe).
    """
    c = (cmd or "").strip()
    if not c:
        return READ_ONLY
    if _PRIVILEGED.search(c):
        return PRIVILEGED
    if _DESTRUCTIVE_CMD.search(c):
        return DESTRUCTIVE
    if _PAID.search(c):
        return PAID_EXTERNAL
    if _NETWORK.search(c):
        return NETWORK
    if _LOCAL_SAFE.search(c):
        return LOCAL_SAFE
    if _READ_ONLY.search(c):
        return READ_ONLY
    return REPO_MUTATION


def command_allowed(cmd: str, *, network_permitted: bool = False) -> tuple:
    """Return (allowed: bool, risk: str, reason: str).

    DESTRUCTIVE / PRIVILEGED / PAID_EXTERNAL are never allowed inline —
    they must surface as CODE_NEEDS_PERMISSION. NETWORK requires an
    explicit grant. Everything else is allowed within the task sandbox.
    """
    risk = classify_command(cmd)
    if risk in (DESTRUCTIVE, PRIVILEGED, PAID_EXTERNAL):
        return False, risk, (
            f"{risk} command requires explicit permission; "
            "emit CODE_NEEDS_PERMISSION")
    if risk == NETWORK and not network_permitted:
        return False, risk, (
            "network access requires explicit permission; "
            "emit CODE_NEEDS_PERMISSION")
    return True, risk, ""


# --- secret handling (T15.16) ------------------------------------------------
_SECRET = re.compile(
    r"((?:api[_-]?key|apikey|auth[_-]?token|access[_-]?token|secret|"
    r"password|passwd|pwd|private[_-]?key|bearer|session[_-]?cookie|"
    r"connection[_-]?string)\s*[:=]\s*)(['\"]?)([^'\"\s;]{3,})(['\"]?)"
    r"|(ghp_[A-Za-z0-9]{8,}|gho_[A-Za-z0-9]{8,}|"
    r"sk-(live|test)-[A-Za-z0-9]{8,}|xox[bap]-[A-Za-z0-9-]{8,}|"
    r"AKIA[0-9A-Z]{16})", re.I)

_SECRET_LIKE_FILENAME = re.compile(
    r"(\.pem$|\.key$|id_rsa|id_ed25519|\.p12$|\.pfx$|"
    r"credentials?\.json$|\.netrc$|_token\.txt$)", re.I)


def redact_secrets(text: str) -> tuple:
    """Redact secret-like values. Returns (redacted, detections: int).

    Only the COUNT is recorded; contents are never copied to evidence.
    """
    if not text:
        return text, 0
    detections = len(_SECRET.findall(text))

    def _sub(m: re.Match) -> str:
        if m.group(1):
            return m.group(1) + m.group(2) + "***REDACTED***" + m.group(4)
        return "***REDACTED***"

    return _SECRET.sub(_sub, text), detections


def secret_like_path(path: str) -> bool:
    return bool(_SECRET_LIKE_FILENAME.search((path or "").replace("\\", "/")))


# --- protected components (T15.33) -------------------------------------------
# Unless the benchmark task explicitly requires them, CODE must not edit:
PROTECTED_PREFIXES = (
    "evaluations/t11/",
    "evaluations/t12/suites/",
    "evaluations/t13/suites/",
    "evaluations/t14/suites/",
    "evaluations/t14r/suites/",
    "evaluations/t14r2/ode_microbench/",
    "evaluations/t15/suites/mango-code-eval-v1/final",
    "training/adapters/sciencemath-v0.1-t3/",
    "src/sciencemath/scicomp/fidelity.py",
    "src/sciencemath/scicomp/semantic.py",
    "src/sciencemath/scicomp/router.py",
    "src/sciencemath/executive/correction.py",
    "evaluations/t14r2/final_audit.json",
    "evaluations/t15/final_audit.json",
    "evaluations/t15/t15_entry_gate.json",
    "evaluations/t15/frozen_components.json",
)
PROTECTED_SUFFIXES = (".safetensors",)


def protected_edit(path: str, *, task_allows: tuple = ()) -> bool:
    """True if editing `path` is a protected-component violation."""
    p = (path or "").replace("\\", "/").lstrip("./")
    for allow in task_allows:
        if p == allow or p.startswith(allow.rstrip("/") + "/"):
            return False
    if p.endswith(PROTECTED_SUFFIXES):
        return True
    return any(p == pre or p.startswith(pre) for pre in PROTECTED_PREFIXES)


# --- repository prompt-injection defense (T15.35) -----------------------------
_INJECTION = re.compile(
    r"(ignore (all |your |previous |above )?instructions|disregard .*"
    r"instructions|you are now |new instructions:|system prompt|"
    r"upload .*secrets?|exfiltrat|delete all tests|run .*curl.*\|\s*"
    r"(bash|sh)|disable .*safe|bypass .*safe|do not (verify|test|check))",
    re.I)


def detect_prompt_injection(text: str) -> bool:
    """Detect instruction-override attempts embedded in repository DATA."""
    return bool(_INJECTION.search(text or ""))


_INJECTION_FILES = re.compile(
    r"(?i)(exfil|backdoor|payload|reverse.?shell|keylog|ransom|miner|c2server)")


def suspicious_filename(path: str) -> bool:
    p = (path or "").replace("\\", "/")
    return bool(_INJECTION_FILES.search(p))
