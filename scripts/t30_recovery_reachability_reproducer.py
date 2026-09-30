"""Disposable, non-spending reproducer: is designated recovery reachable in the
frozen T30 REAL production stack?

No model load, no real rows, no predecessor oracle, no store, no ledger.
"""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path.cwd().resolve()

# ---- A. static scan of every module reachable from the REAL adapter stack ----
SCAN = [p for base in ("src", "t25_protocol", "t26_protocol")
        for p in (ROOT / base).rglob("*.py")]
SCAN += [ROOT / "t27_protocol/production.py", ROOT / "t30_protocol/production.py",
         ROOT / "t30_protocol/official_environment.py"]
raise_sites, status_literals, subclasses = [], [], []
for path in SCAN:
    rel = path.relative_to(ROOT).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            name = getattr(target, "id", getattr(target, "attr", None))
            if name == "RecoverableError":
                raise_sites.append(f"{rel}:{node.lineno}")
        if isinstance(node, ast.Constant) and node.value in (
                "RECOVERABLE_ERROR", "BUDGET_CHANGE"):
            status_literals.append(f"{rel}:{node.lineno}:{node.value}")
        if isinstance(node, ast.ClassDef) and any(
                getattr(b, "id", getattr(b, "attr", None)) == "RecoverableError"
                for b in node.bases):
            subclasses.append(f"{rel}:{node.lineno}:{node.name}")

# Disposable-only producers (never used in REAL mode) for contrast.
disposable = []
for rel in ("t30_protocol/qualification.py", "t26_protocol/qualification.py",
            "t26_protocol/rehearsal.py"):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    disposable += [f"{rel}:{n.lineno}" for n in ast.walk(tree)
                   if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
                   and getattr(n.exc.func, "id", None) == "RecoverableError"]

# ---- B. dynamic checks against frozen functions (stubs only) ----
from sciencemath.integrated.runner import (ExecutionError, RecoverableError,
                                           UnavailableError)
from t30_protocol.production import _provider_call, normalize_provider_status

class _StubProvider:
    web_provider = None
    def _dispatch(self, *a, **k):
        raise RecoverableError("transient")

ctx = {"router_decision": {"selected_capability": "GENERAL"},
       "router_input": {"query": "disposable"}, "scenario_id": "t30-disposable-x",
       "step_id": "s1", "classification": "PRIVATE_BLIND"}
try:
    _provider_call(_StubProvider(), "GENERAL", {"query": "disposable"}, ctx)
    provider_transient = "RETURNED"
except UnavailableError:
    provider_transient = "CONVERTED_TO_UnavailableError"
except RecoverableError:
    provider_transient = "RecoverableError_PROPAGATED"
status_map = {}
for status in ("RECOVERABLE_ERROR", "BUDGET_CHANGE"):
    try:
        status_map[status] = normalize_provider_status(status)
    except ExecutionError:
        status_map[status] = "REJECTED_ExecutionError"

# ---- C. scorer consequence with frozen score_suite on disposable outputs ----
from t30_protocol.scorer import score_suite
from t30_protocol.contract import NONVACUITY_MINIMUMS
n = NONVACUITY_MINIMUMS["recoverable_cases"]
plan = {"completion_condition": {"required_steps": ["s1", "s2", "s3"]},
        "budgets": {"max_total_retries": 3}, "steps": [{}, {}, {}]}
gold = [{"expected_terminal": "COMPLETE", "expected_verified_steps": 3,
         "designated_recoverable": True, "designated_abstention": False,
         "expected_replan_trigger": None, "expected_fallback_capability": None}
        for _ in range(n)]
# Best case the REAL stack can emit: perfect COMPLETE, retries necessarily 0.
outputs = [{"terminal": "COMPLETE", "verified_steps": ["s1", "s2", "s3"],
            "final_answer_commitment": "x", "authority": "COORDINATE_INTERNAL_WORK_ONLY",
            "trace": [{"verification_result": "PASS", "capability_selected": "MATH_T4"}],
            "handoffs": [], "replans": [], "budget_state": {"total_retries": 0}}
           for _ in range(n)]
score = score_suite(outputs, gold, [plan] * n)
recovery = score["metrics"]["recovery_success_rate"]

result = {
    "schema_version": "t30-recovery-reachability-reproducer-v1",
    "scanned_module_count": len(SCAN),
    "real_stack_raise_RecoverableError_sites": raise_sites,
    "real_stack_RecoverableError_subclasses": subclasses,
    "real_stack_status_literals": status_literals,
    "disposable_only_raise_sites": disposable,
    "provider_transient_exception": provider_transient,
    "provider_status_normalization": status_map,
    "nonvacuity_recoverable_minimum": n,
    "best_case_recovery_success_rate": {k: recovery[k] for k in (
        "numerator", "denominator", "observed", "floor", "pass")},
    "best_case_suite_status": score["status"],
}
print(json.dumps(result, indent=1, sort_keys=True))
print("REPRODUCER_SHA256",
      hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest())
