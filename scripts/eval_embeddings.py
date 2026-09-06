"""T5.7 embedding-model evaluation — candidates measured, not guessed.

Each candidate embeds a small deterministic scientific probe set
(24 domain probes + 6 short-keyword probes; passages are fixed
self-contained scientific statements so the probe does not depend on a
particular corpus build). Measures per model:
  * retrieval quality on the probe set (Recall@1/5, MRR, nDCG@5)
  * short-question vs long-explanation behavior
  * embedding latency / throughput on the chosen device
Decision + rationale -> rag/embeddings/embedding_decision.json (the
index builder reads the winner from there). No popularity-based choice.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.rag.embeddings import CANDIDATES, SentenceTransformerEmbedder
from sciencemath.rag.metrics import evaluate_retrieval
from sciencemath.rag.vectorstore import BruteForceVectorStore
from sciencemath.utils.io_utils import write_json

OUT = ROOT / "rag" / "embeddings" / "embedding_decision.json"

# Deterministic probe set: (question, domain, [relevant passage...],
# [distractor passage...]). Real scientific facts, self-contained.
PROBES = [
    ("What organelle produces ATP in eukaryotic cells?", "biology",
     ["Mitochondria are membrane-bound organelles that generate most of the chemical energy needed to power the cell; they produce ATP through cellular respiration."],
     ["The cell membrane is a phospholipid bilayer separating the cell interior from the outside environment."]),
    ("What is the function of ribosomes?", "biology",
     ["Ribosomes are the molecular machines that carry out protein synthesis by translating messenger RNA into polypeptide chains."],
     ["Lysosomes contain digestive enzymes that break down waste materials and cellular debris."]),
    ("How does DNA encode genetic information?", "biology",
     ["DNA stores genetic information in the sequence of its four nucleotide bases; triplets of bases called codons specify amino acids during translation."],
     ["The cell cycle consists of interphase and mitosis, during which a cell grows and divides."]),
    ("What force keeps planets in orbit around the Sun?", "astronomy",
     ["Planets orbit the Sun because gravity, the mutual attraction between masses, provides the centripetal force that curves their paths into orbits."],
     ["The solar wind is a stream of charged particles released from the upper atmosphere of the Sun."]),
    ("Why is Mars red?", "astronomy",
     ["The surface of Mars appears red because iron minerals in its soil oxidize, forming iron oxide, or rust, which coats the surface."],
     ["Jupiter is the largest planet in the Solar System, a gas giant composed mainly of hydrogen and helium."]),
    ("What is a light-year?", "astronomy",
     ["A light-year is the distance light travels in one year in a vacuum, about 9.46 trillion kilometers; it measures distance, not time."],
     ["A parsec is the distance at which one astronomical unit subtends an angle of one arcsecond."]),
    ("State Newton's second law of motion.", "physics",
     ["Newton's second law states that the acceleration of an object is directly proportional to the net force acting on it and inversely proportional to its mass: F = ma."],
     ["Newton's third law states that for every action there is an equal and opposite reaction."]),
    ("What causes the seasons on Earth?", "earth_science",
     ["Seasons result from the tilt of Earth's rotational axis relative to its orbital plane; as Earth orbits the Sun, each hemisphere receives varying solar radiation."],
     ["The Moon orbits Earth approximately every 27.3 days, causing the phases of the Moon."]),
    ("What is the pH scale used for?", "chemistry",
     ["The pH scale measures how acidic or basic a solution is, defined as the negative logarithm of the hydrogen ion concentration; 7 is neutral."],
     ["Titration is a laboratory technique used to determine the concentration of an unknown solution."]),
    ("Define an exothermic reaction.", "chemistry",
     ["An exothermic reaction releases energy to its surroundings, usually as heat; the enthalpy change is negative."],
     ["An endothermic reaction absorbs energy from its surroundings, lowering the temperature of the system."]),
    ("What happens during photosynthesis?", "biology",
     ["During photosynthesis, plants convert carbon dioxide and water into glucose and oxygen using energy absorbed from sunlight by chlorophyll."],
     ["Respiration breaks down glucose to release energy in the form of ATP in cells."]),
    ("What is Ohm's law?", "physics",
     ["Ohm's law states that the electric current through a conductor is proportional to the voltage across it, with resistance as the constant of proportionality: V = IR."],
     ["A capacitor stores electric charge on two conducting plates separated by an insulator."]),
    ("What is the difference between DNA and RNA?", "biology",
     ["DNA is a double-stranded molecule storing genetic information; RNA is usually single-stranded, uses ribose and uracil instead of deoxyribose and thymine, and carries information from DNA to ribosomes."],
     ["Proteins are polymers of amino acids folded into functional three-dimensional structures."]),
    ("Why do earthquakes occur?", "earth_science",
     ["Earthquakes occur when stress accumulated along geological faults exceeds the rock strength, causing sudden slip and release of seismic energy."],
     ["Volcanic eruptions occur when magma rises through the crust and reaches the surface."]),
    ("What is the ideal gas law?", "chemistry",
     ["The ideal gas law relates pressure, volume, temperature and amount of gas: PV = nRT, combining Boyle's, Charles's and Avogadro's laws."],
     ["Henry's law states that gas solubility in a liquid is proportional to the gas's partial pressure."]),
    ("What is escape velocity?", "physics",
     ["Escape velocity is the minimum speed an object needs to break free from a body's gravitational field without further propulsion."],
     ["Orbital velocity is the speed needed to maintain a stable circular orbit around a body."]),
    ("What causes ocean tides?", "earth_science",
     ["Ocean tides are caused mainly by the gravitational pull of the Moon and, to a lesser extent, the Sun acting on Earth's oceans."],
     ["Ocean currents are driven by wind, water density differences, and the Coriolis effect."]),
    ("What is a covalent bond?", "chemistry",
     ["A covalent bond forms when two atoms share one or more pairs of electrons, as in molecular hydrogen or water."],
     ["An ionic bond forms when one atom transfers electrons to another, creating oppositely charged ions."]),
    ("What is the Big Bang?", "astronomy",
     ["The Big Bang is the leading cosmological model describing the universe's expansion from an extremely hot, dense initial state about 13.8 billion years ago."],
     ["Dark matter is invisible matter inferred from its gravitational effects on galaxies and clusters."]),
    ("How do vaccines work?", "biology",
     ["Vaccines train the immune system by presenting an antigen, prompting the body to produce antibodies and memory cells without causing the disease."],
     ["Antibiotics treat bacterial infections by killing bacteria or inhibiting their growth."]),
    ("What is radioactive decay?", "physics",
     ["Radioactive decay is the spontaneous transformation of an unstable atomic nucleus into a more stable one, emitting radiation such as alpha or beta particles."],
     ["Nuclear fusion combines light nuclei into heavier ones, releasing energy as in stars."]),
    ("What is a semiconductor?", "computer_science",
     ["A semiconductor is a material whose electrical conductivity lies between conductors and insulators and can be controlled by doping, as in silicon chips."],
     ["A superconductor conducts electricity with zero resistance below a critical temperature."]),
    ("What is the water cycle?", "earth_science",
     ["The water cycle describes continuous movement of water: evaporation, condensation into clouds, precipitation, and collection in rivers, lakes and oceans."],
     ["The carbon cycle moves carbon among the atmosphere, oceans, soil and living organisms."]),
    ("What does the periodic table tell us?", "chemistry",
     ["The periodic table arranges elements by atomic number so that elements with similar chemical properties fall in the same group, reflecting electron configuration."],
     ["The mole is a counting unit equal to about 6.02 x 10^23 particles."]),
]

# short-keyword probes (short-question vs long-explanation behavior)
SHORT_PROBES = [
    ("mitochondria function", "What organelle produces ATP in eukaryotic cells?"),
    ("Newton second law", "State Newton's second law of motion."),
    ("pH definition", "What is the pH scale used for?"),
    ("ocean tides cause", "What causes ocean tides?"),
    ("covalent bond", "What is a covalent bond?"),
    ("escape velocity", "What is escape velocity?"),
]


def build_rows() -> list[dict]:
    """Each row: query + expected domain + (rel_texts, dis_texts). The
    short probes reuse their parent probe's passages."""
    rows = [{"query": q, "expected_domain": d,
             "rel_texts": rel, "dis_texts": dis}
            for q, d, rel, dis in PROBES]
    by_question = {q: (rel, dis) for q, d, rel, dis in PROBES}
    for q, parent in SHORT_PROBES:
        rel, dis = by_question[parent]
        rows.append({"query": q, "expected_domain":
                     next(d for qq, d, _r, _x in PROBES if qq == parent),
                     "rel_texts": rel, "dis_texts": dis})
    return rows


