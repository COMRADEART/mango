"""T21R11 current code_runtime freeze and historical-anchor supersession."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r11"
FREEZE = OUT / "code_runtime_freeze.json"
SUPERSESSION = OUT / "historical_anchor_supersession.json"

HISTORICAL_CODE_RUNTIME = (
    "cf9dc3c640d9410ee147e2ba8ca5ce42a2feeb36155d5ba61b462c94a988e627"
)
CURRENT_CODE_RUNTIME = (
    "5cb8cd1c77e5ae6cfbd756ba20e8cca1d0367dc7bec422fc1ebb51eed39fb3aa"
)
EDITOR_LF = (
    "58b477a2230f87382a6368b5b8af18881092dfcffb735dad4396e6001570e3f5"
)
SECURITY_CANDIDATE = (
    "741a245664ce2bd0b916eafe521da05688852155"
)

SUPERSEDED_NODE_IDS = (
    "tests/test_scicomp_registry_active.py::"
    "test_scicomp_implementation_hash_unchanged",
    "tests/test_t19_post_merge_audit_cleanup.py::"
    "test_historical_floors_checksums_and_planner_untouched",
    "tests/test_t21r3_blind_holdout_contract.py::"
    "test_runtime_composites_unchanged_since_freeze",
    "tests/test_t21r4_blind_holdout_contract.py::"
    "test_runtime_composites_unchanged_since_freeze",
    "tests/test_t21r5_blind_holdout_contract.py::"
    "test_runtime_composites_unchanged_since_freeze",
)

HISTORICAL_ARTIFACTS = (
    ("evaluations/t19/frozen_components.json", ("composites", "code")),
    ("evaluations/t21r3/runtime_freeze.json",
     ("runtime_composites", "code_runtime")),
    ("evaluations/t21r4/runtime_freeze.json",
     ("runtime_composites", "code_runtime")),
    ("evaluations/t21r5/runtime_freeze.json",
     ("runtime_composites", "code_runtime")),
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _nul() -> bytes:
    return bytes([0])


def _sha_group(rel_dir: str) -> str:
    h = hashlib.sha256()
    sep = _nul()
    for p in sorted((ROOT / rel_dir).glob("*.py")):
        rel = (rel_dir + "/" + p.name).replace("\\", "/")
        h.update(rel.encode("utf-8"))
        h.update(sep)
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
        h.update(sep)
    return h.hexdigest()


def _sha_file(rel: str) -> str:
    data = (ROOT / rel).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _lookup(doc: dict, keys: tuple[str, ...]):
    cur = doc
    for key in keys:
        cur = cur[key]
    return cur


def _group_from_dir(workspace: Path) -> str:
    h = hashlib.sha256()
    sep = _nul()
    for p in sorted(workspace.glob("*.py")):
        rel = f"src/sciencemath/code/{p.name}"
        h.update(rel.encode("utf-8"))
        h.update(sep)
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
        h.update(sep)
    return h.hexdigest()


def test_code_runtime_freeze_matches_current_tree() -> None:
    freeze = _json(FREEZE)
    assert freeze["artifact"] == "T21R11_CODE_RUNTIME_FREEZE"
    assert freeze["auto_refresh"] is False
    assert freeze["composite_sha256"] == CURRENT_CODE_RUNTIME
    assert _sha_group("src/sciencemath/code") == CURRENT_CODE_RUNTIME
    assert freeze["editor_py_sha256_lf"] == EDITOR_LF
    assert _sha_file("src/sciencemath/code/editor.py") == EDITOR_LF
    assert freeze["security_candidate_commit"] == SECURITY_CANDIDATE
    assert freeze["historical_superseded_sha256"] == HISTORICAL_CODE_RUNTIME
    assert set(freeze["component_sha256"]) == {
        f"src/sciencemath/code/{p.name}"
        for p in (ROOT / "src/sciencemath/code").glob("*.py")
    }
    for path, digest in freeze["component_sha256"].items():
        assert _sha_file(path) == digest, path


def test_code_runtime_freeze_refuses_missing_component(tmp_path: Path) -> None:
    freeze = _json(FREEZE)
    workspace = tmp_path / "code"
    shutil.copytree(ROOT / "src/sciencemath/code", workspace)
    target = workspace / "editor.py"
    assert target.is_file()
    target.unlink()
    assert "editor.py" not in {p.name for p in workspace.glob("*.py")}
    assert _group_from_dir(workspace) != freeze["composite_sha256"]


def test_code_runtime_freeze_refuses_modified_editor(tmp_path: Path) -> None:
    freeze = _json(FREEZE)
    workspace = tmp_path / "code"
    shutil.copytree(ROOT / "src/sciencemath/code", workspace)
    target = workspace / "editor.py"
    target.write_bytes(target.read_bytes() + b"\n# tamper\n")
    assert _group_from_dir(workspace) != freeze["composite_sha256"]
    data = target.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(data).hexdigest() != EDITOR_LF


def test_code_runtime_freeze_refuses_extra_component(tmp_path: Path) -> None:
    freeze = _json(FREEZE)
    workspace = tmp_path / "code"
    shutil.copytree(ROOT / "src/sciencemath/code", workspace)
    (workspace / "extra_probe.py").write_text(
        "# unauthorized extra\n", encoding="utf-8", newline="\n")
    assert _group_from_dir(workspace) != freeze["composite_sha256"]
    assert "src/sciencemath/code/extra_probe.py" not in freeze["component_sha256"]


def test_code_runtime_freeze_does_not_auto_refresh() -> None:
    freeze = _json(FREEZE)
    assert freeze["auto_refresh"] is False
    text = FREEZE.read_text(encoding="utf-8")
    assert '"auto_refresh": false' in text


def test_historical_code_runtime_anchors_remain_unchanged() -> None:
    from test_scicomp_registry_active import CODE_IMPL
    assert CODE_IMPL == HISTORICAL_CODE_RUNTIME
    for rel, keys in HISTORICAL_ARTIFACTS:
        assert _lookup(_json(ROOT / rel), keys) == HISTORICAL_CODE_RUNTIME


def test_supersession_registry_binds_five_historical_anchors() -> None:
    doc = _json(SUPERSESSION)
    assert doc["artifact"] == "T21R11_HISTORICAL_ANCHOR_SUPERSESSION"
    assert doc["status"] == "SUPERSEDED_FOR_CURRENT_R11_ONLY"
    assert doc["classification"] == (
        "HISTORICAL_ANCHOR_NOT_APPLICABLE_TO_CURRENT_R11_TREE")
    assert doc["historical_artifacts_modified"] is False
    assert doc["historical_expectations_rewritten"] is False
    assert doc["tests_deleted_or_xfailed"] is False
    assert doc["live_security_behavior_nodes_included"] is False
    assert doc["current_r11_code_runtime_sha256"] == CURRENT_CODE_RUNTIME
    assert doc["historical_code_runtime_sha256"] == HISTORICAL_CODE_RUNTIME
    nodes = doc["superseded_nodes"]
    assert len(nodes) == 5
    assert [n["nodeid"] for n in nodes] == list(SUPERSEDED_NODE_IDS)
    assert all(n["historical_match"] is True for n in nodes)
    assert all(n["live_security_behavior"] is False for n in nodes)
    assert all(
        n["classification"] ==
        "HISTORICAL_ANCHOR_NOT_APPLICABLE_TO_CURRENT_R11_TREE"
        for n in nodes)
    acct = doc["applicable_gate_accounting"]
    assert acct["historical_exclusions"] == 6
    assert acct["historical_anchor_supersessions"] == 5
    assert acct["do_not_merge_into_single_excluded_count"] is True
    assert len(doc["historical_exclusions_unchanged"]) == 6
    for node in SUPERSEDED_NODE_IDS:
        path = ROOT / node.split("::")[0]
        assert path.is_file(), path
        fn = node.split("::")[1]
        assert f"def {fn}" in path.read_text(encoding="utf-8")
