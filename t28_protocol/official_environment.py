"""Frozen T28 official evaluation environment (authorization §20–§29).

The builder owns every execution-relevant dependency — model/adapter/tokenizer
stack, GENERAL ExecContext, live provider, firewall stack, production
provider, adapter registry, runner factory — and returns an identity-bound
environment object.  The T28 closed entrypoint only ever passes the
environment this module built; anonymous/closure dependencies and
caller-supplied providers, contexts, corpora, document roots or runners are
refused.  The environment never reads private blind/gold material, never
opens the T27 or T28 private stores, and never executes the candidate
(preflight constructs the stack without running any scenario).

Mode-dependent identity: the frozen environment identity carries the real
environment root (requires ``live_or_fixture = live``) and the explicitly
tagged disposable rehearsal root (fixture substitutes); both are frozen at
preconstruction and verified at construction time.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from t21_protocol.util import sha256_json

from sciencemath.integrated.runner import IntegratedRunner
from t25_protocol.firewall import FirewallSearchProvider
from t25_protocol.provider import PROVIDER_ID, T25ProductionRouterProvider
from t26_protocol.firewall import T26LiveWebSourceFirewall
from t26_protocol.official_runner import (DeterministicFixtureSearchProvider,
                                          DeterministicGeneralContext,
                                          _contains_gold, _control_identity,
                                          _dependency_identity,
                                          _public_file_identity,
                                          build_general_context_identity,
                                          inspect_live_provider)
from t26_protocol.production import build_adapters

ENVIRONMENT_BUILDER_ID = (
    "t28_protocol.official_environment:build_official_evaluation_environment")
FACTORY_ID = "T28_OFFICIAL_PRODUCTION_RUNNER_FACTORY_V1"
FACTORY_CLASS = "t28_protocol.official_environment:T28OfficialRunnerFactory"
IDENTITY_PATH = "evaluations/t28/official_environment_identity.json"
PRODUCTION_CONFIG = "evaluations/t25/production_provider_config.json"
PUBLIC_CORPUS = "rag/gk_corpus"
EXPECTED_BASE_MODEL = "Qwen/Qwen3-1.7B"
TOKENIZER_FILES = ("merges.txt", "tokenizer.json",
                   "tokenizer_config.json", "vocab.json")

MODEL_PINS = {
    "base_model_id": "Qwen/Qwen3-1.7B",
    "base_revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
    "adapter_path": "training/adapters/sciencemath-v0.1-t3/"
                    "adapter_model.safetensors",
    "adapter_sha256":
        "f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668",
    "adapter_bytes": 139512976,
    "adapter_name": "t3",
    "adapter_active_required": True,
    "model_implementation_class": "PeftModelForCausalLM",
    "quantization_mode": "bf16",
    "is_quantized": False,
    "parameter_dtype": "torch.bfloat16",
    "eval_mode": True,
    "inference_mode": True,
    "retrieval_k": 3,
    "tokenizer_class": "Qwen2Tokenizer",
    "chat_template_required": True,
}

WORKSPACE_MODE = "T28_OFFICIAL_EVALUATION"
T26_WORKSPACE_MODE_PREDECESSOR = "REAL_EXPERIMENT"
CANDIDATE_RUNTIME_MODULES = (
    "src/sciencemath/integrated/__init__.py",
    "src/sciencemath/integrated/runner.py",
)


def _sha(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _repo_bytes(root: Path, relative: str) -> bytes:
    data = (root / relative).read_bytes()
    if b"\0" not in data:
        data = data.replace(b"\r\n", b"\n")
    return data


def load_production_model_stack(root: Path) -> tuple:
    """Load the exact qualified T25/T26/T27 GENERAL model stack.

    T28 continues the T27 production model stack (§21); the adapter payload
    is pinned by SHA and the provenance manifest must agree with the frozen
    production configuration.
    """
    root = Path(root).resolve()
    import os

    import torch
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from sciencemath.executive.runner import ExecContext
    from sciencemath.training.attach import load_base_with_adapter

    config = json.loads((root / PRODUCTION_CONFIG).read_text(encoding="utf-8"))
    adapter = root / MODEL_PINS["adapter_path"]
    if (adapter.stat().st_size != MODEL_PINS["adapter_bytes"] or
            _sha(adapter.read_bytes()) != MODEL_PINS["adapter_sha256"]):
        raise ValueError("qualified hydrated GENERAL adapter unavailable")
    manifest = json.loads(
        (adapter.parent / "artifact_manifest.json").read_text(encoding="utf-8"))
    if (manifest["base_model"] != MODEL_PINS["base_model_id"] or
            manifest["base_revision"] != MODEL_PINS["base_revision"]):
        raise ValueError("qualified GENERAL adapter provenance mismatch")
    torch.set_num_threads(min(4, os.cpu_count() or 4))
    tokenizer, model, info = load_base_with_adapter(
        MODEL_PINS["base_model_id"], str(adapter.parent), quantized_4bit=False)
    if not info.get("ok") or not info.get("adapter_state", {}).get(
            "adapter_active"):
        raise ValueError(f"qualified GENERAL runtime unavailable: "
                         f"{info.get('error')}")
    context = ExecContext(model=model, tokenizer=tokenizer,
                          generation=dict(config["general_generation"]))
    return context, model, tokenizer, config


def t28_general_context_document(root: Path, context: Any) -> dict[str, Any]:
    """T28 GENERAL-context identity bound to the T26 predecessor document.

    T26's identity projection is reused because T28 ships the same production
    model stack (§21); the document is re-keyed into the T28 namespace with
    the T26 predecessor root recorded.  Model/tokenizer object graphs remain
    opaque; only the bounded control plane is surfaced.
    """
    root = Path(root).resolve()
    underlying = build_general_context_identity(root, context)
    if underlying["candidate_gold_access"] or underlying["private_store_dependency"]:
        raise ValueError("gold or private-store channel in GENERAL context")
    document = {key: value for key, value in underlying.items()
                if key != "identity_root"}
    document["schema_version"] = "t28-official-general-context-identity-v1"
    document["artifact"] = "T28_OFFICIAL_GENERAL_CONTEXT_IDENTITY"
    document["classification"] = "PUBLIC_SAFE"
    document["experiment"] = "t28"
    document["workspaces"] = {
        "mode": WORKSPACE_MODE,
        "predecessor_mode": T26_WORKSPACE_MODE_PREDECESSOR,
    }
    document["t26_predecessor_document"] = {
        "schema_version": underlying["schema_version"],
        "artifact": underlying["artifact"],
        "identity_root": underlying["identity_root"],
    }
    return _rooted(document)


def disposable_general_context_document() -> dict[str, Any]:
    context = DeterministicGeneralContext()
    if getattr(context, "candidate_gold_access", True):
        raise ValueError("gold-carrying disposable GENERAL context refused")
    document = {
        "schema_version": "t28-official-general-context-identity-v1",
        "artifact": "T28_DISPOSABLE_GENERAL_CONTEXT",
        "classification": "PUBLIC_SAFE", "experiment": "t28",
        "context_kind": "DISPOSABLE",
        "data": _control_identity(vars(context), field="disposable_context"),
        "candidate_gold_access": False,
        "private_store_dependency": False,
        "policy": {
            "fixture_allowed_only_for_disposable_rehearsal": True,
            "context_builder_shared_with_real_mode": False,
            "explicitly_tagged_substitute": True,
        },
    }
    return _rooted(document)


def _rooted(document: dict[str, Any]) -> dict[str, Any]:
    document["identity_root"] = sha256_json({
        key: value for key, value in document.items() if key != "identity_root"})
    return document


def verify_general_context_document(root: Path, context: Any) -> dict[str, Any]:
    expected = json.loads(
        (Path(root).resolve() / "evaluations/t28/official_general_context.json")
        .read_text(encoding="utf-8"))
    observed = t28_general_context_document(root, context)
    if observed != expected:
        raise ValueError("official T28 GENERAL context identity mismatch")
    return observed


def environment_identity(root: Path, *, real: bool,
                         general_context_identity_root: str,
                         live_provider_identity_root: str) -> dict[str, Any]:
    """Identity of the frozen environment (§20–§29), without self-hash."""
    root = Path(root).resolve()
    corpus_root = subprocess.run(
        ["git", "rev-parse", f"HEAD:{PUBLIC_CORPUS}"], cwd=root,
        capture_output=True, text=True, check=True).stdout.strip()
    from sciencemath.executive.skills import SKILL_IDS
    registry_root = sha256_json({
        "registered_skills": list(SKILL_IDS),
        "builder": "t28_protocol.production:build_adapters"})
    return {
        "schema_version": "t28-official-environment-identity-v1",
        "artifact": "T28_OFFICIAL_ENVIRONMENT_IDENTITY",
        "classification": "PUBLIC_SAFE", "experiment": "t28",
        "builder_id": ENVIRONMENT_BUILDER_ID,
        "builder_class": FACTORY_CLASS,
        "builder_implementation_sha256": _sha(_repo_bytes(
            root, "t28_protocol/official_environment.py")),
        "real": bool(real),
        "real_requires_live_or_fixture": "live",
        "workspace_mode": WORKSPACE_MODE,
        "predecessor_workspace_mode": T26_WORKSPACE_MODE_PREDECESSOR,
        "candidate_runtime": {
            "modules": CANDIDATE_RUNTIME_MODULES,
            "modules_sha256": {relative: _sha(_repo_bytes(root, relative))
                               for relative in CANDIDATE_RUNTIME_MODULES},
            "integrated_runner_class":
                "sciencemath.integrated.runner:IntegratedRunner",
        },
        "model": MODEL_PINS,
        "tokenizer": {
            "source_id": EXPECTED_BASE_MODEL,
            "source_revision": MODEL_PINS["base_revision"],
            "tokenizer_files": TOKENIZER_FILES,
            "chat_template_required": True,
        },
        "production_provider": {
            "provider_id": PROVIDER_ID,
            "provider_kind": "REAL_CANDIDATE",
            "synthetic": False,
            "workspace_mode": WORKSPACE_MODE,
            "firewall_mandatory": True,
            "implementation_sha256": _sha(_repo_bytes(
                root, "t25_protocol/provider.py")),
            "configuration_root": _sha(_repo_bytes(root, PRODUCTION_CONFIG)),
        },
        "firewall_stack": {
            "firewall_search_provider":
                "t25_protocol.firewall:FirewallSearchProvider",
            "firewall_search_provider_sha256": _sha(_repo_bytes(
                root, "t25_protocol/firewall.py")),
            "t26_live_web_firewall":
                "t26_protocol.firewall:T26LiveWebSourceFirewall",
            "t26_live_web_firewall_sha256": _sha(_repo_bytes(
                root, "t26_protocol/firewall.py")),
        },
        "adapter_registry": {
            "builder": "t28_protocol.production:build_adapters",
            "registered_skill_ids": list(SKILL_IDS),
            "internal_only": True,
            "may_perform_external_action": False,
            "registry_root": registry_root,
        },
        "corpus": {"path_policy": PUBLIC_CORPUS, "source": "FROZEN_PUBLIC",
                   "content_root": corpus_root,
                   "caller_selected_directories_allowed": False},
        "document_mount_policy": {
            "source": "PER_SCENARIO_PRIVATE_EVALUATION_WORKSPACE",
            "derivation": ["sealed T28 private manifest",
                           "isolated evaluation workspace"],
            "relative_path": "documents",
            "initially_empty": True,
            "cross_scenario_visibility": False,
            "caller_document_roots_allowed": False,
            "policy_root": sha256_json({
                "policy": "PER_SCENARIO_PRIVATE_EVALUATION_WORKSPACE",
                "derivation": ["sealed T28 private manifest",
                               "isolated evaluation workspace"],
                "cross_scenario_visibility": False}),
        },
        "general_context_identity_root": general_context_identity_root,
        "live_provider_identity_root": live_provider_identity_root,
        "authority": {
            "external_action_authority": False,
            "candidate_gold_access": False,
        },
        "policy": {
            "caller_supplied_runner_allowed": False,
            "caller_supplied_context_allowed": False,
            "caller_supplied_corpus_allowed": False,
            "caller_supplied_document_roots_allowed": False,
            "anonymous_or_closure_provider_allowed": False,
            "fixture_allowed_only_for_disposable_rehearsal": True,
            "identity_bound_before_ledger": True,
        },
    }


class T28OfficialRunnerFactory:
    """Callable canonical factory; each call creates an isolated runner."""

    def __init__(self, root: Path, *, web_provider: Any,
                 general_context: Any, real: bool) -> None:
        self.root = Path(root).resolve()
        self.real = bool(real)
        self.web_provider = web_provider
        self.general_context = general_context
        self.corpus_dir = self._validate_corpus()
        self.runner_count = 0
        self.last_stack: dict[str, Any] = {}
        self._provider: T25ProductionRouterProvider | None = None
        self._adapters: dict[str, Any] | None = None

    def _validate_corpus(self) -> Path:
        approved = (self.root / PUBLIC_CORPUS).resolve()
        if not approved.is_dir():
            raise ValueError("official T28 corpus mount unavailable")
        if _contains_gold(approved):
            raise ValueError("corpus mount carries gold content")
        return approved

    def __call__(self, workspace: Path) -> IntegratedRunner:
        workspace = Path(workspace).resolve()
        if not workspace.is_dir():
            raise ValueError("official T28 runner workspace absent")
        document_root = (workspace / "documents").resolve()
        if workspace not in document_root.parents:
            raise ValueError("official document mount escapes workspace")
        document_root.mkdir(parents=False, exist_ok=False)
        if self._provider is None:
            # The web-source firewall is inherited unchanged from the official
            # T26/T27 environment and binds the historical T26 qualification
            # exclusion registry; the T28 qualification exclusions are bound
            # separately (construction gate + evaluation bindings).
            from t26_protocol.exclusion import T26_QUALIFICATION_EXCLUSIONS
            exclusions = json.loads(
                (self.root / T26_QUALIFICATION_EXCLUSIONS).read_text(
                    encoding="utf-8"))
            firewall = T26LiveWebSourceFirewall(self.root, exclusions)
            wrapped = FirewallSearchProvider(self.web_provider, firewall)
            self._provider = T25ProductionRouterProvider(
                self.corpus_dir, web_provider=wrapped,
                general_context=self.general_context,
                document_roots=(document_root,),
                # The frozen T23 provider layer keeps its historical two-mode
                # pin (unmodified predecessor bytes); the T28-declared mode
                # "T28_OFFICIAL_EVALUATION" lives in the identity/binding layer.
                workspace_mode=(
                    "REAL_EXPERIMENT" if self.real else
                    "SYNTHETIC_DISPOSABLE"),
                firewall_mandatory=True)
            self._adapters = build_adapters(self._provider)
        else:
            # Evaluation is sequential; rebinding the sole DOCUMENT root per
            # runner preserves scenario isolation while the frozen
            # corpus/firewall/adapter composition is reused.
            self._provider.document_roots = (document_root,)
        provider, adapters = self._provider, self._adapters
        from sciencemath.executive.skills import SKILL_IDS
        if set(adapters) != set(SKILL_IDS):
            raise ValueError("official T28 adapter registry mismatch")
        if any(not adapter.internal_only or adapter.may_perform_external_action
               for adapter in adapters.values()):
            raise ValueError("official T28 adapter authority mismatch")
        if (not isinstance(provider.web_provider, FirewallSearchProvider) or
                not isinstance(provider.web_provider.firewall,
                               T26LiveWebSourceFirewall)):
            raise ValueError("official T28 firewall stack mismatch")
        runner = IntegratedRunner(adapters, sandbox_root=workspace)
        self.runner_count += 1
        self.last_stack = {
            "factory_id": FACTORY_ID,
            "integrated_runner_used": isinstance(runner, IntegratedRunner),
            "production_adapter_registry_used": True,
            "provider_id": provider.provider_id,
            "provider_kind": provider.provider_kind,
            "provider_synthetic": provider.synthetic,
            "workspace_mode": WORKSPACE_MODE,
            "firewall_mandatory": True,
            "firewall_search_provider_used": True,
            "t26_firewall_used": True,
            "inner_live_or_fixture": provider.web_provider.live_or_fixture,
            "external_authority": False,
            "candidate_gold_access": False,
            "corpus_source": "FROZEN_PUBLIC",
            "document_root_source":
                "PER_SCENARIO_PRIVATE_EVALUATION_WORKSPACE",
            "general_context_identity_bound": True,
        }
        return runner

    def preflight(self) -> dict[str, Any]:
        """Construct the exact stack without executing any scenario."""
        before = self.runner_count
        with TemporaryDirectory(prefix="t28-official-runner-preflight-") as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            runner = self(workspace)
            if not isinstance(runner, IntegratedRunner):
                raise ValueError("official preflight runner type mismatch")
            if list(workspace.rglob("checkpoints/*.json")):
                raise ValueError("runner initialization executed a scenario")
        self.runner_count = before
        return dict(self.last_stack)

    def binding(self) -> dict[str, Any]:
        return {
            "official_runner_factory_id": FACTORY_ID,
            "official_runner_factory_class": FACTORY_CLASS,
            "production_provider_id": PROVIDER_ID,
            "workspace_mode": WORKSPACE_MODE,
            "inner_live_or_fixture": self.web_provider.live_or_fixture,
            "network_required": bool(self.web_provider.network_required),
            "external_authority": False,
            "candidate_gold_access": False,
        }


def require_stack_attestation(stack: dict[str, Any], *, real: bool) -> None:
    required = {
        "factory_id": FACTORY_ID,
        "integrated_runner_used": True,
        "production_adapter_registry_used": True,
        "provider_kind": "REAL_CANDIDATE",
        "provider_synthetic": False,
        "workspace_mode": WORKSPACE_MODE,
        "firewall_mandatory": True,
        "firewall_search_provider_used": True,
        "t26_firewall_used": True,
        "inner_live_or_fixture": "live" if real else "fixture",
        "external_authority": False,
        "candidate_gold_access": False,
        "corpus_source": "FROZEN_PUBLIC",
        "document_root_source":
            "PER_SCENARIO_PRIVATE_EVALUATION_WORKSPACE",
    }
    if any(stack.get(key) != value for key, value in required.items()):
        raise ValueError("official T28 production stack attestation mismatch")


class T28OfficialEnvironment:
    """Identity-bound owned environment produced by the sole official builder."""

    def __init__(self, *, root: Path, real: bool, context: Any,
                 factory: T28OfficialRunnerFactory,
                 provider_identity: dict[str, Any],
                 general_context_document: dict[str, Any],
                 environment_identity_document: dict[str, Any]) -> None:
        self.root = Path(root).resolve()
        self.real = bool(real)
        self.context = context
        self.factory = factory
        self.provider_identity = provider_identity
        self.general_context_document = general_context_document
        self.environment_identity_document = environment_identity_document

    @property
    def environment_root(self) -> str:
        return self.environment_identity_document["environment_root"]

    def policy_root(self) -> str:
        return sha256_json({
            "caller_supplied_runner_allowed": False,
            "factory_owns_provider_construction": True,
            "candidate_gold_access": False,
            "synthetic_data_source_allowed_only_for_disposable_rehearsal": True,
            "real_mode_requires_sealed_store": True,
            "workspace_mode": WORKSPACE_MODE})

    def official_runner_identity_root(self) -> str:
        return sha256_json({
            "factory_id": FACTORY_ID,
            "builder_implementation_sha256": _sha(_repo_bytes(
                self.root, "t28_protocol/official_environment.py")),
            "environment_root": self.environment_root,
            "context_identity_root":
                self.general_context_document["identity_root"],
            "live_provider_identity_root":
                self.provider_identity["identity_root"],
            "provider_id": PROVIDER_ID,
            "workspace_mode": WORKSPACE_MODE})

    def binding(self) -> dict[str, Any]:
        return {
            "environment_builder_id": ENVIRONMENT_BUILDER_ID,
            "environment_root": self.environment_root,
            "general_context_identity_root":
                self.general_context_document["identity_root"],
            "live_provider_identity_root":
                self.provider_identity["identity_root"],
            "live_provider_name": self.factory.web_provider.provider_name,
            "live_or_fixture": self.factory.web_provider.live_or_fixture,
            "network_required": bool(self.factory.web_provider.network_required),
            "official_runner_factory_id": FACTORY_ID,
            "official_runner_identity_root": self.official_runner_identity_root(),
            "official_runner_policy_root": self.policy_root(),
            "workspace_mode": WORKSPACE_MODE,
            "policy": {
                "caller_supplied_runner_allowed": False,
                "external_action_authority": False,
                "candidate_gold_access": False,
            },
        }

    def preflight(self) -> dict[str, Any]:
        stack = self.factory.preflight()
        require_stack_attestation(stack, real=self.real)
        if self.factory.runner_count != 0:
            raise ValueError("environment preflight executed a candidate")
        return stack


def build_official_evaluation_environment(root: Path, *,
                                          real: bool) -> T28OfficialEnvironment:
    """The sole official environment builder (§20); caller substitution impossible."""
    root = Path(root).resolve()
    if real:
        context, _model, _tokenizer, _config = load_production_model_stack(root)
        general_document = verify_general_context_document(root, context)
        provider = wikipedia_live_provider()
    else:
        context = DeterministicGeneralContext()
        general_document = disposable_general_context_document()
        provider = DeterministicFixtureSearchProvider()
    provider_identity = inspect_live_provider(root, provider, real=real)
    factory = T28OfficialRunnerFactory(
        root, web_provider=provider, general_context=context, real=real)
    identity_document = build_environment_identity_document(
        root, real=real,
        general_context_identity_root=general_document["identity_root"],
        live_provider_identity_root=provider_identity["identity_root"])
    return T28OfficialEnvironment(
        root=root, real=real, context=context, factory=factory,
        provider_identity=provider_identity,
        general_context_document=general_document,
        environment_identity_document=identity_document)


def wikipedia_live_provider() -> Any:
    """Approved live provider, constructed inside the environment only."""
    from sciencemath.web.live_provider import WikipediaLiveProvider
    return WikipediaLiveProvider(timeout_s=8.0, enabled=True)


def build_environment_identity_document(root: Path, *, real: bool,
                                        general_context_identity_root: str,
                                        live_provider_identity_root: str
                                        ) -> dict[str, Any]:
    """Rebuild and verify the frozen environment identity for one mode."""
    root = Path(root).resolve()
    expected = json.loads(
        (root / IDENTITY_PATH).read_text(encoding="utf-8"))
    identity = environment_identity(
        root, real=real,
        general_context_identity_root=general_context_identity_root,
        live_provider_identity_root=live_provider_identity_root)
    key = "environment_root" if real else "rehearsal_environment_root"
    observed_root = sha256_json(identity)
    if observed_root != expected[key]:
        raise ValueError(f"official T28 environment identity drift ({key})")
    return {**identity, "environment_root": observed_root,
            "identity_mode_key": key}


def stage_environment_identity(root: Path, *, rehearsal_only: bool = False
                               ) -> dict[str, Any]:
    """Compute the frozen identity document (preconstruction staging only).

    real mode requires loading the qualified model stack; the disposable
    rehearsal root is computed without the model.  This function never reads
    private material and never executes the candidate.
    """
    root = Path(root).resolve()
    provider = wikipedia_live_provider()
    provider_identity = inspect_live_provider(root, provider, real=True)
    if rehearsal_only:
        fixture_identity = inspect_live_provider(
            root, DeterministicFixtureSearchProvider(), real=False)
        disposable_root = sha256_json(environment_identity(
            root, real=False,
            general_context_identity_root=
            disposable_general_context_document()["identity_root"],
            live_provider_identity_root=fixture_identity["identity_root"]))
        return {"live_provider_identity_root":
                    provider_identity["identity_root"],
                "rehearsal_environment_root": disposable_root}
    context, _model, _tokenizer, _config = load_production_model_stack(root)
    general = t28_general_context_document(root, context)
    real_root = sha256_json(environment_identity(
        root, real=True,
        general_context_identity_root=general["identity_root"],
        live_provider_identity_root=provider_identity["identity_root"]))
    return {"general_context_document": general,
            "live_provider_identity_root": provider_identity["identity_root"],
            "environment_root": real_root}