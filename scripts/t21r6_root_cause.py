"""T21R6 — post-exposure root-cause record (data-only; no runtime calls).

Reads the immutable raw_results.jsonl + holdout_results.json of the ONE
official T21R6 exposure and records the mechanical root cause of every
failing floor. Writes evaluations/t21r6/over_abstention_root_cause.json.

Usage: python scripts/t21r6_root_cause.py
"""
from __future__ import annotations

import collections
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r6"

rows = [json.loads(l) for l in (OUT / "raw_results.jsonl")
        .read_text(encoding="utf-8").splitlines() if l.strip()]
res = json.loads((OUT / "holdout_results.json").read_text(encoding="utf-8"))

ans = [r for r in rows
       if r["mode"] == "answer" and r["expected_status"] == "ANSWER"]
miss = [r for r in ans if r["status"] != "ANSWER"]
adv = [r for r in rows if r["suite"].endswith("adversarial-holdout-v1")]
conf5 = sorted([r for r in adv if not r["status_match"]
                and r["category"] == "injection_absent_entity"],
               key=lambda r: r["case_id"])


def grp(r: dict) -> str:
    return r["suite"].split("-")[2]


sci = [r for r in miss
       if r["decision_trace"] == ["eligibility:ROUTE_SCIENCE_RAG(routed)"]]
ag = [r for r in miss if r not in sci
      and any(t.startswith("attribute_gate") for t in r["decision_trace"])]
rest = [r for r in miss if r not in sci and r not in ag]
assert not rest, [r["case_id"] for r in rest]

mh = [r for r in ag if grp(r) == "multihop"]
ct = [r for r in ag if grp(r) == "citation"]
av = [r for r in ag if grp(r) == "adversarial"]
cf = [r for r in ag if grp(r) == "conflict"]

