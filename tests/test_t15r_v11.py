"""T15R.18 v1.1 metadata correction + microbench smoke."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "evaluations/t15/suites/mango-code-eval-v1"
V11 = ROOT / "evaluations/t15r/suites/mango-code-eval-v1.1"
RL = ROOT / "evaluations/t15r/suites/mango-code-repair-loop-v1"

IMMUTABLE = (
    "task_id", "category", "op", "request", "fixture", "checks",
    "context_files", "tests_to_run", "repair_file", "model_needed",
    "family", "review_file", "review_bad", "review_base",
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _rows(p: Path) -> list:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def test_v1_historical_checksum_unchanged():
    man = json.loads((V1 / "manifest.json").read_text(encoding="utf-8"))
    assert _sha(V1 / "final.jsonl") == man["final_sha256"]
    assert man["final_sha256"] == (
        "1676bd9e5a539efdb7d2160c1d88604d1f7d2fc8e2a7568f819189861389bddc")


def test_v11_only_corrects_import_err_golden():
    v1 = {r["task_id"]: r for r in _rows(V1 / "final.jsonl")}
    v11 = {r["task_id"]: r for r in _rows(V11 / "final.jsonl")}
    assert set(v1) == set(v11)
    changed = []
    for tid, a in v1.items():
        b = v11[tid]
        for k in IMMUTABLE:
            if k == "task_id":
                continue
            assert a.get(k) == b.get(k), (tid, k)
        if a.get("golden") != b.get("golden"):
            changed.append(tid)
            assert a.get("category") == "import_err"
            assert not a.get("golden")
            files = {g["file"] for g in b["golden"]}
            assert a.get("repair_file") in files
            assert all("old" not in g and "new" not in g for g in b["golden"])
    assert changed, "expected at least one import_err golden correction"
    man = json.loads((V11 / "manifest.json").read_text(encoding="utf-8"))
    assert man["behavioral_changes"] == "NONE"
    assert _sha(V11 / "final.jsonl") == man["final_sha256"]


def test_v11_unrelated_edit_metric_uses_repair_file():
    """Empty v1 golden made any touch unrelated; v1.1 counts repair_file."""
    row = {"category": "import_err", "files_touched": ["src/im02.py"]}
    gold_v1 = set()
    gold_v11 = {"src/im02.py"}
    extra_v1 = set(row["files_touched"]) - gold_v1
    extra_v11 = set(row["files_touched"]) - gold_v11
    assert extra_v1 == {"src/im02.py"}
    assert extra_v11 == set()


def test_repair_microbench_frozen_and_in_range():
    man = json.loads((RL / "manifest.json").read_text(encoding="utf-8"))
    assert 100 <= man["total"] <= 160
    assert man["dev_n"] + man["final_n"] == man["total"]
    assert _sha(RL / "final.jsonl") == man["final_sha256"]
    assert _sha(RL / "dev.jsonl") == man["dev_sha256"]
    required = {
        "single-step repair", "two-step repair", "three-step repair",
        "multi-file repair", "partial-progress",
        "regression-introducing patch", "data transform",
        "interface mismatch", "schema mismatch", "algorithm edge case",
        "unsafe partial patch", "protected-file mutation",
        "test weakening attempt", "already-best state",
    }
    assert required <= set(man["categories"])


def test_repair_microbench_rank_and_delta_smoke():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from t15r_run_repair_microbench import run_case  # noqa: E402
    rows = _rows(RL / "final.jsonl")
    rank = next(c for c in rows if c["harness"] == "rank")
    delta = next(c for c in rows if c["harness"] == "delta")
    assert run_case(rank)["ok"]
    assert run_case(delta)["ok"]
