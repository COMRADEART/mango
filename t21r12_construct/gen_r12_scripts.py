#!/usr/bin/env python3
"""Generate R12 construction scripts from R11 templates + method patches."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path.cwd()
SCRIPTS = ROOT / "scripts"
METHODS = Path(__file__).resolve().parent / "methods"

CONSTRUCTION_TOKEN = "T21R12_REAL_BLIND_CONSTRUCTION_AUTHORIZED"
SEAL_TOKEN = "T21R12_BLIND_SEAL_AUTHORIZED"


def replace_method(src: str, method_name: str, new_body: str) -> str:
    pattern = rf"(    def {method_name}\([^\)]*\)[^\n]*\n)"
    m = re.search(pattern, src)
    if not m:
        raise SystemExit(f"method not found: {method_name}")
    rest = src[m.end():]
    end_rel = None
    for match in re.finditer(r"\n    def |\n\ndef |\n# ----", rest):
        end_rel = match.start()
        break
    if end_rel is None:
        raise SystemExit(f"cannot find end of {method_name}")
    end = m.end() + end_rel
    return src[:m.start()] + new_body.rstrip() + "\n\n" + src[end:].lstrip("\n")


def transform_globals(src: str) -> str:
    for a, b in [
        ("T21R11", "T21R12"),
        ("t21r11", "t21r12"),
        ("r11b", "r12b"),
        ("R11", "R12"),
        ("mango-r11b-v1", "mango-r12b-v1"),
        ("mango-t21r11-", "mango-t21r12-"),
        ("gk_holdout_t21r11", "gk_holdout_t21r12"),
        ("pre11q-", "pre12q-"),
    ]:
        src = src.replace(a, b)
    src = src.replace(
        '"construction_tags": ["multisource_path", design]',
        '"construction_tags": [design, "meta:multisource_path"]',
    )
    src = src.replace(
        'row["construction_tags"].append("relation_surface_sensitive")',
        'row["construction_tags"].append("meta:relation_surface_sensitive")',
    )
    src = src.replace(
        '"construction_tags": ["multisource_path"]',
        '"construction_tags": ["meta:multisource_path"]',
    )
    src = src.replace(
        '"construction_tags": ["partial_path_ie_stress"]',
        '"construction_tags": ["meta:partial_path_ie_stress"]',
    )
    src = src.replace(
        '["query_injection_or_spoof"]',
        '["meta:query_injection_or_spoof"]',
    )
    src = src.replace(
        'row["construction_tags"] = ["relation_surface_sensitive"]',
        'row["construction_tags"] = ["meta:relation_surface_sensitive"]',
    )
    return src


def write_author() -> None:
    src = (SCRIPTS / "t21r11_blind_author.py").read_text(encoding="utf-8")
    out = transform_globals(src)
    if "from collections import Counter" not in out:
        out = out.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nfrom collections import Counter\n",
            1,
        )
    for name in ["citation", "crossdomain", "temporal", "adversarial", "conflict", "mayors"]:
        body = (METHODS / f"{name}.py.txt").read_text(encoding="utf-8")
        method = "_build_mayors" if name == "mayors" else f"_build_{name}"
        out = replace_method(out, method, body)
    (SCRIPTS / "t21r12_blind_author.py").write_text(out, encoding="utf-8", newline="\n")
    print("wrote t21r12_blind_author.py", len(out))


def adapt_file(src_name: str, dst_name: str, is_freeze: bool = False) -> None:
    text = (SCRIPTS / src_name).read_text(encoding="utf-8")
    for a, b in [
        ("T21R11", "T21R12"),
        ("t21r11", "t21r12"),
        ("r11b", "r12b"),
        ("R11", "R12"),
        ("mango-r11b-v1", "mango-r12b-v1"),
        ("mango-t21r11-", "mango-t21r12-"),
        ("gk_holdout_t21r11", "gk_holdout_t21r12"),
        ("pre11q-", "pre12q-"),
    ]:
        text = text.replace(a, b)
    # authorization phrases
    text = text.replace("T21R12_BLIND_CONSTRUCTION_AUTHORIZED", CONSTRUCTION_TOKEN)
    text = text.replace("T21R11_BLIND_CONSTRUCTION_AUTHORIZED", CONSTRUCTION_TOKEN)
    if is_freeze:
        text = re.sub(
            r'AUTHORIZATION_PHRASE = "[^"]+"',
            f'AUTHORIZATION_PHRASE = "{SEAL_TOKEN}"',
            text,
            count=1,
        )
        text = text.replace('SCHEMA_VERSION = "t21r11-seal-v1"', 'SCHEMA_VERSION = "t21r12-seal-v1"')
        text = text.replace('SCHEMA_VERSION = "t21r12-seal-v1"', 'SCHEMA_VERSION = "t21r12-seal-v1"')
    else:
        text = re.sub(
            r'AUTHORIZATION_PHRASE = "[^"]+"',
            f'AUTHORIZATION_PHRASE = "{CONSTRUCTION_TOKEN}"',
            text,
            count=1,
        )
    (SCRIPTS / dst_name).write_text(text, encoding="utf-8", newline="\n")
    print("wrote", dst_name)


def main() -> int:
    if not (SCRIPTS / "t21r11_blind_author.py").is_file():
        raise SystemExit("run from mango repo root")
    write_author()
    adapt_file("t21r11_world.py", "t21r12_world.py")
    adapt_file("t21r11_build_suites.py", "t21r12_build_suites.py")
    adapt_file("t21r11_uniqueness.py", "t21r12_uniqueness.py")
    adapt_file("t21r11_blindness_audit.py", "t21r12_blindness_audit.py")
    adapt_file("t21r11_construction_audit.py", "t21r12_construction_audit.py")
    adapt_file("t21r11_freeze_holdout.py", "t21r12_freeze_holdout.py", is_freeze=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