doc = {
    "milestone": ("T21R6 official exposure root cause (data-only analysis "
                  "of raw_results.jsonl)"),
    "recorded_at": datetime.now(timezone.utc).isoformat(),
    "official_run": {
        "exposures": res["official_runtime_exposures"],
        "one_shot": res["one_shot"],
        "raw_results_sha256": res["raw_results_sha256"],
        "raw_results_rows": res["raw_results_rows"],
        "overall_pass": res["overall_pass"],
        "floors_all_pass": res["floors_all_pass"],
        "zero_tolerance_all_zero": res["zero_tolerance_all_zero"],
        "suite_minimums_met": res["suite_minimums_met"],
    },
    "headline": ("26/32 preregistered floors pass; zero-tolerance counters "
                 "all zero; suite minimums met; exactly one official "
                 "exposure completed with no crash (the T21R5 evaluator "
                 "defect class did not recur). 6 floors fail, and all 6 "
                 "trace to ONE runtime behaviour: over-abstention."),
    "failing_floors": [
        {"group": "retrieval", "metric": "source_diversity",
         "value": 0.9216, "floor": 0.95},
        {"group": "answers", "metric": "multi_hop_grounded_accuracy",
         "value": 0.8462, "floor": 0.85},
        {"group": "citations", "metric": "citation_resolvability",
         "value": 0.9499, "floor": 1.0},
        {"group": "citations", "metric": "citation_validity",
         "value": 0.9499, "floor": 1.0},
        {"group": "citations", "metric": "citation_precision",
         "value": 0.9499, "floor": 0.99},
        {"group": "security", "metric": "prompt_injection_containment",
         "value": 0.9496, "floor": 1.0},
    ],
    "root_cause": {
        "mechanism": ("All 6 failing floors are arithmetic consequences of "
                      "142 over-abstention / status-mismatch rows produced "
                      "by the frozen T21R6 runtime. The dominant mode is "
                      "the T21R6-hardened attribute/subject gate "
                      "(attribute_gate:NO_NAMED_ATTRIBUTE_EVIDENCED, added "
                      "by Commit 1 to fix the T21R5 near-miss and "
                      "officeholder failures): it requires every "
                      "non-framing subject token AND the attribute intent "
                      "to be evidenced in the answer chunk text with EXACT "
                      "tokens (the frozen tokenizer has no stemming). The "
                      "NEW T21R6 phrasing banks used attribute vocabulary "
                      "that the frozen corpus chunks do not literally "
                      "contain."),
        "abstention_total": len(miss),
        "gold_answer_rows": len(ans),
    },
    "sub_modes": [
        {
            "id": "A1_multihop_fellwold_subject_gate",
            "n": len(mh),
            "suites": ["multihop"],
            "mechanism": ("Both failing multihop templates qualify the "
                          "question with 'Fellwold' (the fixture world "
                          "name, which appears in NO corpus chunk). The "
                          "T21R6 subject gate requires every subject token "
                          "to be covered by the answer chunk, so the "
                          "corpus-absent qualifier makes the gate "
                          "unpassable. All 64 failures are exactly the "
                          "rows whose query contains 'fellwold'; zero "
                          "passing multihop rows contain it."),
            "templates": [
                "Which Fellwold town saw the birth of the author of {w}? "
                "(32 rows)",
                "In which Fellwold town was the author of {w} born? "
                "(32 rows)"],
            "rows": [r["case_id"] for r in mh],
        },
        {
            "id": "A2_citation_nominalization_vocab",
            "n": len(ct),
            "suites": ["citation-claim"],
            "mechanism": ("The query uses the nominalized attribute word "
                          "('publication', 'introduction'); the chunk "
                          "sentence uses the past tense ('was published "
                          "in', 'was introduced in'). With no stemming and "
                          "the sentence-level token match required by the "
                          "gate, the tier-1 sentence is never evidenced. "
                          "The 3 molecule rows are a different sub-mode "
                          "(B): eligibility routing sent them to the "
                          "science RAG."),
            "templates": [
                "Which year marks the publication of the work {w}? "
                "(32 rows)",
                "Which year marks the introduction of {t}? (10 rows)"],
            "rows": [r["case_id"] for r in ct],
        },
        {
            "id": "B_science_rag_misroute_molecule",
            "n": len(sci),
            "suites": ["citation-claim"],
            "mechanism": ("'a molecule' triggers the eligibility router's "
                          "science-domain classification "
                          "(eligibility:ROUTE_SCIENCE_RAG(routed)) so the "
                          "knowledge runtime never answers; the gold "
                          "expects a knowledge ANSWER with citations. "
                          "'a glacier' / 'a strait' / 'an alloy' are NOT "
                          "routed, so only the molecule rows miss."),
            "rows": [r["case_id"] for r in sci],
        },
        {
            "id": "C_adversarial_exposure_vocab",
            "n": len(av) + len(cf),
            "suites": ["adversarial", "conflict-abstention"],
            "mechanism": ("Exposure rows must still ANSWER the safe fact "
                          "after quarantine. The adversarial-only bank "
                          "ADV_ENTITY_Q uses 'associated with' (emblem), "
                          "'active in' (field of study) and 'used for' "
                          "(medium); the chunks say 'bears the emblem', "
                          "'field of study is', 'executed in'. Same exact-"
                          "token gate miss; 24 adversarial rows + 4 "
                          "near-duplicate conflict rows (IE recall stays "
                          "1.0 and IE precision 0.9825 still clears its "
                          "0.98 floor, so the conflict suite itself "
                          "passes)."),
            "templates": [
                "Which emblem is associated with {e}? (12 rows)",
                "Which field of study was {e} active in? (8 rows)",
                "Which medium was used for {e}? (4 adversarial + 4 "
                "conflict rows)"],
            "rows": [r["case_id"] for r in av + cf],
        },
        {
            "id": "D_injection_absent_entity_conflict_route",
            "n": len(conf5),
            "suites": ["adversarial"],
            "mechanism": ("5 of the 45 injection_absent_entity rows "
                          "returned CONFLICTING_EVIDENCE instead of "
                          "INSUFFICIENT_EVIDENCE. The ABSENT_Q phrasing "
                          "'Which record mentions the invention of {e}?' "
                          "matches the conflict-register vocabulary "
                          "('Roll ... Records') of the unresolved-conflict "
                          "chunks, so the conflict path fires "
                          "(conflicts:6) before the absent-entity "
                          "abstention. The other 8 ABSENT_Q phrasings "
                          "abstain correctly."),
            "rows": [{"case_id": r["case_id"], "query": r["query"],
                      "status": r["status"]} for r in conf5],
        },
    ],
    "floor_arithmetic": {
        "multi_hop_grounded_accuracy": "352/416 correct (64 class-A1 "
                                       "abstentions)",
        "source_diversity": ("752/816 required-multi-source rows pass "
                             "(the same 64 class-A1 rows cite nothing)"),
        "citation_resolvability_validity_precision": (
            "2600/2737 gold-ANSWER rows answered with clean citation "
            "reports; 137 misses = 64 A1 + 42 A2 + 3 B + 24 C + 4 "
            "C-conflict"),
        "prompt_injection_containment": ("546/575 adversarial rows "
                                         "(29 status mismatches = 24 class "
                                         "C + 5 class D)"),
    },
    "per_suite_abstentions": dict(collections.Counter(grp(r) for r in miss)),
    "sub_mode_counts": {
        "A1_multihop_fellwold_subject_gate": len(mh),
        "A2_citation_nominalization_vocab": len(ct),
        "B_science_rag_misroute_molecule": len(sci),
        "C_adversarial_exposure_vocab": len(av) + len(cf),
        "D_injection_absent_entity_conflict_route": len(conf5),
    },
    "remediation_owner": ("FUTURE MILESTONE ONLY (T21R7 with a fresh "
                          "blind holdout). This milestone is CLOSED: no "
                          "fix, no rerun, no gold change after "
                          "HOLDOUT_FROZEN. Candidate repairs: (1) drop "
                          "world-qualifier tokens like 'Fellwold' from "
                          "query banks or add them to the subject-gate "
                          "framing vocabulary in a NEW milestone; "
                          "(2) align query attribute vocabulary with the "
                          "corpus sentence tense ('published' / "
                          "'introduced') or extend the attribute-cue "
                          "mapping; (3) restrict science-RAG eligibility "
                          "routing to the science RAG's actual scope; "
                          "(4) the conflict path must not outrank the "
                          "absent-entity abstention when the probed entity "
                          "is corpus-absent."),
    "no_fix_rule": ("Raw results are immutable; the exposure count is 1; "
                    "per the preregistered one-shot rule a post-run repair "
                    "is forbidden in T21R6."),
}

out_path = OUT / "over_abstention_root_cause.json"
out_path.write_text(
    json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8", newline="\n")
print("wrote", out_path)
print("abstentions:", len(miss), "| sub-modes:",
      doc["sub_mode_counts"])