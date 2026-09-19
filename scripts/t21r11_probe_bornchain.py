"""C7 born-pattern article fix — open-corpus probe (dev world)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from sciencemath.knowledge.corpus import load_corpus  # noqa: E402
from sciencemath.knowledge.pipeline import answer_knowledge  # noqa: E402
from sciencemath.knowledge.relations import parse_relation_path  # noqa: E402
import t21r11_diag_world as world  # noqa: E402

PROBES = [
    # born-chain shapes that abstained before the article fix
    "The leader of the Brenn Accord was born in which town?",
    "The author of The Sandglass of Corolla was born in which town?",
    "Within which town was the author of The Orrery of Harrow born?",
    # regression: born-year terminal, clean nominals, C7 frame variants
    "The author of The Sandglass of Corolla was born in which year?",
    "What is the birthplace of the author of The Sandglass of Corolla?",
    "Who is the leader of the Brenn Accord?",
    "When was the Meridian Concord signed?",
    "Who wrote The Sandglass of Corolla?",
    "Tell me who wrote The Orrery of Harrow.",
    "What is the birthplace of Kellsie Dunsterville?",
    # guard: born questions whose nominal head contains 'born' never existed
    # here, but the trailing-frame strip must not eat born frames
    "Where was the leader of the Brenn Accord born?",
]

corpus = load_corpus(world.WORLD_DIR)
out = []
for query in PROBES:
    parsed = parse_relation_path(query)
    result = answer_knowledge(query, corpus)
    out.append({
        "query": query,
        "parsed": [parsed[0], [str(r) for r in parsed[1]]] if parsed else None,
        "status": result.status,
        "answer": result.answer[:220],
        "n_citations": len(result.citations),
        "trace": [t for t in result.decision_trace
                  if "path" in t.lower() or "conflict" in t.lower()],
    })
print(json.dumps(out, indent=1, ensure_ascii=False))