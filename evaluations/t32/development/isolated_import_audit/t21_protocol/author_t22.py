"""T22 row-authoring composition for the contract-driven author spec.

The runtime-native builder (``t21_protocol.builder:_runtime_native_row``)
consumes an optional ``row_authoring`` block from the author spec: per-tag
query templates, sub-shapes, freshness classes, the candidate-visible
request_date carrier, and per-tag expect_status. Prior experiments
(T16-T21R17) never supply the block and keep their frozen byte-identical
default authoring, so this module is gated on a T22-only contract
declaration (``artifacts.temporal_holdout_design``) and returns ``None``
for every earlier contract.

The block itself is not restated here: it is loaded from the frozen design
artifact and validated against the same artifact's candidate_visible_signals
templates, the design's request_date carrier, and the contract's exact
design (tags, counts, order). Templates therefore have exactly one frozen
source (protocol sections 25/33/34; the measuring-stick constraint that
only the candidate changes).
"""
from __future__ import annotations

import copy
import re
from typing import Any

from .errors import ContractError
from .util import read_json

DESIGN_SCHEMA = "t22-temporal-holdout-design-v1"
DESIGN_ARTIFACT = "T22_TEMPORAL_HOLDOUT_DESIGN"
DESIGN_EXPERIMENT = "t22"
DESIGN_STATUS = "PREREGISTERED_PRECONSTRUCTION"

ROUTE_STATUSES = frozenset({"ANSWER", "ROUTE_WEB_RESEARCH"})
FRESHNESS_CLASSES = frozenset({"TIME_SENSITIVE", "STATIC"})
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _fail(message: str) -> None:
    raise ContractError(f"t22 row_authoring composition: {message}")


def _validate_family_block(
    tag: str, block: dict[str, Any], family: dict[str, Any], family_count: int
) -> None:
    if tag != family["gold_construction_tag"]:
        _fail(f"by_tag key {tag!r} does not match the family gold_construction_tag")
    if block.get("freshness") != family["source_freshness_class"]:
        _fail(f"by_tag[{tag!r}].freshness contradicts the frozen family freshness class")
    signals = family["candidate_visible_signals"]
    subshapes = block.get("subshapes")
    if subshapes is None:
        if len(signals) != 1:
            _fail(f"by_tag[{tag!r}] lacks sub-shapes but the family declares multiple sub-shapes")
        (name, signal), = signals.items()
        if block.get("query_template") != signal["query_template"]:
            _fail(f"by_tag[{tag!r}] query template is not the frozen {name} template")
        if signal["count"] != family_count:
            _fail(f"frozen {name} count does not match the family count")
        return
    names = list(signals)
    if len(subshapes) != len(names):
        _fail(f"by_tag[{tag!r}] sub-shape count differs from the frozen family sub-shape count")
    if sum(subshape["count"] for subshape in subshapes) != family_count:
        _fail(f"by_tag[{tag!r}] sub-shape counts do not sum to the frozen family count")
    for index, (subshape, (name, signal)) in enumerate(zip(subshapes, signals.items())):
        if not isinstance(subshape, dict) or set(subshape) != {"count", "query_template", "freshness"}:
            _fail(f"by_tag[{tag!r}] sub-shape {index} violates the closed sub-shape schema")
        if subshape["count"] != signal["count"]:
            _fail(f"by_tag[{tag!r}] sub-shape {name} count differs from the frozen design")
        if subshape["query_template"] != signal["query_template"]:
            _fail(f"by_tag[{tag!r}] sub-shape {name} template differs from the frozen design")
        if subshape.get("freshness") != family["source_freshness_class"]:
            _fail(f"by_tag[{tag!r}] sub-shape {name} freshness contradicts the family freshness class")
        if signal.get("expected_route", family["expected_status"]) != family["expected_status"]:
            _fail(f"frozen sub-shape {name} route contradicts the family expected status")


