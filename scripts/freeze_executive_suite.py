"""T7.20 — Freeze the executive evaluation suite as
mango-executive-eval-v1.

Assembles the workflow-authored per-class files, validates the schema,
checks INSUFFICIENT golds only appear in the classes designed for them,
emits questions.jsonl (with eval_id == question_id for the frozen-suite
checksum contract), a per-question checksum.json, and a manifest.
After freeze, the suite is IMMUTABLE and is never used for training.

Usage: python -X utf8 scripts/freeze_executive_suite.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import t6_entry_gate as t6  # noqa: E402

SUITE = REPO / "evaluations" / "executive-suite" / "v1"

EXPECTED_CLASSES = {
    "simple": "simple", "multi_step_math": "msm",
    "multi_hop_science": "mhs", "mixed": "mixed", "distractor": "dist",
    "missing_info": "minfo", "contradictory": "contr",
    "tool_failure": "toolf", "retrieval_failure": "retf",
    "self_correction": "selfc", "counterfactual": "cfv",
}
INSUFFICIENT_CLASSES = {"missing_info", "contradictory"}
VALID_HARNESS = {"fail_tools", "fail_retrieval"}


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def main() -> int:
    records: list[dict] = []
    errors: list[str] = []
    sources: dict[str, int] = {}

    for path in sorted(SUITE.glob("author_*.json")):
        cls = path.stem.removeprefix("author_")
        data = json.loads(path.read_text(encoding="utf-8"))
        sources = {path.name: len(data)}
        for r in data:
            qid = r.get("question_id", "")
            if r.get("class") != cls:
                errors.append(f"{path.name}: {qid} class mismatch "
                              f"({r.get('class')} != {cls})")
            if not qid.startswith(f"mq-{EXPECTED_CLASSES.get(cls, cls)}-"):
                errors.append(f"{path.name}: {qid} id prefix wrong for "
                              f"class {cls}")
            for f in ("question", "answer_type", "expected_answer"):
                if not r.get(f):
                    errors.append(f"{qid}: missing {f}")
            if r.get("answer_type") not in ("numeric", "text"):
                errors.append(f"{qid}: answer_type "
                              f"{r.get('answer_type')!r} invalid")
            gold = str(r.get("expected_answer", "")).strip().lower()
            if gold == "insufficient" and cls not in INSUFFICIENT_CLASSES:
                errors.append(f"{qid}: INSUFFICIENT gold outside "
                              f"{sorted(INSUFFICIENT_CLASSES)}")
            if gold != "insufficient" and cls in INSUFFICIENT_CLASSES:
                errors.append(f"{qid}: missing_info/contradictory gold "
                              "must be INSUFFICIENT")
            h = r.get("harness") or {}
            if not set(h) <= VALID_HARNESS:
                errors.append(f"{qid}: unknown harness flags {sorted(h)}")
            if cls == "tool_failure" and not h.get("fail_tools"):
                errors.append(f"{qid}: tool_failure must set "
                              "harness.fail_tools")
            if cls == "retrieval_failure" and not h.get("fail_retrieval"):
                errors.append(f"{qid}: retrieval_failure must set "
                              "harness.fail_retrieval")
            records.append(r)
        sources[path.name] = len(data)

    ids = [r["question_id"] for r in records]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        errors.append(f"duplicate question_ids: {sorted(dupes)}")

    # contamination: identical question text in any frozen suite
    frozen_texts: set[str] = set()
    for d in ("evaluations/eval-core/v1", "evaluations/tool-suite/v1",
              "evaluations/rag-suite/v1"):
        p = REPO / d / "questions.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    frozen_texts.add(
                        json.loads(line)["question"].strip().lower())
    for r in records:
        if r["question"].strip().lower() in frozen_texts:
            errors.append(f"{r['question_id']}: exact duplicate of a "
                          "frozen-suite question")

    if errors:
        print("FREEZE BLOCKED:")
        for e in errors:
            print(" -", e)
        return 1

    out_records = []
    for r in sorted(records, key=lambda x: (x["class"],
                                            x["question_id"])):
        rec = dict(r)
        rec["eval_id"] = rec["question_id"]
        rec.setdefault("choices", None)
        out_records.append(rec)

    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True)
             for r in out_records]
    (SUITE / "questions.jsonl").write_text("\n".join(lines) + "\n",
                                           encoding="utf-8")
    (SUITE / "checksum.json").write_text(json.dumps(
        {r["eval_id"]: sha256_text(l) for r, l in
         zip(out_records, lines)}, indent=1), encoding="utf-8")

    per_class: dict[str, int] = {}
    for r in out_records:
        per_class[r["class"]] = per_class.get(r["class"], 0) + 1
    manifest = {
        "suite": "mango-executive-eval-v1",
        "frozen_date": date.today().isoformat(),
        "total": len(out_records),
        "per_class": per_class,
        "source_files": sources,
        "schema": "question_id, eval_id(=question_id), class, question, "
                  "answer_type, choices, expected_answer, harness, notes",
        "insufficient_classes": sorted(INSUFFICIENT_CLASSES),
        "usage": "evaluation ONLY — never used for training (T7.20)",
        "questions_sha256": sha256_text(
            (SUITE / "questions.jsonl").read_text(encoding="utf-8")),
    }
    (SUITE / "manifest.json").write_text(json.dumps(manifest, indent=2),
                                         encoding="utf-8")

    v = t6.verify_question_level_checksums(SUITE)
    print(f"frozen: {len(out_records)} questions, per_class={per_class}")
    print("checksum verify:", v)
    return 0 if v["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())