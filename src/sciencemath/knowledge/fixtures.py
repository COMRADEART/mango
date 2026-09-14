"""T21 fixture world — deterministic general-knowledge content.

The frozen evaluation corpus is project-owned fixture material: no
third-party text is ingested, nothing is scraped, nothing is licensed
content. Two layers provide the mass and the distractor structure:

  1. A small curated layer of stable real-world reference facts.
  2. A deterministic fixture world (fictional towns, people, works,
     institutions, technologies) whose structured attributes generate the
     volume, the multi-hop chains, the conflicts, and the temporal
     boundary cases.

Everything is derived from fixed tables and index arithmetic; no build
order, wall clock, or model memory enters any fact. The same fixture
module builds the corpus (rag/gk_corpus/) and the benchmark suites
(evaluations/t21/suites/), so gold chunk IDs always resolve.
"""
from __future__ import annotations

SEED = 42
SNAPSHOT_DATE = "2026-01-31"

# ---------------------------------------------------------------------------
# Publisher collections (deterministic source identities)
# ---------------------------------------------------------------------------
COLLECTIONS = [
    # (publisher_or_collection, authority_class, source_type)
    ("GK Reference Shelf", "ENCYCLOPEDIC", "reference_work"),
    ("Atlas & Almanac Collection", "INSTITUTIONAL", "reference_work"),
    ("University Press Companion", "ENCYCLOPEDIC", "academic_reference"),
    ("Municipal Records Office", "INSTITUTIONAL", "government_register"),
]
REV = "rev-1"
LICENSE = "CC0-1.0 (project fixture)"
ORIGIN = "mango-t21-fixture-corpus"

# ---------------------------------------------------------------------------
# Curated stable facts: (entity, attribute, value, context)
# The attribute label matches the attribute noun used in the fact sentence
# and in the benchmark question templates.
# ---------------------------------------------------------------------------
CURATED_FACTS = [
    ("Guernica", "painter", "Pablo Picasso",
     "A large 1937 painting reacting to the bombing of a Basque town "
     "during the Spanish Civil War."),
    ("Pride and Prejudice", "author", "Jane Austen",
     "A novel of manners set in rural England, first printed in 1813."),
    ("the Rosetta Stone", "discovery year", "1799",
     "An ancient stele carrying a priestly decree in three scripts."),
    ("the World Wide Web", "invention year", "1989",
     "A hypertext information system proposed at a European physics lab."),
    ("the Apollo 11 mission", "landing year", "1969",
     "The first crewed lunar landing mission."),
    ("Japan", "capital", "Tokyo", "An island nation in East Asia."),
    ("Canberra", "country", "Australia",
     "A purpose-built national capital city."),
    ("the Danube", "mouth", "the Black Sea",
     "Europe's second-longest river."),
    ("the United States Constitution", "ratification year", "1788",
     "Drafted in 1787 at a convention in Philadelphia."),
    ("the United States Senate", "seats", "100",
     "The upper chamber of a bicameral national legislature."),
    ("gross domestic product", "definition",
     "the total value of goods and services produced in a period",
     "A standard measure of economic output."),
    ("inflation", "definition",
     "a sustained increase in the general price level",
     "Commonly measured year over year."),
    ("TCP", "layer", "transport",
     "A core internet protocol providing reliable ordered delivery."),
    ("a hash function", "property", "deterministic output",
     "Maps input of arbitrary size to a fixed-size output."),
    ("the printing press", "inventor", "Johannes Gutenberg",
     "Movable-type printing transformed European book production."),
    ("the Magna Carta", "sealing year", "1215",
     "An English charter agreed at Runnymede."),
]

# Deliberately ABSENT famous facts: the pipeline must abstain, never
# backfill from model memory (T21.21 traps). Near-miss distractor passages
# share surface tokens but never the answer.
ABSENT_ENTITIES = [
    "Hamlet", "the theory of relativity", "the Mona Lisa",
    "the French Revolution", "Mount Everest",
]

# ---------------------------------------------------------------------------
# Fixture world tables
# ---------------------------------------------------------------------------
COUNTRIES = ["Norvalia", "Cardenmark", "Ellsmere", "Vantoria"]
CITY_NAMES = [
    "Cardenfield", "Alderport", "Bramble Bay", "Fairhaven", "Meriden",
    "Stonewick", "Larkspur", "Glenmoor", "Haverbrook", "Windmere",
    "Ashcombe", "Fernvale", "Corlton", "Duskhaven", "Elmsworth",
    "Farrowdale", "Greystone", "Hollis Bay", "Ivorton", "Jarrow Reach",
    "Kesterfield", "Lyndhurst", "Marrowgate", "Northam", "Oakhurst",
    "Pellworth", "Quarrington", "Ravensmoor", "Silvermere", "Thornbury",
    "Ulverton", "Vexford", "Wrenfield", "Yarrowton", "Zellwood",
    "Brightwater", "Caldervale", "Dovemoor", "Eastmere", "Foxhollow",
]
FIRST_NAMES = ["Alma", "Bertram", "Cordelia", "Desmond", "Estelle", "Felix",
               "Greta", "Hugh", "Isolde", "Julian", "Katriel", "Leopold",
               "Marguerite", "Nathaniel", "Ottilie", "Percival", "Rosamund",
               "Sebastian", "Tabitha", "Ursula", "Victor", "Wilhelmina"]
