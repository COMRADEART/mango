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
import os
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciencemath.executive.budgets import Budgets, default_usage
from sciencemath.executive.runner import DEFAULT_FEATURES, ExecContext
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
GENERAL_CONTEXT_SCHEMA = "t26-official-general-context-identity-v1"
GENERAL_CONTEXT_IDENTITY_PATH = (
    "evaluations/t26/T26_OFFICIAL_GENERAL_CONTEXT.json")
PUBLIC_CORPUS = "rag/gk_corpus"
QUALIFICATION_EXCLUSIONS = "evaluations/t26/qualification_exclusions.json"
PRODUCTION_CONFIG = "evaluations/t25/production_provider_config.json"

EXPECTED_BASE_MODEL = "Qwen/Qwen3-1.7B"
EXPECTED_BASE_REVISION = "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
EXPECTED_ADAPTER = (
    "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors")
EXPECTED_ADAPTER_SHA256 = (
    "f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668")
EXPECTED_ADAPTER_BYTES = 139512976
EXPECTED_RETRIEVAL_K = 3
EXEC_CONTEXT_FIELDS = tuple(field.name for field in fields(ExecContext))
TOKENIZER_FILES = (
    "merges.txt", "tokenizer.json", "tokenizer_config.json", "vocab.json")

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
    general_context = json.loads((root / GENERAL_CONTEXT_IDENTITY_PATH)
                                 .read_text(encoding="utf-8"))
    if (general_context.get("schema_version") != GENERAL_CONTEXT_SCHEMA or
            general_context.get("identity_root") != sha256_json({
                key: value for key, value in general_context.items()
                if key != "identity_root"})):
        raise ValueError("official GENERAL context identity document invalid")
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
        "general_context_identity_root": general_context["identity_root"],
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
        "general_context_identity_root": general_context["identity_root"],
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


def _assert_safe_projected_path(value: str, *, field: str) -> None:
    """Reject private/evaluation paths on the bounded execution surface.

    Model and tokenizer object graphs are deliberately opaque and are never
    passed here.  Only explicit, serializable control-plane configuration is
    path-checked.
    """
    lowered = value.replace("\\", "/").casefold()
    forbidden = (
        "t26-store-01", "/construction/", "/gold/",
        "/evaluation/workspaces/", "/evaluation/raw_outputs",
        "/evaluation/scored_rows", "/evaluation/summary",
        "/evaluation/provenance", "private_evaluation",
        "historical_private_store",
    )
    if any(fragment in lowered for fragment in forbidden):
        raise ValueError(f"private path on GENERAL context surface: {field}")


def _bounded_control(value: Any, *, field: str,
                     seen: set[int] | None = None) -> Any:
    """Canonicalize bounded execution control data, never opaque ML graphs."""
    seen = seen or set()
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        _assert_safe_projected_path(value, field=field)
        return value
    if isinstance(value, Path):
        rendered = value.resolve().as_posix()
        _assert_safe_projected_path(rendered, field=field)
        return rendered
    marker = id(value)
    if marker in seen:
        raise ValueError(f"cyclic GENERAL context control data: {field}")
    seen.add(marker)
    if isinstance(value, dict):
        if any(str(key).casefold() in GOLD_MARKERS for key in value):
            raise ValueError(f"gold marker on GENERAL context surface: {field}")
        result = {}
        for key in sorted(value, key=lambda item: str(item)):
            if not isinstance(key, (str, int, float, bool)):
                raise ValueError(f"non-scalar GENERAL context key: {field}")
            child = value[key]
            if callable(child):
                raise ValueError(f"callable GENERAL context injection: {field}")
            result[str(key)] = _bounded_control(
                child, field=f"{field}.{key}", seen=seen)
        return result
    if isinstance(value, (list, tuple)):
        return [_bounded_control(child, field=f"{field}[{index}]", seen=seen)
                for index, child in enumerate(value)]
    if isinstance(value, (set, frozenset)):
        normalized = [_bounded_control(child, field=f"{field}[]", seen=seen)
                      for child in value]
        return sorted(normalized, key=lambda item: json.dumps(
            item, sort_keys=True, separators=(",", ":")))
    raise ValueError(
        f"opaque object on bounded GENERAL context surface: {field} "
        f"({type(value).__module__}:{type(value).__qualname__})")


def _control_identity(value: Any, *, field: str) -> dict[str, Any]:
    normalized = _bounded_control(value, field=field)
    return {"value": normalized, "root": sha256_json(normalized)}


def _dependency_identity(root: Path, value: Any, *, role: str) -> dict[str, Any]:
    if value is None:
        return {"kind": "NONE"}
    identity = _implementation_identity(root, value, role=role)
    state = _control_identity(vars(value), field=role.replace(" ", "_"))
    identity.update({"kind": "SOURCE_BACKED", "configuration": state})
    if role == "retriever" and not any(
            key in state["value"] for key in
            ("corpus_identity", "corpus_root", "corpus", "source")):
        raise ValueError("retriever corpus identity required")
    identity["identity_root"] = sha256_json(identity)
    return identity


