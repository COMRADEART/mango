"""Metric computation for evaluation runs. Deterministic, test-covered,
no LLM judging. RAG/citation/tool-use metrics are deliberately NOT here —
those systems do not exist until T4/T5."""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict


def compute_metrics(predictions: list[dict],
                    peak_vram_bytes: int | None = None,
                    model_load_vram_bytes: int | None = None) -> dict:
    """Compute the T2 metric block from a list of prediction dicts (each with
    at least: eval_id, category, correct, refusal, extraction_success,
    latency_s, input_tokens, output_tokens, failure)."""
    total = len(predictions)
    if total == 0:
        return {"total": 0}

    correct = sum(1 for p in predictions if p.get("correct"))
    by_cat: dict[str, list[bool]] = defaultdict(list)
    for p in predictions:
        by_cat.setdefault(p.get("category", "unknown"), []).append(bool(p.get("correct")))
    per_category = {c: round(sum(v) / len(v), 4) for c, v in sorted(by_cat.items())}
    macro = round(sum(per_category.values()) / len(per_category), 4) if per_category else None

    math_macro = _macro(per_category, _MATH_CATEGORY_NAMES)
    science_macro = _macro(per_category, _SCIENCE_CATEGORY_NAMES)

    latencies = [p["latency_s"] for p in predictions
                 if isinstance(p.get("latency_s"), (int, float)) and p.get("latency_s") is not None]
    failures = Counter(p.get("failure") for p in predictions if p.get("failure"))
    metrics = {
        "total": total,
        "overall_accuracy": round(correct / total, 4) if total else 0.0,
        "correct": correct,
        "per_category_accuracy": per_category,
        "macro_category_accuracy": macro,
        "math_macro_accuracy": math_macro,
        "science_macro_accuracy": science_macro,
        "extraction_success_rate": round(
            sum(1 for p in predictions if p.get("extracted_answer") is not None) / total, 4),
        "invalid_response_rate": round(
            sum(1 for p in predictions if p.get("failure") in
                ("EXTRACTION_FAILURE", "INVALID_CHOICE", "FORMAT_FAILURE")) / total, 4),
        "refusal_rate": round(
            sum(1 for p in predictions if p.get("failure") == "REFUSAL") / total, 4),
        "failure_counts": dict(failures),
        "avg_latency_s": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "median_latency_s": round(statistics.median(latencies), 3) if latencies else None,
        "avg_input_tokens": round(sum(p.get("input_tokens") or 0 for p in predictions) / total, 1),
        "avg_output_tokens": round(sum(p.get("output_tokens") or 0 for p in predictions) / total, 1),
        "peak_vram_bytes": peak_vram_bytes,
        "model_load_vram_bytes": model_load_vram_bytes,
    }
    return metrics


_MATH_CATEGORY_NAMES = {"arithmetic", "algebra", "geometry",
                        "trigonometry_precalculus", "calculus",
                        "probability_statistics"}
_SCIENCE_CATEGORY_NAMES = {"physics", "chemistry", "biology",
                           "astronomy_earth_science", "general_science",
                           "interdisciplinary"}


def _macro(per_category: dict, names: set) -> float | None:
    vals = [v for c, v in per_category.items()
            if c in names and v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def metrics_markdown(model_slug: str, metrics: dict) -> str:
    lines = [f"# Evaluation metrics — {model_slug}", ""]
    lines.append(f"*Questions:* {metrics.get('total')}  ")
    lines.append(f"*Overall accuracy:* {metrics.get('overall_accuracy')}  ")
    lines.append(f"*Macro category accuracy:* {metrics.get('macro_category_accuracy')}  ")
    lines.append(f"*Math macro:* {metrics.get('math_macro_accuracy')}  ")
    lines.append(f"*Science macro:* {metrics.get('science_macro_accuracy')}  ")
    lines.append("")
    lines += ["| metric | value |", "|---|---|"]
    for k in ("correct", "extraction_success_rate", "invalid_response_rate",
              "refusal_rate", "avg_latency_s", "median_latency_s",
              "avg_input_tokens", "avg_output_tokens", "peak_vram_bytes",
              "model_load_vram_bytes"):
        if metrics.get(k) is not None:
            lines.append(f"| {k} | {metrics[k]} |")
    lines += ["", "## Per-category accuracy", "", "| category | accuracy |", "|---|---|"]
    for c, v in (metrics.get("per_category_accuracy") or {}).items():
        lines.append(f"| {c} | {v} |")
    lines += ["", "## Failure counts", ""]
    for f, n in sorted((metrics.get("failure_counts") or {}).items()):
        lines.append(f"- {f}: {n}")
    return "\n".join(lines) + "\n"