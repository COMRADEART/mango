"""T5R.12 — build mango-rag-dev-v1, a development set DISTINCT from the
frozen mango-rag-eval-v1 suite.

Purpose: compare prompt/pipeline variants A–E on a dev split so the final
architecture choice is not made on a single frozen-suite result. The frozen
suite itself is NEVER touched and NEVER used for variant selection; dev
questions are newly authored, share the frozen suite's schema and category
shapes (factual / multi_hop / quantitative / insufficient / distractor /
conflicting / source_attribution / domain_routing / retrieval_relevance)
but are different questions.

Outputs (evaluations/rag-suite/dev-v1/):
  questions.jsonl   60 questions
  checksum.json     per-line sha256 (same integrity convention)
  suite_manifest.json  name mango-rag-dev-v1, counts, provenance
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "rag-suite" / "dev-v1"


def q(eval_id: str, category: str, question: str, *, answer_type:
      str = "exact_answer", expected_answer: str | None = None,
      expected_route: str | None = None, expected_domain: str | None = None,
      supporting_fact: str | None = None,
      choices: list[str] | None = None) -> dict:
    row = {
        "eval_id": eval_id, "category": category, "question": question,
        "answer_type": answer_type,
        "expected_answer": expected_answer,
        "expected_route": expected_route,
        "expected_domain": expected_domain,
        "supporting_fact": supporting_fact,
    }
    if choices:
        row["choices"] = choices
    return row


# eval_id: deterministic rdv1-<sha8> of the question text (unique ids,
# same convention as the frozen suite, no randomness)
def eid(text: str) -> str:
    return "rdv1-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


QUESTIONS: list[dict] = []


def add(category: str, text: str, **kw) -> None:
    QUESTIONS.append(q(eid(text), category, text, **kw))


# ---- factual_science_qa (12) ------------------------------------------------
FACTUAL = [
    ("What is the chemical symbol for gold?", "Au"),
    ("Which planet has the most extensive ring system?", "Saturn"),
    ("Which blood cells carry oxygen through the body?", "red blood cells"),
    ("What pigment absorbs light in photosynthesis?", "chlorophyll"),
    ("What is the most abundant gas in Earth's atmosphere?", "nitrogen"),
    ("Which organelle contains most of the cell's DNA?", "nucleus"),
    ("What type of rock forms from cooling lava?", "igneous"),
    ("What gas do humans exhale that plants use in photosynthesis?",
     "carbon dioxide"),
    ("Which metal is liquid at room temperature?", "mercury"),
    ("What process moves water vapor from the ocean into the atmosphere?",
     "evaporation"),
    ("What is the smallest unit of an element that keeps its chemical "
     "properties?", "atom"),
    ("Which organ pumps blood through the human body?", "heart"),
]
for t, a in FACTUAL:
    add("factual_science_qa", t, expected_answer=a)

# ---- multi_hop_science_qa (6: premise + dependent question) ------------------
MULTIHOP = [
    ("Green plants make their own food using sunlight. What pigment "
     "allows a plant to absorb light energy?", "chlorophyll"),
    ("Sound needs a medium to travel. Does sound travel faster in water "
     "or in air?", "water"),
    ("Metals are good conductors of heat. Which metal is liquid at room "
     "temperature?", "mercury"),
    ("The Moon orbits the Earth about once every 27 days. What force "
     "keeps the Moon in its orbit?", "gravity"),
    ("Ice floats on liquid water. What property of ice makes it float "
     "on water?", "density"),
    ("A magnet attracts iron nails. What is the region around a magnet "
     "where its force acts called?", "magnetic field"),
]
for t, a in MULTIHOP:
    add("multi_hop_science_qa", t, expected_answer=a)

# ---- quantitative_science (6, numeric, constants supplied inline) -----------
QUANT = [
    ("The speed of light is approximately 300000 km/s. How far does "
     "light travel in 2 seconds, in km?", 600000),
    ("A car travels 100 km in 2 hours. What is its average speed in "
     "km/h?", 50),
    ("Water has a density of 1 g/cm^3. What is the mass of 500 cm^3 of "
     "water, in grams?", 500),
    ("The specific heat of water = 4180 J/(kg*C). How much energy is "
     "needed to raise 1 kg of water by 10 C, in J?", 41800),
    ("An object moves at 10 m/s for 30 seconds. How far does it travel, "
     "in meters?", 300),
    ("A current of 2 A flows for 60 seconds. How much charge passes, in "
     "coulombs?", 120),
]
for t, a in QUANT:
    add("quantitative_science", t, expected_answer=str(a), answer_type="numeric")

# ---- mixed_math_science (6, numeric, science + arithmetic) ------------------
MIXED = [
    ("A star fuses 300 million tons of hydrogen per second. How many "
     "tons does it fuse in 20 seconds?", 6000000000),
    ("A wire carries a current of 5 A. How much charge flows through it "
     "in 40 seconds, in coulombs?", 200),
    ("Light travels at 300000 km/s. How far does it travel in 5 seconds, "
     "in km?", 1500000),
    ("An electric heater uses 1000 W of power for 30 seconds. How much "
     "energy does it use, in joules?", 30000),
    ("Sound travels at about 340 m/s in air. How far does sound travel "
     "in 10 seconds, in meters?", 3400),
    ("A solar panel produces 250 W. How much energy does it produce in "
     "2 hours, in watt-hours?", 500),
]
for t, a in MIXED:
    add("mixed_math_science", t, expected_answer=str(a), answer_type="numeric")

# ---- insufficient_evidence (6, uncertainty) ---------------------------------
INSUF = [
    "What will the sunspot number be in March 2031?",
    "What is the exact number of stars in the Milky Way?",
    "What will the average global temperature be in 2075?",
    "What will the next major volcanic eruption be?",
    "What is the exact mass of the universe?",
    "What exact weather will London have on January 1st, 2030?",
]
for t in INSUF:
    add("insufficient_evidence", t, answer_type="uncertainty")

# ---- distractor_retrieval (6, fake science, no expected answer) -------------
DISTRACTOR = [
    ("earth_science",
     "What is the resistance of a river delta to erosion during a "
     "storm surge?"),
    ("physics",
     "What is the magnetic charge of a copper wire carrying sunlight?"),
    ("chemistry",
     "What is the boiling temperature of solid nitrogen metal?"),
    ("biology",
     "Which organ filters sound from the human bloodstream?"),
    ("astronomy",
     "What is the orbital period of a comet made of liquid rock?"),
    ("earth_science",
     "What is the current flowing through a canyon called when it "
     "empties into the sea?"),
]
for dom, t in DISTRACTOR:
    add("distractor_retrieval", t, expected_domain=dom)

# ---- conflicting_evidence (4, uncertainty) ----------------------------------
CONFLICT = [
    "Do some sources claim glass is a slow-flowing liquid while others "
    "say it is an amorphous solid? Which is it?",
    "One older claim says the Earth is the center of the solar system, "
    "while modern astronomy says otherwise. Is the Earth the center of "
    "the solar system?",
    "Some old textbooks claim lightning never strikes the same place "
    "twice; modern physics says it can. Does lightning ever strike the "
    "same place twice?",
    "According to some sources, water is a mineral, while others "
    "classify it as a compound. Is water a mineral?",
]
for t in CONFLICT:
    add("conflicting_evidence", t, answer_type="uncertainty")

# ---- source_attribution (6, exact answer + citation required) ---------------
# Answers are SINGLE TERMS the model can box verbatim (the frozen grader
# is exact-match), and each term is verbatim in its corpus chunk so the
# deterministic citation support threshold is reachable.
SRCATTR = [
    ("Using the supplied sources, what do we call the organelle that "
     "contains the cell's genetic material? Answer with the single "
     "term and cite the source chunk you used.", "nucleus"),
    ("Using the supplied sources, what do we call the process by which "
     "liquid water becomes water vapor? Answer with the single term "
     "and cite the source chunk you used.", "evaporation"),
    ("Using the supplied sources, what do we call the force that pulls "
     "two masses toward each other? Answer with the single term and "
     "cite the source chunk you used.", "gravity"),
    ("Using the supplied sources, sound is a ___ that travels through "
     "a medium: fill in the missing word and cite the source chunk "
     "you used.", "vibration"),
    ("Using the supplied sources, what do we call the green pigment "
     "that absorbs light for photosynthesis? Answer with the single "
     "term and cite the source chunk you used.", "chlorophyll"),
    ("Using the supplied sources, what do we call the continuous "
     "movement of water through evaporation, condensation and "
     "precipitation? Answer with the single term and cite the source "
     "chunk you used.", "water cycle"),
]
for t, a in SRCATTR:
    add("source_attribution", t, expected_answer=a)

# ---- domain_routing (6, routing only) ---------------------------------------
ROUTING = [
    ("Solve 2x + 7 = 19", "MATH"),
    ("What causes the seasons on Earth?", "SCIENCE"),
    ("The density of aluminum is 2.7 g/cm^3. What is the mass of 100 "
     "cm^3 of aluminum?", "MIXED"),
    ("Write a short story about a lighthouse", "GENERAL"),
    ("What is the derivative of x^2?", "MATH"),
    ("Why is the sky blue during the day?", "SCIENCE"),
]
for t, r in ROUTING:
    add("domain_routing", t, expected_route=r)

# ---- retrieval_relevance (8, retrieval-only probes) -------------------------
RELEVANCE = [
    ("physics", "How do charged particles move in an electric field?"),
    ("chemistry", "What happens during an acid-base neutralization "
                  "reaction?"),
    ("biology", "How does the immune system recognize pathogens?"),
    ("astronomy", "How do stars form from clouds of gas and dust?"),
    ("earth_science", "How do tectonic plates move and cause "
                      "earthquakes?"),
    ("physics", "What is conservation of energy in a closed system?"),
    ("chemistry", "How does a catalyst speed up a chemical reaction?"),
    ("biology", "How do genes determine inherited traits?"),
]
for dom, t in RELEVANCE:
    add("retrieval_relevance", t, expected_domain=dom,
        supporting_fact="See the corpus article on the topic")

# ---------------------------------------------------------------------------
# T5R.6 retrieval-invocation ground truth per category (declared BEFORE
# any variant runs): whether retrieval SHOULD run for the category.
EXPECTED_RETRIEVAL = {
    "factual_science_qa": True,
    "multi_hop_science_qa": True,
    "quantitative_science": False,      # constants supplied inline
    "insufficient_evidence": True,
    "distractor_retrieval": True,
    "conflicting_evidence": True,
    "source_attribution": True,
    "mixed_math_science": False,        # self-contained computation
}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    qpath = OUT_DIR / "questions.jsonl"
    if qpath.exists():
        print("dev suite already exists; refusing to overwrite", qpath,
              file=sys.stderr)
        return 1
    lines = []
    checksums = {}
    for row in QUESTIONS:
        line = json.dumps(row, ensure_ascii=False)
        line = line + "\n"
        checksums[row["eval_id"]] = hashlib.sha256(
            line.rstrip("\n").encode("utf-8")).hexdigest()
        lines.append(line)
    qpath.write_text("".join(lines), encoding="utf-8")
    (OUT_DIR / "checksum.json").write_text(
        json.dumps(checksums, indent=1), encoding="utf-8")
    cats = Counter(r["category"] for r in QUESTIONS)
    manifest = {
        "name": "mango-rag-dev-v1",
        "purpose": "T5R.12 development set for variant comparison; "
                   "distinct from the frozen mango-rag-eval-v1 suite",
        "n_questions": len(QUESTIONS),
        "categories": dict(cats),
        "expected_retrieval_by_category": EXPECTED_RETRIEVAL,
        "provenance": "authored for T5R (new questions; schema mirrors "
                      "mango-rag-eval-v1)",
        "frozen_suite_untouched": True,
    }
    (OUT_DIR / "suite_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())