def _hf_snapshot() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        hub = Path(os.environ["HF_HUB_CACHE"])
    else:
        hf_home = Path(os.environ.get(
            "HF_HOME", str(Path.home() / ".cache" / "huggingface")))
        hub = hf_home / "hub"
    model_root = hub / "models--Qwen--Qwen3-1.7B"
    ref = model_root / "refs" / "main"
    if (not ref.is_file() or
            ref.read_text(encoding="utf-8").strip() != EXPECTED_BASE_REVISION):
        raise ValueError("qualified base-model cache revision unavailable")
    snapshot = model_root / "snapshots" / EXPECTED_BASE_REVISION
    if not snapshot.is_dir():
        raise ValueError("qualified base-model snapshot unavailable")
    return snapshot


def _public_file_identity(snapshot: Path, names: tuple[str, ...]) -> list[dict[str, Any]]:
    entries = []
    for name in names:
        path = snapshot / name
        if not path.is_file():
            raise ValueError(f"qualified public model file absent: {name}")
        data = path.read_bytes()
        entries.append({"path": name, "sha256": _sha(data), "bytes": len(data)})
    return entries


def _inspect_model_provenance(root: Path, model: Any) -> dict[str, Any]:
    from sciencemath.training.attach import adapter_active_state

    config = json.loads((root / PRODUCTION_CONFIG).read_text(encoding="utf-8"))
    adapter = (root / EXPECTED_ADAPTER).resolve()
    if (config.get("general_model") != EXPECTED_BASE_MODEL or
            config.get("general_base_revision") != EXPECTED_BASE_REVISION or
            config.get("general_adapter") != EXPECTED_ADAPTER or
            config.get("general_adapter_sha256") != EXPECTED_ADAPTER_SHA256):
        raise ValueError("qualified GENERAL production config drift")
    if (not adapter.is_file() or adapter.stat().st_size != EXPECTED_ADAPTER_BYTES or
            _sha(adapter.read_bytes()) != EXPECTED_ADAPTER_SHA256):
        raise ValueError("qualified GENERAL adapter payload unavailable")
    state = adapter_active_state(model)
    if (not state.get("is_peft_model") or
            not state.get("adapter_active") or
            state.get("adapters_disabled") or
            state.get("adapter_names") != ["t3"]):
        raise ValueError("qualified GENERAL adapter is not active")
    peft_config = getattr(model, "peft_config", {}).get("t3")
    if (peft_config is None or
            getattr(peft_config, "base_model_name_or_path", None) !=
            EXPECTED_BASE_MODEL or
            getattr(peft_config, "inference_mode", None) is not True):
        raise ValueError("qualified GENERAL PEFT provenance mismatch")
    if bool(getattr(model, "training", True)):
        raise ValueError("qualified GENERAL model is not in eval mode")
    if bool(getattr(model, "is_quantized", False)):
        raise ValueError("qualified GENERAL model unexpectedly quantized")
    dtype = str(getattr(model, "dtype", "unknown"))
    if dtype != "torch.bfloat16":
        raise ValueError("qualified GENERAL model dtype mismatch")
    snapshot = _hf_snapshot()
    model_files = _public_file_identity(
        snapshot, ("config.json", "model.safetensors.index.json"))
    return {
        "module": type(model).__module__,
        "class": type(model).__qualname__,
        "base_model_id": EXPECTED_BASE_MODEL,
        "base_revision": EXPECTED_BASE_REVISION,
        "base_public_metadata": model_files,
        "base_public_metadata_root": sha256_json(model_files),
        "quantization": {"mode": "bf16", "is_quantized": False,
                         "parameter_dtype": dtype},
        "adapter": {"path": EXPECTED_ADAPTER,
                    "sha256": EXPECTED_ADAPTER_SHA256,
                    "bytes": EXPECTED_ADAPTER_BYTES,
                    "name": "t3", "active": True},
        "eval_mode": True,
        "inference_mode": True,
        "initialized_from_public_artifacts": True,
    }


def _inspect_tokenizer_identity(tokenizer: Any) -> dict[str, Any]:
    if str(getattr(tokenizer, "name_or_path", "")) != EXPECTED_BASE_MODEL:
        raise ValueError("qualified GENERAL tokenizer source mismatch")
    snapshot = _hf_snapshot()
    files = _public_file_identity(snapshot, TOKENIZER_FILES)
    template = getattr(tokenizer, "chat_template", None)
    if not isinstance(template, (str, dict)):
        raise ValueError("qualified GENERAL tokenizer chat template absent")
    template_identity = _control_identity(template, field="chat_template")
    return {
        "module": type(tokenizer).__module__,
        "class": type(tokenizer).__qualname__,
        "source_id": EXPECTED_BASE_MODEL,
        "source_revision": EXPECTED_BASE_REVISION,
        "public_files": files,
        "public_file_root": sha256_json(files),
        "chat_template_root": template_identity["root"],
        "chat_template_included": False,
        "is_fast": bool(getattr(tokenizer, "is_fast", False)),
        "initialized_from_public_artifacts": True,
    }


