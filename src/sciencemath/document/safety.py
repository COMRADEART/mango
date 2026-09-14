"""T17.17–T17.25 — path, size, archive, and execution safety.

Documents are untrusted DATA. Access only supplied/fixture files.
"""
from __future__ import annotations

import os
from pathlib import Path

from sciencemath.document.limits import DocumentLimits

RESERVED_WIN = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

ARCHIVE_EXT = {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".xz", ".bz2"}
MACRO_EXT = {".docm", ".xlsm", ".pptm", ".xlam", ".dotm"}
BINARY_EXT = {".exe", ".dll", ".so", ".dylib", ".bat", ".cmd", ".ps1",
              ".sh", ".com", ".scr", ".msi", ".wasm", ".js"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff",
             ".bmp"}


def _is_unc(s: str) -> bool:
    return s.startswith("\\\\") or s.startswith("//") or s.startswith("\\\\?\\")


def _is_device(s: str) -> bool:
    u = s.upper().replace("/", "\\")
    if u.startswith("\\\\.\\") or u.startswith("\\\\?\\"):
        return True
    stem = Path(s).stem.upper()
    return stem in RESERVED_WIN


def _is_symlink(path: Path) -> bool:
    try:
        return bool(path.is_symlink() or os.path.islink(path))
    except OSError:
        return True


def resolve_supplied(path: str | os.PathLike, *, sandbox_roots: list[Path],
                     allow_absolute_inside: bool = True) -> dict:
    """Resolve a user-supplied path. Escape => blocked."""
    raw = str(path or "")
    out = {
        "ok": False, "path": None, "reason": None, "raw": raw,
        "instruction_authority": 0,
    }
    if not raw.strip():
        out["reason"] = "empty_path"
        return out
    if "\x00" in raw:
        out["reason"] = "nul_byte"
        return out
    if _is_unc(raw):
        out["reason"] = "unc_path"
        return out
    if _is_device(raw):
        out["reason"] = "device_or_reserved_path"
        return out
    if raw.startswith("file:"):
        out["reason"] = "file_uri"
        return out
    candidate = Path(raw)
    if ".." in candidate.parts or raw.replace("\\", "/").split("/").count(".."):
        out["reason"] = "path_traversal"
        return out
    try:
        expanded = candidate.expanduser()
    except Exception:
        out["reason"] = "unparseable"
        return out
    if expanded.is_absolute() and not allow_absolute_inside:
        out["reason"] = "absolute_escape"
        return out
    roots = []
    for r in sandbox_roots:
        try:
            roots.append(r.resolve())
        except OSError:
            roots.append(r)
    resolved = None
    if expanded.is_absolute():
        resolved = expanded
    else:
        for r in roots:
            trial = r / expanded
            resolved = trial
            break
        if resolved is None:
            out["reason"] = "no_sandbox"
            return out
    try:
        resolved = resolved.resolve()
    except OSError:
        out["reason"] = "unresolvable"
        return out
    if _is_symlink(Path(raw)) or _is_symlink(resolved):
        out["reason"] = "symlink_or_junction"
        return out
    inside = False
    for r in roots:
        try:
            resolved.relative_to(r)
            inside = True
            break
        except ValueError:
            continue
    if not inside:
        out["reason"] = "absolute_escape"
        return out
    home = Path.home().resolve()
    sensitive = (
        home / ".ssh",
        home / ".gnupg",
        Path(os.environ.get("APPDATA", "C:/nonexistent")) / "Mozilla",
        Path(os.environ.get("LOCALAPPDATA", "C:/nonexistent")) / "Google" / "Chrome",
    )
    for s in sensitive:
        try:
            if resolved.is_relative_to(s.resolve()) if hasattr(resolved, "is_relative_to") else False:
                out["reason"] = "sensitive_store"
                return out
        except Exception:
            pass
        try:
            resolved.relative_to(s)
            out["reason"] = "sensitive_store"
            return out
        except Exception:
            pass
    out["ok"] = True
    out["path"] = resolved
    return out


def size_allowed(size: int, file_type: str,
                 limits: DocumentLimits | None = None) -> dict:
    limits = limits or DocumentLimits()
    caps = {
        "pdf": limits.max_pdf_bytes,
        "csv": limits.max_csv_bytes,
        "tsv": limits.max_csv_bytes,
        "json": limits.max_json_bytes,
        "jsonl": limits.max_json_bytes,
        "txt": limits.max_text_bytes,
        "md": limits.max_text_bytes,
        "markdown": limits.max_text_bytes,
        "html": limits.max_html_bytes,
        "xlsx": limits.max_csv_bytes,
    }
    cap = caps.get(file_type, limits.max_text_bytes)
    if size > cap:
        return {"ok": False, "reason": "oversized", "limit": cap, "size": size}
    return {"ok": True, "reason": None, "limit": cap, "size": size}


def archive_or_macro(filename: str) -> str | None:
    ext = Path(filename).suffix.lower()
    if ext in ARCHIVE_EXT:
        return "archive_unsupported"
    if ext in MACRO_EXT:
        return "macro_unsupported"
    if ext in BINARY_EXT:
        return "binary_unsupported"
    return None


def formula_like(value: str | None) -> bool:
    if not value:
        return False
    s = str(value)
    if not s:
        return False
    return s[0] in "=+-@"
