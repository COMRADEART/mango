"""Build, verify, and freeze mango-eval-core-v1 (T6.2/T6.3).

Pipeline (all gates must pass before the suite is frozen):
  1. merge authored staging items and apply adversarial verdicts
     (REJECT and UNSURE are excluded — reviewed/excluded)
  2. schema validation against the capability taxonomy
  3. tool_check verification: re-run the declared T4 tool invocation and
     compare against expected_answer (0 false-PASS tolerance, T6.24)
  4. source_fact verification: quotes must appear verbatim in the
     approved retrieval corpus (T6.6)
  5. contamination check vs training corpora and the frozen eval suites
  6. freeze + checksum + verify_frozen

Usage: python scripts/build_eval_core.py [--freeze]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from sciencemath.curriculum.capabilities import track_ids, track_spec  # noqa: E402
from sciencemath.curriculum.eval_core import (  # noqa: E402
    CORE_CATEGORIES, SUITE_VERSION, contamination_check, eval_id_for,
    freeze_suite, routing_label, validate_item, verify_frozen,
)
from sciencemath.tools.router import build_default_registry  # noqa: E402

AUTHORED = REPO / "evaluations" / "t6" / "eval_core_staging" / "authored"
VERDICTS = REPO / "evaluations" / "t6" / "eval_core_staging" / "verdicts"
RAG_CORPUS = REPO / "rag" / "corpus" / "wikipedia_en.jsonl"
OUT_DIR = REPO / "evaluations" / "eval-core" / "v1"

_CONTAM_REFS = (
    "training/datasets/sciencemath-sft-v1/train.jsonl",
    "training/datasets/sciencemath-sft-v1/validation.jsonl",
    "evaluations/suite/v1/questions.jsonl",
    "evaluations/rag-suite/v1/questions.jsonl",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _numeric(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    m = re.fullmatch(r"(-?\d+)/(\d+)", s)
    if m:
        return int(m.group(1)) / int(m.group(2))
    return float(s)


def _dig(result: dict, path: str):
    """Resolve 'solutions[0].x' style field paths into tool results."""
    cur = result
    for token in re.findall(r"\[([^]]+)\]|\.?([A-Za-z_][A-Za-z0-9_]*)",
                            path):
        key = token[0] if token[0] else token[1]
        if isinstance(cur, list) and key.isdigit():
            cur = cur[int(key)]
        elif isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            raise KeyError(path)
    return cur


def check_tool(item: dict, registry) -> str | None:
    """Re-run the item's tool_check; None when consistent, else reason."""
    tc = item.get("tool_check")
    if not tc:
        return None
    inv = registry.invoke(tc["tool"], tc.get("args", {}))
    if inv.status != "ok":
        return f"tool {tc['tool']} failed: {getattr(inv, 'detail', inv)}"
    try:
        got = _dig(inv.result, tc["field"])
    except (KeyError, IndexError, TypeError) as exc:
        return f"field {tc['field']!r} not in result ({exc})"
    try:
        want = _numeric(item["expected_answer"])
        got_n = _numeric(got)
        exp_s = str(item["expected_answer"]).strip()
        m = re.fullmatch(r"(-?\d+)\.(\d+)", exp_s)
        if m:   # expected is rounded to dp decimals -> compare at that precision
            dp = len(m.group(2))
            if abs(got_n - want) > 0.5 * 10 ** (-dp) + 1e-9:
                return (f"tool value {got!r} not equal (at {dp} dp) to "
                        f"expected {exp_s!r}")
        elif abs(got_n - want) > 1e-6:
            return f"tool value {got!r} != expected {item['expected_answer']!r}"
    except (TypeError, ValueError):
        if str(got).strip() != str(item["expected_answer"]).strip():
            return f"tool value {got!r} != expected {item['expected_answer']!r}"
    return None