def build_general_context_identity(root: Path,
                                   context: ExecContext) -> dict[str, Any]:
    """Project and bind the complete official ExecContext execution surface.

    The Transformer model and tokenizer are opaque identity-bound dependencies:
    their arbitrary ``__dict__`` graphs (including vocabulary tokens) are not
    interpreted as candidate-visible data.  Every ExecContext control-plane
    field remains explicit, bounded, gold-checked, path-checked, and rooted.
    """
    root = Path(root).resolve()
    if type(context) is not ExecContext:
        raise ValueError("REAL_BLIND requires exact ExecContext type")
    observed_fields = tuple(vars(context))
    if set(observed_fields) != set(EXEC_CONTEXT_FIELDS):
        unexpected = sorted(set(observed_fields) - set(EXEC_CONTEXT_FIELDS))
        missing = sorted(set(EXEC_CONTEXT_FIELDS) - set(observed_fields))
        raise ValueError(
            f"unexpected ExecContext attributes: extra={unexpected} missing={missing}")
    generation = _control_identity(context.generation, field="generation")
    usage = _control_identity(context.usage, field="usage")
    budgets = _control_identity(context.budgets.to_dict(), field="budgets")
    features = _control_identity(context.features, field="features")
    expected_usage = _control_identity(default_usage(), field="usage")
    expected_budgets = _control_identity(Budgets().to_dict(), field="budgets")
    expected_features = _control_identity(dict(DEFAULT_FEATURES), field="features")
    production = json.loads((root / PRODUCTION_CONFIG).read_text(encoding="utf-8"))
    expected_generation = _control_identity(
        production["general_generation"], field="generation")
    if generation != expected_generation:
        raise ValueError("official GENERAL generation settings mismatch")
    if usage != expected_usage:
        raise ValueError("official GENERAL usage state is not pristine")
    if budgets != expected_budgets:
        raise ValueError("official GENERAL budgets mismatch")
    if features != expected_features:
        raise ValueError("official GENERAL feature map mismatch")
    if context.trajectory is not None:
        raise ValueError("official GENERAL trajectory sink is not approved")
    if context.checkpointer is not None:
        raise ValueError("official GENERAL checkpointer is not approved")
    if type(context.retrieval_k) is not int or context.retrieval_k != EXPECTED_RETRIEVAL_K:
        raise ValueError("official GENERAL retrieval_k mismatch")
    context_identity = _implementation_identity(root, context, role="general context")
    registry = _dependency_identity(root, context.registry, role="registry")
    retriever = _dependency_identity(root, context.retriever, role="retriever")
    model = _inspect_model_provenance(root, context.model)
    tokenizer = _inspect_tokenizer_identity(context.tokenizer)
    gold_channel_count = 0
    private_dependency_count = 0
    document = {
        "schema_version": GENERAL_CONTEXT_SCHEMA,
        "artifact": "T26_OFFICIAL_GENERAL_CONTEXT_IDENTITY",
        "classification": "PUBLIC_SAFE", "experiment": "t26",
        "context": {**context_identity,
                    "field_contract": list(EXEC_CONTEXT_FIELDS),
                    "context_kind": "PRODUCTION"},
        "model": model, "tokenizer": tokenizer,
        "registry": registry, "retriever": retriever,
        "generation": generation, "initial_usage": usage,
        "budgets": budgets, "features": features,
        "trajectory_policy": "NONE",
        "checkpointer_policy": "NONE",
        "retrieval_k": context.retrieval_k,
        "opaque_dependency_boundary": {
            "model_recursive_introspection": False,
            "tokenizer_recursive_introspection": False,
            "bounded_control_plane_recursive_inspection": True},
        "gold_channel_count": gold_channel_count,
        "private_dependency_count": private_dependency_count,
        "candidate_gold_access": gold_channel_count != 0,
        "private_store_dependency": private_dependency_count != 0,
    }
    document["identity_root"] = sha256_json(document)
    return document


def verify_general_context_identity_document(
        root: Path, context: ExecContext) -> dict[str, Any]:
    root = Path(root).resolve()
    expected = json.loads((root / GENERAL_CONTEXT_IDENTITY_PATH)
                          .read_text(encoding="utf-8"))
    observed = build_general_context_identity(root, context)
    if observed != expected:
        raise ValueError("official GENERAL context identity mismatch")
    return observed


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
    if real:
        return verify_general_context_identity_document(root, context)
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
