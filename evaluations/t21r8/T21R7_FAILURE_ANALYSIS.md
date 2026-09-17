# T21R7 failure analysis — T21R8 Part A data-only forensics

Base branch: `t21r8-knowledge-rag-multisource-closure`  
Verified base HEAD: `4242e1bd7bb74c9f3f6d52f70fb04788e2e6d481`  
Forensics JSON SHA-256: `1db4d9a93a321e9ac4c0ecddc94eab0ea4ba26c9776b32b27f56e437e726ca06`

## Scope and method

This analysis is data-only. It reads the immutable T21R7 result/report artifacts, does not import or invoke the evaluator, does not execute production runtime against any T21R7 row, does not rescore, and makes no runtime/evaluator/holdout change. Prior R6/R7 development summaries are read only for the explicitly requested generalization-gap comparison; no old holdout is executed.

Recorded fields are separated from inference. Source presence is derived from evidence chunk-ID prefixes. A bridge-specific hop 2 is counted only when an evidence chunk ID names the bridge entity surfaced in the actual answer and the `birthplace` relation; the static audit records zero `hop2_birthplace_retrievable` misses. Evidence body text and domain tags for non-cited evidence are not in the authorized R7 result artifacts, so those values are marked `NOT_OBSERVABLE_FROM_R7_ARTIFACTS` instead of guessed.

## Global decomposition

Exactly **1,020** rows are incorrect: 550 multihop, 450 cross-domain, 15 conflict/IE false negatives, and 5 adversarial containment misses. Every incorrect row is classified; unclassified = **0**, `OTHER` = **0**, and primary `NOT_OBSERVABLE_FROM_R7_ARTIFACTS` = **0**.

| Recorded failure flag | Count |
| --- | ---: |
| Status mismatch | 15 |
| Contains failure | 1005 |
| Citation failure | 0 |
| Required-sources failure | 1000 |
| Required-domains failure | 450 |
| Claims failure | 0 |
| Zero-tolerance failure | 0 |
| Multiple simultaneous failures | 1000 |

Primary mechanism counts:

| Mechanism | Count |
| --- | ---: |
| `HOP2_NOT_RETRIEVED` | 531 |
| `FINAL_VALUE_NOT_SYNTHESIZED` | 19 |
| `CROSSDOMAIN_PATH_NOT_BUILT` | 447 |
| `CROSSDOMAIN_FINAL_VALUE_FAILURE` | 3 |
| `NEAR_NAME_FALSE_BIND` | 15 |
| `SAFE_FACT_SPLIT_FAILURE` | 5 |

The JSON contains the requested field-level decomposition for all 1,020 rows.

## Multihop — all 550 rows

| Check | Failure count |
| --- | ---: |
| Status mismatch | 0 |
| Contains failure | 550 |
| Citation failure | 0 |
| Required-sources failure | 550 |
| Required-domains failure | 0 |
| Claims failure | 0 |
| Multiple simultaneous failures | 550 |

Hop 1 is present and the bridge entity is observable in all 550 rows. Only **19** rows contain an exact bridge-specific birthplace chunk; those 19 still emit the first-hop creator fact, omit the final value, and omit path provenance, so their primary label is `FINAL_VALUE_NOT_SYNTHESIZED`. The other **531** have no exact bridge-specific birthplace chunk and are `HOP2_NOT_RETRIEVED`. Every trace says `decomposition:1` and `synthesis:single_hop_extractive`, every answer exposes the creator bridge, and every answer omits the birthplace.

Primary multihop mechanism: **`HOP2_NOT_RETRIEVED` — 531**.

## Cross-domain — all 450 rows

Status is correct in all 450; answer text, required sources, and required domains fail in all 450. Both required source IDs are present in **114** rows and only the first required source is present in **336**. Zero rows cite both required sources and zero cite both required domains. Direct both-domain presence for the full evidence set is not observable because raw rows expose domains only for cited sources; the exact source-identity proxy is retained separately.

Only **3** rows contain an exact bridge-specific birthplace chunk; they are `CROSSDOMAIN_FINAL_VALUE_FAILURE`. The remaining **447** are `CROSSDOMAIN_PATH_NOT_BUILT`. The cross-domain mechanism is **`SAME_PRIMARY_MECHANISM_AS_MULTIHOP`** at the causal-family level: the bridge is surfaced but the second-hop path is not completed. Required-domain failure is a cross-domain consequence of the same partial-path answer, not evidence of a separate dominant mechanism.

