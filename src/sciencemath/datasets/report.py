"""Dataset validation report: aggregated statistics and data-quality
counters, emitted as JSON + Markdown under data/processed/."""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from sciencemath.utils.io_utils import write_json


def build_validation_report(*, records: list[dict],
                            rejected: list[str] | Counter | None = None,
                            duplicates: list[dict] | None = None,
                            licensing_exclusions: list[dict] | None = None,
                            split_summary: dict | None = None,
                            leakage_report: dict | None = None,
                            metadata: dict | None = None) -> dict:
    dup_list = duplicates or []
    excl = licensing_exclusions or []
    rejected_counter: Counter = Counter(rejected or [])

    by_domain = Counter(r.get("domain", "unknown") for r in records)
    by_subject = Counter(r.get("subject") or "unknown" for r in records)
    by_source = Counter(r.get("source", "unknown") for r in records)
    by_difficulty = Counter(
        str(r.get("difficulty")) if r.get("difficulty") is not None else "unspecified"
        for r in records)
    by_split_source = defaultdict(lambda: Counter())
    for r in records:
        split = r.get("split", "")
        split = split if split in {"train", "validation", "test"} else "unsplit"
        by_split_source[split][r.get("source", "unknown")] += 1

    return {
        "metadata": metadata or {},
        "total_examples": len(records),
        "by_domain": dict(by_domain.most_common()),
        "by_subject": dict(by_subject.most_common(60)),
        "by_source": dict(by_source.most_common()),
        "by_difficulty": dict(sorted(by_difficulty.items())),
        "duplicate_count": len(dup_list),
        "duplicates_by_reason": dict(Counter(d.get("reason", "?") for d in dup_list)),
        "rejected_count": sum(rejected_counter.values()),
        "rejected_by_reason": dict(rejected_counter.most_common(40)),
        "licensing_exclusions": {
            "count": len(excl),
            "by_source": dict(Counter(e.get("source", "?") for e in excl)),
        },
        "splits": split_summary or {},
        "leakage": leakage_report or {},
        "distribution": {
            "by_split": {s: {"total": n} for s, n in
                         (split_summary or {}).get("counts", {}).items()},
            "splits_by_source": {s: dict(c.most_common())
                                 for s, c in by_split_source.items()},
        },
    }


def render_markdown(report: dict) -> str:
    lines = ["# ScienceMath Dataset Validation Report", ""]
    meta = report.get("metadata") or {}
    if meta:
        lines.append(f"*Generated:* {meta.get('generated_at', '')}  ")
        lines.append(f"*Config:* {meta.get('config', '')}  ")
        lines.append("")
    lines.append(f"**Total examples:** {report['total_examples']}")
    lines.append(f"**Duplicates removed:** {report['duplicate_count']} "
                 f"({report['duplicates_by_reason']})")
    lines.append(f"**Rejected examples:** {report['rejected_count']} "
                 f"({list(report['rejected_by_reason'].items())[:10]})")
    lines.append(f"**Licensing exclusions:** {report['licensing_exclusions']['count']} "
                 f"by source: {report['licensing_exclusions']['by_source']}")
    leakage = report.get("leakage") or {}
    lines.append(f"**Contamination check passed:** {leakage.get('passed', 'n/a')}")
    lines.append("")

    lines += ["## Split distribution", "", "| split | count | fraction |", "|---|---|---|"]
    counts = (report.get("splits") or {}).get("counts", {})
    fracs = (report.get("splits") or {}).get("fractions", {})
    for name in ("train", "validation", "test"):
        if name in counts:
            lines.append(f"| {name} | {counts[name]} | {fracs.get(name, 0):.3f} |")

    for title, key in (("Domain", "by_domain"), ("Source", "by_source"),
                       ("Difficulty", "by_difficulty"), ("Subject (top 30)", "by_subject")):
        lines += ["", f"## Examples by {title}", "", "| value | count |", "|---|---|"]
        for k, v in list(report.get(key, {}).items())[:30]:
            lines.append(f"| {k} | {v} |")
    return "\n".join(lines) + "\n"


def save_report(report: dict, out_dir: str | Path, stem: str = "dataset_validation") -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    write_json(json_path, report)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))
    return json_path, md_path