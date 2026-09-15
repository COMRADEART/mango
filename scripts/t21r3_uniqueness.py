"""T21R3.15 — holdout uniqueness audit.

Mechanically verifies that the T21R3 blind holdout shares NO identity with
ALL prior evaluation worlds (T21, T21R and T21R2) and contains no
internal
duplication. Every check compares the T21R3 material against the UNION of
T21 and T21R, and each must be exactly zero:

  1. exact_duplicate_rows          duplicate full gold rows (case_id
                                   excluded) across the 8 T21R3 suites
  2. exact_duplicate_queries       duplicate query strings within T21R3
  3. case_id overlap               = 0 vs T21/T21R/T21R2 case ids
  4. entity_identity_overlap       = 0 between T21R3 fixture-world entity
                                   names and T21/T21R/T21R2 entity names,
                                   and no prior entity may appear inside
                                   any T21R3 query (or vice versa)
  5. query overlap                 = 0 exact query strings shared with any
                                   T21 dev/final row or T21R/T21R2 holdout
                                   row
  6. chunk_id / source_id overlap  = 0 between the T21R3 corpus and the
                                   T21 / T21R / T21R2 corpora
  7. gold answer overlap           = 0 expect_answer_contains strings
                                   shared with T21/T21R/T21R2 gold
  8. source text overlap           = 0 exact chunk text strings shared
                                   with the T21 / T21R / T21R2 corpora
  9. attack phrase overlap         = 0 verbatim T21R3 attack strings
                                   inside any prior-suite row query (and
                                   vice versa)
 10. near_duplicate_flags          informational (audit-only): pairs of
                                   distinct T21R3 queries with token
                                   Jaccard >= 0.90, and cross-world query
                                   pairs reaching the same threshold

Output: evaluations/t21r3/holdout_uniqueness.json
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t21r3_world as W  # noqa: E402
from t21r3_world import INJECTION_DIRECTIVES  # noqa: E402
from t21r3_build_suites import OVERRIDE_PHRASES, SPOOF_PREAMBLES  # noqa: E402

OUT_DIR = ROOT / "evaluations" / "t21r3"
SUITES_DIR = OUT_DIR / "suites"
T21R3_CORPUS = ROOT / "rag" / "gk_holdout_t21r3"
T21_SUITES = ROOT / "evaluations" / "t21" / "suites"
T21R_SUITES = ROOT / "evaluations" / "t21r" / "suites"
T21R2_SUITES = ROOT / "evaluations" / "t21r2" / "suites"
T21_CORPUS = ROOT / "rag" / "gk_corpus"
T21R_CORPUS = ROOT / "rag" / "gk_holdout_t21r"
T21R2_CORPUS = ROOT / "rag" / "gk_holdout_t21r2"

T21R3_SUITES = [
    "mango-t21r3-retrieval-holdout-v1",
    "mango-t21r3-singlehop-holdout-v1",
    "mango-t21r3-multihop-holdout-v1",
    "mango-t21r3-crossdomain-holdout-v1",
    "mango-t21r3-citation-claim-holdout-v1",
    "mango-t21r3-conflict-abstention-holdout-v1",
    "mango-t21r3-temporal-holdout-v1",
    "mango-t21r3-adversarial-holdout-v1",
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
    t21r3_rows: dict[str, list[dict]] = {}
    for name in T21R3_SUITES:
        t21r3_rows[name] = load_jsonl(SUITES_DIR / name / "holdout.jsonl")
    all_t21r3 = [r for rows in t21r3_rows.values() for r in rows]

    t21_rows: list[dict] = []
    for d in sorted(T21_SUITES.iterdir()):
        for fname in ("dev.jsonl", "final.jsonl"):
            p = d / fname
            if p.exists():
                t21_rows.extend(load_jsonl(p))
    t21r_rows: list[dict] = []
    for d in sorted(T21R_SUITES.iterdir()):
        p = d / "holdout.jsonl"
        if p.exists():
            t21r_rows.extend(load_jsonl(p))
    t21r2_rows: list[dict] = []
    for d in sorted(T21R2_SUITES.iterdir()):
        p = d / "holdout.jsonl"
        if p.exists():
            t21r2_rows.extend(load_jsonl(p))
    prior_rows = t21_rows + t21r_rows + t21r2_rows

    t21r3_queries = [r["request"]["query"] for r in all_t21r3]
    prior_queries = [r["request"]["query"] for r in prior_rows]

    # --- 1. exact duplicate rows (identity apart from case_id) ----------
    def row_identity(r: dict) -> str:
        core = {k: v for k, v in r.items() if k != "case_id"}
        return json.dumps(core, sort_keys=True, ensure_ascii=False)
    seen: dict[str, list[str]] = {}
    for r in all_t21r3:
        seen.setdefault(row_identity(r), []).append(r["case_id"])
    duplicate_rows = {k: v for k, v in seen.items() if len(v) > 1}

    # --- 2. exact duplicate queries (within T21R3) ----------------------
    q_seen: dict[str, list[str]] = {}
    for r in all_t21r3:
        q_seen.setdefault(r["request"]["query"], []).append(r["case_id"])
    duplicate_queries = {q: ids for q, ids in q_seen.items() if len(ids) > 1}

    # --- 3. case_id overlap ---------------------------------------------
    t21r3_ids = {r["case_id"] for r in all_t21r3}
    prior_ids = {r["case_id"] for r in prior_rows}
    case_id_overlap = sorted(t21r3_ids & prior_ids)

    # --- 4. entity identity overlap -------------------------------------
    t21r3_entities: set[str] = set()
    for e in W.TOWNS:
        t21r3_entities.add(e.lower())
    for e in W.NATIONS:
        t21r3_entities.add(e.lower())
    for p in W.PEOPLE:
        t21r3_entities.add(p["entity"].lower())
    for w in W.WORKS:
        t21r3_entities.add(w["entity"].lower())
    for a in W.ARTWORKS:
        t21r3_entities.add(a["entity"].lower())
    for i in W.INSTITUTIONS:
        t21r3_entities.add(i["entity"].lower())
    for t in W.TECHS:
        t21r3_entities.add(t["entity"].lower())
    for e, _attr, _value, _blurb, _dom1, _dom2 in W.CURATED_FACTS:
        t21r3_entities.add(e.lower())
    for e, _attr, _value, _blurb, _dom in W.SLOW_GEOGRAPHY_FACTS:
        t21r3_entities.add(e.lower())
    for e in W.ABSENT_ENTITIES:
        t21r3_entities.add(e.lower())
    for c in W.CONFLICTS:
        t21r3_entities.add(c["entity"].lower())

    # prior world entities, from the runtime fixture modules (constants
    # only — no runtime function is executed on any holdout datum)
    from sciencemath.knowledge import fixtures as t21_fixtures
    import t21r_fixtures as t21r_fixtures
    prior_entities: set[str] = set()
    for obj in (t21_fixtures.fixture_cities() + t21_fixtures.fixture_people()
                + t21_fixtures.fixture_works()
                + t21_fixtures.fixture_institutions()
                + t21_fixtures.fixture_techs()):
        prior_entities.add(obj["entity"].lower())
    for row in t21_fixtures.all_fixture_facts():
        prior_entities.add(str(row[0]).lower())
    for e in t21r_fixtures.fixture_entities():
        prior_entities.add(e.lower())
    for e, _a, _v, _c in t21r_fixtures.CURATED_FACTS:
        prior_entities.add(e.lower())
    # T21R2 world entities, read as DATA (JSONL) from its frozen corpus
    for line in (T21R2_CORPUS / "world.jsonl") \
            .read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("type") == "WorldEntity":
            prior_entities.add(row["entity_id"].lower())

    entity_name_overlap = sorted(t21r3_entities & prior_entities)
    t21r3_in_prior = sorted(
        e for e in t21r3_entities
        if any(e in q.lower() for q in prior_queries))
    prior_in_t21r3 = sorted(
        e for e in prior_entities
        if any(e in q.lower() for q in t21r3_queries))

    # --- 5. exact query overlap -----------------------------------------
    query_overlap = sorted(set(t21r3_queries) & set(prior_queries))

    # --- 6. chunk / source id overlap -----------------------------------
    t21r3_chunk_ids = {c["chunk_id"]
                       for c in load_jsonl(T21R3_CORPUS / "chunks.jsonl")}
    t21r3_source_ids = {s["source_id"]
                        for s in load_jsonl(T21R3_CORPUS / "sources.jsonl")}
    prior_chunk_ids: set[str] = set()
    prior_source_ids: set[str] = set()
    for corpus in (T21_CORPUS, T21R_CORPUS, T21R2_CORPUS):
        prior_chunk_ids.update(c["chunk_id"]
                               for c in load_jsonl(corpus / "chunks.jsonl"))
        prior_source_ids.update(s["source_id"]
                                for s in load_jsonl(corpus / "sources.jsonl"))
    chunk_id_overlap = sorted(t21r3_chunk_ids & prior_chunk_ids)
    source_id_overlap = sorted(t21r3_source_ids & prior_source_ids)

    # --- 7. gold answer value overlap ------------------------------------
    t21r3_answers: set[str] = set()
    for r in all_t21r3:
        for v in r["gold"].get("expect_answer_contains", []) or []:
            t21r3_answers.add(str(v).lower())
    prior_answers: set[str] = set()
    for r in prior_rows:
        for v in r["gold"].get("expect_answer_contains", []) or []:
            prior_answers.add(str(v).lower())
    answer_overlap = sorted(t21r3_answers & prior_answers)

    # --- 8. exact source-text overlap ------------------------------------
    t21r3_texts = {c["text"] for c in load_jsonl(T21R3_CORPUS / "chunks.jsonl")}
    prior_texts: set[str] = set()
    for corpus in (T21_CORPUS, T21R_CORPUS, T21R2_CORPUS):
        prior_texts.update(c["text"]
                           for c in load_jsonl(corpus / "chunks.jsonl"))
    text_overlap = sorted(t21r3_texts & prior_texts)

    # --- 9. verbatim attack-string overlap -------------------------------
    attack_strings = list(INJECTION_DIRECTIVES) + [
        p for p in OVERRIDE_PHRASES] + list(SPOOF_PREAMBLES)
    attack_hits: list[dict] = []
    for phrase in attack_strings:
        low = phrase.lower()
        if any(low in q.lower() for q in prior_queries):
            attack_hits.append({"direction": "t21r3_phrase_in_prior_query",
                                "phrase": phrase})
        # directives also live inside corpus chunks of prior worlds
        for corpus_name, corpus in (("t21", T21_CORPUS),
                                    ("t21r", T21R_CORPUS),
                                    ("t21r2", T21R2_CORPUS)):
            if any(low in c["text"].lower()
                   for c in load_jsonl(corpus / "chunks.jsonl")):
                attack_hits.append({
                    "direction": f"t21r3_phrase_in_{corpus_name}_chunk",
                    "phrase": phrase})
    prior_attack_hits = [
        q for q in prior_queries
        if any(q.lower() in rq.lower() or rq.lower() in q.lower()
               for rq in t21r3_queries if len(rq) > 40)]
    for q in prior_attack_hits:
        attack_hits.append({"direction": "prior_query_in_t21r3",
                            "phrase": q})

    # --- 10. near duplicates (informational, audit-only) -----------------
    near_flags: list[dict] = []
    reps: list[tuple[str, frozenset]] = []
    seen_q: set[str] = set()
    for q in t21r3_queries:
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

    suite_counts = {name: len(rows) for name, rows in t21r3_rows.items()}
    suite_hashes = {
        name: hashlib.sha256(
            (SUITES_DIR / name / "holdout.jsonl").read_bytes()).hexdigest()
        for name in T21R3_SUITES}

    report = {
        "audit": "t21r3_holdout_uniqueness",
        "baseline": "evaluations/t21 + evaluations/t21r + "
                     "evaluations/t21r2",
        "suites": suite_counts,
        "suite_holdout_sha256": suite_hashes,
        "total_rows": len(all_t21r3),
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
                "t21r3_entities_in_prior_queries": {
                    "count": len(t21r3_in_prior), "detail": t21r3_in_prior},
                "prior_entities_in_t21r3_queries": {
                    "count": len(prior_in_t21r3),
                    "detail": prior_in_t21r3},
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
            "t21r3_entities_in_prior_queries"]["count"]
        == gate["entity_identity_overlap"]
        and checks["entity_identity_overlap"][
            "prior_entities_in_t21r3_queries"]["count"]
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