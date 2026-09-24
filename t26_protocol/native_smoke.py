"""Public native MATH_T4 -> MATH_T4 -> SCICOMP dependency smoke."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from sciencemath.integrated.runner import IntegratedRunner
from sciencemath.web.fixture_provider import FixtureCorpus, FixtureSearchProvider
from t25_protocol.firewall import FirewallSearchProvider
from t25_protocol.provider import T25ProductionRouterProvider
from .firewall import T26LiveWebSourceFirewall
from .production import build_adapters
from .qualification import make_case
from .scorer import score_suite


def native_case() -> tuple[dict, dict]:
    scenario, gold, _ = make_case("math_chain", 0)
    scenario = json.loads(json.dumps(scenario))
    scenario["scenario_id"] = "t26-native-public-math-scicomp-01"
    plan = scenario["plan"]
    plan["plan_id"] = "plan-t26-native-public-math-scicomp-01"
    plan["goal"] = "Compute a sum, use it in another sum, then verify a descriptive mean with SciComp"
    for index, capability in enumerate(("MATH_T4", "MATH_T4", "SCICOMP")):
        step = plan["steps"][index]
        step["capability"] = capability
        step["router_input"]["query"] = f"Perform {capability} for public native math SciComp dependency step {index + 1}"
        step["router_input"]["requested_capability"] = capability
        step["fallback_capability"] = None
    plan["steps"][0]["input"] = {"expression": "2+3"}
    plan["steps"][1]["input"] = {"delta": 2}
    plan["steps"][2]["input"] = {"op": "describe_previous", "delta": 1}
    gold = {**gold, "scenario_id": scenario["scenario_id"],
            "expected_answer": 8.0}
    return scenario, gold


def run_native_smoke(root: Path, exclusions: dict) -> dict:
    root = Path(root).resolve()
    scenario, gold = native_case()
    with TemporaryDirectory(prefix="t26-native-smoke-") as tmp:
        sandbox = Path(tmp)
        web = FirewallSearchProvider(
            FixtureSearchProvider(FixtureCorpus([], query_time="2026-09-24")),
            T26LiveWebSourceFirewall(root, exclusions))
        provider = T25ProductionRouterProvider(
            root / "rag" / "gk_corpus", web_provider=web,
            workspace_mode="SYNTHETIC_DISPOSABLE")
        adapters = build_adapters(provider)
        output = IntegratedRunner(adapters, sandbox_root=sandbox).run(scenario)
    score = score_suite([output], [gold], [scenario["plan"]])
    score.pop("rows")
    passed = (output["terminal"] == "COMPLETE" and output["final_answer"] == 8.0
              and output["verified_steps"] == ["s1", "s2", "s3"]
              and [e["capability_selected"] for e in output["trace"]] ==
              ["MATH_T4", "MATH_T4", "SCICOMP"]
              and len(output["handoffs"]) == 2 and score["status"] == "PASS")
    return {"schema_version": "t26-native-integration-smoke-v1",
            "artifact": "T26_NATIVE_INTEGRATION_SMOKE",
            "status": "PASS" if passed else "FAIL",
            "scenario_id": scenario["scenario_id"],
            "native_capabilities": ["MATH_T4", "SCICOMP"],
            "verified_steps": len(output["verified_steps"]),
            "handoffs": len(output["handoffs"]),
            "terminal": output["terminal"],
            "final_answer_commitment": output["final_answer_commitment"],
            "score": score,
            "real_blind_rows": 0}
