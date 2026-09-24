#!/usr/bin/env python3
"""One-shot T25 protocol clone: t24_protocol -> t25_protocol with namespace swaps.

This is a build-time helper (not part of the frozen protocol surface). The
resulting t25_protocol modules are then hand-adapted (anchor, contract, policy,
firewall, exclusions, freeze, doctor) before use.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "t24_protocol"
DST = ROOT / "t25_protocol"

# Ordered: longest / most specific first.
SUBSTITUTIONS: list[tuple[str, str]] = [
    ("t24-shadow-disposable", "t25-shadow-disposable"),
    ("t24-qualification", "t25-qualification"),
    ("t24-doctor-", "t25-doctor-"),
    ("t24-doctor", "t25-doctor"),
    ("t24-rehearsal-", "t25-rehearsal-"),
    ("t24-corpus-", "t25-corpus-"),
    ("t24-private-", "t25-private-"),
    ("t24-private://", "t25-private://"),
    ("t24-private", "t25-private"),
    ("t24_protocol", "t25_protocol"),
    ("t23_protocol", "t23_protocol"),  # anchor only (rewritten by hand below)
    ("t24-fingerprint-set", "t25-fingerprint-set"),
    ("t24-fingerprint", "t25-fingerprint"),
    ("t24_", "t25_"),
    ("t24-", "t25-"),
    ('"t24"', '"t25"'),
    ("'t24'", "'t25'"),
    ("t24", "t25"),
    ("T24_", "T25_"),
    ("T24-", "T25-"),
    ("T24", "T25"),
]

KEEP_AS_IS = {"anchor_t23.py"}  # replaced by hand-written anchor_t24.py


def transform(text: str) -> str:
    for old, new in SUBSTITUTIONS:
        text = text.replace(old, new)
    return text


def main() -> None:
    if (DST / "status_contract.py").exists():
        # Preserve the already-written remediation modules.
        keep = ROOT / ".t25_keep"
        keep.mkdir(exist_ok=True)
        for name in ("status_contract.py", "__init__.py"):
            shutil.copy2(DST / name, keep / name)
    if DST.exists():
        shutil.rmtree(DST, ignore_errors=True)
    if DST.exists():
        for stale in DST.glob("*.py"):
            stale.unlink()
    DST.mkdir(parents=True, exist_ok=True)
    keep_dir = ROOT / ".t25_keep"
    if keep_dir.exists():
        for name in ("status_contract.py", "__init__.py"):
            shutil.copy2(keep_dir / name, DST / name)
        shutil.rmtree(keep_dir)
    for path in sorted(SRC.glob("*.py")):
        if path.name in KEEP_AS_IS:
            continue
        target = DST / path.name.replace("anchor_t23.py", "anchor_t24.py")
        target.write_text(transform(path.read_text(encoding="utf-8")), encoding="utf-8",
                          newline="\n")
    print("t25_protocol cloned:", sorted(p.name for p in DST.glob("*.py")))


if __name__ == "__main__":
    main()