Primary cross-domain mechanism: **`CROSSDOMAIN_PATH_NOT_BUILT` — 447**.

## Source diversity — all 1,000 denominator rows

| Mechanical condition | Count |
| --- | ---: |
| All required sources retrieved, only one required source cited | 348 |
| Second required source not retrieved | 652 |
| Multiple required sources cited | 0 |
| No required source cited | 0 |
| Duplicate-source collapse | 0 |
| Other | 0 |

Citation-count distribution is **960 rows with one citation** and **40 with two citations**. The 40 two-citation rows use two distinct sources, but the second is a non-required restatement source supporting the same first-hop creator fact; this is same-fact corroboration, not reasoning-path provenance. All 1,000 rows cite exactly one required source—the first—and none cite the second. Therefore **0/1,000** denominator rows satisfy all required sources, mechanically producing source diversity **0.0**.

Primary source-diversity mechanism: **`SECOND_HOP_REQUIRED_SOURCE_NEVER_CITED` — 1,000**.

## Insufficient-evidence recall

There are exactly **15** IE false negatives, all category `absent_entity`. Each retrieves a recorded `near-miss-note` and binds the absent artifact head to a named place sharing that head—such as “dynamo” to “Dynamo Walk”—then answers with an unrelated defining/location fact. No conflict is surfaced.

Primary distribution: **`NEAR_NAME_FALSE_BIND`: 15**. Secondary observed consequences are absent-entity binding and absent-relation binding.

## Prompt-injection containment misses

There are exactly **5** containment failures. In all five, the target location chunk is present and flagged as source injection, `acted_on` is false, zero-tolerance counters are all zero, and the trace says `source_injection:contained`; nevertheless synthesis selects the neighboring establishment-year chunk instead of the safe location fact.

Primary distribution: **`SAFE_FACT_SPLIT_FAILURE`: 5**. Directive-structure overlay: authority impersonation 2, tool-action directive 1, imperative directive 1, citation override 1. Source body text is not present in the authorized immutable result artifacts and is explicitly recorded as not observable. No regex patch is proposed.

## Generalization gap

| Finding | Tag | Evidence summary |
| --- | --- | --- |
| Template specialization | **SUPPORTED** | R6 documented exact-template/vocabulary misses and R7's development replay clears exposed R6, while fresh R7 multihop/cross-domain fall to 0.0; the exact internal boundary is not observable. |
| Relation-family specialization | **NOT PROVEN** | R7 failure spans author, painter, inventor, and other creator relations; the observed issue is broad second-hop failure. |
| Author/birthplace specialization | **CONTRADICTED** | All 550 fresh R7 author→birthplace multihop rows fail. |
| Creator-only bridge specialization | **CONTRADICTED** | Creator bridges themselves fail across both suites. |
| Citation logic tied to terminal fact only | **NOT PROVEN** | The intended terminal fact is never emitted; citations follow the emitted first-hop claim. |
| Second-hop provenance loss | **PROVEN** | The second required source is cited in 0/1,000 rows, including all rows where it is retrieved. |
| Same-fact corroboration confused with reasoning-path provenance | **PROVEN** | 40 rows cite a non-required restatement source for the same first-hop fact instead of the biography path source. |
| Partial-path answering | **PROVEN** | All 1,000 answers stop at the creator bridge and all traces report single-hop extraction. |
| Fresh injection wording gap | **CONTRADICTED** | All misses are non-fresh category rows; directives are detected/contained and the safe fact is lost during answer selection. |

## Frozen root-cause statement

The dominant R7 failure is partial-path answering: the system retrieves and emits the first-hop creator relation, usually never retrieves the exact bridge-specific second-hop birthplace, and never preserves the second required source/domain in citations. Where exact hop-2 evidence is present, it is still not synthesized or cited. IE loss is a separate near-name false bind, and the five injection misses are safe-fact split failures after successful directive detection.

This report makes no runtime repair recommendation and authorizes no repair, freeze, R8 holdout, or T22 action.
