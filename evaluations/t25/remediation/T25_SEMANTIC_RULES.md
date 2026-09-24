# T25 Public Semantic Status Rules (authorization §5)

Established **before** any T25 candidate change or any status mapping, from the
public frozen runtime only. No T24 private row was opened (authorization §3);
the only T24 inputs are the aggregate counts already in the PUBLIC_SAFE official
report (4× `GENERAL→GENERAL[UNKNOWN]` unmatched; 72× `PARTIALLY_SUPPORTED`,
4× `UNCERTAIN` matched).

## R1 — Terminal status closure

A dispatch that terminates carries exactly one status from its capability's
closed status set (see `T25_STATUS_TAXONOMY_CONTRACT.json`). "Status absent"
is not a status: the runtime must always report one. *Justification:* the
measurement layer is total over defined statuses; an absent status is
unmeasurable and cannot support any honest verdict.

## R2 — Status provenance

A terminal status may be derived only from the run's own recorded epistemic
signals via the frozen uncertainty engine (`decide_status` over the recorded
observation/signal vector). The adapter must never invent a status, and the
model's self-assessment is never a status. *Justification:* this is the same
deterministic mapping the runtime already applies on its normal final paths;
reusing it on exceptional terminals adds no new semantic.

## R3 — UNKNOWN is an internal axis value only

`UNKNOWN` remains valid inside the runtime (classification axes, verify
verdicts, provenance, trust classes) but must never terminate a dispatch. The
frozen dispatch-evaluator rule (`UNKNOWN ⇒ unmatched`, zero tolerance) is
retained unchanged as the permanent guard. *Justification:* the runtime's
evidence-status taxonomy has no `UNKNOWN` member; a placeholder for "not
reported" is an adapter defect, not an epistemic state.

## R4 — Internal failures do not fabricate success

A run that terminates `BUDGET_EXHAUSTED`, `STALLED`, or via a system error
carries the status its recorded signal vector yields (e.g. `UNCERTAIN` when no
usable-evidence signal exists, `INSUFFICIENT_INFORMATION` when retrieval or
inputs were unusable) and keeps its full cause record
(`termination_reason`, `failure_category`, `error`). It never carries a
stronger status than its evidence supports. *Justification:* this preserves
the engine's own semantics — the derived status is a function of observable
signals only — while removing the defective "absent status" channel.

## R5 — No aggregate-satisfying mapping

No mapping in this remediation was chosen with reference to any desired
aggregate. The mapping is the frozen uncertainty engine applied at the
terminal boundary; it is fixed before use, deterministic, and validated on
synthetic non-blind cases (authorization §7). Any conversion of
`UNKNOWN→UNCERTAIN`/`PARTIALLY_SUPPORTED` performed solely to satisfy the T24
aggregate is forbidden and was not done.