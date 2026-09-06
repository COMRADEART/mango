"""T4.5 benchmark harness for mango-tool-eval-v1.

Four metric families (directive T4.5):

1. `verifier_selftest`  — deterministic, no GPU: gold answers must verify
   PASS, perturbed/garbage answers must NOT (false-PASS rate is the
   critical metric, target ~0), and the UNKNOWN rate is reported.
2. `router_metrics`     — invocation precision/recall of the rule-based
   router against the suite's `correct_tools` annotations (strict rows
   only for P/R; plausible rows contribute a math-routing-coverage rate).
3. `run_no_tool`        — model generation WITHOUT tools (reuses the T2
   runner; predictions for reused eval_ids are copied from the existing
   base runs, only new questions are generated).
4. `run_tool_enabled`   — model generation with a JSON tool-call protocol:
   the model may call a T4 tool by emitting {"tool": ..., "arguments": ...}
   on its own line; the harness executes it via invoke_logged (mandatory
   audit log), feeds the result back, and loops up to MAX_TOOL_ROUNDS.

Scoring in both model arms uses the T4 verifier (verify_model_output) on
the PRESERVED raw output — extraction never rewrites predictions.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from sciencemath.tools.base import ToolRegistry
from sciencemath.tools.router import (ToolCallLogger, build_default_registry,
                                      invoke_logged, route_question)
from sciencemath.tools.verifier import verify_model_output

MAX_TOOL_ROUNDS = 4          # 3 tool calls + final answer round

TOOL_PROTOCOL_INSTRUCTION = """You have access to these deterministic tools:
- calculator: arguments {"expression": "<arithmetic expression>"}
- equation_solver: arguments {"equation": "<e.g. 2*x + 3 = 11>"}
- symbolic_math: arguments {"operation": "simplify|expand|factor|derivative|integral|evaluate", "expression": "<expression>"}
- unit_converter: arguments {"value": <number>, "from_unit": "<unit>", "to_unit": "<unit>"}
- numerical_math: arguments {"operation": "describe|percentile|ncr|npr|factorial|determinant|inverse|multiply|transpose", ...}

