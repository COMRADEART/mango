"""T21R5.13 — holdout uniqueness audit.

Mechanically verifies that the T21R5 blind holdout shares NO identity with
ALL prior evaluation worlds (T21, T21R, T21R2, T21R3 and T21R4) and
contains no internal duplication. Every check compares the T21R5 material
against the UNION of the five prior worlds, and each must be exactly zero:

  1. exact_duplicate_rows          duplicate full gold rows (case_id
                                   excluded) across the 8 T21R5 suites
  2. exact_duplicate_queries       duplicate query strings within T21R5
  3. case_id overlap               = 0 vs T21/T21R/T21R2/T21R3/T21R4 ids
  4. entity_identity_overlap       = 0 between T21R5 fixture-world entity
                                   names and prior-world entity names, and
                                   no prior entity may appear inside any
                                   T21R5 query (or vice versa)
  5. query overlap                 = 0 exact query strings shared with any
                                   prior-suite row
  6. chunk_id / source_id overlap  = 0 between the T21R5 corpus and the
                                   five prior corpora
  7. gold answer overlap           = 0 expect_answer_contains strings
                                   shared with prior gold
  8. source text overlap           = 0 exact chunk text strings shared
                                   with the five prior corpora
  9. attack phrase overlap         = 0 verbatim T21R5 attack strings
                                   inside any prior-suite row query or
                                   prior-corpus chunk (and vice versa)
 10. near_duplicate_flags          informational (audit-only): pairs of
                                   distinct T21R5 queries with token
                                   Jaccard >= 0.90, and cross-world query
                                   pairs reaching the same threshold

Prior-world entities are read as DATA from the frozen corpora
(chunks.jsonl metadata fact_entity) — no runtime module is imported or
executed on any holdout datum.

Output: evaluations/t21r5/holdout_uniqueness.json
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import t21r5_world as W  # noqa: E402
from t21r5_world import INJECTION_DIRECTIVES  # noqa: E402
from t21r5_build_suites import (  # noqa: E402
    OVERRIDE_PHRASES, SPOOF_PREAMBLES)

OUT_DIR = ROOT / "evaluations" / "t21r5"
SUITES_DIR = OUT_DIR / "suites"
T21R5_CORPUS = ROOT / "rag" / "gk_holdout_t21r5"
T21_SUITES = ROOT / "evaluations" / "t21" / "suites"
T21R_SUITES = ROOT / "evaluations" / "t21r" / "suites"
T21R2_SUITES = ROOT / "evaluations" / "t21r2" / "suites"
T21R3_SUITES_DIR = ROOT / "evaluations" / "t21r3" / "suites"
T21R4_SUITES_DIR = ROOT / "evaluations" / "t21r4" / "suites"
T21_CORPUS = ROOT / "rag" / "gk_corpus"
T21R_CORPUS = ROOT / "rag" / "gk_holdout_t21r"
T21R2_CORPUS = ROOT / "rag" / "gk_holdout_t21r2"
T21R3_CORPUS = ROOT / "rag" / "gk_holdout_t21r3"
T21R4_CORPUS = ROOT / "rag" / "gk_holdout_t21r4"
PRIOR_CORPORA = (("t21", T21_CORPUS), ("t21r", T21R_CORPUS),
                 ("t21r2", T21R2_CORPUS), ("t21r3", T21R3_CORPUS),
                 ("t21r4", T21R4_CORPUS))

T21R5_SUITES = [
    "mango-t21r5-retrieval-holdout-v1",
    "mango-t21r5-singlehop-holdout-v1",
    "mango-t21r5-multihop-holdout-v1",
    "mango-t21r5-crossdomain-holdout-v1",
    "mango-t21r5-citation-claim-holdout-v1",
    "mango-t21r5-conflict-abstention-holdout-v1",
    "mango-t21r5-temporal-holdout-v1",
    "mango-t21r5-adversarial-holdout-v1",
]


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line
            in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def token_set(text: str) -> set[str]:
    return {t for t
            in "".join(c.lower() if c.isalnum() else " " for c in text)
            .split() if len(t) > 3}


def jaccard(a: frozenset, b: frozenset) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def main() -> int:
    t21r5_rows: dict[str, list[dict]] = {}
    for name in T21R5_SUITES:
        t21r5_rows[name] = load_jsonl(SUITES_DIR / name / "holdout.jsonl")
    all_t21r5 = [r for rows in t21r5_rows.values() for r in rows]

    t21_rows: list[dict] = []
    for d in sorted(T21_SUITES.iterdir()):
        for fname in ("dev.jsonl", "final.jsonl"):
            p = d / fname
            if p.exists():
                t21_rows.extend(load_jsonl(p))
    prior_rows: list[dict] = list(t21_rows)
    for suites_dir in (T21R_SUITES, T21R2_SUITES, T21R3_SUITES_DIR,
                       T21R4_SUITES_DIR):
        for d in sorted(suites_dir.iterdir()):
            p = d / "holdout.jsonl"
            if p.exists():
                prior_rows.extend(load_jsonl(p))

    t21r5_queries = [r["request"]["query"] for r in all_t21r5]
    prior_queries = [r["request"]["query"] for r in prior_rows]

    # --- 1. exact duplicate rows (identity apart from case_id) ----------
    def row_identity(r: dict) -> str:
        core = {k: v for k, v in r.items() if k != "case_id"}
        return json.dumps(core, sort_keys=True, ensure_ascii=False)
    seen: dict[str, list[str]] = {}
    for r in all_t21r5:
        seen.setdefault(row_identity(r), []).append(r["case_id"])
    duplicate_rows = {k: v for k, v in seen.items() if len(v) > 1}

    # --- 2. exact duplicate queries (within T21R5) ----------------------
    q_seen: dict[str, list[str]] = {}
    for r in all_t21r5:
        q_seen.setdefault(r["request"]["query"], []).append(r["case_id"])
    duplicate_queries = {q: ids for q, ids in q_seen.items() if len(ids) > 1}

    # --- 3. case_id overlap ---------------------------------------------
    t21r5_ids = {r["case_id"] for r in all_t21r5}
    prior_ids = {r["case_id"] for r in prior_rows}
    case_id_overlap = sorted(t21r5_ids & prior_ids)

    # --- 4. entity identity overlap -------------------------------------
    t21r5_entities: set[str] = set()
    for e in W.TOWNS:
        t21r5_entities.add(e.lower())
    for e in W.NATIONS:
        t21r5_entities.add(e.lower())
    for p in W.PEOPLE:
        t21r5_entities.add(p["entity"].lower())
    for w in W.WORKS:
        t21r5_entities.add(w["entity"].lower())
    for a in W.ARTWORKS:
        t21r5_entities.add(a["entity"].lower())
    for i in W.INSTITUTIONS:
        t21r5_entities.add(i["entity"].lower())
    for t in W.TECHS:
        t21r5_entities.add(t["entity"].lower())
    for e, _attr, _value, _blurb, _dom1, _dom2 in W.CURATED_FACTS:
        t21r5_entities.add(e.lower())
    for e, _attr, _value, _blurb, _dom in W.SLOW_GEOGRAPHY_FACTS:
        t21r5_entities.add(e.lower())
    for e in W.ABSENT_ENTITIES:
        t21r5_entities.add(e.lower())
    for c in W.CONFLICTS:
        t21r5_entities.add(c["entity"].lower())
    for _src, entity, _attr, _idx in getattr(W, "INJECTED_FACTS", []):
        t21r5_entities.add(entity.lower())
    for text in W.NEAR_MISS_CHUNKS:
        t21r5_entities.add(text.split()[0] + " " + text.split()[1]
                           if len(text.split()) > 1 else text.lower())

    # prior world entities, read as DATA from the frozen corpora
    prior_entities: set[str] = set()
    for _name, corpus in PRIOR_CORPORA:
        for chunk in load_jsonl(corpus / "chunks.jsonl"):
            ent = (chunk.get("metadata") or {}).get("fact_entity")
            if ent:
                prior_entities.add(str(ent).strip().lower())
    for corpus_name in ("t21r3", "t21r4"):
        corpus = ROOT / "rag" / f"gk_holdout_{corpus_name}"
        world_path = corpus / "world.jsonl"
        if not world_path.exists():
            continue
        for line in world_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("type") == "WorldEntity":
                prior_entities.add(row["entity_id"].lower())

    entity_name_overlap = sorted(t21r5_entities & prior_entities)

    def entity_in(texts: list[str], needle: str) -> bool:
        # whole-phrase match: "the po" must not hit "the population ..."
        pat = re.compile(r"\b" + re.escape(needle) + r"\b")
        return any(pat.search(t.lower()) for t in texts)

    t21r5_in_prior = sorted(
        e for e in t21r5_entities
        if entity_in(prior_queries, e))
    prior_in_t21r5 = sorted(
        e for e in prior_entities
        if entity_in(t21r5_queries, e))

    # --- 5. exact query overlap -----------------------------------------
    query_overlap = sorted(set(t21r5_queries) & set(prior_queries))

    # --- 6. chunk / source id overlap -----------------------------------
    t21r5_chunk_ids = {c["chunk_id"]
                       for c in load_jsonl(T21R5_CORPUS / "chunks.jsonl")}
    t21r5_source_ids = {s["source_id"]
                        for s in load_jsonl(T21R5_CORPUS / "sources.jsonl")}
    prior_chunk_ids: set[str] = set()
    prior_source_ids: set[str] = set()
    for _name, corpus in PRIOR_CORPORA:
        prior_chunk_ids.update(c["chunk_id"]
                               for c in load_jsonl(corpus / "chunks.jsonl"))
        prior_source_ids.update(s["source_id"]
                                for s in load_jsonl(corpus / "sources.jsonl"))
    chunk_id_overlap = sorted(t21r5_chunk_ids & prior_chunk_ids)
    source_id_overlap = sorted(t21r5_source_ids & prior_source_ids)

    # --- 7. gold answer value overlap ------------------------------------
    t21r5_answers: set[str] = set()
    for r in all_t21r5:
        for v in r["gold"].get("expect_answer_contains", []) or []:
            t21r5_answers.add(str(v).lower())
    prior_answers: set[str] = set()
    for r in prior_rows:
        for v in r["gold"].get("expect_answer_contains", []) or []:
            prior_answers.add(str(v).lower())
    answer_overlap = sorted(t21r5_answers & prior_answers)

    # --- 8. exact source-text overlap ------------------------------------
    t21r5_texts = {c["text"] for c in load_jsonl(T21R5_CORPUS / "chunks.jsonl")}
    prior_texts: set[str] = set()
    for _name, corpus in PRIOR_CORPORA:
        prior_texts.update(c["text"]
                           for c in load_jsonl(corpus / "chunks.jsonl"))
    text_overlap = sorted(t21r5_texts & prior_texts)

    # --- 9. verbatim attack-string overlap -------------------------------
    attack_strings = list(INJECTION_DIRECTIVES) + [
        p for p in OVERRIDE_PHRASES] + list(SPOOF_PREAMBLES)
    prior_chunk_cache: dict[str, list[str]] = {}
    for corpus_name, corpus in PRIOR_CORPORA:
        prior_chunk_cache[corpus_name] = [
            c["text"].lower() for c in load_jsonl(corpus / "chunks.jsonl")]
    attack_hits: list[dict] = []
    for phrase in attack_strings:
        low = phrase.lower()
        if any(low in q.lower() for q in prior_queries):
            attack_hits.append({"direction": "t21r5_phrase_in_prior_query",
                                "phrase": phrase})
        for corpus_name, texts in prior_chunk_cache.items():
            if any(low in t for t in texts):
                attack_hits.append({
                    "direction": f"t21r5_phrase_in_{corpus_name}_chunk",
                    "phrase": phrase})
    prior_attack_hits = [
        q for q in prior_queries
        if any(q.lower() in rq.lower() or rq.lower() in q.lower()
               for rq in t21r5_queries if len(rq) > 40)]
    for q in prior_attack_hits:
        attack_hits.append({"direction": "prior_query_in_t21r5",
                            "phrase": q})

    # --- 10. near duplicates (informational, audit-only) -----------------
    near_flags: list[dict] = []
    reps: list[tuple[str, frozenset]] = []
    seen_q: set[str] = set()
    for q in t21r5_queries:
        if q in seen_q:
            continue
        seen_q.add(q)
        reps.append((q, frozenset(token_set(q))))
    for i, (q1, t1) in enumerate(reps):
        for q2, t2 in reps[i + 1:]:
            j = jaccard(t1, t2)
            if j >= 0.90:
                near_flags.append({"scope": "internal", "query_a": q1,
                                   "query_b": q2, "jaccard": round(j, 3)})
    prior_reps = []
    seen_pq: set[str] = set()
    for q in prior_queries:
        if q in seen_pq:
            continue
        seen_pq.add(q)
        prior_reps.append((q, frozenset(token_set(q))))
    for q1, t1 in reps:
        for q2, t2 in prior_reps:
            j = jaccard(t1, t2)
            if j >= 0.90:
                near_flags.append({"scope": "cross_world", "query_a": q1,
                                   "query_b": q2, "jaccard": round(j, 3)})

    suite_counts = {name: len(rows) for name, rows in t21r5_rows.items()}
    suite_hashes = {
        name: hashlib.sha256(
            (SUITES_DIR / name / "holdout.jsonl").read_bytes()).hexdigest()
        for name in T21R5_SUITES}

    report = {
        "audit": "t21r5_holdout_uniqueness",
        "baseline": "evaluations/t21 + evaluations/t21r + "
                     "evaluations/t21r2 + evaluations/t21r3 + "
                     "evaluations/t21r4",
        "suites": suite_counts,
        "suite_holdout_sha256": suite_hashes,
        "total_rows": len(all_t21r5),
        "checks": {
            "exact_duplicate_rows": {
                "count": len(duplicate_rows), "detail": duplicate_rows},
            "exact_duplicate_queries": {
                "count": len(duplicate_queries), "detail": duplicate_queries},
            "case_id_overlap_with_prior_worlds": {
                "count": len(case_id_overlap), "detail": case_id_overlap},
            "entity_identity_overlap": {
                "entity_name_overlap": {
                    "count": len(entity_name_overlap),
                    "detail": entity_name_overlap},
                "t21r5_entities_in_prior_queries": {
                    "count": len(t21r5_in_prior), "detail": t21r5_in_prior},
                "prior_entities_in_t21r5_queries": {
                    "count": len(prior_in_t21r5),
                    "detail": prior_in_t21r5},
            },
            "exact_query_overlap_with_prior_worlds": {
                "count": len(query_overlap), "detail": query_overlap},
            "chunk_id_overlap_with_prior_worlds": {
                "count": len(chunk_id_overlap), "detail": chunk_id_overlap},
            "source_id_overlap_with_prior_worlds": {
                "count": len(source_id_overlap), "detail": source_id_overlap},
            "gold_answer_value_overlap_with_prior_worlds": {
                "count": len(answer_overlap), "detail": answer_overlap},
            "exact_source_text_overlap_with_prior_worlds": {
                "count": len(text_overlap), "detail": text_overlap},
            "verbatim_attack_string_overlap_with_prior_worlds": {
                "count": len(attack_hits), "detail": attack_hits},
            "near_duplicate_flags": {
                "count": len(near_flags),
                "pairs": (near_flags[:50] if len(near_flags) > 50
                          else near_flags)},
        },
        "gate": {
            "exact_duplicate_rows": 0,
            "exact_duplicate_queries": 0,
            "case_id_overlap": 0,
            "entity_identity_overlap": 0,
            "query_overlap": 0,
            "chunk_id_overlap": 0,
            "source_id_overlap": 0,
            "gold_answer_overlap": 0,
            "source_text_overlap": 0,
            "attack_string_overlap": 0,
        },
    }

    gate = report["gate"]
    checks = report["checks"]
    ok = (
        checks["exact_duplicate_rows"]["count"]
        == gate["exact_duplicate_rows"]
        and checks["exact_duplicate_queries"]["count"]
        == gate["exact_duplicate_queries"]
        and checks["case_id_overlap_with_prior_worlds"]["count"]
        == gate["case_id_overlap"]
        and checks["entity_identity_overlap"]["entity_name_overlap"]["count"]
        == gate["entity_identity_overlap"]
        and checks["entity_identity_overlap"][
            "t21r5_entities_in_prior_queries"]["count"]
        == gate["entity_identity_overlap"]
        and checks["entity_identity_overlap"][
            "prior_entities_in_t21r5_queries"]["count"]
        == gate["entity_identity_overlap"]
        and checks["exact_query_overlap_with_prior_worlds"]["count"]
        == gate["query_overlap"]
        and checks["chunk_id_overlap_with_prior_worlds"]["count"]
        == gate["chunk_id_overlap"]
        and checks["source_id_overlap_with_prior_worlds"]["count"]
        == gate["source_id_overlap"]
        and checks["gold_answer_value_overlap_with_prior_worlds"]["count"]
        == gate["gold_answer_overlap"]
        and checks["exact_source_text_overlap_with_prior_worlds"]["count"]
        == gate["source_text_overlap"]
        and checks[
            "verbatim_attack_string_overlap_with_prior_worlds"]["count"]
        == gate["attack_string_overlap"]
    )
    report["verdict"] = "UNIQUE" if ok else "OVERLAP_DETECTED"

    out = OUT_DIR / "holdout_uniqueness.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"],
                      "total_rows": report["total_rows"],
                      "suite_counts": suite_counts,
                      "near_duplicate_flags": len(near_flags)}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())