SURNAMES = ["Ashdown", "Belrose", "Calloway", "Dunmore", "Eastley",
            "Fairbanks", "Goldwyn", "Hartwell", "Ingram", "Jessup",
            "Kestrel", "Lownde", "Merriweather", "Northcote", "Oakley",
            "Pemberton", "Quimby", "Ravensworth", "Stanmore", "Thornley"]
FIELDS = ["astronomy", "botany", "cartography", "entomology", "geology",
          "hydrology", "meteorology", "ornithology"]
RIVERS = ["the Amberline", "the Brackwater", "the Corren", "the Duskfield"]
LANDMARKS = ["a clock tower", "a covered bridge", "a stone aqueduct",
             "a botanical garden", "a lighthouse", "an old market hall"]
REGION_WORDS = ["the northern lowlands", "the southern hills",
                "the eastern coast", "the western plateau"]
INSTITUTION_TYPES = ["Observatory", "Institute", "Society", "Academy"]
TECH_PROPERTIES = ["deterministic output", "reversible operation",
                   "bounded latency", "fixed precision"]

WORK_GENRES = ["novel", "essay", "play", "treatise", "monograph"]
WORK_WORDS = ["Winter", "Harbour", "Orchard", "Meridian", "Cartographer",
              "Almanac", "Foundry", "Herald", "Compass", "Lantern",
              "Sparrow", "Tidewater", "Garden", "Ledger", "Clockwork",
              "Bridgeways", "Inheritance", "Pilgrim", "Signal", "Anchor"]
WORK_SUBJECTS = ["cartography", "harbour life", "alpine travel",
                 "clockmaking", "tidal science"]

# ---------------------------------------------------------------------------
# Deterministic generators (pure index arithmetic — no randomness needed)
# ---------------------------------------------------------------------------


