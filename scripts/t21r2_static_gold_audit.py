"""T21R2.6 — static pre-freeze QA of the derived gold suites.

This script performs ONLY static, data-only validation. It must NEVER
import anything from src/sciencemath/knowledge (enforced mechanically by
tests/test_t21r2_blind_holdout_contract.py). The tokenizer, coverage and
entity-gate semantics used below are LOCAL REIMPLEMENTATIONS transcribed
from the frozen runtime source, kept bit-for-bit in sync by the firewall
test's schema cross-check.

Checks:
  A. corpus integrity: unique ids, FK integrity, checksum agreement,
     ordinal ordering, manifest agreement
  B. suite schema: required fields, status/mode/category vocabularies,
     global case_id uniqueness, gold-field consistency
  C. grounding: every ANSWER gold value occurs in its gold chunk text and
     in the world fact store; gold chunk ids exist; required sources exist
  D. temporal consistency: temporal cue words match the preregistered
     category; gold mayor/publication values match the world
  E. conflict consistency: unresolved/authority/freshness rows match the
     declared conflict table
  F. static retrieval proxies: coverage (>= 0.60) over gold chunk text
     and a conservative upper bound over any 8-chunk union; entity-gate
     reimplemented and checked against the gold chunk
  G. uniqueness: exact query overlap vs T21 and T21R == 0; near-duplicate
     similarity reported for audit only
  H. contract floors: suite sizes, composition minimums, multihop rules

Usage: python scripts/t21r2_static_gold_audit.py
Exit code 0 = PASS; any finding exits 1.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import t21r2_world as W  # data-generation module (NOT runtime code)
HOLDOUT = ROOT / "rag" / "gk_holdout_t21r2"
SUITES_DIR = ROOT / "evaluations" / "t21r2" / "suites"
CONTRACT = ROOT / "evaluations" / "t21r2" / "validation_contract.json"

# ---------------------------------------------------------------------------
# Local reimplementations of frozen runtime mechanics (data transcription;
# cross-checked by tests/test_t21r2_blind_holdout_contract.py)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOP = {"a", "an", "the", "of", "to", "in", "and", "or", "is", "are",
         "was", "were", "be", "been", "it", "its", "as", "at", "by",
         "for", "on", "with", "that", "this", "from", "which", "who",
         "whom", "what", "when", "where", "how", "why", "did", "does",
         "do", "have", "has", "had", "many", "much", "there", "their",
         "about", "into", "also"}

_CAP_FRAMEWORDS = {
    "the", "a", "an", "in", "on", "at", "as", "of", "and", "or", "what",
    "when", "where", "who", "which", "how", "why", "is", "was", "were",
    "did", "does", "do", "to", "for", "with", "by", "from", "that",
    "this", "it", "answer", "question", "please", "tell", "give", "name",
    "list", "identify", "say", "use", "skip", "ignore", "make", "return",
    "i", "define", "describe", "state"}

# Local transcription of the frozen query-override patterns (injection.py)
# so gold checks can compute the EFFECTIVE query exactly as the runtime
# does. Cross-checked by tests/test_t21r2_blind_holdout_contract.py.
_OVERRIDE_PATTERNS = (
    re.compile(r"ignore (?:the )?(?:citations|sources|provenance)",
               re.IGNORECASE),
    re.compile(r"answer (?:from|with|using) (?:your )?(?:memory|own "
               r"knowledge|internal knowledge|training)", re.IGNORECASE),
    re.compile(r"say you (?:found|have|used) (?:a |the )?source",
               re.IGNORECASE),
    re.compile(r"(?:return|include|make up|fabricate) (?:a |the )?"
               r"(?:fake|nonexistent|dummy) (?:url|citation|source)",
               re.IGNORECASE),
    re.compile(r"use (?:the |this )?source even if (?:it is |it's |you are "
               r"|they are )?unrelated", re.IGNORECASE),
    re.compile(r"skip (?:the )?(?:verification|evidence gate|claim check)",
               re.IGNORECASE),
    re.compile(r"ignore (?:all |any |the )?(?:previous|prior|above|earlier)"
               r" (?:instructions|prompts|rules)", re.IGNORECASE),
    re.compile(r"(?:i am|this is) (?:the )?(?:system|administrator|"
               r"developer|official|authoritative)", re.IGNORECASE),
)


def _effective_query(q: str) -> str:
    """Mirror of the frozen _strip_injection_phrases for query-override
    patterns: remove matches, then keep text after the last colon."""
    cleaned = q
    flagged = False
    for pattern in _OVERRIDE_PATTERNS:
        if pattern.search(cleaned):
            flagged = True
            cleaned = pattern.sub(" ", cleaned, count=1)
    if flagged and ":" in cleaned:
        cleaned = cleaned.rsplit(":", 1)[-1]
    return _normalize_query(cleaned)


# Local transcription of the frozen temporal regexes (freshness.py /
# pipeline.py) for the as-of coverage-gate model.
_AS_OF_RE = re.compile(
    r"\bas of\s+(?:the\s+)?(?:end of\s+)?(\d{4}|[A-Z][a-z]+ \d{1,2},? "
    r"\d{4}|\w+ \d{4})\b", re.IGNORECASE)
_QUESTION_FRAME_RE = re.compile(
    r"\b(?:which|what|where|when|who|whose|why|how)\b", re.IGNORECASE)


def _coverage_query(q: str) -> str:
    """Mirror of the frozen _as_of_coverage_query: for any 'as of <date>'
    query the frame (the as-of phrase and question-function words) is
    stripped before coverage measurement."""
    if not _AS_OF_RE.search(q):
        return q
    text = _AS_OF_RE.sub(" ", q)
    text = _QUESTION_FRAME_RE.sub(" ", text)
    return _normalize_query(text)

MIN_COVERAGE = 0.60


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP]


def _normalize_query(q: str) -> str:
    return re.sub(r"\s+", " ", q).rstrip("?!. ")


def _content_terms(query: str) -> list[str]:
    return [t for t in _tokenize(_normalize_query(query)) if len(t) > 3]


def _coverage(terms: list[str], span_tokens: set[str]) -> float:
    if not terms:
        return 1.0
    covered = sum(1 for t in terms if t in span_tokens)
    return covered / len(terms)


def _capitalized_entities(query: str) -> list[str]:
    out = []
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9'-]*", query):
        if raw[0].isupper():
            low = raw.lower()
            if low not in _CAP_FRAMEWORDS and low not in out:
                out.append(low)
    return out


_CURRENT_CUE = re.compile(
    r"\b(current|currently|today|now|right now|this week|this month|"
    r"this year|this quarter|so far|at present|as we speak|live)\b",
    re.IGNORECASE)
_AS_OF = re.compile(r"\bas of\b", re.IGNORECASE)

STATUS = {"ANSWER", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE",
          "ROUTE_WEB_RESEARCH"}
MODES = {"retrieval", "answer"}
DOMAINS = {"geography", "government_civics", "culture", "history",
           "biography", "literature", "arts", "education_reference",
           "technology_history", "economics", "computing",
           "natural_world"}

# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

FAILURES: list[str] = []
WARNINGS: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


# ---------------------------------------------------------------------------
# A. corpus integrity
# ---------------------------------------------------------------------------

sources = [json.loads(l) for l in
           (HOLDOUT / "sources.jsonl").read_text(encoding="utf-8")
           .splitlines() if l.strip()]
chunks = [json.loads(l) for l in
          (HOLDOUT / "chunks.jsonl").read_text(encoding="utf-8")
          .splitlines() if l.strip()]
manifest = json.loads((HOLDOUT / "corpus_manifest.json")
                      .read_text(encoding="utf-8"))
world = [json.loads(l) for l in
         (HOLDOUT / "world.jsonl").read_text(encoding="utf-8")
         .splitlines() if l.strip()]

SRC_IDS = {s["source_id"] for s in sources}
CHUNK_IDS = [c["chunk_id"] for c in chunks]
CHUNK_BY_ID = {c["chunk_id"]: c for c in chunks}
FACTS: dict[tuple[str, str], str] = {}
for r in world:
    if r["type"] == "WorldFact":
        # First occurrence wins: canonical facts are registered in the
        # entity sections; the conflict loop later adds a second fact with
        # the alt value under the same (subject, predicate).
        FACTS.setdefault((r["subject"], r["predicate"]), r["object"])
RELATIONS = {(r["subject"], r["predicate"]): r["object"]
             for r in world if r["type"] == "WorldRelation"}
FACTS.update(RELATIONS)  # author/painter/inventor links live as relations
# Declared conflict rows carry entity/predicate/class (world.jsonl
# WorldConflict records only carry ids and values).
CONFLICTS = W.CONFLICTS

if len(CHUNK_IDS) != len(set(CHUNK_IDS)):
    fail("duplicate chunk ids in chunks.jsonl")
if len(SRC_IDS) != len(sources):
    fail("duplicate source ids in sources.jsonl")
for c in chunks:
    if not c["chunk_id"].startswith("gk-"):
        fail(f"chunk id missing gk- prefix: {c['chunk_id']}")
    if c["source_id"] not in SRC_IDS:
        fail(f"chunk {c['chunk_id']} references unknown source")
for s in sources:
    if not s["source_id"].startswith("gk-"):
        fail(f"source id missing gk- prefix: {s['source_id']}")
# ordinal ordering within each source
_by_src: dict[str, list[int]] = {}
for c in chunks:
    ordinal = int(c["chunk_id"].rsplit(":", 1)[1])
    _by_src.setdefault(c["source_id"], []).append(ordinal)
for src, ordinals in _by_src.items():
    if ordinals != sorted(ordinals):
        fail(f"chunk ordinals not ascending in {src}")
# chunk text checksum agreement (sha256 of text) if manifest lists files
if "file_checksums" in manifest:
    for rel, digest in manifest["file_checksums"].items():
        path = HOLDOUT / rel
        if not path.exists():
            fail(f"manifest lists missing file {rel}")
            continue
        import hashlib
        actual = hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if actual != digest:
            fail(f"manifest checksum mismatch for {rel}")

# ---------------------------------------------------------------------------
# B. suite schema
# ---------------------------------------------------------------------------

suites: dict[str, list[dict]] = {}
for path in sorted(SUITES_DIR.glob("*/holdout.jsonl")):
    name = path.parent.name
    rows = [json.loads(l) for l in
            path.read_text(encoding="utf-8").splitlines() if l.strip()]
    suites[name] = rows

all_ids: set[str] = set()
all_queries: dict[str, str] = {}  # query -> first case_id
for name, rows in suites.items():
    for row in rows:
        cid = row.get("case_id")
        if not cid:
            fail(f"{name}: row missing case_id")
        elif cid in all_ids:
            fail(f"duplicate case_id across suites: {cid}")
        all_ids.add(cid)
        for key in ("category", "mode", "request", "gold"):
            if key not in row:
                fail(f"{cid}: missing field {key}")
        query = (row.get("request") or {}).get("query")
        if not query or not query.strip():
            fail(f"{cid}: empty query")
        else:
            owner = all_queries.setdefault(query, cid)
            if owner != cid:
                warn(f"query duplicated within T21R2: {query!r} "
                     f"({owner} / {cid})")
        gold = row.get("gold") or {}
        status = gold.get("expect_status")
        if status not in STATUS:
            fail(f"{cid}: bad expect_status {status!r}")
        mode = row.get("mode")
        if mode not in MODES:
            fail(f"{cid}: bad mode {mode!r}")
        if "expect_answer_contains" in gold and \
                not isinstance(gold["expect_answer_contains"], list):
            fail(f"{cid}: expect_answer_contains must be a list")
        if status == "ANSWER" and mode == "answer" and \
                not gold.get("expect_answer_contains"):
            fail(f"{cid}: answer-mode ANSWER row without "
                 f"expect_answer_contains")
        if mode == "retrieval" and not gold.get("gold_chunk_id"):
            fail(f"{cid}: retrieval row without gold_chunk_id")
        if gold.get("expect_answer_contains") and status != "ANSWER":
            fail(f"{cid}: expect_answer_contains on non-ANSWER row")

# ---------------------------------------------------------------------------
# C. grounding: gold chunk existence, values in chunk text and world
# ---------------------------------------------------------------------------

_BRIDGE_VALUE_RE = re.compile(r"^[A-Z][a-z]+ [A-Z][a-z]+$")

for name, rows in suites.items():
    for row in rows:
        cid, gold = row["case_id"], row["gold"]
        gcid = gold.get("gold_chunk_id")
        if gcid and gcid not in CHUNK_BY_ID:
            fail(f"{cid}: gold chunk id not in corpus: {gcid}")
            continue
        rs = gold.get("required_sources") or []
        for s in rs:
            if s not in SRC_IDS:
                fail(f"{cid}: required source not in corpus: {s}")
        contains = gold.get("expect_answer_contains") or []
        two_hop = len(rs) >= 2
        if gcid:
            text = CHUNK_BY_ID[gcid]["text"].lower()
            meta = CHUNK_BY_ID[gcid]["metadata"]
            fe, fa = meta.get("fact_entity"), meta.get("fact_attribute")
            if two_hop:
                # Two-hop bridge rows: the gold chunk is the hop-1 creator
                # chunk; the answer value comes from the hop-2 birthplace
                # chunk of that creator.
                creator = None
                if fe and fa:
                    creator = FACTS.get((fe, fa))
                    if creator is None:
                        fail(f"{cid}: gold chunk fact ({fe}, {fa}) missing "
                             f"from world")
                    elif not _BRIDGE_VALUE_RE.match(creator):
                        fail(f"{cid}: creator value {creator!r} does not "
                             f"match the frozen bridge pattern")
                if creator is not None:
                    bp = FACTS.get((creator, "birthplace"))
                    if bp is None:
                        fail(f"{cid}: no birthplace fact for {creator!r}")
                    else:
                        for v in contains:
                            if v.lower() != bp.lower():
                                fail(f"{cid}: gold value {v!r} != "
                                     f"birthplace {bp!r}")
                        bp_chunks = [c for c in chunks
                                     if c["metadata"].get("fact_entity")
                                     == creator
                                     and c["metadata"].get(
                                         "fact_attribute") == "birthplace"
                                     and not any(
                                         m in c["section"]
                                         for m in (" (record)",
                                                   " (restated)",
                                                   " (conflict a)",
                                                   " (conflict b)",
                                                   " (alt)", " (draft)"))]
                        if not bp_chunks:
                            fail(f"{cid}: no birthplace chunk for "
                                 f"{creator!r}")
                        elif len(rs) == 2:
                            hop2_src = bp_chunks[0]["source_id"]
                            if rs[1] != hop2_src:
                                fail(f"{cid}: required_sources[1] {rs[1]} "
                                     f"!= birthplace chunk source "
                                     f"{hop2_src}")
            else:
                for v in contains:
                    if v.lower() not in text:
                        fail(f"{cid}: gold value {v!r} not in gold chunk "
                             f"text {gcid}")
                if fe and fa:
                    world_v = FACTS.get((fe, fa))
                    if world_v is None:
                        fail(f"{cid}: gold chunk fact ({fe}, {fa}) missing "
                             f"from world")
                    elif contains:
                        if not any(v.lower() == world_v.lower()
                                   or v.lower() in world_v.lower()
                                   for v in contains):
                            fail(f"{cid}: gold contains {contains} "
                                 f"disagrees with world fact {world_v!r}")
        # non-gold ANSWER rows must be abstention/absent classes, i.e. an
        # expected abstention status; ANSWER rows without gold chunk are
        # only allowed for route/abstain statuses
        if gold.get("expect_status") == "ANSWER" and not gcid and \
                row["mode"] == "answer":
            fail(f"{cid}: ANSWER answer-mode row without gold_chunk_id")
        if gold.get("require_citations") and \
                gold.get("expect_status") != "ANSWER":
            fail(f"{cid}: require_citations on non-ANSWER row")

# ---------------------------------------------------------------------------
# D/E. temporal + conflict consistency
# ---------------------------------------------------------------------------

conflict_by_entity_attr = {(c["entity"], c["predicate"]): c
                           for c in CONFLICTS}
unresolved = {c["entity"] for c in CONFLICTS
              if c["class"] == "EQUAL_AUTHORITY_UNRESOLVED"}
authority = {(c["entity"], c["predicate"]): c for c in CONFLICTS
             if c["class"] == "AUTHORITY_RESOLVABLE"}
freshness = {(c["entity"], c["predicate"]): c for c in CONFLICTS
             if c["class"] == "FRESHNESS_RESOLVABLE"}

for name, rows in suites.items():
    for row in rows:
        cid, cat, gold = row["case_id"], row["category"], row["gold"]
        q = row["request"]["query"]
        if cat == "explicit_current" and not _CURRENT_CUE.search(q):
            fail(f"{cid}: explicit_current row without current cue")
        if cat == "historical_as_of" and not _AS_OF.search(q):
            fail(f"{cid}: historical_as_of row without 'as of'")
        if cat == "future_as_of":
            if not _AS_OF.search(q) or "2031" not in q:
                fail(f"{cid}: future_as_of row without 'as of 2031'")
        if cat == "snapshot_too_old":
            if not _AS_OF.search(q) or "2019" not in q:
                fail(f"{cid}: snapshot_too_old row without 'as of 2019'")
        if cat in ("snapshot_answer", "slow_changing_reference") and \
                (_CURRENT_CUE.search(q) or _AS_OF.search(q)):
            fail(f"{cid}: {cat} row carries a temporal cue: {q!r}")
        if cat in ("explicit_current",) and \
                gold["expect_status"] != "ROUTE_WEB_RESEARCH":
            fail(f"{cid}: explicit_current must expect ROUTE_WEB_RESEARCH")
        if cat in ("historical_as_of", "snapshot_answer", "future_as_of",
                   "snapshot_too_old", "slow_changing_reference") and \
                gold["expect_status"] != "ANSWER":
            fail(f"{cid}: {cat} must expect ANSWER")
        if cat == "unresolved_conflict":
            ent = re.search(r"town of ([A-Z][a-z]+)|was ([A-Z][a-z]+) "
                            r"established", q)
            m = re.search(r"\b([A-Z][a-z]+)\b", q.replace(
                "The ", "").replace("In ", "").replace("What ", "")
                .replace("When ", "").replace("Which ", ""))
            ent_name = None
            for town in unresolved:
                if re.search(rf"\b{re.escape(town)}\b", q):
                    ent_name = town
                    break
            if ent_name is None:
                fail(f"{cid}: unresolved row without a conflict town")
            elif gold["expect_status"] != "CONFLICTING_EVIDENCE":
                fail(f"{cid}: unresolved row must expect CONFLICTING")
        if cat == "authority_resolvable_conflict" and \
                gold["expect_status"] != "ANSWER":
            fail(f"{cid}: authority-resolvable must expect ANSWER")
        if cat == "freshness_resolvable_conflict" and \
                gold["expect_status"] != "ANSWER":
            fail(f"{cid}: freshness-resolvable must expect ANSWER")

# ---------------------------------------------------------------------------
# F. static retrieval proxies (selected-span gate model)
#
# The frozen pipeline measures the coverage gate over the spans it SELECTS
# for synthesis: the single top-1 chunk (or the authority winner), plus the
# hop-2 birthplace chunk on the two-hop bridge path. It never unions all
# retrieved items for the gate. The proxies below mirror exactly that.
# ---------------------------------------------------------------------------

CHUNK_TOKENS = {c["chunk_id"]: set(_tokenize(c["text"])) for c in chunks}


def _birthplace_chunk_tokens(creator: str | None) -> set[str]:
    if not creator:
        return set()
    for c in chunks:
        m = c["metadata"]
        if m.get("fact_entity") == creator and \
                m.get("fact_attribute") == "birthplace" and \
                not any(x in c["section"] for x in (" (record)",
                                                    " (restated)",
                                                    " (conflict a)",
                                                    " (conflict b)",
                                                    " (alt)", " (draft)")):
            return CHUNK_TOKENS[c["chunk_id"]]
    return set()


for name, rows in suites.items():
    for row in rows:
        cid, gold = row["case_id"], row["gold"]
        q = _effective_query(row["request"]["query"])
        gcid = gold.get("gold_chunk_id")
        # Coverage terms are measured on the as-of-stripped coverage query;
        # the entity gate sees the full effective query.
        cov_terms = _content_terms(_coverage_query(q))
        terms = cov_terms
        caps = _capitalized_entities(q)
        two_hop = len(gold.get("required_sources") or []) >= 2
        if gold["expect_status"] == "ANSWER" and gcid:
            gtokens = CHUNK_TOKENS[gcid]
            if two_hop:
                creator = None
                meta = CHUNK_BY_ID[gcid]["metadata"]
                creator = FACTS.get(
                    (meta.get("fact_entity"), meta.get("fact_attribute")))
                gtokens = gtokens | _birthplace_chunk_tokens(creator)
            cov = _coverage(terms, gtokens)
            if cov < MIN_COVERAGE:
                fail(f"{cid}: ANSWER row coverage {cov:.2f} < "
                     f"{MIN_COVERAGE} over selected spans")
            missing = [c for c in caps if c not in gtokens]
            if missing:
                # The entity gate runs on selected[0] (= the gold chunk);
                # any capitalized query term missing from it fails the gate.
                fail(f"{cid}: entity gate would fail: {missing} not in "
                     f"gold chunk text")
        if gold["expect_status"] == "INSUFFICIENT_EVIDENCE":
            # Guaranteed-abstain: for EVERY chunk, either its coverage is
            # below the gate or it fails the entity gate (a required
            # capitalized query token is absent from its text). If any
            # chunk could pass both gates AND plausibly tops retrieval,
            # the row may be answerable — flag it.
            could = []
            for ck, tokens in CHUNK_TOKENS.items():
                if _coverage(terms, tokens) >= MIN_COVERAGE and \
                        all(c in tokens for c in caps):
                    could.append(ck)
            if could:
                fail(f"{cid}: INSUFFICIENT row may be answerable via "
                     f"{len(could)} chunks (e.g. {could[0]})")

# ---------------------------------------------------------------------------
# G. uniqueness vs T21 and T21R
# ---------------------------------------------------------------------------

old_queries: set[str] = set()
for base in (ROOT / "evaluations" / "t21", ROOT / "evaluations" / "t21r"):
    for path in sorted(base.glob("suites/**/holdout.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                q = (row.get("request") or {}).get("query")
                if q:
                    old_queries.add(q.strip().lower())

overlap = {q for q in (r["request"]["query"].strip().lower()
                       for rows in suites.values() for r in rows)
           if q in old_queries}
if overlap:
    fail(f"exact query overlap vs T21/T21R: {len(overlap)}")

# near-duplicate similarity (audit only): max Jaccard over token sets
old_token_sets = []
for base in (ROOT / "evaluations" / "t21", ROOT / "evaluations" / "t21r"):
    for path in sorted(base.glob("suites/**/holdout.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                q = (row.get("request") or {}).get("query")
                if q:
                    old_token_sets.append(set(_tokenize(q)))
max_j = 0.0
max_pair = None
for rows in suites.values():
    for r in rows:
        ts = set(_tokenize(r["request"]["query"]))
        for ot in old_token_sets:
            inter = len(ts & ot)
            if not inter:
                continue
            j = inter / len(ts | ot)
            if j > max_j:
                max_j, max_pair = j, (r["request"]["query"],)
warn(f"max query token-Jaccard vs old holdouts: {max_j:.3f} "
     f"(audit only; exact overlap = {len(overlap)})")

# old attack-string overlap: injection directives and fake ids
old_texts: set[str] = set()
for base in (ROOT / "evaluations" / "t21", ROOT / "evaluations" / "t21r"):
    for path in sorted(base.glob("suites/**/holdout.jsonl")):
        old_texts.update(path.read_text(encoding="utf-8").splitlines())
for rows in suites.values():
    for r in rows:
        if json.dumps(r, sort_keys=True) in old_texts:
            fail(f"{r['case_id']}: verbatim row overlap vs old holdouts")

# ---------------------------------------------------------------------------
# H. contract floors
# ---------------------------------------------------------------------------

contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
mins = contract["suite_minimums"]
for name, m in mins.items():
    if name not in suites:
        fail(f"missing suite {name}")
    elif len(suites[name]) < m:
        fail(f"suite {name}: {len(suites[name])} < minimum {m}")
total = sum(len(v) for v in suites.values())
if total < contract["minimum_holdout_total"]:
    fail(f"total holdout rows {total} < {contract['minimum_holdout_total']}")

temporal = suites.get("mango-t21r2-temporal-holdout-v1", [])
tc: dict[str, int] = {}
for r in temporal:
    tc[r["category"]] = tc.get(r["category"], 0) + 1
for cat, m in contract["temporal_composition_minimums"].items():
    if tc.get(cat, 0) < m:
        fail(f"temporal composition {cat}: {tc.get(cat, 0)} < {m}")

conflict = suites.get("mango-t21r2-conflict-abstention-holdout-v1", [])
cc: dict[str, int] = {}
for r in conflict:
    cc[r["category"]] = cc.get(r["category"], 0) + 1
cmin = contract["conflict_composition_minimums"]
for key, cat in (("authority_resolvable",
                  "authority_resolvable_conflict"),
                 ("freshness_resolvable",
                  "freshness_resolvable_conflict"),
                 ("unresolved_equal_authority", "unresolved_conflict"),
                 ("near_duplicate_false_conflict",
                  "near_duplicate_false_conflict")):
    if cc.get(cat, 0) < cmin[key]:
        fail(f"conflict composition {cat}: {cc.get(cat, 0)} < {cmin[key]}")

mp = suites.get("mango-t21r2-multihop-holdout-v1", [])
two_src = sum(1 for r in mp
              if len(r["gold"].get("required_sources") or []) >= 2)
if mp and two_src / len(mp) < contract["multihop_rules"][
        "min_share_two_distinct_sources"]:
    fail(f"multihop two-source share {two_src / len(mp):.2f} below floor")
if len(mp) < contract["multihop_rules"]["min_cases"]:
    fail(f"multihop cases {len(mp)} < {contract['multihop_rules']['min_cases']}")

# non-ASCII audit (data hygiene)
non_ascii = [c["chunk_id"] for c in chunks
             if any(ord(ch) > 127 for ch in c["text"])]
if non_ascii:
    warn(f"{len(non_ascii)} chunks contain non-ASCII text")

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

report = {
    "status": "PASS" if not FAILURES else "FAIL",
    "suites": {name: len(rows) for name, rows in sorted(suites.items())},
    "total_rows": total,
    "failures": FAILURES,
    "warnings": WARNINGS,
}
out = ROOT / "evaluations" / "t21r2" / "static_gold_audit.json"
out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
               encoding="utf-8", newline="\n")
print(json.dumps({"status": report["status"],
                  "failures": len(FAILURES),
                  "warnings": len(WARNINGS),
                  "total_rows": total,
                  "out": out.as_posix()}, indent=2))
for f in FAILURES[:40]:
    print("FAIL:", f)
for w in WARNINGS[:20]:
    print("warn:", w)
return_code = 0 if not FAILURES else 1
sys.exit(return_code)