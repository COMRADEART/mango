# T21R7 Final Report — Knowledge RAG relation-grounding closure (non-promotion)

Canonical final evaluation commit:
`d9e2ddd444582fa2102d98ec3688641a7f7e1939`

Decision: **KEEP_KNOWLEDGE_RAG_EXPERIMENTAL**

T21: **OPEN**
T22: **BLOCKED**

This report summarizes only existing immutable evidence from the frozen
T21R7 state. Nothing was rerun, repaired, or re-scored. The exposed
T21R7 holdout is consumed and non-promotional.

## Identity chain

| Item | Value |
| --- | --- |
| Canonical base | `57f4188c736b7ffd59227deb808ecd29b02fcc33` |
| Repair SHA | `ba3b1ce4f80886fd0f7d5cde4946a82109472f9c` |
| Construction preregistration SHA | `554f000ad511dedc5b7752887558ab24b1fa0d27` |
| Runtime freeze HEAD | `74823b88c140d770a42a76b577fd82e9ee398ca8` |
| Final validation SHA | `d9e2ddd444582fa2102d98ec3688641a7f7e1939` |

## Blind holdout

- Holdout rows: **4200**
  (600 adversarial, 450 citation-claim, 750 conflict-abstention,
  450 cross-domain, 550 multi-hop, 600 retrieval, 550 single-hop,
  250 temporal)
- Construction contract: **79 / 79 PASS**
  (`holdout_construction_contract.json`; 79 requirements evaluated,
  79 passed; static gold audit PASS)
- Independence: **UNIQUE vs T21 through T21R6**
  (zero overlap on case IDs, entity identities, source IDs, chunk IDs,
  exact queries, exact answers, exact source text, verbatim attacks)
- Pre-freeze runtime exposures: **0**
  (blindness audit PASS; no suite row reached the runtime before
  `HOLDOUT_FROZEN`)

## Official run

- Official run: **exit 0**, one-shot, ledger integrity verified
- Official exposures: **1** (the single authorized evaluation after
  `HOLDOUT_FROZEN`)

## Results

Floors: **25 / 32 PASS** (all 32 floors unchanged and never lowered).

Failed floors:

| Metric | Value | Floor |
| --- | --- | --- |
| IE recall (insufficient-evidence recall) | 0.951 | ≥ 0.97 |
| Cross-domain synthesis accuracy | 0.0 | ≥ 0.86 |
| Domain macro grounded accuracy | 0.8248 | ≥ 0.88 |
| Multi-hop grounded accuracy | 0.0 | ≥ 0.85 |
| Overall grounded accuracy | 0.7167 | ≥ 0.90 |
| Source diversity | 0.0 | ≥ 0.95 |
| Prompt-injection containment | 0.9917 | = 1.0 |

Zero tolerance: **ALL ZERO** (every zero-tolerance counter remained 0
across all 4200 rows of the official run).

## Regression safety

Pytest (full suite, post-construction / pre-freeze record):
**2161 passed, 2 skipped, 0 failed, 0 errors** (2163 tests).

## Decision

- Decision: **KEEP_KNOWLEDGE_RAG_EXPERIMENTAL**
- Knowledge RAG availability: **EXPERIMENTAL**
- T21 status: **OPEN**
- Ready for T22: **NO** (T22 is **BLOCKED**; T21R7 did not pass all 32
  unchanged promotion floors)
- Promotion commit: **NONE**
- R7 holdout: **CONSUMED / NON-PROMOTIONAL**

## Rules going forward

- Do not repair, rerun, or re-score against the exposed T21R7 holdout.
- Do not alter gold, floors, or the evaluator against it.
- No root-cause repair in T21R7. Any future repair belongs to **T21R8**
  with a **new fresh blind holdout** under the same ordering discipline
  (repair commit → runtime freeze → evaluator freeze → blind holdout
  construction → audits → `HOLDOUT_FROZEN` → one-shot evaluation).
- Do not start T22.