To call a tool, end your reply with one line containing ONLY a JSON object:
{"tool": "<tool name>", "arguments": {<arguments as JSON>}}
You will then receive the tool result in a message and may continue.
Use at most 3 tool calls. When you are ready, give your final answer in the required \\boxed{} format.
If no tool is needed, answer directly in the required \\boxed{} format."""

_TOOL_CALL_RE = re.compile(r"^\s*(\{.*\"tool\".*\})\s*$", re.DOTALL)


def load_suite(suite_dir: Path) -> list[dict]:
    rows = []
    with open(Path(suite_dir) / "questions.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# 1. verifier self-test (deterministic)
# ---------------------------------------------------------------------------

def _perturbations(expected: str, answer_type: str) -> list[str]:
    """Deterministic wrong-answer variants; each must NOT verify PASS."""
    if answer_type == "multiple_choice" or expected in (None, ""):
        return []
    # NOTE: appending a bare digit ("\frac{1}{2}" -> "\frac{1}{2}1") is
    # NOT a valid perturbation — implicit multiplication makes it equal
    # the original — so the offset is additive.
    out = [expected + "+1"]               # additive offset
    try:
        v = float(expected)
    except ValueError:
        if "," in expected:
            first, rest = expected.split(",", 1)
            out = [first + "+1," + rest]
        else:
            # symbolic: scale a coefficient instead
            out.append("2*" + expected)
        return [p for p in out if p and p != expected]
    if v == int(v) and abs(v) >= 10:
        digits = str(abs(int(v)))
        if len(digits) >= 2 and digits[0] != digits[1]:
            out.append(digits[1] + digits[0] + digits[2:])   # transpose
    if v != 0:
        out.append(repr(v + 1))           # off-by-one
        out.append(repr(v * 10))          # order of magnitude
    # comma-separated solution sets: perturb ONE element additively (the
    # "2*" prefix trick fails on a leading 0: 2*0 == 0, so the set is
    # genuinely unchanged and PASS would be correct)
    if "," in expected:
        first, rest = expected.split(",", 1)
        out = [first + "+1," + rest]
    return [p for p in out if p and p != expected]


GARBAGE_ANSWERS = ["asdkjhqwe", "the answer is maybe"]


def verifier_selftest(rows: list[dict]) -> dict:
    """Run the verifier over gold / perturbed / garbage answers.

    Returns gold_pass_rate, false_pass_rate (critical), unknown_rate, and
    per-case evidence for any false PASS (which would be a T4 gate failure).
    """
    gold_total = gold_pass = gold_unknown = 0
    wrong_total = wrong_pass = unknown_after_wrong = 0
    false_pass_cases: list[dict] = []
    gold_unknown_cases: list[dict] = []

    for r in rows:
        at = r.get("answer_type", "numeric")
        expected = r.get("expected_answer")
        if expected in (None, "", "__UNKNOWN__"):
            continue                       # uncertainty handled by signal
        # --- gold as model output: must PASS ---
        rec = verify_model(rf"\boxed{{{expected}}}", expected, at,
                           r.get("choices"))
        gold_total += 1
        if rec["verdict"] == "PASS":
            gold_pass += 1
        elif rec["verdict"] == "UNKNOWN":
            gold_unknown += 1
            gold_unknown_cases.append({"eval_id": r["eval_id"],
                                       "expected": expected,
                                       "detail": rec.get("detail")})
        # --- perturbed: must FAIL (never PASS) ---
        for p in _perturbations(str(expected), at):
            rec = verify_model(rf"\boxed{{{p}}}", expected, at,
                               r.get("choices"))
            wrong_total += 1
            if rec["verdict"] == "PASS":
                wrong_pass += 1
                false_pass_cases.append({"eval_id": r["eval_id"],
                                         "perturbed": p, "expected": expected,
                                         "method": rec.get("method")})
            elif rec["verdict"] == "UNKNOWN":
                unknown_after_wrong += 1
    # --- garbage against a numeric reference: must NOT be PASS ---
    numeric_rows = [r for r in rows
                    if r.get("answer_type") == "numeric"
                    and r.get("expected_answer") not in (None, "",
                                                         "__UNKNOWN__")]
    for r in numeric_rows:
        for g in GARBAGE_ANSWERS:
            rec = verify_model(rf"\boxed{{{g}}}", r["expected_answer"],
                               "numeric", None)
            wrong_total += 1
            if rec["verdict"] == "PASS":
                wrong_pass += 1
                false_pass_cases.append({"eval_id": r["eval_id"],
                                         "perturbed": g,
                                         "expected": r["expected_answer"],
                                         "method": rec.get("method")})

    return {
        "gold_cases": gold_total,
        "gold_pass_rate": gold_pass / gold_total if gold_total else None,
        "gold_unknown_rate": gold_unknown / gold_total if gold_total else None,
        "gold_unknown_cases": gold_unknown_cases,
        "wrong_cases": wrong_total,
        "false_pass_rate": wrong_pass / wrong_total if wrong_total else None,
        "wrong_unknown_rate": (unknown_after_wrong / wrong_total
                               if wrong_total else None),
        "false_pass_cases": false_pass_cases,
        "critical_gate": "PASS" if not wrong_pass else "FAIL",
    }


def verify_model(raw: str, expected: str, answer_type: str,
                 choices: list[str] | None) -> dict:
    from sciencemath.tools.verifier import verify_model_output
    at = {"multiple_choice": "multiple_choice"}.get(answer_type,
                                                    "exact_answer")
    return verify_model_output(raw, expected, at, choices=choices)


# ---------------------------------------------------------------------------
# 2. router metrics (deterministic)
# ---------------------------------------------------------------------------

def router_metrics(rows: list[dict]) -> dict:
    """Invocation precision/recall vs `correct_tools`.

    Strict rows (unambiguous annotation) drive precision/recall. Rows with
    correct_tools == [] measure false-positive invocations (a tool routed
    for pure science prose). Plausible rows only contribute
    math_routing_coverage.
    """
    tp = fp = fn = 0
    coverage_total = coverage_hit = 0
    per_question = []
    for r in rows:
        routed = route_question(r["question"])["tools"]
        correct = set(r.get("correct_tools") or [])
        entry = {"eval_id": r["eval_id"], "routed": routed,
                 "correct_tools": sorted(correct),
                 "annotation_kind": r.get("annotation_kind")}
        if r.get("annotation_kind") == "strict":
            hit = set(routed) & correct
            extra = set(routed) - correct
            missed = correct - set(routed)
            tp += len(hit)
            fp += len(extra)
            fn += len(missed)
            entry.update({"tp": sorted(hit), "fp": sorted(extra),
                          "fn": sorted(missed)})
        else:
            coverage_total += 1
            if set(routed) & correct:
                coverage_hit += 1
        per_question.append(entry)

    return {
        "tp": tp, "fp": fp, "fn": fn,
        "invocation_precision": tp / (tp + fp) if (tp + fp) else None,
        "invocation_recall": tp / (tp + fn) if (tp + fn) else None,
        "math_routing_coverage": (coverage_hit / coverage_total
                                  if coverage_total else None),
        "per_question": per_question,
    }


# ---------------------------------------------------------------------------
# 3+4. model arms
# ---------------------------------------------------------------------------

class PredictionWriter:
    """Append-safe JSONL writer (same contract as the T2 runner)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def write(self, record: dict) -> None:
        import os
        self._fh.write(json.dumps(record, ensure_ascii=False,
                                  default=str) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


def done_eval_ids(path: Path) -> set[str]:
    path = Path(path)
    if not path.exists():
        return set()
    done = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                done.add(json.loads(line)["eval_id"])
            except Exception:
                continue
    return done


def _parse_tool_call(text: str) -> dict | None:
    """Last line that is a JSON object with a "tool" key; None otherwise."""
    for line in reversed([l for l in (text or "").splitlines()
                          if l.strip()]):
        m = _TOOL_CALL_RE.match(line)
        if not m:
            continue
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None                     # malformed JSON: treat as final
        if isinstance(obj, dict) and isinstance(obj.get("tool"), str):
            args = obj.get("arguments")
            return {"tool": obj["tool"],
                    "arguments": args if isinstance(args, dict) else {}}
    return None


def run_tool_enabled(*, model, tokenizer, rows: list[dict], out_dir: Path,
                     generation: dict, model_id: str,
                     registry: ToolRegistry | None = None,
                     logger: ToolCallLogger | None = None,
                     max_new_tokens: int = 320, max_seq_tokens: int = 2048,
                     enable_thinking: bool | None = False,
                     tools_enabled: bool = True,
                     question_ids: set[str] | None = None) -> dict:
    """Model arm of the benchmark. With tools_enabled=True this is the
    tool-enabled arm: a JSON tool-call protocol loop where the model may
    end a reply with {"tool": ..., "arguments": ...}; the harness executes
    the call through invoke_logged (every call is in the JSONL audit log),
    feeds the result back, and continues — up to MAX_TOOL_ROUNDS. With
    tools_enabled=False it is the no-tool arm: same harness, same verifier,
    single round, no protocol instruction — the ONLY difference is tool
    access, which keeps the comparison apples-to-apples. Raw output of
    every round is preserved verbatim."""
    import time

    import torch

    registry = registry or build_default_registry()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = out_dir / "predictions.jsonl"
    tool_log_path = out_dir / "tool_calls.jsonl"
    tool_logger = logger or ToolCallLogger(tool_log_path)
    done = done_eval_ids(pred_path)
    writer = PredictionWriter(pred_path)
    fail_log = open(out_dir / "failures.jsonl", "a", encoding="utf-8")

    do_sample = bool(generation.get("do_sample", False))
    seed = int(generation.get("seed", 42))
    n_questions = 0
    try:
        for item in rows:
            qid = item["eval_id"]
            if qid in done or (question_ids and qid not in question_ids):
                continue
            n_questions += 1
            record = {
                "eval_id": qid,
                "category": item.get("category"),
                "source_suite": item.get("source_suite"),
                "question": item["question"],
                "expected_answer": item.get("expected_answer"),
                "answer_type": item["answer_type"],
                "model_id": model_id,
                "arm": "tool_enabled" if tools_enabled else "no_tool",
                "raw_model_output": None,
                "extracted_answer": None,
                "verdict": None,
                "correct": None,
                "tool_calls": [],
                "n_rounds": 0,
                "latency_s": None,
                "input_tokens": None,
                "output_tokens": None,
                "error": None,
            }
            content = item["question"].strip()
            if item.get("answer_type") == "multiple_choice" \
                    and item.get("choices"):
                content = "\n".join(
                    [content, ""] +
                    [f"{chr(65 + i)}. {c}"
                     for i, c in enumerate(item["choices"])] + [""])
            if tools_enabled:
                content += "\n\n" + TOOL_PROTOCOL_INSTRUCTION

            messages = [{"role": "user", "content": content}]
            chunks: list[str] = []
            t0 = time.time()
            n_in_total = n_out_total = 0
            try:
                for round_no in range(MAX_TOOL_ROUNDS if tools_enabled
                                      else 1):
                    templ = tokenizer.apply_chat_template(
                        messages, tokenize=False,
                        add_generation_prompt=True,
                        **({"enable_thinking": enable_thinking}
                           if enable_thinking is not None else {}))
                    torch.manual_seed(seed)
                    if torch.cuda.is_available():
                        torch.cuda.manual_seed_all(seed)
                    inputs = tokenizer(templ, return_tensors="pt",
                                       truncation=True,
                                       max_length=max_seq_tokens)
                    inputs = {k: v.to(model.device) for k, v in
                              inputs.items()}
                    n_in_total += int(inputs["input_ids"].shape[1])
                    gen_kwargs = {"max_new_tokens": max_new_tokens,
                                  "pad_token_id": tokenizer.pad_token_id
                                  or tokenizer.eos_token_id,
                                  "do_sample": False}
                    if do_sample:
                        gen_kwargs.update({
                            "do_sample": True,
                            "temperature": float(generation["temperature"]),
                            "top_p": float(generation["top_p"]),
                            "top_k": int(generation.get("top_k", 0)),
                        })
                    with torch.no_grad():
                        out = model.generate(**inputs, **gen_kwargs)
                    n_out_total += int(out.shape[1]) - \
                        int(inputs["input_ids"].shape[1])
                    text = tokenizer.decode(
                        out[0][int(inputs["input_ids"].shape[1]):],
                        skip_special_tokens=True)
                    chunks.append(f"[round {round_no + 1}]\n{text}")
                    call = _parse_tool_call(text) if tools_enabled else None
                    if call is None or round_no == MAX_TOOL_ROUNDS - 1:
                        break                   # final answer (or cap)
                    result = invoke_logged(
                        registry, tool_logger, qid, call["tool"],
                        call["arguments"])
                    record["tool_calls"].append({
                        "round": round_no + 1,
                        "tool": call["tool"],
                        "arguments": call["arguments"],
                        "status": result.status,
                        "error_code": (result.error or {}).get("code")
                        if result.status == "error" else None,
                    })
                    result_json = json.dumps(
                        result.to_dict()["result"] if result.ok
                        else result.to_dict()["error"])
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user",
                                     "content": "TOOL RESULT: "
                                                + result_json})
            except Exception as exc:            # noqa: BLE001
                record["error"] = f"{type(exc).__name__}: {exc}"

            raw = "\n".join(chunks)
            record.update({
                "raw_model_output": raw,
                "n_rounds": len(chunks),
                "latency_s": round(time.time() - t0, 3),
                "input_tokens": n_in_total,
                "output_tokens": n_out_total,
            })
            rec = verify_model(raw, item.get("expected_answer"),
                               item["answer_type"], item.get("choices"))
            record["extracted_answer"] = rec.get("extracted_answer")
            record["verdict"] = rec["verdict"]
            record["verdict_method"] = rec.get("method")
            record["correct"] = rec["verdict"] == "PASS"
            writer.write(record)
    finally:
        writer.close()
        fail_log.close()

    return {"status": "COMPLETE", "questions_run": n_questions,
            "predictions_path": str(pred_path),
            "tool_log_path": str(tool_log_path)}


