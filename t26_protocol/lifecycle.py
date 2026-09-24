"""Private one-shot T26 construction/evaluation architecture (not invoked now)."""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from sciencemath.integrated.runner import IntegratedRunner, validate_plan
from .contract import FAMILIES
from .scorer import score_suite

CONSTRUCTION_TOKEN = "T26_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION"
EVALUATION_TOKEN = "T26_ONE_SHOT_OFFICIAL_EVALUATION"
SCHEME = "t26-private://"
STORE_ID = "T26-STORE-01"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def require_token(token: str, phase: str) -> None:
    expected = CONSTRUCTION_TOKEN if phase == "construction" else EVALUATION_TOKEN if phase == "evaluation" else None
    if token != expected:
        raise PermissionError("exact T26 phase authorization token required")


class T26PrivateStore:
    def __init__(self, root: Path, public_repo: Path):
        self.root = Path(root).resolve()
        repo = Path(public_repo).resolve()
        if self.root == repo or repo in self.root.parents or self.root in repo.parents:
            raise ValueError("T26 private store must be separate from public Git")
        if self.root.name != STORE_ID:
            raise ValueError("wrong private store identity")
        self.public_repo = repo
        self.namespace = self.root / "t26"

    def path(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise ValueError("invalid T26 private locator")
        p = (self.namespace / relative).resolve()
        if self.namespace not in p.parents:
            raise ValueError("private locator escape")
        return p

    def locator(self, relative: str) -> str:
        self.path(relative)
        return f"{SCHEME}{STORE_ID}/t26/{relative}"

    def write_once(self, relative: str, value: Any) -> dict:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _bytes(value)
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return {"locator": self.locator(relative), "sha256": _sha(data),
                "bytes": len(data), "classification": "PRIVATE_BLIND"}

    def read(self, relative: str) -> Any:
        return json.loads(self.path(relative).read_text(encoding="utf-8"))


def validate_blind_cases(cases: list[dict], gold: list[dict],
                         exclusions: dict[str, Any],
                         historical_exclusions: dict[str, Any]) -> dict:
    """Validate future authored private material without exposing it publicly."""
    required_historical = {"case_ids", "exact_queries", "exact_answers",
                           "t25_private_overlap_attested"}
    if (not isinstance(historical_exclusions, dict) or
            set(historical_exclusions) != required_historical or
            historical_exclusions["t25_private_overlap_attested"] is not True or
            any(not isinstance(historical_exclusions[key], list)
                for key in required_historical - {"t25_private_overlap_attested"})):
        raise ValueError("sealed T23/T24/T25 exclusion oracle required")
    if len(cases) != 512 or len(gold) != 512:
        raise ValueError("T26 blind design requires exactly 512 scenarios")
    counts = Counter()
    ids = set()
    forbidden_ids = set(exclusions["case_id_sha256"])
    forbidden_goals = set(exclusions["goal_sha256"])
    forbidden_queries = set(exclusions["router_query_sha256"])
    historical_ids = set(historical_exclusions["case_ids"])
    historical_queries = set(historical_exclusions["exact_queries"])
    historical_answers = set(historical_exclusions["exact_answers"])
    for scenario, key in zip(cases, gold):
        if set(scenario) != {"scenario_id", "plan", "classification", "family"}:
            raise ValueError("private scenario schema mismatch")
        family = scenario["family"]
        if family not in FAMILIES or scenario["classification"] != "PRIVATE_BLIND":
            raise ValueError("invalid blind family or classification")
        candidate_case = {k: v for k, v in scenario.items() if k != "family"}
        validate_plan(candidate_case["plan"])
        sid = candidate_case["scenario_id"]
        if sid in ids or _sha(sid.encode()) in forbidden_ids | historical_ids:
            raise ValueError("duplicate or qualification-excluded case id")
        if _sha(candidate_case["plan"]["goal"].encode()) in forbidden_goals:
            raise ValueError("qualification-excluded goal")
        if any(_sha(step["router_input"]["query"].encode()) in forbidden_queries | historical_queries
               for step in candidate_case["plan"]["steps"]):
            raise ValueError("qualification-excluded query")
        if key.get("scenario_id") != sid:
            raise ValueError("gold identity mismatch")
        answer = key.get("expected_answer")
        if isinstance(answer, str) and _sha(answer.encode()) in historical_answers:
            raise ValueError("historically excluded answer")
        ids.add(sid)
        counts[family] += 1
    if set(counts) != set(FAMILIES) or any(counts[f] != 32 for f in FAMILIES):
        raise ValueError("blind family cardinality mismatch")
    return {"status": "PASS", "case_count": 512,
            "family_counts": dict(counts), "case_id_root": _sha(_bytes(sorted(ids)))}


def construct_real(token: str, store: T26PrivateStore,
                   cases: list[dict], gold: list[dict], exclusions: dict,
                   historical_exclusions: dict) -> dict:
    """Future authorized one-shot private materialization. Never called in preconstruction."""
    require_token(token, "construction")
    # Carry every T25 public hash-only exclusion source forward without
    # opening any historical blind row. The secure private oracle must add
    # T25's private overlap attestation at construction time.
    from t25_protocol.exclusions import load_exclusion_sources

    registry = json.loads((store.public_repo / "evaluations/t25/t25_exclusion_sources.json")
                          .read_text(encoding="utf-8"))
    public_forbidden = load_exclusion_sources(store.public_repo, registry)
    combined = dict(historical_exclusions)
    for field in ("case_ids", "exact_queries", "exact_answers"):
        combined[field] = sorted(set(historical_exclusions.get(field, [])) |
                                 public_forbidden[field])
    audit = validate_blind_cases(cases, gold, exclusions, combined)
    ledger = store.path("construction/ledger.json")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("xb") as handle:
        handle.write(_bytes({"phase": "LEDGER_CREATED", "attempt": 1}))
        handle.flush()
        os.fsync(handle.fileno())
    inputs = store.write_once("construction/inputs.json", cases)
    gold_meta = store.write_once("construction/gold.json", gold)
    manifest = {"schema_version": "t26-private-manifest-v1",
                "inputs": inputs, "gold": gold_meta, "audit": audit}
    manifest_meta = store.write_once("construction/manifest.json", manifest)
    seal = {"schema_version": "t26-holdout-seal-v1",
            "manifest_sha256": manifest_meta["sha256"],
            "inputs_sha256": inputs["sha256"],
            "gold_sha256": gold_meta["sha256"],
            "state": "SEALED"}
    seal_meta = store.write_once("construction/seal.json", seal)
    # The ledger is append-only after its one exclusive creation.
    with ledger.open("ab") as handle:
        handle.write(_bytes({"phase": "SEALED", "seal_sha256": seal_meta["sha256"]}))
        handle.flush()
        os.fsync(handle.fileno())
    return {"status": "SEALED", "case_count": 512,
            "seal_sha256": seal_meta["sha256"], "private_manifest_sha256": manifest_meta["sha256"]}


def evaluate_once(token: str, store: T26PrivateStore,
                  runner_factory: Callable[[Path], IntegratedRunner]) -> dict:
    """Future one-shot evaluator with gold inaccessible to the executor."""
    require_token(token, "evaluation")
    seal = store.read("construction/seal.json")
    if seal.get("state") != "SEALED":
        raise ValueError("T26 holdout not sealed")
    manifest_bytes = store.path("construction/manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if _sha(manifest_bytes) != seal.get("manifest_sha256"):
        raise ValueError("private manifest seal mismatch")
    inputs_bytes = store.path("construction/inputs.json").read_bytes()
    gold_bytes = store.path("construction/gold.json").read_bytes()
    if (_sha(inputs_bytes) != seal.get("inputs_sha256") or
            _sha(gold_bytes) != seal.get("gold_sha256") or
            manifest["inputs"]["sha256"] != seal["inputs_sha256"] or
            manifest["gold"]["sha256"] != seal["gold_sha256"]):
        raise ValueError("private holdout bytes drifted")
    cases = json.loads(inputs_bytes)
    gold = json.loads(gold_bytes)
    if len(cases) != 512 or len(gold) != 512:
        raise ValueError("private holdout cardinality drift")
    ledger = store.path("evaluation/ledger.json")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("xb") as handle:
        handle.write(_bytes({"phase": "LEDGER_CREATED", "attempt": 1,
                             "seal_sha256": _sha(store.path("construction/seal.json").read_bytes())}))
        handle.flush()
        os.fsync(handle.fileno())
    outputs = []
    plans = []
    for scenario in cases:
        # The executor receives no gold and no family label.
        candidate_case = {k: scenario[k] for k in
                          ("scenario_id", "plan", "classification")}
        case_root = store.path(f"evaluation/workspaces/{scenario['scenario_id']}")
        case_root.mkdir(parents=True, exist_ok=False)
        runner = runner_factory(case_root)
        outputs.append(runner.run(candidate_case))
        plans.append(candidate_case["plan"])
    raw_meta = store.write_once("evaluation/raw_outputs.json", outputs)
    score = score_suite(outputs, gold, plans)
    scored_meta = store.write_once("evaluation/scored_rows.json", score.pop("rows"))
    summary_meta = store.write_once("evaluation/summary.json", score)
    with ledger.open("ab") as handle:
        handle.write(_bytes({"phase": "COMPLETE", "raw_sha256": raw_meta["sha256"],
                             "scored_sha256": scored_meta["sha256"],
                             "summary_sha256": summary_meta["sha256"]}))
        handle.flush()
        os.fsync(handle.fileno())
    return public_receipt(score, raw_meta["sha256"], summary_meta["sha256"])


def public_receipt(score: dict, raw_sha256: str, summary_sha256: str) -> dict:
    """Only hashes and aggregate scores leave the private evaluator side."""
    return {"schema_version": "t26-public-evaluation-receipt-v1",
            "artifact": "T26_PUBLIC_EVALUATION_RECEIPT",
            "status": score["status"], "scenario_count": score["scenario_count"],
            "metrics": score["metrics"],
            "critical_counters": score["critical_counters"],
            "raw_outputs_sha256": raw_sha256,
            "private_summary_sha256": summary_sha256,
            "raw_rows_included": False, "gold_included": False}