def compose_row_authoring(contract: Any, root_for_contract_artifacts) -> dict[str, Any] | None:
    """Return the frozen T22 row_authoring block, or ``None`` for contracts
    that do not declare the temporal design artifact (all prior
    experiments - the author spec stays byte-identical for them)."""
    try:
        relative = contract.get("artifacts.temporal_holdout_design")
    except KeyError:
        return None
    if not relative:
        return None
    design = read_json(root_for_contract_artifacts / relative)

    if design.get("schema_version") != DESIGN_SCHEMA:
        _fail("unsupported temporal design schema_version")
    if design.get("artifact") != DESIGN_ARTIFACT or design.get("experiment") != DESIGN_EXPERIMENT:
        _fail("temporal design identity mismatch")
    if design.get("status") != DESIGN_STATUS:
        _fail("temporal design is not the frozen preconstruction artifact")
    request_date = design.get("request_date") or {}
    if not _DATE_RE.match(str(request_date.get("value") or "")):
        _fail("temporal design request_date carries no ISO date value")
    blindness = design.get("blindness") or {}
    if blindness.get("runtime_data_contract_addition") is None:
        _fail("temporal design blindness contract is absent")

    suites = contract.get("suites")
    suite_name = design.get("suite")
    suite = (suites or {}).get(suite_name)
    if suite is None:
        _fail("temporal design suite is not a contract suite")
    if suite["count"] != design.get("suite_total"):
        _fail("temporal design suite_total differs from the contract suite count")
    design_family = suite["family"]
    exact = contract.get("exact_design").get(design_family)
    if not isinstance(exact, dict) or not exact:
        _fail("contract exact_design carries no temporal family requirements")

    authoring = design.get("row_authoring")
    if not isinstance(authoring, dict):
        _fail("frozen row_authoring block is absent from the temporal design")
    required_keys = {
        "rule", "value_prefix", "request_date", "by_tag", "default", "expect_status_by_tag",
    }
    if set(authoring) != required_keys:
        _fail(f"row_authoring fields differ: unexpected={sorted(set(authoring) - required_keys)}, "
              f"missing={sorted(required_keys - set(authoring))}")
    if not isinstance(authoring["value_prefix"], str) or not authoring["value_prefix"]:
        _fail("row_authoring value_prefix must be a non-empty string")
    if authoring["request_date"] != request_date["value"]:
        _fail("row_authoring request_date differs from the frozen design carrier-E value")

    by_tag = authoring["by_tag"]
    if not isinstance(by_tag, dict) or not by_tag:
        _fail("row_authoring by_tag must be a non-empty object")
    if set(by_tag) != set(exact):
        _fail(f"by_tag coverage differs from the frozen exact design: "
              f"unexpected={sorted(set(by_tag) - set(exact))}, "
              f"missing={sorted(set(exact) - set(by_tag))}")
    families = design.get("families") or {}
    if set(families) != set(by_tag):
        _fail("design families and by_tag tags disagree")
    for tag, count in exact.items():
        family = families.get(tag)
        if family is None:
            _fail(f"frozen design carries no family block for tag {tag!r}")
        if family["gold_construction_tag"] != tag or family["count"] != count:
            _fail(f"frozen family {tag!r} disagrees with the contract exact design")
        block = by_tag[tag]
        if not isinstance(block, dict) or set(block) - {"freshness", "subshapes", "query_template"}:
            _fail(f"by_tag[{tag!r}] violates the closed by_tag schema")
        _validate_family_block(tag, block, family, count)

    expect_status = authoring["expect_status_by_tag"]
    if set(expect_status) != set(by_tag):
        _fail("expect_status_by_tag coverage differs from by_tag")
    for tag, status in expect_status.items():
        if status != families[tag]["expected_status"]:
            _fail(f"expect_status_by_tag[{tag!r}] contradicts the frozen family expected status")
        if status not in ROUTE_STATUSES:
            _fail(f"expect_status_by_tag[{tag!r}] carries an unregistered status")

    default_block = authoring["default"]
    if not isinstance(default_block, dict) or set(default_block) != {"query_template", "freshness"}:
        _fail("row_authoring default violates the closed default schema")
    if default_block["query_template"] != by_tag["stale_snapshot"]["query_template"]:
        _fail("row_authoring default is not the frozen record-pinned template")
    if default_block["freshness"] not in FRESHNESS_CLASSES or default_block["freshness"] != "STATIC":
        _fail("row_authoring default must carry the STATIC record-pinned freshness class")
    for block in list(by_tag.values()) + [default_block]:
        for subshape in block.get("subshapes", []) or [block]:
            if "{case_id}" not in subshape.get("query_template", ""):
                _fail("a frozen row template does not carry the {case_id} slot")
    return copy.deepcopy(authoring)


__all__ = ["compose_row_authoring"]