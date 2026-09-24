"""T25 live-web source firewall: T23, T24, historical, and qualification sources denied pre-candidate.

Every live-provider result is normalized, checked against denied repository
identities, URI prefixes, content hashes, and text fingerprints, and only
allowed results reach the candidate. T24's sealed/evaluated material joins the
denied set through the T24_SEALED_EVALUATED anchor (authorization §16); denied
results are counted, never returned.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any
from unicodedata import normalize

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "evaluations" / "t25" / "live_web_source_firewall_registry.json"
FIREWALL_SCHEMA = "t25-live-web-source-firewall-v1"
_REJECTION_RULES = (
    "QUERY_FINGERPRINT_T23_EXPOSED", "REPOSITORY_IDENTITY", "URI_PREFIX",
    "T23_CONTENT_HASH", "T23_TEXT_FINGERPRINT", "HISTORICAL_FINGERPRINT",
    "QUALIFICATION_FINGERPRINT", "T24_ARTIFACT_HASH", "T24_REHEARSAL_FINGERPRINT",
    "T24_QUALIFICATION_FINGERPRINT",
)
_T24_RULES = frozenset({"T24_ARTIFACT_HASH", "T24_REHEARSAL_FINGERPRINT",
                        "T24_QUALIFICATION_FINGERPRINT"})


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", normalize("NFKC", text or "").casefold()).strip()


def text_fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def load_registry(path: Path = REGISTRY) -> dict[str, Any]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry.get("schema_version") != FIREWALL_SCHEMA or not registry.get("pre_candidate_filtering"):
        raise ValueError("T25 live-web firewall registry drift")
    return registry


def _load_fingerprint_set(root: Path, record: dict[str, Any]) -> set[str]:
    path = (Path(root) / record["path"]).resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError(f"firewall fingerprint source changed: {record['path']}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != "t25-fingerprint-set-v1" or document.get("raw_values_included") is not False:
        raise ValueError(f"invalid fingerprint set: {record['path']}")
    return set(document["fingerprints"])


def _load_exposed_query_fingerprints(root: Path, record: dict[str, Any]) -> set[str]:
    path = (Path(root) / record["path"]).resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError("firewall T23 anchor changed")
    anchor = json.loads(path.read_text(encoding="utf-8"))
    if anchor.get("schema_version") != "t23-exposed-sealed-anchor-v1":
        raise ValueError("firewall T23 anchor schema mismatch")
    return set(anchor["dimensions"]["exact_queries"]["fingerprints"])


def _load_t24_anchor_fingerprints(root: Path, record: dict[str, Any]) -> dict[str, set[str]]:
    path = (Path(root) / record["path"]).resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError("firewall T24 anchor changed")
    anchor = json.loads(path.read_text(encoding="utf-8"))
    if (anchor.get("schema_version") != "t24-sealed-evaluated-anchor-v1"
            or anchor.get("raw_values_included") is not False
            or anchor.get("t24_must_not_be_rerun") is not True):
        raise ValueError("firewall T24 anchor schema mismatch")
    dimensions = anchor["dimensions"]
    return {
        "artifacts": set(dimensions["artifact_content"]["fingerprints"]),
        # Rehearsal semantics: T24's disposable-rehearsal CONTENT identities
        # (answers, source text, attack wording). Query/case identities belong
        # to the qualification rule below; keeping the two classes disjoint is
        # what makes each denial rule precisely attributable.
        "rehearsal": (set(dimensions["exact_answers"]["fingerprints"])
                      | set(dimensions["exact_source_text"]["fingerprints"])
                      | set(dimensions["verbatim_attack_wording"]["fingerprints"])),
        "qualification": (set(dimensions["case_ids"]["fingerprints"])
                          | set(dimensions["exact_queries"]["fingerprints"])),
    }


class LiveWebSourceFirewall:
    def __init__(self, registry: dict[str, Any], root: Path = ROOT) -> None:
        if registry.get("schema_version") != FIREWALL_SCHEMA:
            raise ValueError("T25 live-web firewall registry drift")
        self.registry = registry
        self.counters = {"results_retrieved": 0, "results_rejected_total": 0,
                         "t23_derived_rejected": 0, "historical_eval_rejected": 0,
                         "qualification_derived_rejected": 0, "t24_derived_rejected": 0,
                         "candidate_visible_results": 0, "queries_denied": 0,
                         "rejected_rule_counts": {}}
        self._denied_prefixes = tuple(prefix.lower() for prefix in registry["denied_uri_prefixes"])
        root = Path(root)
        self._denied_content_sha256: set[str] = set()
        self._denied_text_fingerprints: set[str] = set()
        self._denied_query_fingerprints: set[str] = set()
        self._historical_fingerprints: set[str] = set()
        self._qualification_fingerprints: set[str] = set()
        self._t24_artifact_sha256: set[str] = set()
        self._t24_rehearsal_fingerprints: set[str] = set()
        self._t24_qualification_fingerprints: set[str] = set()
        for record in registry["t23_content_bindings"]:
            self._denied_content_sha256 |= _load_fingerprint_set(root, record)
        for record in registry["t23_text_bindings"]:
            self._denied_text_fingerprints |= _load_fingerprint_set(root, record)
        for record in registry["t23_query_bindings"]:
            self._denied_query_fingerprints |= _load_exposed_query_fingerprints(root, record)
        for record in registry["historical_bindings"]:
            self._historical_fingerprints |= _load_fingerprint_set(root, record)
        for record in registry["qualification_bindings"]:
            self._qualification_fingerprints |= _load_fingerprint_set(root, record)
        for record in registry["t24_anchor_bindings"]:
            loaded = _load_t24_anchor_fingerprints(root, record)
            self._t24_artifact_sha256 |= loaded["artifacts"]
            self._t24_rehearsal_fingerprints |= loaded["rehearsal"]
            self._t24_qualification_fingerprints |= loaded["qualification"]

    def normalize(self, result: Any) -> dict[str, Any]:
        if isinstance(result, dict):
            url = str(result.get("url", ""))
            title = str(result.get("title", ""))
            text = str(result.get("text", result.get("content", "")))
            content_hash = str(result.get("content_hash", ""))
        else:
            url = str(getattr(result, "url", "") or "")
            title = str(getattr(result, "title", "") or "")
            text = str(getattr(result, "content", "") or getattr(result, "text", ""))
            content_hash = str(getattr(result, "content_hash", "") or "")
        host, repo_parts = _host_and_repo(url)
        return {"url": url, "host": host, "repo": "/".join(repo_parts),
                "title": title, "text": text,
                "content_sha256": content_hash or (hashlib.sha256(text.encode("utf-8")).hexdigest()
                                                   if text else ""),
                "text_fingerprint": text_fingerprint(text) if text else ""}

    def evaluate(self, query: str, normalized: dict[str, Any]) -> tuple[bool, str | None]:
        if _query_fingerprint(query) in self._denied_query_fingerprints:
            return False, "QUERY_FINGERPRINT_T23_EXPOSED"
        host = (normalized["host"] or "").lower()
        repo = normalized["repo"].lower()
        for entry in self.registry["denied_repositories"]:
            if (host == entry["host"].lower() and repo == f"{entry['owner'].lower()}/{entry['repo'].lower()}"):
                return False, "REPOSITORY_IDENTITY"
        url = (normalized["url"] or "").lower()
        stripped = re.sub(r"^[a-z][a-z0-9+.-]*://", "", url)
        for prefix in self._denied_prefixes:
            # Scheme'd prefixes match the raw URL; scheme-less match after stripping.
            if url.startswith(prefix) or stripped.startswith(prefix):
                return False, "URI_PREFIX"
        if normalized["content_sha256"] and normalized["content_sha256"] in self._denied_content_sha256:
            return False, "T23_CONTENT_HASH"
        if normalized["text_fingerprint"] and normalized["text_fingerprint"] in self._denied_text_fingerprints:
            return False, "T23_TEXT_FINGERPRINT"
        if normalized["text_fingerprint"] and normalized["text_fingerprint"] in self._historical_fingerprints:
            return False, "HISTORICAL_FINGERPRINT"
        if normalized["text_fingerprint"] and normalized["text_fingerprint"] in self._qualification_fingerprints:
            return False, "QUALIFICATION_FINGERPRINT"
        if normalized["content_sha256"] and normalized["content_sha256"] in self._t24_artifact_sha256:
            return False, "T24_ARTIFACT_HASH"
        if normalized["text_fingerprint"] and (
                normalized["content_sha256"] in self._t24_rehearsal_fingerprints
                or _query_fingerprint(query) in self._t24_rehearsal_fingerprints):
            return False, "T24_REHEARSAL_FINGERPRINT"
        if normalized["text_fingerprint"] and _query_fingerprint(query) in self._t24_qualification_fingerprints:
            return False, "T24_QUALIFICATION_FINGERPRINT"
        return True, None

    def _count(self, rule: str, category: str) -> None:
        self.counters["results_rejected_total"] += 1
        self.counters[category] += 1
        counts = self.counters["rejected_rule_counts"]
        counts[rule] = counts.get(rule, 0) + 1

    def filter(self, query: str, results: Any) -> list[Any]:
        if _query_fingerprint(query) in self._denied_query_fingerprints:
            self.counters["queries_denied"] += 1
            return []
        allowed = []
        for result in results:
            self.counters["results_retrieved"] += 1
            normalized = self.normalize(result)
            ok, rule = self.evaluate(query, normalized)
            if not ok:
                if rule in _T24_RULES:
                    category = "t24_derived_rejected"
                elif rule in {
                    "QUERY_FINGERPRINT_T23_EXPOSED", "REPOSITORY_IDENTITY", "URI_PREFIX",
                    "T23_CONTENT_HASH", "T23_TEXT_FINGERPRINT"}:
                    category = "t23_derived_rejected"
                elif rule == "QUALIFICATION_FINGERPRINT":
                    category = "qualification_derived_rejected"
                else:
                    category = "historical_eval_rejected"
                self._count(rule, category)
                continue
            allowed.append(result)
            self.counters["candidate_visible_results"] += 1
        return allowed


def _query_fingerprint(query: str) -> str:
    return hashlib.sha256((query or "").encode("utf-8")).hexdigest()


def _host_and_repo(url: str) -> tuple[str, list[str]]:
    without_scheme = re.sub(r"^[a-z][a-z0-9+.-]*://", "", (url or "").strip().lower())
    host = without_scheme.split("/", 1)[0]
    rest = without_scheme[len(host):].lstrip("/")
    parts = [part for part in rest.split("/") if part][:2]
    return host, parts


class FirewallSearchProvider:
    """Wraps the live/fixture search provider; only firewall-allowed results surface."""

    def __init__(self, inner: Any, firewall: LiveWebSourceFirewall) -> None:
        self.inner = inner
        self.firewall = firewall

    @property
    def live_or_fixture(self) -> str:
        return getattr(self.inner, "live_or_fixture", "fixture")

    @property
    def provider_name(self) -> str:
        return f"FIREWALL[{getattr(self.inner, 'provider_name', 'PROVIDER')}]"

    @property
    def provider_cost_class(self) -> Any:
        return getattr(self.inner, "provider_cost_class", None)

    @property
    def network_required(self) -> bool:
        return bool(getattr(self.inner, "network_required", False))

    def timestamp(self) -> str:
        return self.inner.timestamp()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def search(self, query: str) -> list[Any]:
        return self.firewall.filter(query, self.inner.search(query))


def build_firewall_document(root: Path, *, t23_anchor_record: dict[str, str],
                            historical_records: list[dict[str, str]],
                            qualification_records: list[dict[str, str]],
                            t23_content_records: list[dict[str, str]],
                            t23_text_records: list[dict[str, str]],
                            t24_anchor_record: dict[str, str]) -> dict[str, Any]:
    return {"schema_version": FIREWALL_SCHEMA,
            "artifact": "T25_LIVE_WEB_SOURCE_FIREWALL_REGISTRY", "experiment": "t25",
            "pre_candidate_filtering": True,
            "denied_repositories": [
                {"host": "github.com", "owner": "COMRADEART", "repo": "mango",
                 "reason": "T23_EXPOSED_SEALED"},
                {"host": "raw.githubusercontent.com", "owner": "COMRADEART", "repo": "mango",
                 "reason": "T23_EXPOSED_SEALED"}],
            "denied_uri_prefixes": [
                "github.com/comradeart/mango", "raw.githubusercontent.com/comradeart/mango",
                "https://github.com/comradeart/mango", "https://raw.githubusercontent.com/comradeart/mango",
                "http://github.com/comradeart/mango", "http://raw.githubusercontent.com/comradeart/mango"],
            "denial_rules": list(_REJECTION_RULES),
            "t23_construction_commit": "aa613c30483f697295f6f993319e37fd45b07f12",
            "t24_receipt_commit": "d64160bf0ebb715a6a30647d06e420b7dde6b24e",
            "t23_query_bindings": [t23_anchor_record],
            "t23_content_bindings": t23_content_records,
            "t23_text_bindings": t23_text_records,
            "historical_bindings": historical_records,
            "qualification_bindings": qualification_records,
            "t24_anchor_bindings": [t24_anchor_record]}