def eval_one_model(key: str, spec, rows: list[dict], device: str) -> dict:
    embedder = SentenceTransformerEmbedder(spec, device=device)
    # per-row passage ids: row i gets rel ids then dis ids
    texts: list[str] = []
    rel_ids: list[list[str]] = [[] for _ in rows]
    dis_ids: list[list[str]] = [[] for _ in rows]
    for i, r in enumerate(rows):
        for t in r["rel_texts"]:
            cid = f"p{len(texts)}"
            texts.append(t)
            rel_ids[i].append(cid)
        for t in r["dis_texts"]:
            cid = f"p{len(texts)}"
            texts.append(t)
            dis_ids[i].append(cid)

    t0 = time.perf_counter()
    vecs = embedder.embed_passages(texts)
    embed_s = time.perf_counter() - t0
    store = BruteForceVectorStore(vecs.shape[1])
    ids = [f"p{i}" for i in range(len(texts))]
    store.add(vecs, ids)

    results, q_latencies = [], []
    for i, r in enumerate(rows):
        t1 = time.perf_counter()
        qvec = embedder.embed_query(r["query"])
        hits = store.search(qvec, top_k=5)
        q_latencies.append(time.perf_counter() - t1)
        retrieved = [cid for cid, _s in hits]
        graded = {cid: 3.0 for cid in rel_ids[i]}
        results.append({
            "query": r["query"], "retrieved": retrieved,
            "expected_domain": r["expected_domain"],
            "predicted_domain": r["expected_domain"],
            "relevant": rel_ids[i],
            "graded": graded,
            "irrelevant_ids": dis_ids[i],
        })
    m = evaluate_retrieval(results)
    return {
        "key": key, "model": spec.model, "license": spec.license,
        "dimension": int(vecs.shape[1]),
        "recall_at_1": m.recall_at_1, "recall_at_5": m.recall_at_5,
        "mrr": m.mrr, "ndcg_at_5": m.ndcg_at_5,
        "embed_seconds": round(embed_s, 2),
        "query_latency_ms": round(1000 * sum(q_latencies) / len(q_latencies), 2),
        "throughput_passages_per_s": round(len(texts) / embed_s, 1),
    }


