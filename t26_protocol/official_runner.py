"""Canonical, identity-bound production runner factory for T26 evaluation.

The module is additive: it composes the byte-frozen production adapter,
provider, firewall, and IntegratedRunner implementations without modifying
them.  The real evaluator owns construction of this factory; callers may
supply only low-level live/model dependencies whose identities are captured
before the one-shot ledger is created.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciencemath.executive.skills import SKILL_IDS
from sciencemath.integrated.runner import IntegratedRunner
from t21_protocol.util import sha256_json
from t25_protocol.firewall import FirewallSearchProvider
from t25_protocol.provider import PROVIDER_ID, T25ProductionRouterProvider

from .firewall import T26LiveWebSourceFirewall
from .production import PROVIDER_CAPABILITIES, build_adapters

FACTORY_ID = "T26_OFFICIAL_PRODUCTION_RUNNER_FACTORY_V1"
IDENTITY_SCHEMA = "t26-official-runner-factory-identity-v1"
IDENTITY_PATH = "evaluations/t26/T26_OFFICIAL_RUNNER_FACTORY.json"
PUBLIC_CORPUS = "rag/gk_corpus"
QUALIFICATION_EXCLUSIONS = "evaluations/t26/qualification_exclusions.json"

PRODUCTION_SHA256 = "594a481fcbf1ea4ad04fe8ce7fae4a9c01a07a2a83563689347b7fae32088697"
INTEGRATED_RUNNER_SHA256 = "a097a31c883cd8f93f12576c8ff2a49a945604d7aa3ab194e2df8a8c269b458a"

GOLD_MARKERS = frozenset({
    "gold", "expected_answer", "expected_terminal", "expected_capabilities",
    "expected_replan_trigger", "recoverable_failure", "safe_abstention",
    "scoring_metadata", "scored_rows",
})


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _repo_bytes(root: Path, relative: str) -> bytes:
    from .freeze import _repository_bytes, _text_attributes

    attribute = _text_attributes(root, [relative])[relative]
    return _repository_bytes(root, relative, attribute)


def _repo_sha(root: Path, relative: str) -> str:
    return _sha(_repo_bytes(root, relative))


def _tree_identity(root: Path, relative: str) -> dict[str, Any]:
    directory = (root / relative).resolve()
    if not directory.is_dir() or root not in directory.parents:
        raise ValueError("approved T26 corpus directory missing")
    entries = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix()
        data = _repo_bytes(root, rel)
        entries.append({"path": rel, "sha256": _sha(data), "byte_size": len(data)})
    if not entries:
        raise ValueError("approved T26 corpus is empty")
    return {"path": relative, "file_count": len(entries),
            "file_root": sha256_json(entries), "files": entries}


def adapter_registry_document() -> dict[str, Any]:
    local = {
        "MATH_T4": "t26_protocol.production:_math",
        "SCICOMP": "t26_protocol.production:_scicomp",
        "CODE": "t26_protocol.production:_code",
        "MEMORY": "t26_protocol.production:_memory",
        "PLANNING": "t26_protocol.production:_planning",
        "ORCHESTRATION": "t26_protocol.production:_orchestration",
        "NO_TOOL": "t26_protocol.production:_no_tool",
    }
    entries = []
    for capability in SKILL_IDS:
        implementation = ("t26_protocol.production:_provider_call"
                          if capability in PROVIDER_CAPABILITIES else
                          local[capability])
        entries.append({"capability": capability,
                        "implementation": implementation,
                        "internal_only": True,
                        "may_perform_external_action": False})
    document = {"registered_skill_ids": list(SKILL_IDS), "entries": entries}
    document["registry_root"] = sha256_json(document)
    return document


def build_runner_identity_document(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    registry = adapter_registry_document()
    corpus = _tree_identity(root, PUBLIC_CORPUS)
    hashes = {
        "factory_implementation_sha256": _repo_sha(
            root, "t26_protocol/official_runner.py"),
        "integrated_runner_runtime_sha256": _repo_sha(
            root, "src/sciencemath/integrated/runner.py"),
        "production_runtime_sha256": _repo_sha(root, "t26_protocol/production.py"),
        "production_provider_sha256": _repo_sha(root, "t25_protocol/provider.py"),
        "t25_firewall_sha256": _repo_sha(root, "t25_protocol/firewall.py"),
        "t26_firewall_sha256": _repo_sha(root, "t26_protocol/firewall.py"),
    }
    if (hashes["production_runtime_sha256"] != PRODUCTION_SHA256 or
            hashes["integrated_runner_runtime_sha256"] !=
            INTEGRATED_RUNNER_SHA256):
        raise ValueError("frozen T26 runner dependency drift")
    live_policy = {
        "real_required_live_or_fixture": "live",
        "real_network_required": True,
        "required_interface": ["search", "timestamp", "provider_name",
                               "live_or_fixture", "network_required"],
        "fixture_allowed_only_for_disposable_rehearsal": True,
        "anonymous_or_closure_provider_allowed": False,
        "identity_bound_before_ledger": True,
    }
    provider_policy = {
        "provider_id": PROVIDER_ID,
        "provider_kind": "REAL_CANDIDATE",
        "synthetic": False,
        "real_workspace_mode": "REAL_EXPERIMENT",
        "rehearsal_workspace_mode": "SYNTHETIC_DISPOSABLE",
        "firewall_mandatory": True,
    }
    mount_policy = {
        "corpus": {"source": "FROZEN_PUBLIC", **corpus},
        "document_roots": {
            "source": "PER_SCENARIO_PRIVATE_WORKSPACE",
            "relative_path": "documents", "initially_empty": True,
            "cross_scenario_visibility": False},
        "general_context": {
            "source": "IDENTITY_BOUND_PRODUCTION_DEPENDENCY",
            "gold_fields_forbidden": True},
        "caller_selected_directories_allowed": False,
    }
    core = {
        "schema_version": IDENTITY_SCHEMA,
        "artifact": "T26_OFFICIAL_RUNNER_FACTORY_IDENTITY",
        "classification": "PUBLIC_SAFE", "experiment": "t26",
        "factory_id": FACTORY_ID,
        "factory_entrypoint":
            "t26_protocol.official_runner:build_official_runner_factory",
        "runner_class": "sciencemath.integrated.runner:IntegratedRunner",
        "production_adapter_builder": "t26_protocol.production:build_adapters",
        "production_provider_id": PROVIDER_ID,
        **hashes,
        "production_adapter_registry": registry,
        "production_adapter_registry_root": registry["registry_root"],
        "production_provider_policy": provider_policy,
        "live_provider_policy": live_policy,
        "mount_policy": mount_policy,
        "external_action_authority": False,
        "candidate_gold_access": False,
    }
    policy = {
        "factory_id": FACTORY_ID,
        "hashes": hashes,
        "adapter_registry_root": registry["registry_root"],
        "production_provider_policy": provider_policy,
        "live_provider_policy": live_policy,
        "mount_policy": mount_policy,
        "external_action_authority": False,
        "candidate_gold_access": False,
    }
    core["official_runner_policy_root"] = sha256_json(policy)
    core["identity_root"] = sha256_json(core)
    return core


def verify_runner_identity_document(
        root: Path, document: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    observed = document if document is not None else json.loads(
        (root / IDENTITY_PATH).read_text(encoding="utf-8"))
    expected = build_runner_identity_document(root)
    if observed != expected:
        raise ValueError("T26 official runner factory identity mismatch")
    return dict(observed)


def _contains_gold(value: Any, seen: set[int] | None = None) -> bool:
    seen = seen or set()
    marker = id(value)
    if marker in seen:
        return False
    seen.add(marker)
    if isinstance(value, dict):
        return (any(str(key).casefold() in GOLD_MARKERS for key in value) or
                any(_contains_gold(child, seen) for child in value.values()))
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_gold(child, seen) for child in value)
    if isinstance(value, Path):
        lowered = value.as_posix().casefold()
        return "gold" in lowered or "/construction/" in lowered
    if hasattr(value, "__dict__"):
        return _contains_gold(vars(value), seen)
    return False


def _implementation_identity(root: Path, instance: Any, *, role: str) -> dict[str, Any]:
    cls = type(instance)
    module = cls.__module__
    name = cls.__qualname__
    if "<lambda>" in name or "<locals>" in name:
        raise ValueError(f"anonymous or closure {role} refused")
    source = inspect.getsourcefile(cls)
    if source is None:
        raise ValueError(f"source-backed {role} identity required")
    source_path = Path(source).resolve()
    try:
        relative = source_path.relative_to(root).as_posix()
    except ValueError:
        data = source_path.read_bytes()
        source_locator = f"external:{module}"
    else:
        data = _repo_bytes(root, relative)
        source_locator = relative
    return {"module": module, "class": name,
            "source": source_locator, "implementation_sha256": _sha(data)}


def inspect_live_provider(root: Path, provider: Any, *, real: bool) -> dict[str, Any]:
    required = ("search", "timestamp", "provider_name", "live_or_fixture",
                "network_required")
    if any(not hasattr(provider, name) for name in required):
        raise ValueError("low-level web provider interface mismatch")
    if not callable(provider.search) or not callable(provider.timestamp):
        raise ValueError("low-level web provider callables missing")
    kind = provider.live_or_fixture
    network = bool(provider.network_required)
    if real and (kind != "live" or not network):
        raise ValueError("REAL_BLIND requires a live network-backed provider")
    if not real and kind != "fixture":
        raise ValueError("disposable rehearsal requires a fixture provider")
    if _contains_gold(provider):
        raise ValueError("gold-containing web provider refused")
    identity = _implementation_identity(root, provider, role="web provider")
    identity.update({"provider_name": str(provider.provider_name),
                     "live_or_fixture": kind, "network_required": network})
    identity["identity_root"] = sha256_json(identity)
    return identity


def inspect_general_context(root: Path, context: Any, *, real: bool) -> dict[str, Any]:
    if context is None:
        raise ValueError("identity-bound general context required")
    if _contains_gold(context):
        raise ValueError("gold-containing general context refused")
    identity = _implementation_identity(root, context, role="general context")
    identity.update({"context_kind": str(getattr(
        context, "context_kind", "PRODUCTION" if real else "DISPOSABLE")),
        "candidate_gold_access": False})
    identity["identity_root"] = sha256_json(identity)
    return identity


def validate_corpus_mount(root: Path, requested: Path) -> Path:
    approved = (Path(root).resolve() / PUBLIC_CORPUS).resolve()
    if Path(requested).resolve() != approved:
        raise ValueError("caller-selected corpus path refused")
    return approved


def validate_gold_free_mount(value: Any) -> None:
    if _contains_gold(value):
        raise ValueError("gold-containing runner mount refused")


def validate_stack_attestation(attestation: dict[str, Any], *, real: bool) -> None:
    required = {
        "factory_id": FACTORY_ID,
        "integrated_runner_used": True,
        "production_adapter_registry_used": True,
        "provider_id": PROVIDER_ID,
        "provider_kind": "REAL_CANDIDATE",
        "provider_synthetic": False,
        "workspace_mode": "REAL_EXPERIMENT" if real else "SYNTHETIC_DISPOSABLE",
        "firewall_mandatory": True,
        "firewall_search_provider_used": True,
        "t26_firewall_used": True,
        "inner_live_or_fixture": "live" if real else "fixture",
        "external_authority": False,
        "candidate_gold_access": False,
        "corpus_source": "FROZEN_PUBLIC",
        "document_root_source": "PER_SCENARIO_PRIVATE_WORKSPACE",
    }
    if any(attestation.get(key) != value for key, value in required.items()):
        raise ValueError("official production runner stack attestation mismatch")


class DeterministicFixtureSearchProvider:
    provider_name = "T26_DISPOSABLE_INNER_SEARCH"
    live_or_fixture = "fixture"
    network_required = False
    provider_cost_class = "FIXTURE"

    def timestamp(self) -> str:
        return "2026-09-26T00:00:00+00:00"

    def search(self, _query: str) -> list[dict[str, Any]]:
        return [{"url": "https://example.test/t26-disposable",
                 "text": "deterministic disposable production-stack result",
                 "title": "T26 disposable"}]


class DeterministicGeneralContext:
    context_kind = "DISPOSABLE"
    candidate_gold_access = False


class OfficialRunnerFactory:
    """Callable canonical factory; each call creates an isolated provider/runner."""

    def __init__(self, root: Path, *, web_provider: Any,
                 general_context: Any, real: bool) -> None:
        self.root = Path(root).resolve()
        self.real = bool(real)
        self.identity = verify_runner_identity_document(self.root)
        self.web_provider = web_provider
        self.general_context = general_context
        self.live_provider_identity = inspect_live_provider(
            self.root, web_provider, real=self.real)
        self.general_context_identity = inspect_general_context(
            self.root, general_context, real=self.real)
        self.corpus_dir = validate_corpus_mount(
            self.root, self.root / PUBLIC_CORPUS)
        self.runner_count = 0
        self.last_stack: dict[str, Any] = {}
        self._provider: T25ProductionRouterProvider | None = None
        self._adapters: dict[str, Any] | None = None

    def __call__(self, workspace: Path) -> IntegratedRunner:
        workspace = Path(workspace).resolve()
        if not workspace.is_dir():
            raise ValueError("official runner workspace absent")
        document_root = (workspace / "documents").resolve()
        if workspace not in document_root.parents:
            raise ValueError("official document mount escapes scenario workspace")
        document_root.mkdir(parents=False, exist_ok=False)
        if self._provider is None:
            exclusions = json.loads((self.root / QUALIFICATION_EXCLUSIONS)
                                    .read_text(encoding="utf-8"))
            firewall = T26LiveWebSourceFirewall(self.root, exclusions)
            wrapped = FirewallSearchProvider(self.web_provider, firewall)
            self._provider = T25ProductionRouterProvider(
                self.corpus_dir, web_provider=wrapped,
                general_context=self.general_context,
                document_roots=(document_root,),
                workspace_mode="REAL_EXPERIMENT" if self.real else
                "SYNTHETIC_DISPOSABLE", firewall_mandatory=True)
            self._adapters = build_adapters(self._provider)
        else:
            # Evaluation is sequential.  Rebinding the sole DOCUMENT root
            # before each runner is created preserves scenario isolation while
            # the immutable corpus/firewall/adapter composition is reused.
            self._provider.document_roots = (document_root,)
        provider = self._provider
        adapters = self._adapters
        if adapters is None:
            raise ValueError("official production adapters absent")
        if set(adapters) != set(SKILL_IDS):
            raise ValueError("official production adapter registry mismatch")
        if any(not adapter.internal_only or adapter.may_perform_external_action
               for adapter in adapters.values()):
            raise ValueError("official production adapter authority mismatch")
        if (provider.provider_id != PROVIDER_ID or
                provider.provider_kind != "REAL_CANDIDATE" or
                provider.synthetic is not False or
                not isinstance(provider.web_provider, FirewallSearchProvider) or
                not isinstance(provider.web_provider.firewall,
                               T26LiveWebSourceFirewall)):
            raise ValueError("official production provider stack mismatch")
        runner = IntegratedRunner(adapters, sandbox_root=workspace)
        self.runner_count += 1
        self.last_stack = {
            "factory_id": FACTORY_ID,
            "integrated_runner_used": isinstance(runner, IntegratedRunner),
            "production_adapter_registry_used": True,
            "adapter_registry_root":
                self.identity["production_adapter_registry_root"],
            "provider_id": provider.provider_id,
            "provider_kind": provider.provider_kind,
            "provider_synthetic": provider.synthetic,
            "workspace_mode": provider.workspace_mode,
            "firewall_mandatory": True,
            "firewall_search_provider_used":
                isinstance(provider.web_provider, FirewallSearchProvider),
            "t26_firewall_used":
                isinstance(provider.web_provider.firewall,
                           T26LiveWebSourceFirewall),
            "inner_live_or_fixture": provider.web_provider.live_or_fixture,
            "external_authority": False,
            "candidate_gold_access": False,
            "corpus_source": "FROZEN_PUBLIC",
            "document_root_source": "PER_SCENARIO_PRIVATE_WORKSPACE",
            "general_context_identity_root":
                self.general_context_identity["identity_root"],
        }
        validate_stack_attestation(self.last_stack, real=self.real)
        return runner

    def binding(self) -> dict[str, Any]:
        return {
            "official_runner_factory_id": self.identity["factory_id"],
            "official_runner_factory_sha256":
                self.identity["factory_implementation_sha256"],
            "production_runtime_sha256":
                self.identity["production_runtime_sha256"],
            "production_provider_id": self.identity["production_provider_id"],
            "production_provider_sha256":
                self.identity["production_provider_sha256"],
            "production_adapter_registry_root":
                self.identity["production_adapter_registry_root"],
            "official_runner_policy_root":
                self.identity["official_runner_policy_root"],
            "live_provider_identity_root":
                self.live_provider_identity["identity_root"],
            "general_context_identity_root":
                self.general_context_identity["identity_root"],
        }

    def preflight(self) -> dict[str, Any]:
        """Construct the exact stack without executing any scenario."""
        before = self.runner_count
        with TemporaryDirectory(prefix="t26-official-runner-preflight-") as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            runner = self(workspace)
            if not isinstance(runner, IntegratedRunner):
                raise ValueError("official preflight runner type mismatch")
            if list(workspace.rglob("checkpoints/*.json")):
                raise ValueError("runner initialization executed a scenario")
        self.runner_count = before
        return dict(self.last_stack)


def build_official_runner_factory(
        root: Path, *, live_web_provider: Any, general_context: Any,
        real: bool = True) -> OfficialRunnerFactory:
    """The sole canonical factory constructor for real and rehearsal stacks."""
    return OfficialRunnerFactory(
        root, web_provider=live_web_provider,
        general_context=general_context, real=real)


def validate_factory_instance(factory: Any, root: Path, *, real: bool) -> None:
    if type(factory) is not OfficialRunnerFactory:
        raise ValueError("arbitrary runner factory refused")
    expected = verify_runner_identity_document(root)
    if factory.identity != expected or factory.real is not real:
        raise ValueError("official runner factory identity or mode mismatch")
