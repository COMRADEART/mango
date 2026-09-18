"""Exact-hash compatibility gate for the authorized T21R8 base repair."""
from __future__ import annotations

import json
from pathlib import Path

_CANONICAL_BASE = "bffe86b67107ba2a097aa3030acc17e687d84d25"
_COMPONENTS = {
    "code_runtime": {
        "historical_sha256":
            "cf9dc3c640d9410ee147e2ba8ca5ce42a2feeb36155d5ba61b462c94a988e627",
        "remediated_sha256":
            "b7f4468426fe275feb1a0c351660211d510f47da14ae453d1bc2d338d5bc9502",
        "changed_files": ["src/sciencemath/code/testsel.py"],
    },
    "memory_runtime": {
        "historical_sha256":
            "ac77f2d448345b4fb489911d6f9cd3c98dec06f4528ddf0e47e54852ccc4002d",
        "remediated_sha256":
            "2f6eb6da3ebfc612c71d21346e204cb29e713042ed39f926a155481fb52f5043",
        "changed_files": [
            "src/sciencemath/memory/pipeline.py",
            "src/sciencemath/memory/store.py",
        ],
    },
}
_SOURCE_FILES = sorted(
    path for component in _COMPONENTS.values()
    for path in component["changed_files"]
)


def t21r8_hash_matches(root: Path, component: str, actual: str,
                       historical: str) -> bool:
    """Accept the frozen hash or the one exact, evidenced remediation hash."""
    expected = _COMPONENTS.get(component)
    if expected is None or historical != expected["historical_sha256"]:
        return False
    if actual == historical:
        return True
    if actual != expected["remediated_sha256"]:
        return False

    artifact = json.loads(
        (root / "evaluations/t21r8/base_remediation_exception.json")
        .read_text(encoding="utf-8")
    )
    return (
        artifact.get("canonical_base") == _CANONICAL_BASE
        and artifact.get("authorization_status") ==
        "AUTHORIZED_BASE_REMEDIATION"
        and artifact.get("exception_scope") ==
        "restore canonical base test reproducibility only"
        and artifact.get("compatibility_policy") ==
        "historical hash or exact remediation hash only"
        and artifact.get("r7_raw_results_read") is False
        and artifact.get("r8_forensics_started") is False
        and artifact.get("historical_artifacts_modified") is False
        and sorted(artifact.get("authorized_source_files", [])) ==
        _SOURCE_FILES
        and artifact.get("implementation_hash_compatibility", {})
        .get(component) == expected
    )
