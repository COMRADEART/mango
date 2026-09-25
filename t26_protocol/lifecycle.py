"""Private one-shot T26 construction/evaluation architecture (not invoked now)."""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from sciencemath.integrated.runner import IntegratedRunner, validate_plan
from t21_protocol.util import sha256_json

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
        self._commitments: dict[str, dict] = {}
        self._index_path = self.root / "commitments.json"
        if self._index_path.exists():
            index = json.loads(self._index_path.read_text(encoding="utf-8"))
            if index.get("store_identity") != STORE_ID or index.get("namespace") != "t26":
                raise ValueError("T26 private store identity mismatch")
            self._commitments = {entry["logical_id"]: entry
                                 for entry in index["commitments"]}

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

    def has(self, relative: str) -> bool:
        return self.path(relative).is_file()

    def write_once(self, relative: str, value: Any,
                   classification: str = "PRIVATE_BLIND") -> dict:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _bytes(value)
        return self.write_bytes_once(relative, data, classification=classification)

    def write_bytes_once(self, relative: str, data: bytes,
                         classification: str = "PRIVATE_BLIND") -> dict:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        if classification not in {"PRIVATE_BLIND", "PRIVATE_EVALUATION",
                                  "REAL_BLIND_INPUT", "REAL_BLIND_GOLD"}:
            raise ValueError("unknown private artifact classification")
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        meta = {"logical_id": relative, "locator": self.locator(relative),
                "sha256": _sha(data), "bytes": len(data),
                "classification": classification}
        self._commit(relative, meta)
        return meta

    def replace(self, relative: str, value: Any) -> dict:
        """Replace an existing store artifact and refresh its commitment."""
        path = self.path(relative)
        data = _bytes(value)
        with path.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        meta = dict(self._commitments.get(relative, {}))
        meta.update({"logical_id": relative, "locator": self.locator(relative),
                     "sha256": _sha(data), "bytes": len(data)})
        self._commit(relative, meta)
        return meta

    def _commit(self, relative: str, meta: dict) -> None:
        self._commitments[relative] = meta
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        commitments = [self._commitments[key]
                       for key in sorted(self._commitments)]
        self._index_path.write_text(json.dumps(
            {"schema_version": "t26-private-store-index-v1",
             "store_identity": STORE_ID, "namespace": "t26",
             "commitments": commitments,
             "artifact_root": sha256_json(commitments)},
            indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n")

    def read(self, relative: str) -> Any:
        return json.loads(self.path(relative).read_text(encoding="utf-8"))

    def read_bytes(self, relative: str) -> bytes:
        return self.path(relative).read_bytes()

    def commitment(self, relative: str) -> dict:
        if relative not in self._commitments:
            raise ValueError(f"T26 store commitment absent: {relative}")
        return dict(self._commitments[relative])

    def commitments(self) -> list[dict]:
        return [dict(self._commitments[key]) for key in sorted(self._commitments)]

    def artifact_root(self, exclude: frozenset[str] = frozenset()) -> str:
        entries = [self._commitments[key] for key in sorted(self._commitments)
                   if key not in exclude]
        return sha256_json(entries)

    def verify(self) -> dict:
        """Full independent verification of every private commitment."""
        missing: list[str] = []
        hash_mismatches: list[str] = []
        classification_mismatches: list[str] = []
        root_mismatches: list[str] = []
        valid_classes = {"PRIVATE_BLIND", "PRIVATE_EVALUATION", "REAL_BLIND_INPUT",
                         "REAL_BLIND_GOLD"}
        for logical_id, entry in sorted(self._commitments.items()):
            path = self.path(logical_id)
            if not path.is_file():
                missing.append(logical_id)
                continue
            if _sha(path.read_bytes()) != entry.get("sha256"):
                hash_mismatches.append(logical_id)
            if entry.get("classification") not in valid_classes:
                classification_mismatches.append(logical_id)
        recomputed_root = self.artifact_root()
        if self._commitments and self._index_path.exists():
            stored_root = json.loads(
                self._index_path.read_text(encoding="utf-8")).get("artifact_root")
            if stored_root != recomputed_root:
                root_mismatches.append("commitments.artifact_root")
        if missing or hash_mismatches or classification_mismatches or root_mismatches:
            raise ValueError("T26 private store verification failed: "
                             f"missing={missing} hash_mismatches={hash_mismatches} "
                             f"classification_mismatches={classification_mismatches} "
                             f"root_mismatches={root_mismatches}")
        return {"status": "PASS", "store_identity": STORE_ID, "namespace": "t26",
                "artifact_count": len(self._commitments),
                "missing_artifacts": 0, "hash_mismatches": 0,
                "classification_mismatches": 0, "root_mismatches": 0,
                "artifact_root": recomputed_root}


def validate_blind_cases(cases: list[dict], gold: list[dict],
                         exclusions: dict[str, Any],
                         historical_exclusions: dict[str, Any]) -> dict:
    """Validate future authored private material without exposing it publicly.

    Uses the full nine-dimensional exclusion model. A bare Boolean T25
    attestation is no longer accepted: the T25 private overlap must be a
    hash-bound oracle result verified by ``t26_protocol.oracle``.
    """
    from .exclusion import DIMENSIONS

    if (not isinstance(historical_exclusions, dict) or
            set(historical_exclusions) != set(DIMENSIONS)):
        raise ValueError("full nine-dimensional historical exclusion oracle required")
    oracle_result = exclusions.get("t25_private_overlap_oracle_result") if isinstance(
        exclusions, dict) else None
    if oracle_result is None:
        raise ValueError("hash-bound T25 private overlap oracle result required "
                         "(bare boolean attestation is not sufficient)")
    from .oracle import verify_oracle_result

    verify_oracle_result(oracle_result)
    for dimension in DIMENSIONS:
        values = historical_exclusions[dimension]
        if not isinstance(values, list):
            raise ValueError(f"historical exclusion dimension invalid: {dimension}")
    if len(cases) != 512 or len(gold) != 512:
        raise ValueError("T26 blind design requires exactly 512 scenarios")
    counts = Counter()
    ids = set()
    forbidden_ids = set(exclusions.get("case_id_sha256", []))
    forbidden_goals = set(exclusions.get("goal_sha256", []))
    forbidden_queries = set(exclusions.get("router_query_sha256", []))
    historical_sets = {dimension: set(historical_exclusions[dimension])
                       for dimension in DIMENSIONS}
    for scenario, key in zip(cases, gold):
        if set(scenario) != {"scenario_id", "plan", "classification", "family"}:
            raise ValueError("private scenario schema mismatch")
        family = scenario["family"]
        if family not in FAMILIES or scenario["classification"] != "PRIVATE_BLIND":
            raise ValueError("invalid blind family or classification")
        candidate_case = {k: v for k, v in scenario.items() if k != "family"}
        validate_plan(candidate_case["plan"])
        sid = candidate_case["scenario_id"]
        if sid in ids or _sha(sid.encode()) in (forbidden_ids |
                                                historical_sets["case_ids"]):
            raise ValueError("duplicate or excluded case id")
        if _sha(candidate_case["plan"]["goal"].encode()) in forbidden_goals:
            raise ValueError("qualification-excluded goal")
        if any(_sha(step["router_input"]["query"].encode()) in
               (forbidden_queries | historical_sets["exact_queries"])
               for step in candidate_case["plan"]["steps"]):
            raise ValueError("qualification-excluded query")
        if key.get("scenario_id") != sid:
            raise ValueError("gold identity mismatch")
        answer = key.get("expected_answer")
        if isinstance(answer, str) and _sha(answer.encode()) in historical_sets["exact_answers"]:
            raise ValueError("historically excluded answer")
        ids.add(sid)
        counts[family] += 1
    if set(counts) != set(FAMILIES) or any(counts[f] != 32 for f in FAMILIES):
        raise ValueError("blind family cardinality mismatch")
    return {"status": "PASS", "case_count": 512,
            "family_counts": dict(counts), "case_id_root": _sha(_bytes(sorted(ids)))}


def construct_real(token: str, store: T26PrivateStore,
                   cases: list[dict], gold: list[dict], exclusions: dict,
                   historical_exclusions: dict, *,
                   root: Path | None = None,
                   fixtures: list[dict] | None = None,
                   oracle_result: dict | None = None,
                   provenance: dict | None = None,
                   inject_failure_after_ledger: bool = False) -> dict:
    """Future authorized one-shot private materialization. Never called in preconstruction.

    Delegates to the production-grade lifecycle in ``t26_protocol.construction``:
    the exclusive ledger binds the complete experiment identity, the event chain
    is hash-chained, and the one-shot state machine is
    LEDGER_CREATED -> MATERIALIZED -> AUDITED -> GATE_PASS -> MANIFESTED -> SEALED
    with terminal FAILED semantics.
    """
    require_token(token, "construction")
    if root is None:
        root = Path(__file__).resolve().parents[1]
    from .construction import construct_real as production_construct_real

    return production_construct_real(
        root, store, token=token, cases=cases, gold=gold,
        fixtures=fixtures, oracle_result=oracle_result,
        provenance=provenance,
        inject_failure_after_ledger=inject_failure_after_ledger)


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