def fixture_cities() -> list[dict]:
    """40 fixture towns with six structured attributes each."""
    cities = []
    for i, name in enumerate(CITY_NAMES):
        cities.append({
            "entity": name, "kind": "city",
            "country": COUNTRIES[i % len(COUNTRIES)],
            "founding year": str(1620 + (i * 7) % 240),
            "river": RIVERS[(i // len(RIVERS)) % len(RIVERS)],
            "mayor": f"{FIRST_NAMES[(i * 3) % len(FIRST_NAMES)]} "
                     f"{SURNAMES[(i * 5) % len(SURNAMES)]}",
            "landmark": LANDMARKS[i % len(LANDMARKS)],
            "region": REGION_WORDS[i % len(REGION_WORDS)],
        })
    return cities


def fixture_people() -> list[dict]:
    """30 fixture scholars; the first 20 author the 20 fixture works."""
    works = fixture_works()
    people = []
    for i in range(30):
        name = f"{FIRST_NAMES[(i * 7) % len(FIRST_NAMES)]} " \
               f"{SURNAMES[(i * 3 + 1) % len(SURNAMES)]}"
        people.append({
            "entity": name, "kind": "person",
            "field of study": FIELDS[i % len(FIELDS)],
            "birth year": str(1820 + (i * 11) % 120),
            "birthplace": CITY_NAMES[(i * 13) % len(CITY_NAMES)],
            "notable work": (works[i]["entity"] if i < len(works) else ""),
        })
    return people


def fixture_works() -> list[dict]:
    """20 fixture works with unique titles and three attributes each."""
    works = []
    for i in range(len(WORK_WORDS)):
        title = f"The {WORK_WORDS[i]} of {WORK_WORDS[(i * 9 + 7) % 20]}"
        # Pairs are unique (9 invertible mod 20) and no title is a word
        # swap of another: f(f(i)) = 81i + 70 ≡ i + 10 (mod 20) ≠ i, so
        # "The A of B" / "The B of A" collisions cannot occur.
        works.append({
            "entity": title, "kind": "work",
            "genre": WORK_GENRES[i % len(WORK_GENRES)],
            "publication year": str(1840 + (i * 17) % 150),
            "subject": WORK_SUBJECTS[i % len(WORK_SUBJECTS)],
        })
    return works


def fixture_institutions() -> list[dict]:
    """15 fixture institutions with two structured attributes each."""
    institutions = []
    for i in range(15):
        kind = INSTITUTION_TYPES[i % len(INSTITUTION_TYPES)]
        name = f"{WORK_WORDS[(i * 4 + 2) % len(WORK_WORDS)]} {kind}"
        institutions.append({
            "entity": name, "kind": "institution",
            "founding year": str(1700 + (i * 23) % 200),
            "location": CITY_NAMES[(i * 9 + 4) % len(CITY_NAMES)],
        })
    return institutions


_WORK_LIST = [
    "the Lattice protocol", "the Meridian stack", "the Quillon format",
    "the Brantley cipher", "the Fennmore machine", "the Aldgate engine",
    "the Winslow relay", "the Carden automaton", "the Elsmere tabulator",
    "the Vantor telegraph",
]


def fixture_techs() -> list[dict]:
    """10 fixture technologies with three structured attributes each."""
    techs = []
    for i, system in enumerate(_WORK_LIST):
        techs.append({
            "entity": system, "kind": "technology",
            "inventor": f"{FIRST_NAMES[(i * 5 + 2) % len(FIRST_NAMES)]} "
                        f"{SURNAMES[(i * 7 + 3) % len(SURNAMES)]}",
            "introduction year": str(1890 + (i * 13) % 100),
            "property": TECH_PROPERTIES[i % len(TECH_PROPERTIES)],
        })
    return techs


def all_fixture_facts() -> list[tuple[str, str, str]]:
    """Flatten the fixture world into (entity, attribute, value) rows."""
    rows: list[tuple[str, str, str]] = []
    for city in fixture_cities():
        for attr in ("country", "founding year", "river", "mayor",
                     "landmark", "region"):
            rows.append((city["entity"], attr, city[attr]))
    for person in fixture_people():
        for attr in ("field of study", "birth year", "birthplace"):
            rows.append((person["entity"], attr, person[attr]))
        if person["notable work"]:
            rows.append((person["entity"], "notable work",
                         person["notable work"]))
    for work in fixture_works():
        for attr in ("genre", "publication year", "subject"):
            rows.append((work["entity"], attr, work[attr]))
    for inst in fixture_institutions():
        for attr in ("founding year", "location"):
            rows.append((inst["entity"], attr, inst[attr]))
    for tech in fixture_techs():
        for attr in ("inventor", "introduction year", "property"):
            rows.append((tech["entity"], attr, tech[attr]))
    for entity, attribute, value, _context in CURATED_FACTS:
        rows.append((entity, attribute, value))
    return rows


# ---------------------------------------------------------------------------
# Multi-hop chains: (work, author, author_birthplace)
# ---------------------------------------------------------------------------
def multihop_chains() -> list[tuple[str, str, str]]:
    people = fixture_people()
    works = fixture_works()
    return [(works[i]["entity"], people[i]["entity"],
             people[i]["birthplace"]) for i in range(len(works))]


# ---------------------------------------------------------------------------
# Conflicts.  Equal-authority pairs (same authority class, same freshness)
# are UNRESOLVED -> CONFLICTING_EVIDENCE.  Cross-authority and cross-
# freshness pairs are resolvable by the preregistered rules.
# Conflicting values are always the canonical value shifted deterministically
# so gold stays derivable.
# ---------------------------------------------------------------------------
CONFLICT_EQUAL_CITY_INDICES = [3, 12, 21, 27, 33, 38]


def conflict_equal_rows() -> list[tuple[str, str, str, str, str]]:
    """(entity, attribute, canonical, alt_value, alt_shift) — equal authority.

    Both conflicting sources are ENCYCLOPEDIC and STATIC, so the preregistered
    rules cannot pick a winner: the pipeline must surface
    CONFLICTING_EVIDENCE.
    """
    cities = fixture_cities()
    rows = []
    for k, i in enumerate(CONFLICT_EQUAL_CITY_INDICES):
        city = cities[i]
        shift = 2 if k % 2 == 0 else -3
        alt = str(int(city["founding year"]) + shift)
        rows.append((city["entity"], "founding year",
                     city["founding year"], alt, f"{shift:+d}"))
    return rows


def conflict_authority_rows() -> list[tuple[str, str, str, str]]:
    """(institution, attribute, canonical, alt_value) — authority-resolvable.

    The canonical value is asserted by an ENCYCLOPEDIC source; the
    conflicting value by a GENERAL_REFERENCE source (lower rank), so the
    preregistered rules resolve to the canonical value.
    """
    institutions = fixture_institutions()
    rows = []
    for i in (1, 4, 7, 10, 13):
        inst = institutions[i]
        alt = str(int(inst["founding year"]) + 5)
        rows.append((inst["entity"], "founding year",
                     inst["founding year"], alt))
    return rows


def conflict_freshness_rows() -> list[tuple[str, str, str, str]]:
    """(tech, attribute, canonical, alt_value) — freshness-resolvable.

    Both sources are ENCYCLOPEDIC; the canonical one is STATIC, the
    conflicting one SLOW_CHANGING, so STATIC wins.
    """
    techs = fixture_techs()
    rows = []
    for i in (2, 6):
        tech = techs[i]
        alt = str(int(tech["introduction year"]) - 4)
        rows.append((tech["entity"], "introduction year",
                     tech["introduction year"], alt))
    return rows


if __name__ == "__main__":
    print("cities", len(fixture_cities()), "facts",
          len(all_fixture_facts()), "chains", len(multihop_chains()),
          "conflicts", len(conflict_equal_rows()),
          len(conflict_authority_rows()), len(conflict_freshness_rows()))