def load_corpus_pages() -> dict[str, str]:
    pages: dict[str, str] = {}
    with open(RAG_CORPUS, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            title = row.get("title", "")
            pages.setdefault(title, "")
            pages[title] += " " + row.get("text", "")
    return {t: _norm(txt) for t, txt in pages.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true",
                    help="write the frozen suite (default: report only)")
    args = ap.parse_args()

    tracks = {t: track_spec(t) for t in track_ids()}
    registry = build_default_registry()
    pages = load_corpus_pages()

    # One-off, recorded remaps: authors used two track ids outside the
    # frozen taxonomy. Each remap keeps the item's subject matter and is
    # logged in the build report (no silent correction).
    REMAPS = {
        "math_unit_conversion": ("sci_measurements",
                                 "unit-conversion track is sci_measurements"),
        "sci_retrieval_facts": (None, "replaced per item by domain match"),
        "uncertainty_calibration": ("sci_error_uncertainty",
                                    "uncertainty items live in "
                                    "sci_error_uncertainty"),
    }
    ITEM_REMAPS = {
        "Neptune": ("space_planetary", "Triton: planetary astronomy"),
        "1925 doctoral thesis": ("space_stellar", "stellar composition"),
        "fullerene": ("chem_bonding", "cagelike fullerene molecules"),
        "mitochondria": ("bio_cells", "cell biology"),
        "ozone": ("earth_meteorology", "stratospheric ozone"),
        "Helium was first identified": ("space_stellar",
                                        "helium spectral discovery"),
        "seawater": ("earth_oceanography", "ocean chemistry"),
        "Air-quality": ("earth_meteorology", "atmospheric trace gas"),
    }

    merged, dropped, stats = [], [], []
    for path in sorted(AUTHORED.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        verdicts = {}
        vpath = VERDICTS / f"{path.stem}.verdicts.json"
        if vpath.exists():
            for v in json.loads(vpath.read_text(encoding="utf-8"))["verdicts"]:
                verdicts[v["index"]] = v["verdict"]
        kept = rejected = unsure = 0
        for i, item in enumerate(data["items"]):
            track = item.get("capability_track", "")
            if track in REMAPS and track != "sci_retrieval_facts":
                new_track, why = REMAPS[track]
                item["capability_track"] = new_track
                item["author_note"] = (item.get("author_note", "")
                                       + f" [track remapped: {why}]")
            elif track == "sci_retrieval_facts":
                new_track, why = next(
                    ((nt, w) for probe, (nt, w) in ITEM_REMAPS.items()
                     if probe.lower() in item["question"].lower()),
                    (None, "no domain match"))
                if not new_track:
                    dropped.append({"file": path.name, "index": i,
                                    "verdict": "REMAP",
                                    "reason": f"{track}: {why}"})
                    continue
                item["capability_track"] = new_track
                item["author_note"] = (item.get("author_note", "")
                                       + f" [track remapped: {why}]")
            v = verdicts.get(i, "UNVERIFIED")
            if v in ("REJECT", "UNSURE"):
                dropped.append({"file": path.name, "index": i,
                                "verdict": v,
                                "reason": next((vv.get("reason", "") for vv
                                                in json.loads(vpath
                                                .read_text(
                                                encoding="utf-8"))
                                                ["verdicts"]
                                                if vv["index"] == i), "")})
                if v == "REJECT":
                    rejected += 1
                else:
                    unsure += 1
                continue
            errs = validate_item(item, tracks)
            errs and dropped.append({"file": path.name, "index": i,
                                     "verdict": "SCHEMA", "reason": errs})
            if errs:
                kept += 0
                continue
            tc_reason = check_tool(item, registry)
            if tc_reason:
                dropped.append({"file": path.name, "index": i,
                                "verdict": "TOOL_CHECK", "reason": tc_reason})
                continue
            sf = item.get("source_fact")
            if sf:
                page = pages.get(sf["corpus_title"])
                if page is None:
                    dropped.append({"file": path.name, "index": i,
                                    "verdict": "GROUNDING",
                                    "reason": f"title {sf['corpus_title']!r}"
                                              " not in corpus"})
                    continue
                if _norm(sf["quote"]) not in page:
                    dropped.append({"file": path.name, "index": i,
                                    "verdict": "QUOTE", "reason":
                                    "quote not verbatim in corpus"})
                    continue
            merged.append(item)
            kept += 1
        stats.append({"file": path.name, "authored": len(data["items"]),
                      "kept": kept, "rejected": rejected,
                      "unsure": unsure})

    # contamination gate ---------------------------------------------------
    reference = []
    for rel in _CONTAM_REFS:
        p = REPO / rel
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                reference.append(json.loads(line)["question"])
    contaminated = contamination_check(merged, reference)

    by_cat = {c: 0 for c in CORE_CATEGORIES}
    for it in merged:
        by_cat[it["category"]] += 1
    report = {
        "suite": SUITE_VERSION,
        "files": stats,
        "total_kept": len(merged),
        "excluded": dropped,
        "categories": {k: v for k, v in by_cat.items() if v},
        "contamination_flagged": contaminated,
    }
    print(json.dumps({k: report[k] for k in
                      ("suite", "files", "categories")}, indent=2))
    print(f"excluded: {len(dropped)}  contaminated: {len(contaminated)}")
    if dropped:
        for d in dropped[:20]:
            print("  EXCLUDED", d["file"], d["verdict"], str(d["reason"])[:90])

    if contaminated:
        for c in contaminated:
            print("  CONTAMINATED", c["overlap"], c["question"][:70],
                  "<-", c["matched_reference"][:60])
        print("contamination gate FAILED — excluded items required")
        return 1

    ids = [eval_id_for(it["question"]) for it in merged]
    dupes = {q for q in set(ids) if ids.count(q) > 1}
    if dupes:
        print("duplicate eval_ids (identical questions):", len(dupes))
        return 1

    if not args.freeze:
        print("report only (pass --freeze to write the frozen suite)")
        return 0

    build_config = {"merged_from": sorted(p.name for p in
                                          AUTHORED.glob("*.json")),
                    "excluded_count": len(dropped)}
    freeze_summary = freeze_suite(merged, OUT_DIR,
                                  build_config=build_config)
    verify = verify_frozen(OUT_DIR)
    print(json.dumps({"frozen": str(OUT_DIR), "verify": verify,
                      "summary": freeze_summary}, indent=2))
    if not verify["ok"]:
        print("FROZEN CHECKSUM VERIFY FAILED")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())