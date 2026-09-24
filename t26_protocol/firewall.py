"""T26 additive pre-candidate live-web contamination firewall."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from t25_protocol.firewall import LiveWebSourceFirewall, load_registry


class T26LiveWebSourceFirewall(LiveWebSourceFirewall):
    def __init__(self, root: Path, exclusions: dict[str, Any]) -> None:
        super().__init__(load_registry(), root=root)
        if exclusions.get("artifact") != "T26_QUALIFICATION_EXCLUSIONS" or exclusions.get("permanently_excluded_from_real_t26") is not True:
            raise ValueError("T26 qualification exclusion registry invalid")
        self.t26_queries = set(exclusions["router_query_sha256"])
        self.t26_goals = set(exclusions["goal_sha256"])
        self.t26_case_ids = set(exclusions["case_id_sha256"])
        self.counters["t26_qualification_rejected"] = 0
        self.counters["t25_evaluation_rejected"] = 0

    def evaluate(self, query: str, normalized: dict[str, Any]) -> tuple[bool, str | None]:
        ok, rule = super().evaluate(query, normalized)
        if not ok:
            return ok, rule
        if hashlib.sha256(query.encode("utf-8")).hexdigest() in self.t26_queries:
            return False, "T26_QUALIFICATION_QUERY"
        text = normalized.get("text") or ""
        url = (normalized.get("url") or "").casefold()
        if hashlib.sha256(text.encode("utf-8")).hexdigest() in (self.t26_goals | self.t26_case_ids):
            return False, "T26_QUALIFICATION_CONTENT"
        if any(marker in url for marker in ("t25-private://", "t26-private://",
                                             "/evaluations/t25/evaluation/",
                                             "/evaluations/t26/qualification/")):
            return False, "T25_OR_T26_EXPERIMENT_URL"
        lowered = text.casefold()
        if ("t25_evaluation_public_receipt" in lowered or
                "t25_private" in lowered or "t26_qualification" in lowered or
                "t26-public-qualification" in lowered):
            return False, "T25_OR_T26_EXPERIMENT_TEXT"
        return True, None

    def _count(self, rule: str, category: str) -> None:
        if rule.startswith("T26_QUALIFICATION"):
            category = "t26_qualification_rejected"
        elif rule.startswith("T25_OR_T26"):
            category = "t25_evaluation_rejected"
        super()._count(rule, category)


def negative_controls(root: Path, exclusions: dict) -> dict:
    firewall = T26LiveWebSourceFirewall(root, exclusions)
    controls = [
        ("T26 qualification", {"url": "https://example.test/open",
                               "text": "T26_QUALIFICATION sample"}),
        ("T25 evaluation", {"url": "https://example.test/open",
                            "text": "T25_EVALUATION_PUBLIC_RECEIPT"}),
        ("T25 private locator", {"url": "t25-private://T25-STORE-01/t25/evaluation/raw",
                                   "text": "placeholder"}),
        ("Mango repository", {"url": "https://github.com/COMRADEART/mango/blob/main/README.md",
                              "text": "placeholder"}),
    ]
    denied = []
    for label, result in controls:
        norm = firewall.normalize(result)
        ok, reason = firewall.evaluate("public control query", norm)
        denied.append({"control": label, "denied": not ok, "rule": reason})
    from .qualification import build_public_cases
    query = build_public_cases()[0][0]["plan"]["steps"][0]["router_input"]["query"]
    query_match = hashlib.sha256(query.encode("utf-8")).hexdigest() in firewall.t26_queries
    query_denied = firewall.filter(query, [{"url": "https://example.test/ordinary",
                                            "text": "ordinary public result"}]) == []
    return {"status": "PASS" if all(x["denied"] for x in denied) and query_match and query_denied else "FAIL",
            "controls": denied, "t26_query_fingerprint_loaded": query_match,
            "t26_query_denied_before_candidate": query_denied,
            "pre_candidate_filtering": True}
