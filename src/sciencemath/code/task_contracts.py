"""T15R.14–T15R.16 — task contracts for data transforms and algorithms.

Derived from the request + existing tests (read-only). Never weakens
the frozen benchmark oracle; used only to steer repair prompts.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


_XFORM = re.compile(
    r"\b(rows_to_dict|normalize|transform|schema|csv|json|dict)\b", re.I)
_ALGO = re.compile(
    r"\b(fib|gcd|sort|search|algorithm|complexity|invariant)\b", re.I)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def extract_assert_examples(test_text: str) -> list[str]:
    examples = []
    for line in (test_text or "").splitlines():
        s = line.strip()
        if s.startswith("assert "):
            examples.append(s[:240])
    return examples


def _fn_name_from_stub(src_text: str) -> str | None:
    try:
        tree = ast.parse(src_text or "")
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return None


def data_xform_contract(request: str, *, src_text: str = "",
                        test_text: str = "") -> dict:
    """T15R.14 — concrete transformation contract before patching."""
    examples = extract_assert_examples(test_text)
    fn = _fn_name_from_stub(src_text) or ""
    ordering = any("==" in e and ("[" in e or "{" in e) for e in examples)
    types = []
    if any("dict" in e or "{" in e for e in examples):
        types.append("dict")
    if any("list" in e or "[" in e for e in examples):
        types.append("list")
    if any(re.search(r"\b(0\.\d|1\.0|/)\b", e) for e in examples):
        types.append("float")
    return {
        "kind": "data_xform",
        "function": fn,
        "request": (request or "")[:400],
        "input_schema": "derived from test assertions / stub signature",
        "expected_output_schema": examples[:6],
        "null_edge_handling": "preserve empty inputs; do not invent rows",
        "ordering_semantics": ("output order must match assertion literals"
                               if ordering else "not specified"),
        "type_preservation": types or ["as asserted"],
        "determinism": "required: same input => same output",
        "oracle_examples": examples[:6],
    }


def algo_contract(request: str, *, src_text: str = "",
                  test_text: str = "") -> dict:
    """T15R.15 — algorithm contract. Do not out-strict the frozen oracle."""
    examples = extract_assert_examples(test_text)
    fn = _fn_name_from_stub(src_text) or ""
    edges = []
    blob = (test_text or "") + "\n" + (request or "")
    if "range(0" in blob or "fib(0" in blob or "[0," in blob:
        edges.append("n=0 must match oracle")
    if "gcd" in blob.lower():
        edges.append("gcd(a,b)==gcd(b,a); gcd(a,0)==a")
    return {
        "kind": "algo",
        "function": fn,
        "request": (request or "")[:400],
        "input_domain": "as exercised by existing tests",
        "expected_complexity": "only if specified in the request",
        "edge_cases": edges or ["match oracle examples exactly"],
        "invariants": ["deterministic", "no hidden I/O"],
        "oracle_behavior": examples[:8],
        "note": "Satisfy the frozen benchmark assertions; do not reject "
                "an implementation that meets them.",
    }


def looks_like_data_xform(request: str) -> bool:
    return bool(_XFORM.search(request or ""))


def looks_like_algo(request: str) -> bool:
    return bool(_ALGO.search(request or ""))


def test_repair_intent(request: str) -> bool:
    r = (request or "").lower()
    return "repair the broken test" in r or (
        "without weakening" in r and "test" in r)


def format_contract(contract: dict) -> str:
    if not contract:
        return ""
    lines = [f"Task contract ({contract.get('kind')}):"]
    for k, v in contract.items():
        if k in ("kind", "request"):
            continue
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def load_related_tests(root: str | Path, tests_to_run: list | None) -> str:
    base = Path(root)
    chunks = []
    for rel in list(tests_to_run or [])[:4]:
        p = base / rel
        if p.is_file():
            chunks.append(f"--- {rel} (READ-ONLY oracle) ---\n"
                          + _read(p)[:2000])
    return "\n".join(chunks)
