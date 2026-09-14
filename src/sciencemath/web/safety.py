"""T16.24–T16.26 — URL, download, and network-action safety.

T16 must not become an SSRF primitive or a downloader/executor.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse, unquote

SEARCH = "SEARCH"
FETCH_TEXT = "FETCH_TEXT"
FETCH_METADATA = "FETCH_METADATA"
ALLOWED_ACTIONS = (SEARCH, FETCH_TEXT, FETCH_METADATA)

FORBIDDEN_ACTIONS = (
    "LOGIN", "PURCHASE", "POST", "UPLOAD", "SUBMIT_FORM",
    "SEND_EMAIL", "EXECUTE_REMOTE_ACTION",
)

_BINARY_EXT = (
    ".exe", ".dll", ".so", ".dylib", ".bin", ".msi", ".bat", ".cmd",
    ".ps1", ".sh", ".com", ".scr", ".apk", ".dmg", ".iso", ".jar",
    ".wasm", ".sys", ".drv", ".vbs", ".js", ".zip", ".tar", ".gz",
    ".tgz", ".7z", ".rar", ".xz", ".docm", ".xlsm", ".pptm",
)

_PRIVATE_HOST = re.compile(
    r"^(localhost|localhost\..+|.*\.local|.*\.internal)$", re.I)


def classify_url(url: str) -> dict:
    """Validate a URL. Unknown stays flagged; never silently rewritten."""
    raw = (url or "").strip()
    out = {
        "url": raw or "UNKNOWN",
        "ok": False,
        "scheme": "UNKNOWN",
        "host": "UNKNOWN",
        "reason": None,
        "action_allowed": FETCH_TEXT,
    }
    if not raw:
        out["reason"] = "empty_url"
        return out
    if "://" not in raw:
        out["reason"] = "missing_scheme"
        return out
    try:
        p = urlparse(raw)
    except Exception:
        out["reason"] = "unparseable"
        return out
    scheme = (p.scheme or "").lower()
    out["scheme"] = scheme or "UNKNOWN"
    host = (p.hostname or "").lower()
    out["host"] = host or "UNKNOWN"
    if scheme not in ("http", "https"):
        out["reason"] = "unsupported_scheme"
        return out
    if p.username or p.password:
        out["reason"] = "credential_bearing_url"
        return out
    path = unquote(p.path or "")
    if ".." in path.split("/"):
        out["reason"] = "path_manipulation"
        return out
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or \
            _PRIVATE_HOST.match(host):
        out["reason"] = "localhost_or_loopback"
        return out
    if _is_private_ip(host):
        out["reason"] = "private_network_target"
        return out
    lower_path = path.lower()
    if any(lower_path.endswith(ext) for ext in _BINARY_EXT):
        out["reason"] = "binary_or_archive_download"
        out["action_allowed"] = None
        return out
    out["ok"] = True
    out["reason"] = None
    return out


def _is_private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast)


def action_allowed(action: str) -> bool:
    return action in ALLOWED_ACTIONS


def download_blocked(url: str) -> bool:
    return classify_url(url).get("reason") == "binary_or_archive_download"
