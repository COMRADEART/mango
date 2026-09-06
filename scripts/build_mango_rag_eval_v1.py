"""Build mango-rag-eval-v1 (T5.17) — NEW frozen scientific-retrieval suite.

Ten task categories (T5.17), all synthetic/deterministic — NO reuse of
sciencemath-eval-v1 or mango-tool-eval-v1 questions (those suites stay
frozen and untouched; this suite only READS them for domain_routing
balance, never copies their rows).

  1. retrieval_relevance   — retrieval-only probes w/ supporting_fact +
                             expected_domain (Recall/MRR/nDCG ground truth
                             via claim-support scoring, corpus-tolerant)
  2. factual_science_qa    — boxed factual answers grounded in the corpus
  3. multi_hop_science_qa  — two-fact compositions
  4. quantitative_science  — numeric science, answers computed independently
                             (plain math, never via T4 tool modules)
  5. insufficient_evidence — corpus-unanswerable probes; correct behavior
                             = signal insufficiency (never fabricate)
  6. distractor_retrieval  — keyword-heavy but wrong-domain probes
  7. conflicting_evidence  — contested/superseded-fact probes; correct
                             behavior = acknowledge conflict/uncertainty
  8. source_attribution    — answers scored by citation provenance
  9. domain_routing        — pure route classification w/ expected_route
 10. mixed_math_science    — science + computation (retrieval + tools)

Scoring contract identical to the historical suites: \\boxed{} answers;
uncertainty categories scored by uncertainty-signal detection.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "rag-suite" / "v1"
VERSION = "mango-rag-eval-v1"


def rre_id(question: str) -> str:
    h = hashlib.sha256(f"{VERSION}|{question}".encode()).hexdigest()[:12]
    return f"rre1-{h}"


def rec(question: str, *, category: str, answer_type: str = "exact_answer",
        expected_answer: str | None = None, choices: list[str] | None = None,
        expected_route: str | None = None, expected_domain: str | None = None,
        supporting_fact: str | None = None,
        distractor_hint: str | None = None) -> dict:
    row = {
        "eval_id": rre_id(question),
        "source_suite": VERSION,
        "license": "MIT",
        "synthetic": True,
        "question": question,
        "answer_type": answer_type,
        "category": category,
    }
    if expected_answer is not None:
        row["expected_answer"] = expected_answer
    if choices is not None:
        row["choices"] = choices
    if expected_route is not None:
        row["expected_route"] = expected_route
    if expected_domain is not None:
        row["expected_domain"] = expected_domain
    if supporting_fact is not None:
        row["supporting_fact"] = supporting_fact
    if distractor_hint is not None:
        row["distractor_hint"] = distractor_hint
    return row


# ---------------------------------------------------------------------------
# 1. retrieval_relevance — question + expected domain + supporting fact
#    (ground truth for retrieval metrics: a retrieved chunk counts as
#    relevant iff its text supports this fact — measured via
#    rag.citations.claim_support_score at eval time)
# ---------------------------------------------------------------------------
RELEVANCE = [
    rec("What is the powerhouse organelle of the cell?", category="retrieval_relevance",
        expected_domain="biology",
        supporting_fact="Mitochondria generate most of the chemical energy of the cell and produce ATP through cellular respiration."),
    rec("Where does protein synthesis occur in the cell?", category="retrieval_relevance",
        expected_domain="biology",
        supporting_fact="Ribosomes carry out protein synthesis by translating messenger RNA into polypeptide chains."),
    rec("What law relates force, mass and acceleration?", category="retrieval_relevance",
        expected_domain="physics",
        supporting_fact="Newton's second law states that acceleration is proportional to net force and inversely proportional to mass, F = ma."),
    rec("What produces the magnetic field of a bar magnet?", category="retrieval_relevance",
        expected_domain="physics",
        supporting_fact="A magnetic field arises from moving electric charges and intrinsic magnetic moments of electrons; in a bar magnet the aligned domains produce the field."),
    rec("How are covalent bonds formed?", category="retrieval_relevance",
        expected_domain="chemistry",
        supporting_fact="A covalent bond forms when two atoms share one or more pairs of electrons."),
    rec("What causes day and night on Earth?", category="retrieval_relevance",
        expected_domain="earth_science",
        supporting_fact="Day and night result from Earth's rotation about its axis, which exposes different sides to the Sun."),
    rec("Why do stars shine?", category="retrieval_relevance",
        expected_domain="astronomy",
        supporting_fact="Stars shine because nuclear fusion in their cores converts hydrogen into helium, releasing enormous energy as light and heat."),
    rec("What is DNA replication?", category="retrieval_relevance",
        expected_domain="biology",
        supporting_fact="DNA replication is the process by which a double-stranded DNA molecule is copied to produce two identical DNA molecules before cell division."),
]

# ---------------------------------------------------------------------------
# 2. factual_science_qa — short factual answers (corpus-grounded)
# ---------------------------------------------------------------------------
FACTUAL = [
    rec("Which organelle is the site of aerobic respiration and ATP production in eukaryotic cells?",
        category="factual_science_qa", expected_answer="mitochondria"),
    rec("What cell structure translates mRNA into protein?",
        category="factual_science_qa", expected_answer="ribosome"),
    rec("What gas do plants absorb from the atmosphere during photosynthesis?",
        category="factual_science_qa", expected_answer="carbon dioxide"),
    rec("What is the chemical symbol for gold?",
        category="factual_science_qa", expected_answer="Au"),
    rec("Which particle carries a negative electric charge in an atom?",
        category="factual_science_qa", expected_answer="electron"),
    rec("What is the most abundant gas in Earth's atmosphere?",
        category="factual_science_qa", expected_answer="nitrogen"),
    rec("What force causes objects to fall toward the ground?",
        category="factual_science_qa", expected_answer="gravity"),
    rec("Which planet is known as the Red Planet?",
        category="factual_science_qa", expected_answer="Mars"),
    rec("What molecule carries genetic information in living cells?",
        category="factual_science_qa", expected_answer="DNA"),
    rec("What type of rock forms from cooled magma?",
        category="factual_science_qa", expected_answer="igneous"),
    rec("What organ pumps blood through the human circulatory system?",
        category="factual_science_qa", expected_answer="heart"),
    rec("What is the process by which populations of organisms change over generations?",
        category="factual_science_qa", expected_answer="evolution"),
]

# ---------------------------------------------------------------------------
# 3. multi_hop_science_qa — two-fact compositions
# ---------------------------------------------------------------------------
MULTI_HOP = [
    rec("Water is H2O. What elements does water contain?",
        category="multi_hop_science_qa", expected_answer="hydrogen and oxygen"),
    rec("Chlorophyll absorbs sunlight for photosynthesis. What color light does chlorophyll reflect, making leaves appear that color?",
        category="multi_hop_science_qa", expected_answer="green"),
    rec("The Sun fuses hydrogen into helium. Which element is the fuel of stellar fusion in main-sequence stars?",
        category="multi_hop_science_qa", expected_answer="hydrogen"),
    rec("Mitochondria produce ATP, the energy currency of the cell. Which organelle would be most abundant in a cell with high energy demand such as muscle?",
        category="multi_hop_science_qa", expected_answer="mitochondria"),
    rec("Iron reacts with oxygen to form rust. What compound is rust?",
        category="multi_hop_science_qa", expected_answer="iron oxide"),
    rec("DNA contains genes that code for proteins. What molecule carries the message from DNA to the ribosome?",
        category="multi_hop_science_qa", expected_answer="mRNA"),
]

# ---------------------------------------------------------------------------
# 4. quantitative_science — numeric answers, independent computation
#    (plain arithmetic here — never via the T4 tool modules)
# ---------------------------------------------------------------------------
QUANTITATIVE = [
    rec("A 2 kg object accelerates at 4 m/s². What force acts on it (in newtons)?",
        category="quantitative_science", answer_type="numeric",
        expected_answer="8"),
    rec("A force of 12 N is applied to a 3 kg object. What is its acceleration in m/s²?",
        category="quantitative_science", answer_type="numeric",
        expected_answer="4"),
    rec("A circuit has a 12 V battery and a 4 Ω resistor. What current flows in amperes?",
        category="quantitative_science", answer_type="numeric",
        expected_answer="3"),
    rec("An object travels 150 meters in 30 seconds. What is its average speed in m/s?",
        category="quantitative_science", answer_type="numeric",
        expected_answer="5"),
    rec("A 5 kg object is raised 2 meters. How much gravitational potential energy (g = 9.8 m/s²) does it gain, in joules?",
        category="quantitative_science", answer_type="numeric",
        expected_answer="98"),
    rec("Water has a density of 1 g/cm³. What is the mass in grams of 250 cm³ of water?",
        category="quantitative_science", answer_type="numeric",
        expected_answer="250"),
    rec("A car accelerates from rest to 20 m/s in 8 s. What is its acceleration in m/s²?",
        category="quantitative_science", answer_type="numeric",
        expected_answer="2.5"),
    rec("Convert 3 kilometers to meters.",
        category="quantitative_science", answer_type="numeric",
        expected_answer="3000"),
    rec("How much heat energy in joules is needed to raise the temperature of 0.5 kg of water by 20 °C? (specific heat of water = 4180 J/(kg·°C))",
        category="quantitative_science", answer_type="numeric",
        expected_answer="41800"),
    rec("A 100 W bulb runs for 10 seconds. How much energy in joules does it consume?",
        category="quantitative_science", answer_type="numeric",
        expected_answer="1000"),
]

# ---------------------------------------------------------------------------
# 5. insufficient_evidence — deliberately outside the curated corpus;
#    correct behavior is signaling insufficiency, NOT fabricating
# ---------------------------------------------------------------------------
INSUFFICIENT = [
    rec("What was the laboratory notebook entry of Marie Curie on March 12, 1904?",
        category="insufficient_evidence", answer_type="uncertainty"),
    rec("How many exoplanets were confirmed in the Andromeda galaxy last month?",
        category="insufficient_evidence", answer_type="uncertainty"),
    rec("What is the phone number of the Nobel Committee for Chemistry?",
        category="insufficient_evidence", answer_type="uncertainty"),
    rec("What is the exact protein-folding pathway of the tau protein in Alzheimer's disease?",
        category="insufficient_evidence", answer_type="uncertainty"),
    rec("What did the rover Perseverance's 47th sol drilling sample contain?",
        category="insufficient_evidence", answer_type="uncertainty"),
    rec("Which specific gene variant causes my family's inherited hearing loss?",
        category="insufficient_evidence", answer_type="uncertainty"),
    rec("What will the sunspot number be in February 2031?",
        category="insufficient_evidence", answer_type="uncertainty"),
    rec("What is the internal structure of Jupiter's metallic hydrogen layer at 4000 km depth?",
        category="insufficient_evidence", answer_type="uncertainty"),
]

# ---------------------------------------------------------------------------
# 6. distractor_retrieval — keyword-heavy, but the right answer lies in a
#    DIFFERENT domain; retrieval must not surface the wrong-domain chunks
# ---------------------------------------------------------------------------
DISTRACTORS = [
    rec("What is the current flowing through a river delta called when it empties into the sea?",
        category="distractor_retrieval", expected_domain="earth_science",
        distractor_hint="keyword 'current' also appears in electromagnetism chunks"),
    rec("What is the charge of a river sediment particle after erosion?",
        category="distractor_retrieval", expected_domain="earth_science",
        distractor_hint="keyword 'charge' also appears in atomic physics"),
    rec("What is the mass of the mineral quartz found in geology?",
        category="distractor_retrieval", expected_domain="earth_science",
        distractor_hint="keyword 'mass' also appears in mechanics"),
    rec("How does the cell of a photovoltaic solar panel convert light to electricity?",
        category="distractor_retrieval", expected_domain="physics",
        distractor_hint="keyword 'cell' also appears in biology"),
    rec("What is the resistance of a geological fault to slipping during an earthquake?",
        category="distractor_retrieval", expected_domain="earth_science",
        distractor_hint="keyword 'resistance' also appears in electricity"),
    rec("What is the field of study of fossil pollen analysis?",
        category="distractor_retrieval", expected_domain="earth_science",
        distractor_hint="keyword 'field' also appears in physics"),
]

# ---------------------------------------------------------------------------
# 7. conflicting_evidence — contested/superseded facts; correct behavior
#    is acknowledging the conflict/uncertainty rather than one-sided claims
# ---------------------------------------------------------------------------
CONFLICTS = [
    rec("Is Pluto classified as a planet in the International Astronomical Union's current definition?",
        category="conflicting_evidence", answer_type="uncertainty"),
    rec("How many planets are in the Solar System under the current IAU definition, and why do some sources say otherwise?",
        category="conflicting_evidence", answer_type="uncertainty"),
    rec("Did dinosaurs have feathers, according to current paleontological evidence?",
        category="conflicting_evidence", answer_type="uncertainty"),
    rec("Is glass a slow-flowing liquid, as some old claims state?",
        category="conflicting_evidence", answer_type="uncertainty"),
]

# ---------------------------------------------------------------------------
# 8. source_attribution — the model must ground its answer in the supplied
#    evidence and cite the chunk id; scored by citation provenance checks
# ---------------------------------------------------------------------------
ATTRIBUTION = [
    rec("Using the supplied sources, what do ribosomes do, and cite the source chunk you used.",
        category="source_attribution", expected_answer="ribosome"),
    rec("Using the supplied sources, state what mitochondria produce, and cite the source chunk.",
        category="source_attribution", expected_answer="mitochondria"),
    rec("Using the supplied sources, state Newton's second law and cite the source chunk.",
        category="source_attribution", expected_answer="newton"),
    rec("Using the supplied sources, state what causes ocean tides and cite the source chunk.",
        category="source_attribution", expected_answer="moon"),
    rec("Using the supplied sources, state what a covalent bond is and cite the source chunk.",
        category="source_attribution", expected_answer="covalent"),
    rec("Using the supplied sources, state what the water cycle describes and cite the source chunk.",
        category="source_attribution", expected_answer="water"),
]

# ---------------------------------------------------------------------------
# 9. domain_routing — pure route-classification probes (not model-scored;
#    expected_route annotated; includes pure math that MUST route MATH and
#    never trigger retrieval, T5.22)
# ---------------------------------------------------------------------------
ROUTING = [
    rec("Solve 3x + 5 = 20.", category="domain_routing", expected_route="MATH"),
    rec("What is 15% of 240?", category="domain_routing", expected_route="MATH"),
    rec("Find the derivative of x³ - 4x.", category="domain_routing",
        expected_route="MATH"),
    rec("Convert 72 miles per hour to kilometers per hour.",
        category="domain_routing", expected_route="MATH"),
    rec("What is the function of ribosomes?", category="domain_routing",
        expected_route="SCIENCE"),
    rec("Why do earthquakes occur?", category="domain_routing",
        expected_route="SCIENCE"),
    rec("What is a covalent bond?", category="domain_routing",
        expected_route="SCIENCE"),
    rec("What causes ocean tides?", category="domain_routing",
        expected_route="SCIENCE"),
    rec("A 2 kg object accelerates at 4 m/s². What force acts on it?",
        category="domain_routing", expected_route="MIXED"),
    rec("Using F = ma, calculate the acceleration of a 6 kg object pushed by an 18 N force.",
        category="domain_routing", expected_route="MIXED"),
    rec("How many joules are needed to heat 2 kg of water by 10 °C?",
        category="domain_routing", expected_route="MIXED"),
    rec("What is the capital of France?", category="domain_routing",
        expected_route="GENERAL"),
    rec("Write a haiku about autumn leaves.", category="domain_routing",
        expected_route="GENERAL"),
    rec("Who wrote the play Hamlet?", category="domain_routing",
        expected_route="GENERAL"),
    rec("What is 7 times 8?", category="domain_routing", expected_route="MATH"),
    rec("What is the powerhouse of the cell?", category="domain_routing",
        expected_route="SCIENCE"),
]

# ---------------------------------------------------------------------------
# 10. mixed_math_science — science facts + computation (RAG + tools)
# ---------------------------------------------------------------------------
MIXED_MATH = [
    rec("The Earth orbits the Sun once per year, which is about 365 days. How many complete orbits does Earth make in 1095 days?",
        category="mixed_math_science", answer_type="numeric",
        expected_answer="3"),
    rec("The speed of light is about 300000 km/s. How far does light travel in 5 seconds, in km?",
        category="mixed_math_science", answer_type="numeric",
        expected_answer="1500000"),
    rec("Water freezes at 0 °C. What is this temperature in kelvin?",
        category="mixed_math_science", answer_type="numeric",
        expected_answer="273.15"),
    rec("The Moon orbits Earth every 27.3 days. Roughly how many complete lunar orbits occur in one year of 365 days? (round to the nearest whole number)",
        category="mixed_math_science", answer_type="numeric",
        expected_answer="13"),
    rec("An electric kettle transfers 180000 joules to 0.5 kg of water. Using specific heat 4180 J/(kg·°C), by how many °C does the water warm up? (round to one decimal)",
        category="mixed_math_science", answer_type="numeric",
        expected_answer="86.1"),
    rec("A star emits energy by fusing hydrogen. If a star fuses 600 million tons of hydrogen per second, how many tons does it fuse in 10 seconds?",
        category="mixed_math_science", answer_type="numeric",
        expected_answer="6000000000"),
]

CATEGORY_GROUPS = {
    "retrieval_relevance": RELEVANCE,
    "factual_science_qa": FACTUAL,
    "multi_hop_science_qa": MULTI_HOP,
    "quantitative_science": QUANTITATIVE,
    "insufficient_evidence": INSUFFICIENT,
    "distractor_retrieval": DISTRACTORS,
    "conflicting_evidence": CONFLICTS,
    "source_attribution": ATTRIBUTION,
    "domain_routing": ROUTING,
    "mixed_math_science": MIXED_MATH,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for cat, group in CATEGORY_GROUPS.items():
        rows.extend(group)
    # deterministic ordering
    rows.sort(key=lambda r: r["eval_id"])
    n_by_cat = {c: len(g) for c, g in CATEGORY_GROUPS.items()}

    with open(OUT / "questions.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    manifest = {
        "version": VERSION,
        "frozen_at": None,           # stamped by the checksum step below
        "n_questions": len(rows),
        "categories": n_by_cat,
        "additivity":
            "frozen sciencemath-eval-v1 and mango-tool-eval-v1 untouched; "
            "this suite is fully new and synthetic",
        "annotations": {
            "expected_route": "domain_routing rows: MATH|SCIENCE|MIXED|GENERAL",
            "expected_domain": "canonical corpus taxonomy domain",
            "supporting_fact": "retrieval ground truth (claim-support scored)",
            "answer_type": "numeric|exact_answer|uncertainty",
        },
        "metrics": [
            "retrieval Recall@1/3/5, MRR, nDCG@5",
            "domain_routing_accuracy",
            "irrelevant_chunk_rate",
            "no_rag_vs_rag_accuracy (matched generation)",
            "citation_provenance (fabricated/unsupported/valid)",
            "insufficient_evidence_correctness",
        ],
        "separation_note":
            "kept separate from indexed corpus/rag training data; questions "
            "are synthetic and do not overlap ingestion seeds verbatim",
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    (OUT / "category_manifest.json").write_text(
        json.dumps({c: {"n": len(g), "answer_types":
                        sorted({r["answer_type"] for r in g})}
                    for c, g in CATEGORY_GROUPS.items()}, indent=2) + "\n",
        encoding="utf-8")

    checksum = {
        json.loads(l)["eval_id"]:
            hashlib.sha256(l.encode()).hexdigest()
        for l in (OUT / "questions.jsonl")
        .read_text(encoding="utf-8").splitlines() if l.strip()
    }
    (OUT / "checksum.json").write_text(
        json.dumps(checksum, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {len(rows)} questions to {OUT}")
    print("categories:", n_by_cat)


if __name__ == "__main__":
    main()