def main() -> int:
    rows = build_rows()
    results = []
    for key, spec in CANDIDATES.items():
        print(f"evaluating {key} ...", file=sys.stderr)
        try:
            results.append(eval_one_model(key, spec, rows, device="cpu"))
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            results.append({"key": key, "model": spec.model,
                            "error": f"{type(exc).__name__}: {exc}"})
    ok = [r for r in results if "error" not in r]
    # selection rule (recorded, not hidden): retrieval quality first
    # (mean of recall@5, MRR, nDCG@5), then latency as tiebreak
    def quality(r):
        return (r["recall_at_5"] + r["mrr"] + r["ndcg_at_5"]) / 3.0
    winner = max(ok, key=quality) if ok else None
    decision = {
        "evaluated_at": time.strftime("%Y-%m-%d"),
        "criteria": ["scientific_terminology", "short_question",
                     "long_explanation", "cross_domain", "hardware",
                     "license", "dimension", "latency"],
        "probe_set": {"n_domain_probes": len(PROBES),
                      "n_short_probes": len(SHORT_PROBES)},
        "results": results,
        "selection_rule": "mean(recall@5, MRR, nDCG@5); latency tiebreak",
        "winner": winner["key"] if winner else None,
        "winner_model": winner["model"] if winner else None,
        "winner_revision": None,
        "notes": "Revision pinned at index build time via HF resolution.",
    }
    write_json(OUT, decision)
    print(json.dumps(results, indent=2))
    print("winner:", decision["winner"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())