def summarize(notool_path: Path, tool_path: Path) -> dict:
    """No-tool vs tool-enabled comparison over matched eval_ids."""
    notool = {r["eval_id"]: r for r in _read_predictions(notool_path)}
    tool = {r["eval_id"]: r for r in _read_predictions(tool_path)}
    common = sorted(set(notool) & set(tool))
    if not common:
        return {"error": "no overlapping eval_ids between arms"}

    def acc(records, ids):
        sub = [records[i] for i in ids]
        return sum(1 for r in sub if r.get("correct")) / len(sub)

    by_cat: dict[str, dict] = {}
    for i in common:
        cat = tool[i].get("category") or notool[i].get("category")
        c = by_cat.setdefault(cat, {"n": 0, "notool": 0, "tool": 0})
        c["n"] += 1
        c["notool"] += bool(notool[i].get("correct"))
        c["tool"] += bool(tool[i].get("correct"))

    verdicts = [tool[i].get("verdict") for i in common]
    n_calls = [len(tool[i].get("tool_calls") or []) for i in common]
    return {
        "n_questions": len(common),
        "no_tool_accuracy": acc(notool, common),
        "tool_enabled_accuracy": acc(tool, common),
        "delta": acc(tool, common) - acc(notool, common),
        "by_category": {c: {"n": v["n"],
                            "no_tool_accuracy": v["notool"] / v["n"],
                            "tool_enabled_accuracy": v["tool"] / v["n"]}
                        for c, v in sorted(by_cat.items())},
        "verdict_counts": {
            "PASS": verdicts.count("PASS"),
            "FAIL": verdicts.count("FAIL"),
            "UNKNOWN": verdicts.count("UNKNOWN"),
        },
        "tool_usage": {
            "questions_with_tool_call":
                sum(1 for n in n_calls if n > 0) / len(common),
            "mean_tool_calls_per_question":
                sum(n_calls) / len(common),
        },
    }


def _read_predictions(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows