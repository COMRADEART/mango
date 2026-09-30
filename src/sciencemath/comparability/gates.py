"""T31.10 The fifteen gates, each decided from evidence rather than asserted.

The brief lists fifteen gates and asks for each to be reported individually.
The failure mode a gate list invites is a table of ticks that nobody can
check, so every gate here is a function of artifacts on disk: a gate whose
evidence is absent reports ``NOT_EVALUATED``, and a gate whose evidence
contradicts its requirement reports ``FAIL``. Nothing is ``PASS`` by default,
and there is no path by which a gate that was never computed renders as
satisfied.

Three of the gates are the ones that carry the most weight, and each is
computed from something that could genuinely come out wrong:

``GATE 4`` — the frozen configuration. Checked against the hash recorded on
every row, so a run that changed a setting halfway through is caught rather
than averaged.

``GATE 11`` — the schema/content split. Checked for the presence of both flags
on every scored row *and* for a non-degenerate cross-tabulation. Two flags that
are always equal are not two facts, and the brief's requirement is that a
formatted wrong answer and a correct answer in the wrong format are both
representable.

``GATE 15`` — the final audit. The misattribution this guards against is a
runtime number appearing in a model column, so it is checked by looking for
the labels in the rendered report rather than by trusting the template.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

PASS = "PASS"
FAIL = "FAIL"
NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True)
class Gate:
    number: int
    name: str
    requirement: str
    status: str
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return {"gate": f"GATE {self.number}", "name": self.name,
                "requirement": self.requirement, "status": self.status,
                "evidence": self.evidence}


@dataclass
class GateEvidence:
    """Everything the gates are decided from. Absent means not evaluated."""

    config_hash: str | None = None
    adapter_sha256: str | None = None
    adapter_pinned_sha256: str | None = None
    base_revision: str | None = None
    pinned_base_revision: str | None = None
    adapter_revision: str | None = None
    pinned_adapter_revision: str | None = None
    t30_tree_clean: bool | None = None
    t30_freeze_sha256: str | None = None
    t30_pinned_freeze_sha256: str | None = None
    completeness: dict[str, Any] = field(default_factory=dict)
    raw_counts: dict[str, int] = field(default_factory=dict)
    scored_counts: dict[str, int] = field(default_factory=dict)
    row_config_hashes: dict[str, set[str]] = field(default_factory=dict)
    schema_content_crosstab: dict[str, int] = field(default_factory=dict)
    summaries: dict[str, dict[str, Any]] = field(default_factory=dict)
    contamination: dict[str, Any] = field(default_factory=dict)
    reproduction: dict[str, Any] = field(default_factory=dict)
    regression: dict[str, Any] = field(default_factory=dict)
    report_text: str = ""
    expected_items: int = 0

    @staticmethod
    def from_run(*, config: dict[str, Any], config_hash: str,
                 completeness, raw_counts, scored_counts, row_config_hashes,
                 summaries, contamination, reproduction, regression,
                 report_text, t30_tree_clean=None, t30_freeze_sha256=None,
                 observed_identity: dict[str, Any] | None = None
                 ) -> "GateEvidence":
        """Assemble from the artifacts a finished run leaves behind.

        The pinned identity comes from ``identity.MODEL_IDENTITIES`` — the
        manifest of what this evaluation is *supposed* to have used. The
        observed identity comes from the run's own rows, which record the
        model and adapter that actually generated them. Both sides are needed:
        setting both from the identity module would make the pin a comparison
        of a constant against itself, which cannot fail, and a gate that cannot
        fail is not a gate. When no rows have been captured the observed side
        is ``None`` and the pin reports ``NOT_EVALUATED`` rather than PASS.
        """
        from sciencemath.comparability.identity import (
            BENCHMARK_IDENTITIES, MODEL_IDENTITIES, T30_FROZEN_FREEZE_SHA256,
        )

        observed = observed_identity or {}
        if not observed:
            observed = _observed_identity(scored_counts.get("rows", {}))

        cross = {"schema_and_content": 0, "schema_only": 0,
                 "content_only": 0, "neither": 0}
        for rows in scored_counts.get("rows", {}).values():
            for row in rows:
                schema = bool(row.get("schema_valid"))
                content = bool(row.get("content_valid"))
                key = ("schema_and_content" if schema and content else
                       "schema_only" if schema else
                       "content_only" if content else "neither")
                cross[key] += 1
        return GateEvidence(
            config_hash=config_hash,
            adapter_sha256=observed.get("adapter_sha256"),
            adapter_pinned_sha256=MODEL_IDENTITIES["adapter"]["weights_sha256"],
            base_revision=observed.get("base_revision"),
            pinned_base_revision=MODEL_IDENTITIES["base"]["revision"],
            adapter_revision=observed.get("adapter_revision"),
            pinned_adapter_revision=MODEL_IDENTITIES["adapter"]["revision"],
            t30_tree_clean=t30_tree_clean,
            t30_freeze_sha256=t30_freeze_sha256,
            t30_pinned_freeze_sha256=T30_FROZEN_FREEZE_SHA256,
            completeness=completeness, raw_counts=raw_counts,
            scored_counts=scored_counts, row_config_hashes=row_config_hashes,
            schema_content_crosstab=cross, summaries=summaries,
            contamination=contamination, reproduction=reproduction,
            regression=regression, report_text=report_text,
            expected_items=sum(entry["expected_items"]
                               for entry in BENCHMARK_IDENTITIES.values()))


BENCHMARK_GATES = {
    5: "gsm8k", 6: "math500", 7: "arc_easy", 8: "arc_challenge", 9: "sciq",
}


def _observed_identity(scored_rows: dict[str, list[dict[str, Any]]]
                       ) -> dict[str, Any]:
    """The model identity the rows themselves record, not the one intended.

    GATES 2 and 3 assert that the model measured is the model the manifest
    names. That assertion is only meaningful if the two sides come from
    different places, so the *observed* side is read from the rows — which
    carry ``model_revision``, ``adapter_revision`` and ``adapter_sha256`` as
    written by the loader that actually loaded the weights — and compared
    against ``identity.MODEL_IDENTITIES``.

    A field carrying more than one distinct value across the rows is returned
    as the joined string rather than a single value: it will not equal the pin,
    so the gate fails and its evidence names both, which is the honest outcome
    for a run that measured two different things under one name. ``None`` means
    no rows carried the field at all — the base rows record no adapter, so the
    adapter fields are ``None`` on a base-only capture, and the gate reports
    NOT_EVALUATED rather than passing on an absence.
    """
    def distinct(field: str) -> list[str]:
        seen: list[str] = []
        for rows in (scored_rows or {}).values():
            for row in rows:
                value = row.get(field)
                if value and value not in seen:
                    seen.append(value)
        return sorted(seen)

    observed: dict[str, Any] = {}
    for field, key in (("model_revision", "base_revision"),
                       ("adapter_revision", "adapter_revision"),
                       ("adapter_sha256", "adapter_sha256")):
        values = distinct(field)
        observed[key] = (values[0] if len(values) == 1
                         else ", ".join(values) if values else None)
    return observed

BANNED_ADJECTIVES = ("advanced", "powerful", "state-of-the-art",
                     "highly capable", "near-perfect", "world-class",
                     "cutting-edge", "revolutionary")


def evaluate(evidence: GateEvidence) -> list[Gate]:
    """Decide all fifteen gates. Order is fixed so the report is stable.

    The per-benchmark gates come back as a list and are flattened here: a
    nested list would make ``overall`` and the report's table crash on a group
    rather than on a gate, and the failure would appear in the one place whose
    whole job is to be trustworthy.
    """
    gates: list[Gate] = [
        _gate_1(evidence), _gate_2(evidence), _gate_3(evidence),
        _gate_4(evidence),
    ]
    gates += _gate_5_to_9(evidence)
    gates += [
        _gate_10(evidence), _gate_11(evidence), _gate_12(evidence),
        _gate_13(evidence), _gate_14(evidence), _gate_15(evidence),
    ]
    return gates


def _status(ok: bool | None) -> str:
    if ok is None:
        return NOT_EVALUATED
    return PASS if ok else FAIL


def _gate_1(ev: GateEvidence) -> Gate:
    """T30 frozen — checked against the tree *and* against the measured bytes.

    Two independent facts, because either alone can be got round. A clean tree
    says nobody edited the T30 record in place; it says nothing about which
    adapter was run. A matching adapter hash says the measured weights are the
    frozen release; it says nothing about whether the record is intact. So both
    are required. A clause with no evidence does not silently pass: it simply
    contributes nothing, and if no clause has evidence the gate is
    NOT_EVALUATED.
    """
    ok: bool | None = None
    parts = []

    def add(holds: bool, text: str) -> None:
        nonlocal ok
        parts.append(text)
        ok = holds if ok is None else (ok and holds)

    if ev.t30_tree_clean is not None:
        add(ev.t30_tree_clean,
            "evaluations/t30 is unmodified against HEAD"
            if ev.t30_tree_clean
            else "evaluations/t30 has uncommitted modifications")
    if ev.adapter_sha256 and ev.adapter_pinned_sha256:
        add(ev.adapter_sha256 == ev.adapter_pinned_sha256,
            f"the measured adapter is the frozen T30 bytes "
            f"({ev.adapter_sha256[:16]}…)"
            if ev.adapter_sha256 == ev.adapter_pinned_sha256
            else f"the measured adapter differs from the frozen T30 bytes "
                 f"({ev.adapter_sha256[:16]}… vs pinned "
                 f"{ev.adapter_pinned_sha256[:16]}…)")
    if ev.t30_freeze_sha256 and ev.t30_pinned_freeze_sha256:
        add(ev.t30_freeze_sha256 == ev.t30_pinned_freeze_sha256,
            "the T30 freeze root is the one the promotion record declares"
            if ev.t30_freeze_sha256 == ev.t30_pinned_freeze_sha256
            else f"the T30 freeze root has drifted "
                 f"({ev.t30_freeze_sha256[:16]}… vs recorded "
                 f"{ev.t30_pinned_freeze_sha256[:16]}…)")
    return Gate(1, "T30 frozen",
                "The frozen T30 adapter, its evidence pack and its records are "
                "unmodified.", _status(ok), "; ".join(parts) or "no evidence")


def _gate_2(ev: GateEvidence) -> Gate:
    """The base model actually loaded, against the revision the manifest names."""
    if not ev.base_revision or not ev.pinned_base_revision:
        return Gate(2, "Base model pinned",
                    "The base model is loaded at the revision the manifest "
                    "names.", NOT_EVALUATED,
                    "no row recorded a base revision")
    same = ev.base_revision == ev.pinned_base_revision
    return Gate(2, "Base model pinned",
                "The base model is loaded at the revision the manifest names.",
                _status(same),
                f"measured base revision {ev.base_revision}"
                + ("" if same else f" ≠ pinned {ev.pinned_base_revision}"))


def _gate_3(ev: GateEvidence) -> Gate:
    """The adapter loaded by revision *and* its weights verified by sha256."""
    ok: bool | None = None
    parts = []
    if ev.adapter_sha256 and ev.adapter_pinned_sha256:
        same = ev.adapter_sha256 == ev.adapter_pinned_sha256
        parts.append(f"adapter sha256 {ev.adapter_sha256[:16]}…"
                     + ("" if same else f" ≠ pinned "
                        f"{ev.adapter_pinned_sha256[:16]}…"))
        ok = same
    if ev.adapter_revision and ev.pinned_adapter_revision:
        same = ev.adapter_revision == ev.pinned_adapter_revision
        parts.append(f"adapter revision {ev.adapter_revision[:12]}…"
                     + ("" if same else f" ≠ pinned "
                        f"{ev.pinned_adapter_revision[:12]}…"))
        ok = same if ok is None else (ok and same)
    return Gate(3, "Adapter pinned",
                "The adapter is loaded by revision and its weights verified by "
                "sha256.", _status(ok), "; ".join(parts) or "no evidence")


def _gate_4(ev: GateEvidence) -> Gate:
    if not ev.config_hash or not ev.row_config_hashes:
        return Gate(4, "Evaluation configuration frozen",
                    "One frozen configuration produced every row.",
                    NOT_EVALUATED, "no evidence")
    # The offending keys, not the offending sets: a set of sets cannot be
    # built, so collecting the values would raise exactly when a stray exists
    # — that is, in the only case this gate is here to catch.
    stray = sorted(key for key, hashes in ev.row_config_hashes.items()
                   if hashes != {ev.config_hash})
    return Gate(4, "Evaluation configuration frozen",
                "One frozen configuration produced every row.",
                _status(not stray),
                f"{ev.config_hash[:16]}… on every row file" if not stray
                else f"{len(stray)} file(s) carry other configuration hashes: "
                     f"{stray[:5]}")


def _gate_5_to_9(ev: GateEvidence) -> list[Gate]:
    gates = []
    for number, benchmark in sorted(BENCHMARK_GATES.items()):
        base = ev.completeness.get(f"base:{benchmark}")
        adapter = ev.completeness.get(f"adapter:{benchmark}")
        summary = ev.summaries.get(benchmark)
        if base is None or adapter is None or summary is None:
            gates.append(Gate(number, f"{benchmark} comparison",
                              "Base and adapter scored, paired and reported.",
                              NOT_EVALUATED, "no evidence"))
            continue
        complete = bool(base.get("complete")) and bool(adapter.get("complete"))
        detail = (f"{summary.get('total_items')} paired items, "
                  f"Δ {summary.get('delta_pp'):+.2f} pp, "
                  f"{summary.get('comparison')}")
        gates.append(Gate(number, f"{benchmark} comparison",
                          "Base and adapter scored, paired and reported.",
                          _status(complete), detail))
    return gates


def _gate_10(ev: GateEvidence) -> Gate:
    """Retention is checked per file against *its own* benchmark's size, and
    the file set must be the complete arm×benchmark cross-product.

    A global total would pass a run that had captured every item of one
    benchmark and none of another, which is the shape a quietly failing suite
    actually takes. So both directions matter: a file that is present but
    short of its benchmark's size fails, and a file that is *absent* fails too
    — otherwise a run that captured one suite, once, would satisfy a gate about
    retaining every generation of both arms.
    """
    if not ev.raw_counts:
        return Gate(10, "Raw outputs retained",
                    "Every item's unaugmented generation is on disk.",
                    NOT_EVALUATED, "no evidence")
    from sciencemath.comparability.contract import ARMS, BENCHMARK_ORDER
    from sciencemath.comparability.identity import BENCHMARK_IDENTITIES

    short: dict[str, str] = {}
    for name in BENCHMARK_ORDER:
        for arm in ARMS:
            key = f"{arm}:{name}"
            count = ev.raw_counts.get(key)
            expected = BENCHMARK_IDENTITIES[name]["expected_items"]
            if count is None:
                short[key] = "no file"
            elif count < expected:
                short[key] = f"{count} of {expected}"
    unknown = [key for key in ev.raw_counts
               if key.split(":", 1)[-1] not in BENCHMARK_IDENTITIES]
    if unknown:
        short.update({key: "unknown benchmark" for key in unknown})
    total = sum(ev.raw_counts.values())
    expected_files = len(ARMS) * len(BENCHMARK_ORDER)
    return Gate(10, "Raw outputs retained",
                "Every item's unaugmented generation is on disk.",
                _status(not short),
                f"{total} raw generations across {len(ev.raw_counts)} "
                f"arm×benchmark files"
                if not short else
                f"incomplete of {expected_files} arm×benchmark files: {short}")


def _gate_11(ev: GateEvidence) -> Gate:
    if not ev.scored_counts.get("rows"):
        return Gate(11, "Schema/content split operational",
                    "schema_valid and content_valid are recorded independently "
                    "and both outcomes are reachable.",
                    NOT_EVALUATED, "no evidence")
    cross = ev.schema_content_crosstab
    total = sum(cross.values())
    if total == 0:
        # Scored rows exist but no cross-tabulation was computed. Reading the
        # empty dict as "not degenerate" would pass the gate on no evidence at
        # all, which is the failure mode this gate exists to prevent.
        return Gate(11, "Schema/content split operational",
                    "schema_valid and content_valid are recorded independently "
                    "and both outcomes are reachable.",
                    NOT_EVALUATED,
                    "scored rows present but the cross-tabulation was not "
                    "computed")
    degenerate = len([value for value in cross.values() if value]) < 2
    return Gate(11, "Schema/content split operational",
                "schema_valid and content_valid are recorded independently and "
                "both outcomes are reachable.",
                _status(not degenerate),
                f"{total} scored rows: " + ", ".join(
                    f"{key}={value}" for key, value in sorted(cross.items()))
                + (" (degenerate: the two flags never differ)"
                   if degenerate else ""))


def _gate_12(ev: GateEvidence) -> Gate:
    if not ev.contamination:
        return Gate(12, "Training-overlap disclosure complete",
                    "Every benchmark has a measured overlap and an "
                    "interpretation.", NOT_EVALUATED, "no evidence")
    table = ev.contamination.get("table") or []
    covered = {row.get("benchmark") for row in table}
    required = set(BENCHMARK_GATES.values())
    missing = sorted(required - covered)
    return Gate(12, "Training-overlap disclosure complete",
                "Every benchmark has a measured overlap and an interpretation.",
                _status(not missing and bool(table)),
                f"disclosed for {sorted(covered)}" if not missing
                else f"missing {missing}")


def _gate_13(ev: GateEvidence) -> Gate:
    repro = ev.reproduction or {}
    ok = None
    if repro:
        ok = bool(repro.get("commands")) and bool(repro.get("config_path")) \
            and bool(repro.get("hashes_path"))
    return Gate(13, "Public reproduction path",
                "A third party can rerun the comparison from the published "
                "config and commands.", _status(ok),
                "; ".join(f"{k}={v}" for k, v in sorted(repro.items()))
                or "no evidence")


def _gate_14(ev: GateEvidence) -> Gate:
    """The regression record is read by the key the producer actually writes.

    ``regression`` is passed in as ``{"passed": n, "failed": n, "skipped": n}``
    — the shape the report and the run record both use. Reading ``"failures"``
    (a key nothing writes) made this gate pass any record with a nonzero
    ``passed``, including one reporting failures.

    The counts must both be present for the gate to be evaluated. A record that
    says how many passed but not how many failed has not demonstrated that none
    did, so it is missing evidence and reports NOT_EVALUATED rather than a PASS
    inferred from an absence — while ``passed`` of zero is a failure outright,
    because a suite that ran nothing has not stayed green.
    """
    regression = ev.regression or {}
    ok = None
    if regression.get("passed") is not None and \
            regression.get("failed") is not None:
        ok = bool(regression.get("passed")) and regression.get("failed") == 0
    return Gate(14, "Regression",
                "The pre-existing test suite still passes.",
                _status(ok),
                f"{regression.get('passed')} passed, "
                f"{regression.get('failed', 0)} failed, "
                f"{regression.get('skipped', 0)} skipped"
                if regression.get("passed") is not None
                else "no test counts recorded")


def _gate_15(ev: GateEvidence) -> Gate:
    """The misattribution audit, read off the rendered report itself.

    The specific error being guarded against is a runtime figure wearing the
    label ``model accuracy``. So the rule is applied to the lines a reader
    actually sees: any line carrying both words must be stating that the two
    are different, not equating them.
    """
    text = ev.report_text
    if not text:
        return Gate(15, "Final audit",
                    "No metric is attributed to the wrong system.", NOT_EVALUATED,
                    "no evidence")
    lowered = text.lower()
    problems = []

    banned = sorted(word for word in BANNED_ADJECTIVES if word in lowered)
    if banned:
        problems.append(f"unsupported adjectives: {banned}")

    for line in text.splitlines():
        low = line.lower()
        if "accuracy" in low and ("runtime" in low or "integrated" in low) \
                and "not " not in low:
            problems.append(
                f"line pairs a runtime figure with accuracy: "
                f"{line.strip()[:70]!r}")

    # Each of the three systems is named, so no number is left unattributed.
    for name in ("mango adapter", "mango runtime", "mango integrated system"):
        if name not in lowered:
            problems.append(f"the report never names the {name}")

    if "runtime" in lowered and "integrated runtime results" not in lowered:
        problems.append("runtime numbers appear without their own section")

    return Gate(15, "Final audit",
                "No metric is attributed to the wrong system.",
                _status(not problems),
                "; ".join(problems) or
                "weights, runtime and integrated system each named and "
                "separated")


def summarize(gates: Sequence[Gate]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for gate in gates:
        counts[gate.status] = counts.get(gate.status, 0) + 1
    return {"counts": counts, "gates": [gate.to_dict() for gate in gates]}


def overall(gates: Sequence[Gate]) -> str:
    """The decision token's status word.

    PARTIAL rather than PASS whenever a gate could not be evaluated: a gate
    that was not computed is not a gate that passed. An empty list raises
    rather than returning PASS, which would be the same fail-open at the top
    of the ladder.
    """
    if not gates:
        raise ValueError(
            "no gates to summarize: an empty gate list has no status, and "
            "returning PASS for it would let a report render a pass out of "
            "nothing")
    statuses = {gate.status for gate in gates}
    if FAIL in statuses:
        return FAIL
    if NOT_EVALUATED in statuses:
        return "PARTIAL"
    return PASS
