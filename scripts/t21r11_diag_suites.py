"""T21R11 open diagnostic suites — DEV/VALIDATION row generation (§10-§17).

Tracks (one per failed T21R10 mechanism family, aggregate-audit-derived):
  A  retrieval ranking (Recall@5/10, MRR, nDCG@5)          [source diversity]
  B  multi-hop path resolution stage probes                [multi_hop]
  C  cross-domain single-hop synthesis + out-of-ontology   [crossdomain cats]
  D  conflict detect -> scope -> resolve chain             [conflict_detection]
  E  abstention decisions (precision/recall of NOT answering) [over-abstention]
  F  citation discipline (resolvable/valid/precise/coverage) [citations]

Independence controls (§13):
  - DEV and VALIDATION query DISJOINT entity pools (world registry pools).
  - DEV and VALIDATION use different question frames for the same
    grammatical contract (the frozen runtime grammar is runtime code, not
    holdout content).
  - No row text is derived from any T21R10 blind artifact; the world's
    coinages are asserted disjoint from the T21 fixture tables.

The VALIDATION split is frozen on first build: validation_freeze.json
records the sha256 of validation_suites.jsonl; later builds must reproduce
it byte-for-byte or refuse to run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import t21r11_diag_world as world  # noqa: E402

OUT_DIR = world.OUT_DIR
DEV_PATH = OUT_DIR / "dev_suites.jsonl"
VAL_PATH = OUT_DIR / "validation_suites.jsonl"
FREEZE_PATH = OUT_DIR / "validation_freeze.json"

SPLIT_ORDER = ("dev", "validation")

# Question frames per split (different surfaces, same frozen grammar).
FRAMES = {
    "dev": {
        "attr": "What is the {attr} of {entity}?",
        "attr_are": "What are the {attr} of {entity}?",
        "attr_who": "Who is the {attr} of {entity}?",
        "who_wrote": "Who wrote {entity}?",
        "year_when": "When was {entity} {verb}?",
        "chain": "What is the {terminal} of the {bridge} of {entity}?",
        "born_chain": "The {bridge} of {entity} was born in which town?",
        "path_missing_bridge": "What is the {terminal} of the {bridge} of "
                               "{entity}?",
        "modifier": "According to the records, what is the {attr} of "
                    "{entity}?",
    },
    "validation": {
        "attr": "Tell me the {attr} of {entity}.",
        "attr_are": "Tell me the {attr} of {entity}.",
        "attr_who": "Name the {attr} of {entity}.",
        "who_wrote": "Tell me who wrote {entity}.",
        "year_when": "Tell me when {entity} was {verb}.",
        "chain": "Tell me the {terminal} of the {bridge} of {entity}.",
        "born_chain": "The {bridge} of {entity} was born in which town?",
        "path_missing_bridge": "Tell me the {terminal} of the {bridge} of "
                               "{entity}.",
        "modifier": "According to the records, tell me the {attr} of "
                    "{entity}.",
    },
}

# attribute -> (question noun, optional who-form, year verb form)
ATTR_PHRASES = {
    "country": ("country", False, None),
    "founding year": ("founding year", False, "established"),
    "river": ("river", False, None),
    "mayor": ("mayor", True, None),
    "landmark": ("landmark", False, None),
    "region": ("region", False, None),
    "field of study": ("field of study", False, None),
    "birth year": ("birth year", False, None),
    "birthplace": ("birthplace", False, None),
    "notable work": ("notable work", False, None),
    "author": ("author", True, None),
    "genre": ("genre", False, None),
    "publication year": ("publication year", False, "published"),
    "subject": ("subject", False, None),
    "location": ("location", False, None),
    "inventor": ("inventor", True, None),
    "introduction year": ("introduction year", False, "introduced"),
    "property": ("property", False, None),
    "discovery year": ("discovery year", False, "discovered"),
    "definition": ("definition", False, None),
    "signing year": ("signing year", False, "signed"),
    "emblem": ("emblem", False, None),
    "seats": ("seats", False, None),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _attr_query(frame: dict, attribute: str, entity: str) -> str:
    phrase, who_form, verb = ATTR_PHRASES[attribute]
    if attribute == "seats" and "attr_are" in frame:
        return frame["attr_are"].format(attr=phrase, entity=entity)
    if verb is not None and attribute in ("founding year", "signing year"):
        return frame["year_when"].format(entity=entity, verb=verb)
    if attribute in ("publication year", "introduction year",
                     "discovery year"):
        return frame["attr"].format(attr=phrase, entity=entity)
    if who_form:
        return frame["attr_who"].format(attr=phrase, entity=entity)
    return frame["attr"].format(attr=phrase, entity=entity)


class SuiteBuilder:
    """Generates DEV/VALIDATION rows from the world registry."""

    def __init__(self, world_index: dict) -> None:
        self.index = world_index
        self.entities = world_index["entities"]
        self.pool_entities: dict[str, list[dict]] = {
            "dev": [], "validation": []}
        for entry in self.entities.values():
            if entry["pool"] in ("dev", "validation"):
                self.pool_entities[entry["pool"]].append(entry)
        self.source_domains = world_index["source_domains"]
        self.rows: list[dict] = []

    # -- helpers ------------------------------------------------------------
    def _by_kind(self, split: str, kind: str) -> list[dict]:
        return [e for e in self.pool_entities[split] if e["kind"] == kind]

    def _entry(self, name: str) -> dict:
        return self.entities[name]

    def _add(self, *, split: str, track: str, family: str, mode: str,
             query: str, expect_status: str, expect_contains: list[str] |
             None = None, gold_chunk_id: str | None = None,
             required_sources: list[str] | None = None,
             required_domains: list[str] | None = None,
             probes: dict | None = None, require_citations: bool = False,
             stress: bool = False, note: str = "") -> None:
        n = len(self.rows) + 1
        self.rows.append({
            "case_id": f"r11diag-{split}-{track.lower()}-{n:04d}",
            "split": split, "track": track, "family": family,
            "mode": mode, "query": query,
            "gold": {
                "expect_status": expect_status,
                "expect_answer_contains": expect_contains or [],
                "gold_chunk_id": gold_chunk_id,
                "required_sources": required_sources or [],
                "required_domains": required_domains or [],
                "require_citations": require_citations,
            },
            "probes": probes or {},
            "stress": stress, "note": note,
        })

    def _domains_of(self, source_keys: list[str]) -> list[str]:
        domains: set[str] = set()
        for key in source_keys:
            domains.update(self.source_domains.get(key, []))
        return sorted(domains)

    # -- Track A: retrieval ranking -----------------------------------------
    def track_a(self, split: str) -> None:
        frame = FRAMES[split]
        towns_ = self._by_kind(split, "town")[:5]
        attr_cycle = ("country", "river", "mayor", "landmark", "region")
        for i, town in enumerate(towns_):
            attr = attr_cycle[i % len(attr_cycle)]
            fact = town["facts"][attr]
            query = _attr_query(frame, attr, town["entity"])
            self._add(split=split, track="A", family="a_direct",
                      mode="retrieval", query=query,
                      expect_status="ANSWER",
                      gold_chunk_id=fact["chunk_id"],
                      probes={"dup_chunk_id": self._dup_chunk(
                          town["entity"], attr)})
        # same-entity sibling-attribute discrimination
        for town in self._by_kind(split, "town")[5:8]:
            fact = town["facts"]["region"]
            query = _attr_query(frame, "region", town["entity"])
            self._add(split=split, track="A", family="a_near_miss_attr",
                      mode="retrieval", query=query, expect_status="ANSWER",
                      gold_chunk_id=fact["chunk_id"])
        # multisource duplication: canonical + carrier both relevant
        for name in self._dup_entity_names(split, "town", "country"):
            entry = self._entry(name)
            fact = entry["facts"]["country"]
            query = _attr_query(frame, "country", name)
            self._add(split=split, track="A", family="a_multisource_dup",
                      mode="retrieval", query=query, expect_status="ANSWER",
                      gold_chunk_id=fact["chunk_id"],
                      probes={"dup_chunk_id": self._dup_chunk(
                          name, "country")})
        # modifier-token robustness
        for scholar in self._by_kind(split, "person")[:2]:
            fact = scholar["facts"]["birthplace"]
            query = frame["modifier"].format(attr="birthplace",
                                             entity=scholar["entity"])
            self._add(split=split, track="A", family="a_modifier_tokens",
                      mode="retrieval", query=query, expect_status="ANSWER",
                      gold_chunk_id=fact["chunk_id"])

    def _dup_entry(self, entity: str, attribute: str) -> dict | None:
        for dup in self.index["duplicates"]:
            if dup["entity"] == entity and dup["attribute"] == attribute:
                return dup
        return None

    def _dup_chunk(self, entity: str, attribute: str) -> str | None:
        dup = self._dup_entry(entity, attribute)
        return dup["chunk_id"] if dup else None

    def _near_pairs(self, split: str) -> list[tuple[str, str]]:
        pairs = []
        for q_idx, c_idx in world.NEAR_NAME_PAIRS[split]:
            query_name = world._town_name(q_idx)
            decoy_name = world._town_name(c_idx)
            assert query_name.split()[0] == decoy_name.split()[0], \
                f"near-name pair lost shared token: {query_name} / " \
                f"{decoy_name}"
            assert query_name in self.entities and decoy_name in self.entities
            pairs.append((query_name, decoy_name))
        return pairs

    def _dup_entity_names(self, split: str, kind: str,
                          attribute: str | None = None) -> list[str]:
        names = []
        for dup in self.index["duplicates"]:
            if attribute is not None and dup["attribute"] != attribute:
                continue
            entry = self.entities.get(dup["entity"])
            if entry and entry["pool"] == split and entry["kind"] == kind:
                names.append(dup["entity"])
        return sorted(set(names))

    # -- Track B: multi-hop path resolution ----------------------------------
    def _chain_rows(self, split: str, entries: list[dict], bridge_attr: str,
                    terminal_attr: str, family: str, count: int,
                    terminal_value_getter) -> None:
        frame = FRAMES[split]
        for entry in entries[:count]:
            bridge_value = entry["facts"][bridge_attr]["value"]
            terminal = terminal_value_getter(bridge_value)
            query = frame["chain"].format(
                terminal=ATTR_PHRASES[terminal_attr][0],
                bridge=bridge_attr, entity=entry["entity"])
            hop1 = entry["facts"][bridge_attr]["chunk_id"]
            hop2 = self.entities[bridge_value]["facts"][terminal_attr][
                "chunk_id"]
            self._add(
                split=split, track="B", family=family, mode="answer",
                query=query, expect_status="ANSWER",
                expect_contains=[self.entities[bridge_value]["facts"][
                    terminal_attr]["value"]],
                gold_chunk_id=hop2,
                required_sources=sorted({
                    (self.index["entities"][entry["entity"]]["facts"][
                        bridge_attr]["source_key"]),
                    self.entities[bridge_value]["facts"][terminal_attr][
                        "source_key"]}),
                probes={"gold_hop1_chunk_id": hop1,
                        "gold_hop2_chunk_id": hop2,
                        "bridge_entity": bridge_value,
                        "terminal_attr": terminal_attr},
                require_citations=True, note="two-hop chain")

    def track_b(self, split: str) -> None:
        works_ = self._by_kind(split, "work")
        techs_ = self._by_kind(split, "technology")
        insts = self._by_kind(split, "institution")
        phenos = self._by_kind(split, "phenomenon")
        scholars = self._by_kind(split, "person")

        def birthplace_of(name: str) -> str:
            return self.entities[name]["facts"]["birthplace"]["value"]

        def country_of_town(name: str) -> str:
            return self.entities[name]["facts"]["country"]["value"]

        self._chain_rows(split, works_, "author", "birthplace",
                         "b_chain_work_author_birthplace", 3, birthplace_of)
        self._chain_rows(split, techs_, "inventor", "field of study",
                         "b_chain_tech_inventor_field", 3,
                         lambda v: self.entities[v]["facts"][
                             "field of study"]["value"])
        self._chain_rows(split, insts, "location", "country",
                         "b_chain_inst_location_country", 3,
                         country_of_town)
        self._chain_rows(split, phenos, "location", "country",
                         "b_chain_pheno_location_country", 3, country_of_town)
        self._chain_rows(split, scholars, "birthplace", "country",
                         "b_chain_scholar_birthplace_country", 3,
                         country_of_town)

        # missing bridge relation (composer absent from the ontology)
        frame = FRAMES[split]
        work = works_[0]
        query = frame["path_missing_bridge"].format(
            terminal="birthplace", bridge="composer", entity=work["entity"])
        self._add(split=split, track="B", family="b_missing_bridge",
                  mode="answer", query=query, expect_status="INSUFFICIENT_EVIDENCE",
                  probes={"gold_hop1_chunk_id":
                          work["facts"]["author"]["chunk_id"]})

        # missing terminal (bridge value has no birthplace facts)
        town = self._by_kind(split, "town")[0]
        query = frame["chain"].format(terminal="birthplace", bridge="mayor",
                                      entity=town["entity"])
        self._add(split=split, track="B", family="b_missing_terminal",
                  mode="answer", query=query, expect_status="INSUFFICIENT_EVIDENCE",
                  probes={"gold_hop1_chunk_id":
                          town["facts"]["mayor"]["chunk_id"]})

        # out-of-ontology: leader -> birth (LED_BY absent from the frozen
        # ontology; documented baseline gap)
        for event in self._by_kind(split, "event")[:2]:
            leader = event["facts"]["led by"]["value"]
            query = frame["born_chain"].format(bridge="leader",
                                               entity=event["entity"])
            self._add(
                split=split, track="B", family="b_out_of_ontology_leader",
                mode="answer", query=query, expect_status="ANSWER",
                expect_contains=[leader],
                gold_chunk_id=self.entities[leader]["facts"]["birthplace"][
                    "chunk_id"],
                probes={"gold_hop1_chunk_id":
                        event["facts"]["led by"]["chunk_id"]},
                stress=False,
                note="LED_BY relation absent from frozen ontology")

        # frame-variant two-hop (trailing predicate defeats nominal parse;
        # documented over-abstention mechanism)
        for work in works_[1:3]:
            author = work["facts"]["author"]["value"]
            query = (f"The birthplace of the author of {work['entity']} is "
                     f"in which town?")
            self._add(
                split=split, track="B", family="b_frame_variant",
                mode="answer", query=query, expect_status="ANSWER",
                expect_contains=[self.entities[author]["facts"][
                    "birthplace"]["value"]],
                gold_chunk_id=self.entities[author]["facts"]["birthplace"][
                    "chunk_id"],
                probes={"gold_hop1_chunk_id":
                        work["facts"]["author"]["chunk_id"]},
                stress=True,
                note="trailing predicate defeats parse_relation_path")

    # -- Track C: cross-domain single-hop + out-of-ontology -------------------
    def track_c(self, split: str) -> None:
        frame = FRAMES[split]
        for term in self._by_kind(split, "econ_term"):
            fact = term["facts"]["definition"]
            self._add(
                split=split, track="C", family="c_econ_definition",
                mode="answer", query=_attr_query(frame, "definition",
                                                 term["entity"]),
                expect_status="ANSWER",
                expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_domains=self._domains_of([fact["source_key"]]),
                require_citations=True)
        for charter in self._by_kind(split, "civic_charter")[:2]:
            fact = charter["facts"]["signing year"]
            self._add(
                split=split, track="C", family="c_civics_signing",
                mode="answer", query=_attr_query(frame, "signing year",
                                                 charter["entity"]),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_domains=self._domains_of([fact["source_key"]]),
                require_citations=True)
        for charter in self._by_kind(split, "civic_charter")[2:4]:
            fact = charter["facts"]["emblem"]
            self._add(
                split=split, track="C", family="c_civics_emblem",
                mode="answer", query=_attr_query(frame, "emblem",
                                                 charter["entity"]),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_domains=self._domains_of([fact["source_key"]]),
                require_citations=True)
        for tech in self._by_kind(split, "technology")[:2]:
            fact = tech["facts"]["property"]
            self._add(
                split=split, track="C", family="c_tech_property",
                mode="answer", query=_attr_query(frame, "property",
                                                 tech["entity"]),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_domains=self._domains_of([fact["source_key"]]),
                require_citations=True)
        for pheno in self._by_kind(split, "phenomenon")[:2]:
            fact = pheno["facts"]["discovery year"]
            self._add(
                split=split, track="C", family="c_natural_discovery",
                mode="answer", query=_attr_query(frame, "discovery year",
                                                 pheno["entity"]),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_domains=self._domains_of([fact["source_key"]]),
                require_citations=True)
        for event in self._by_kind(split, "event")[:2]:
            fact = event["facts"]["signing year"]
            self._add(
                split=split, track="C", family="c_history_signed",
                mode="answer", query=_attr_query(frame, "signing year",
                                                 event["entity"]),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_domains=self._domains_of([fact["source_key"]]),
                require_citations=True)
        for event in self._by_kind(split, "event")[2:4]:
            fact = event["facts"]["location"]
            self._add(
                split=split, track="C", family="c_history_location",
                mode="answer", query=_attr_query(frame, "location",
                                                 event["entity"]),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_domains=self._domains_of([fact["source_key"]]),
                require_citations=True)
        # out-of-ontology single-hop: LED_BY absent from the frozen ontology
        for event in self._by_kind(split, "event"):
            leader = event["facts"]["led by"]["value"]
            query = frame["attr_who"].format(attr="leader",
                                             entity=event["entity"])
            self._add(
                split=split, track="C", family="c_out_of_ontology_led",
                mode="answer", query=query, expect_status="ANSWER",
                expect_contains=[leader],
                gold_chunk_id=event["facts"]["led by"]["chunk_id"],
                probes={"gold_hop1_chunk_id":
                        event["facts"]["led by"]["chunk_id"]},
                note="LED_BY relation absent from frozen ontology")

        # literature family: the official T21R10 per-category audit showed
        # literature at 0.0 while geography/civics/technology passed at 1.0;
        # this family measures the literature relation space on open
        # material (author in both phrasings, genre, publication year,
        # notable-work direction).
        for work in self._by_kind(split, "work")[:2]:
            fact = work["facts"]["author"]
            self._add(
                split=split, track="C", family="c_lit_author",
                mode="answer", query=_attr_query(frame, "author",
                                                 work["entity"]),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_domains=self._domains_of([fact["source_key"]]),
                require_citations=True)
        for work in self._by_kind(split, "work")[:2]:
            fact = work["facts"]["author"]
            self._add(
                split=split, track="C", family="c_lit_author_wrote",
                mode="answer",
                query=frame["who_wrote"].format(entity=work["entity"]),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_domains=self._domains_of([fact["source_key"]]),
                require_citations=True)
        for work in self._by_kind(split, "work")[2:4]:
            fact = work["facts"]["genre"]
            self._add(
                split=split, track="C", family="c_lit_genre",
                mode="answer", query=_attr_query(frame, "genre",
                                                 work["entity"]),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_domains=self._domains_of([fact["source_key"]]),
                require_citations=True)
        for work in self._by_kind(split, "work")[2:4]:
            fact = work["facts"]["publication year"]
            self._add(
                split=split, track="C", family="c_lit_pubyear",
                mode="answer", query=_attr_query(frame, "publication year",
                                                 work["entity"]),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_domains=self._domains_of([fact["source_key"]]),
                require_citations=True)
        for person in self._by_kind(split, "person")[:2]:
            fact = person["facts"]["notable work"]
            self._add(
                split=split, track="C", family="c_lit_notable",
                mode="answer", query=_attr_query(frame, "notable work",
                                                 person["entity"]),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_domains=self._domains_of([fact["source_key"]]),
                require_citations=True)

    # -- Track D: conflict machinery ------------------------------------------
    def track_d(self, split: str) -> None:
        frame = FRAMES[split]
        conflict_towns = [e for e in self._by_kind(split, "town")
                          if "conflict_family" in e]
        dev_conflicts = [t for t in self.index["conflict_towns"]
                         if t["pool"] == split]
        by_name = {t["entity"]: t for t in dev_conflicts}

        for name, entry in by_name.items():
            family = entry.get("conflict_family") or ""
            base = entry["facts"]
            if family in ("unresolved_two_source", "unresolved_three_source"):
                query = frame["year_when"].format(
                    entity=name, verb="founded")
                self._add(
                    split=split, track="D", family="d_unresolved_founding",
                    mode="answer", query=query,
                    expect_status="CONFLICTING_EVIDENCE",
                    probes={"canonical_chunk_id":
                            base["founding year"]["chunk_id"],
                            "alt_chunk_ids": [a["chunk_id"] for a in
                                              entry.get("alts", {}).get(
                                                  "founding year", [])]})
            elif family == "resolved_authority":
                query = frame["year_when"].format(entity=name,
                                                  verb="established")
                self._add(
                    split=split, track="D", family="d_resolved_authority",
                    mode="answer", query=query, expect_status="ANSWER",
                    expect_contains=[base["founding year"]["value"]],
                    gold_chunk_id=base["founding year"]["chunk_id"],
                    probes={"canonical_chunk_id":
                            base["founding year"]["chunk_id"],
                            "alt_chunk_ids": [a["chunk_id"] for a in
                                              entry.get("alts", {}).get(
                                                  "founding year", [])]},
                    require_citations=True)
            # mayor conflicts on every conflict town
            query = frame["attr_who"].format(attr="mayor", entity=name)
            unresolved = family != "resolved_authority"
            self._add(
                split=split, track="D",
                family="d_mayor_unresolved" if unresolved
                else "d_mayor_resolved",
                mode="answer", query=query,
                expect_status="CONFLICTING_EVIDENCE" if unresolved
                else "ANSWER",
                expect_contains=[] if unresolved
                else [base["mayor"]["value"]],
                gold_chunk_id=None if unresolved
                else base["mayor"]["chunk_id"],
                probes={"canonical_chunk_id": base["mayor"]["chunk_id"],
                        "alt_chunk_ids": [a["chunk_id"] for a in
                                          entry.get("alts", {}).get(
                                              "mayor", [])]},
                require_citations=not unresolved)
            # partial agreement: same-value river duplicate -> NO_CONFLICT
            query = _attr_query(frame, "river", name)
            self._add(
                split=split, track="D", family="d_partial_agreement",
                mode="answer", query=query, expect_status="ANSWER",
                expect_contains=[base["river"]["value"]],
                gold_chunk_id=base["river"]["chunk_id"],
                probes={"dup_chunk_id": self._dup_chunk(name, "river")},
                require_citations=True)

        # institutions: resolved with the ALT winning
        for inst in [e for e in self.index["conflict_institutions"]
                     if e["pool"] == split]:
            alt = inst["alts"]["founding year"][0]
            query = frame["year_when"].format(entity=inst["entity"],
                                              verb="established")
            self._add(
                split=split, track="D", family="d_resolved_alt_wins",
                mode="answer", query=query, expect_status="ANSWER",
                expect_contains=[alt["value"]],
                gold_chunk_id=alt["chunk_id"],
                probes={"canonical_chunk_id":
                        inst["facts"]["founding year"]["chunk_id"],
                        "alt_chunk_ids": [alt["chunk_id"]]},
                require_citations=True,
                note="PRIMARY_REFERENCE alt outranks INSTITUTIONAL canon")

        for tech in [t for t in self.index["conflict_techs"]
                     if t["pool"] == split]:
            alt = tech["alts"]["introduction year"][0]
            query = frame["year_when"].format(entity=tech["entity"],
                                              verb="introduced")
            self._add(
                split=split, track="D", family="d_resolved_alt_wins",
                mode="answer", query=query, expect_status="ANSWER",
                expect_contains=[alt["value"]],
                gold_chunk_id=alt["chunk_id"],
                probes={"canonical_chunk_id":
                        tech["facts"]["introduction year"]["chunk_id"],
                        "alt_chunk_ids": [alt["chunk_id"]]},
                require_citations=True,
                note="ENCYCLOPEDIC alt outranks ACADEMIC canonical")

        # attribute disagreement: query region while a founding-year
        # conflict co-exists for the same entity (attribute gate must
        # discard it)
        region_towns = [t for t in self._by_kind(split, "town")
                        if "conflict_family" in t and
                        t["conflict_family"] in
                        ("unresolved_two_source",
                         "unresolved_three_source")][:1]
        for town in region_towns:
            query = _attr_query(frame, "region", town["entity"])
            self._add(
                split=split, track="D", family="d_attribute_disagreement",
                mode="answer", query=query, expect_status="ANSWER",
                expect_contains=[town["facts"]["region"]["value"]],
                gold_chunk_id=town["facts"]["region"]["chunk_id"],
                probes={"other_attr_conflict": "founding year"},
                require_citations=True)

        # identity near-name traps (structured binding regression guard)
        for query_name, decoy_name in self._near_pairs(split):
            entry = self._entry(query_name)
            query = frame["attr_who"].format(attr="mayor",
                                             entity=query_name)
            self._add(
                split=split, track="D", family="d_identity_nearname",
                mode="answer", query=query, expect_status="ANSWER",
                expect_contains=[entry["facts"]["mayor"]["value"]],
                gold_chunk_id=entry["facts"]["mayor"]["chunk_id"],
                probes={"decoy_entity": decoy_name},
                require_citations=True)

        # metadata-free contradictory entities (text-fallback stress)
        for name in self.index["text_conflict_entities"][split]:
            query = frame["year_when"].format(entity=name, verb="founded")
            self._add(
                split=split, track="D", family="d_text_fallback_stress",
                mode="answer", query=query,
                expect_status="CONFLICTING_EVIDENCE", stress=True,
                note="no fact metadata in corpus: frozen text-fallback "
                     "path is the only mechanism")

    # -- Track E: abstention decisions ----------------------------------------
    def track_e(self, split: str) -> None:
        frame = FRAMES[split]
        # fully supported
        for entry in self._by_kind(split, "town")[:2]:
            fact = entry["facts"]["country"]
            self._add(
                split=split, track="E", family="e_fully_supported",
                mode="answer", query=_attr_query(frame, "country",
                                                 entry["entity"]),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"], require_citations=True)
        for scholar in self._by_kind(split, "person")[:2]:
            fact = scholar["facts"]["field of study"]
            self._add(
                split=split, track="E", family="e_fully_supported",
                mode="answer", query=_attr_query(frame, "field of study",
                                                 scholar["entity"]),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"], require_citations=True)
        # partially supported: attribute exists in the ontology but not for
        # this entity kind
        town = self._by_kind(split, "town")[0]
        self._add(split=split, track="E", family="e_partially_supported",
                  mode="answer", query=_attr_query(frame, "emblem",
                                                   town["entity"]),
                  expect_status="INSUFFICIENT_EVIDENCE")
        inst = self._by_kind(split, "institution")[0]
        self._add(split=split, track="E", family="e_partially_supported",
                  mode="answer", query=_attr_query(frame, "seats",
                                                   inst["entity"]),
                  expect_status="INSUFFICIENT_EVIDENCE")
        work = self._by_kind(split, "work")[0]
        self._add(split=split, track="E", family="e_partially_supported",
                  mode="answer", query=_attr_query(frame, "property",
                                                   work["entity"]),
                  expect_status="INSUFFICIENT_EVIDENCE")
        # wrong entity: absent targets
        for absent in self.index["absent_entities"][split]:
            self._add(split=split, track="E", family="e_wrong_entity",
                      mode="answer",
                      query=_attr_query(frame, "founding year", absent),
                      expect_status="INSUFFICIENT_EVIDENCE",
                      probes={"absent_entity": absent})
        # stale-only / current-cue routing
        for town in self._by_kind(split, "town")[2:5]:
            query = (f"Who is the current mayor of {town['entity']}, "
                     f"according to the latest report?")
            self._add(split=split, track="E", family="e_stale_only_current",
                      mode="answer", query=query,
                      expect_status="ROUTE_WEB_RESEARCH",
                      probes={"absent_entity": None})
        # malicious source text, mixed chunk: fact must survive quarantine
        mixed = [row for row in self._mixed_injection_hosts(split)]
        for host in mixed:
            town = self._entry(host["entity"])
            query = _attr_query(frame, host["attribute"],
                                host["entity"])
            self._add(
                split=split, track="E", family="e_malicious_mixed",
                mode="answer", query=query, expect_status="ANSWER",
                expect_contains=[host["value"]],
                gold_chunk_id=host["chunk_id"],
                probes={"payload_key": host["payload_key"]},
                require_citations=True,
                note="directive sentence quarantined; fact sentence intact")
        # directive-only chunk co-present with a valid answer
        town = self._by_kind(split, "town")[0]
        fact = town["facts"]["country"]
        self._add(split=split, track="E", family="e_directive_companion",
                  mode="answer", query=_attr_query(frame, "country",
                                                   town["entity"]),
                  expect_status="ANSWER", expect_contains=[fact["value"]],
                  gold_chunk_id=fact["chunk_id"], require_citations=True)
        # gold conflict (abstention class completeness)
        for name in [t["entity"] for t in self.index["conflict_towns"]
                     if t["pool"] == split][:1]:
            query = frame["attr_who"].format(attr="mayor", entity=name)
            self._add(split=split, track="E", family="e_conflict_gold",
                      mode="answer", query=query,
                      expect_status="CONFLICTING_EVIDENCE")

    def _mixed_injection_hosts(self, split: str) -> list[dict]:
        hosts = []
        for chunk_id, role in self._injection_roles_cache.items():
            if role["host"] is not None and role["pool"] == split:
                hosts.append(role["host"] | {"payload_key": role["payload_key"],
                                             "chunk_id": chunk_id})
        return hosts

    def _mixed_injection_hosts_setup(self) -> None:
        from sciencemath.knowledge.corpus import load_corpus
        corpus = load_corpus(world.WORLD_DIR)
        cache: dict[str, dict] = {}
        for row in self.index["injection_chunks"]:
            chunk_id = row["chunk_id"]
            chunk = corpus.chunk(chunk_id)
            meta = (chunk.metadata or {}) if chunk is not None else {}
            host = None
            if meta.get("fact_entity"):
                host = {"entity": meta["fact_entity"],
                        "attribute": meta["fact_attribute"],
                        "value": meta["fact_value"],
                        "chunk_id": chunk_id}
            cache[chunk_id] = {"payload_key": row["payload_key"],
                               "pool": row["pool"], "host": host}
        self._injection_roles_cache = cache

    # -- Track F: citation discipline ------------------------------------------
    def track_f(self, split: str) -> None:
        frame = FRAMES[split]
        # baseline single-source citations
        for entry, attr in [(self._by_kind(split, "town")[0], "country"),
                            (self._by_kind(split, "town")[1], "river"),
                            (self._by_kind(split, "person")[0],
                             "field of study"),
                            (self._by_kind(split, "work")[0], "genre")]:
            fact = entry["facts"][attr]
            self._add(
                split=split, track="F", family="f_baseline", mode="answer",
                query=_attr_query(frame, attr, entry["entity"]),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_sources=[fact["source_key"]],
                require_citations=True)
        # corroboration: required_sources = canonical + carrier
        for name in self._dup_entity_names(split, "town", "founding year")[:2]:
            entry = self._entry(name)
            fact = entry["facts"]["founding year"]
            dup = self._dup_entry(name, "founding year")
            self._add(
                split=split, track="F", family="f_corroboration",
                mode="answer", query=_attr_query(frame, "founding year",
                                                 name),
                expect_status="ANSWER", expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_sources=sorted({fact["source_key"],
                                         dup["source_key"]}),
                probes={"dup_chunk_id": dup["chunk_id"]},
                require_citations=True)
        # two-source path citations
        frame_chains = FRAMES[split]
        for entry in self._by_kind(split, "work")[:2]:
            author = entry["facts"]["author"]["value"]
            hop1 = entry["facts"]["author"]
            hop2 = self.entities[author]["facts"]["birthplace"]
            query = frame["chain"].format(terminal="birthplace",
                                          bridge="author",
                                          entity=entry["entity"])
            self._add(
                split=split, track="F", family="f_path_two_source",
                mode="answer", query=query, expect_status="ANSWER",
                expect_contains=[hop2["value"]],
                gold_chunk_id=hop2["chunk_id"],
                required_sources=sorted({hop1["source_key"],
                                         hop2["source_key"]}),
                probes={"gold_hop1_chunk_id": hop1["chunk_id"],
                        "gold_hop2_chunk_id": hop2["chunk_id"]},
                require_citations=True)
        # same-source distractor discipline (identity traps, mayor)
        for query_name, decoy_name in self._near_pairs(split)[:2]:
            entry = self._entry(query_name)
            fact = entry["facts"]["mayor"]
            self._add(
                split=split, track="F", family="f_nearname_citation",
                mode="answer", query=frame["attr_who"].format(
                    attr="mayor", entity=query_name),
                expect_status="ANSWER",
                expect_contains=[fact["value"]],
                gold_chunk_id=fact["chunk_id"],
                required_sources=[fact["source_key"]],
                probes={"decoy_entity": decoy_name},
                require_citations=True)

    def _source_key_of(self, chunk_id: str | None) -> str:
        if chunk_id is None:
            return ""
        return chunk_id.split(":")[0]


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def build_suites() -> dict:
    world_index = world.build_world()
    out: dict[str, list[dict]] = {}
    for split in SPLIT_ORDER:
        builder = SuiteBuilder(world_index)
        builder._mixed_injection_hosts_setup()
        builder.track_a(split)
        builder.track_b(split)
        builder.track_c(split)
        builder.track_d(split)
        builder.track_e(split)
        builder.track_f(split)
        rows = builder.rows
        for i, row in enumerate(rows, start=1):
            row["case_id"] = f"r11diag-{split}-{row['track'].lower()}-{i:04d}"
        out[split] = rows
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for split, rows in out.items():
        path = DEV_PATH if split == "dev" else VAL_PATH
        text = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False)
                       + "\n" for r in rows)
        path.write_text(text, encoding="utf-8", newline="\n")
    # freeze validation on first build; later builds must reproduce it
    if FREEZE_PATH.exists():
        freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
        want = _sha256(VAL_PATH)
        if freeze.get("validation_sha256") != want:
            raise SystemExit(
                "T21R11 VALIDATION FREEZE MISMATCH: validation_suites.jsonl "
                "changed after freeze; candidate must not edit validation "
                "gold (sha256 want=" + freeze["validation_sha256"]
                + " got=" + want + ")")
    else:
        FREEZE_PATH.write_text(
            json.dumps({
                "artifact": "T21R11_DIAGNOSTIC_VALIDATION_FREEZE",
                "validation_path": str(
                    VAL_PATH.relative_to(ROOT)).replace("\\", "/"),
                "validation_rows": len(out["validation"]),
                "validation_sha256": _sha256(VAL_PATH),
                "note": "Frozen at creation; candidate may inspect DEV only "
                        "during development. Validation gold must not be "
                        "edited after freeze.",
            }, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n")
    counts = {split: len(rows) for split, rows in out.items()}
    families: dict[str, dict] = {}
    for split, rows in out.items():
        for row in rows:
            key = f"{split}:{row['track']}:{row['family']}"
            families[key] = families.get(key, 0) + 1
    return {"artifact": "T21R11_DIAGNOSTIC_SUITES", "counts": counts,
            "families": families,
            "validation_sha256": _sha256(VAL_PATH)}


def main() -> int:
    report = build_suites()
    print(json.dumps(report["counts"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())