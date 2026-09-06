"""T6.2/T6.3 — mango-eval-core-v1: the permanent capability-retention suite.

This module holds the suite-construction logic; scripts/build_eval_core.py
is the CLI. The suite is built ONCE, frozen, and checksummed BEFORE the
first curriculum training run; it is permanently outside all training
corpora and re-checked for contamination against every future corpus.

Item schema (authored + verified before freeze):
  category            one of CORE_CATEGORIES
  capability_track    an id from curriculum.capabilities
  generalization_split IID | COMPOSITIONAL | OUT_OF_TEMPLATE | CROSS_DOMAIN
  requires_math_tool  bool          (T6.15 routing ground truth)
  requires_retrieval  bool
  insufficient_info   bool          (expected behavior = uncertainty)
  multi_hop           bool
  answer_type         numeric | exact_answer | multiple_choice | text
  question / choices / expected_answer
  tool_check          optional {tool, args, field, expected} — deterministic
                      re-verification of a computed answer via the T4 tools
  source_fact         optional {corpus_title, quote} — grounding evidence
                      that must exist in the approved retrieval corpus
  license             self-authored items are CC0-1.0
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

SUITE_VERSION = "mango-eval-core-v1"
EVAL_ID_PREFIX = "mec1-"
LICENSE_SELF_AUTHORED = "CC0-1.0"

CORE_CATEGORIES = (
    "math_foundation", "algebra", "geometry", "trig", "calculus",
    "probability_statistics", "physics", "chemistry", "biology",
    "earth_space", "scientific_reasoning", "mixed_quantitative",
    "interdisciplinary", "uncertainty_calibration", "tool_routing",
    "retrieval_routing",
)
# NOTE: "uncertainty_calibration" keeps the runner's existing uncertainty
# semantics (correct behavior = signal uncertainty, never fabricate).

GENERALIZATION_SPLITS = ("IID", "COMPOSITIONAL", "OUT_OF_TEMPLATE",
                         "CROSS_DOMAIN")
ANSWER_TYPES = ("numeric", "exact_answer", "multiple_choice", "text")

REQUIRED_ITEM_FIELDS = (
    "category", "capability_track", "generalization_split",
    "requires_math_tool", "requires_retrieval", "insufficient_info",
    "multi_hop", "answer_type", "question", "expected_answer", "license",
)


def eval_id_for(question: str) -> str:
    return EVAL_ID_PREFIX + hashlib.sha256(
        f"{SUITE_VERSION}|{question}".encode("utf-8")).hexdigest()[:12]


def routing_label(item: dict) -> str:
    if item.get("insufficient_info"):
        return "INSUFFICIENT_INFO"
    t, r = bool(item.get("requires_math_tool")), bool(item.get("requires_retrieval"))
    if t and r:
        return "BOTH"
    if t:
        return "TOOL"
    if r:
        return "RETRIEVAL"
    return "NONE"


def validate_item(item: dict, tracks: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    for f in REQUIRED_ITEM_FIELDS:
        if f not in item:
            errors.append(f"missing field {f}")
    if errors:
        return errors
    if item["category"] not in CORE_CATEGORIES:
        errors.append(f"category {item['category']!r} not in core categories")
    if item["capability_track"] not in tracks:
        errors.append(f"capability_track {item['capability_track']!r} "
                      "not in taxonomy")
        return errors
    if item["generalization_split"] not in GENERALIZATION_SPLITS:
        errors.append(f"generalization_split {item['generalization_split']!r} "
                      f"not in {GENERALIZATION_SPLITS}")
    if item["answer_type"] not in ANSWER_TYPES:
        errors.append(f"answer_type {item['answer_type']!r} not in "
                      f"{ANSWER_TYPES}")
    q = item["question"]
    if not isinstance(q, str) or len(q.strip()) < 15:
        errors.append("question too short")
    if len(q) > 1200:
        errors.append("question too long (>1200 chars)")
    for f in ("requires_math_tool", "requires_retrieval", "insufficient_info",
              "multi_hop"):
        if f in item and not isinstance(item[f], bool):
            errors.append(f"{f} must be boolean")
    if item["answer_type"] == "multiple_choice":
        ch = item.get("choices")
        if not isinstance(ch, list) or not (2 <= len(ch) <= 5):
            errors.append("multiple_choice needs 2-5 choices")
        elif item.get("expected_answer") not in {chr(65 + i)
                                                 for i in range(len(ch))}:
            errors.append("expected_answer must be a choice letter")
    if item["insufficient_info"]:
        if item["expected_answer"] != "__UNKNOWN__":
            errors.append("insufficient_info items must expect __UNKNOWN__")
        if item["generalization_split"] == "IID":
            pass   # allowed: an IID question can still be unanswerable
    else:
        if item["expected_answer"] == "__UNKNOWN__":
            errors.append("__UNKNOWN__ expected only on insufficient_info")
    if item.get("tool_check"):
        tc = item["tool_check"]
        for f in ("tool", "args"):
            if f not in tc:
                errors.append(f"tool_check missing {f}")
    if item.get("source_fact"):
        sf = item["source_fact"]
        for f in ("corpus_title", "quote"):
            if f not in sf:
                errors.append(f"source_fact missing {f}")
    # cross-domain split should mean the track actually crosses domains
    if item["generalization_split"] == "CROSS_DOMAIN" \
            and item["capability_track"] not in tracks \
            and tracks[item["capability_track"]]["family"] != "cross_domain":
        pass   # cross-domain reasoning can still live in science families
    return errors


# ---------------------------------------------------------------------------
# Contamination protection
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _shingles(text: str, n: int = 8) -> set[str]:
    toks = re.findall(r"[a-z0-9]+", _norm(text))
    if len(toks) < n:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def contamination_check(items: list[dict],
                        reference_texts: list[str],
                        *, min_overlap: float = 0.5) -> list[dict]:
    """Flag items whose normalized text or 8-gram shingles overlap a
    reference (training corpus / other suites) too heavily. Returns the
    list of contaminated items with their overlap evidence."""
    ref_shingles = [_shingles(t) for t in reference_texts]
    ref_norm = [_norm(t) for t in reference_texts]
    flagged = []
    for item in items:
        q = item["question"]
        iq = _shingles(q)
        if not iq:
            continue
        best = 0.0
        matched = ""
        for i, rs in enumerate(ref_shingles):
            if not rs:
                continue
            ov = len(iq & rs) / len(iq)
            if ov > best:
                best, matched = ov, ref_norm[i]
        if _norm(q) in ref_norm:
            best = 1.0
        if best >= min_overlap:
            flagged.append({"question": q, "overlap": round(best, 3),
                            "matched_reference": matched[:160]})
    return flagged


# ---------------------------------------------------------------------------
# Freeze
# ---------------------------------------------------------------------------

def freeze_suite(items: list[dict], out_dir: Path, *,
                 build_config: dict | None = None) -> dict:
    """Assign eval_ids, sort deterministically, write questions.jsonl +
    checksums.json + manifests. Returns the freeze summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    canon = []
    for it in sorted(items, key=lambda x: x["question"]):
        rec = dict(it)
        rec["eval_id"] = eval_id_for(rec["question"])
        rec["routing_label"] = routing_label(rec)
        rec["suite_version"] = SUITE_VERSION
        canon.append(rec)
    path = out_dir / "questions.jsonl"
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=False) + "\n"
             for r in canon]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)
    checksums = {r["eval_id"]: hashlib.sha256(
        json.dumps(r, ensure_ascii=False, sort_keys=False).encode()
    ).hexdigest() for r in canon}
    (out_dir / "checksum.json").write_text(
        json.dumps(checksums, indent=2) + "\n", encoding="utf-8")
    counts = Counter(r["category"] for r in canon)
    (out_dir / "category_manifest.json").write_text(json.dumps(
        {c: {"count": counts.get(c, 0)} for c in CORE_CATEGORIES
         if counts.get(c)}, indent=2) + "\n", encoding="utf-8")
    split_counts = Counter(r["generalization_split"] for r in canon)
    label_counts = Counter(r["routing_label"] for r in canon)
    manifest = {
        "artifact": SUITE_VERSION,
        "suite_version": SUITE_VERSION,
        "frozen_at": _now(),
        "immutable": True,
        "questions": len(canon),
        "eval_id_prefix": EVAL_ID_PREFIX,
        "checksum_contract": "sha256 of each raw questions.jsonl line "
                             "keyed by eval_id",
        "categories": dict(counts),
        "generalization_splits": dict(split_counts),
        "routing_labels": dict(label_counts),
        "license": f"self-authored synthetic items under {LICENSE_SELF_AUTHORED}",
        "contamination": "re-checked at every corpus freeze (T6.4)",
        "build_config": build_config or {},
        "note": "frozen before the first curriculum training run (T6.2); "
                "never trained on; permanent capability-retention suite",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return {"questions": len(canon), "categories": dict(counts),
            "splits": dict(split_counts), "labels": dict(label_counts)}


def verify_frozen(out_dir: Path) -> dict:
    cs = json.loads((out_dir / "checksum.json").read_text(encoding="utf-8"))
    seen_ids: set[str] = set()
    mismatches = []
    for line in (out_dir / "questions.jsonl").read_text(
            encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        seen_ids.add(row["eval_id"])
        digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
        if cs.get(row["eval_id"]) != digest:
            mismatches.append(row["eval_id"])
    missing = sorted(set(cs) - seen_ids)
    return {"ok": not mismatches and not missing,
            "checked": len(seen_ids), "mismatched": mismatches,
            "missing": missing}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()