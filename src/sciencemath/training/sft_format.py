"""Canonical ScienceMath SFT formatting (T3).

One instructional format for the whole corpus. Design rules (T3 contract):

* NO `earable reasoning blocks in training targets. T2 showed unrestricted
  thinking with a 4096-token budget causes mechanical failures (36/37
  extraction failures had an unterminated reasoning block). The T3 training
  protocol is: concise VISIBLE reasoning + explicit final-answer closure,
  rendered through the chat template with enable_thinking=False so training
  and evaluation share one reasoning protocol.
* Math targets end with ``Final answer: \\boxed{...}`` and science targets
  with ``Answer: \\boxed{...}``. The \\boxed{} convention is REQUIRED: the
  frozen sciencemath-eval-v1 prompts instruct exactly that, so training and
  evaluation share the same output contract.
* Reasoning budgets are enforced by character class; targets over budget are
  REJECTED (counted in the quality report), never silently truncated
  mid-sentence (a truncated proof teaches non-closure).
"""
from __future__ import annotations

import re

# ----------------------------------------------------------------- budgets
# Character budgets per target class. Chosen so a target + question fits the
# 1024-token training window with headroom (~4 chars/token worst case).
REASONING_BUDGETS = {
    "math": 1600,          # worked solution + final-answer line
    "science": 700,        # concise explanation + answer line
    "general": 400,        # short instruction-following responses
}

FINAL_MATH = "Final answer:"
FINAL_SCIENCE = "Answer:"

_BOXED_RE = re.compile(r"\\boxed\{")


def last_boxed(text: str) -> str | None:
    """Extract the contents of the last \\boxed{...} (balanced braces)."""
    idx = text.rfind("\\boxed{")
    if idx == -1:
        return None
    depth = 0
    start = idx + len("\\boxed")
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i].strip()
    return None


_GSM_CALC_RE = re.compile(r"<<[^>]*>>")


def strip_gsm8k_solution(raw_answer: str) -> tuple[str, str] | None:
    """Split a raw GSM8K answer ('steps...\\n#### 72') into (solution, final).

    Strips the <<calc=expr>> calculator annotations (they are dataset
    artifacts, not human-readable reasoning). Returns None when the ####
    marker is missing (record cannot teach reliable closure and is rejected
    rather than guessed).
    """
    if "####" not in raw_answer:
        return None
    solution, _, final = raw_answer.rpartition("####")
    solution = _GSM_CALC_RE.sub("", solution)
    return solution.strip(), final.strip().replace(",", "")


def math_response(solution: str, final_answer: str) -> str:
    """Canonical math target: concise worked solution + explicit closure."""
    sol = (solution or "").strip()
    body = f"{sol}\n\n" if sol else ""
    return f"{body}{FINAL_MATH} \\boxed{{{final_answer.strip()}}}"


def science_response(explanation: str, final_answer: str) -> str:
    """Canonical science target: answer first, concise explanation after."""
    expl = (explanation or "").strip()
    head = f"{FINAL_SCIENCE} \\boxed{{{final_answer.strip()}}}"
    return f"{head}\n\n{expl}" if expl else head


def general_response(final_answer: str, explanation: str = "") -> str:
    """Canonical general/instruction target: the asked-for behavior, then at
    most one short explanatory sentence."""
    expl = (explanation or "").strip()
    head = f"{FINAL_SCIENCE} \\boxed{{{final_answer.strip()}}}"
    return f"{head}\n{expl}" if expl else head


# Subjects that carry the short "general reasoning / instruction" budget
# (schema-valid domain is scientific_reasoning; the SUBJECT distinguishes
# behavioral-glue items from substantive science content).
GENERAL_SUBJECTS = frozenset({
    "instruction_following", "unit_conversion", "logic_deduction", "uncertainty",
})


def budget_class(domain: str, subject: str = "") -> str:
    if domain == "mathematics":
        return "math"
    if subject in GENERAL_SUBJECTS:
        return "general"
    return "science"


def within_budget(response: str, domain: str, subject: str = "") -> bool:
    return len(response) <= REASONING_BUDGETS[budget_class(domain, subject)]


def build_target(rec: dict) -> tuple[str | None, str | None]:
    """Build the canonical target_response for a normalized record.

    Returns (target_response, None) on success or (None, reject_reason).

    Source-specific conventions:
      * gsm8k records carry the raw '...steps... #### N' answer; the steps
        become the solution and N the final answer.
      * MATH records carry a solution containing \\boxed{...}; the boxed
        content is the final answer.
      * science records use 'answer' + optional 'explanation'/'support'.
    """
    domain = rec.get("domain", "")
    source = rec.get("source", "")
    answer = str(rec.get("answer") or "").strip()
    solution = str(rec.get("solution") or "").strip()
    explanation = str(rec.get("explanation") or "").strip()

    if domain == "mathematics":
        if source == "gsm8k":
            split = strip_gsm8k_solution(answer)
            if split is None:
                return None, "answer: missing #### closure marker"
            solution, final = split
        else:
            final = last_boxed(solution) or (last_boxed(answer) if "\\boxed{" in answer else None)
            if final is None:
                final = answer if answer and "\n" not in answer and len(answer) <= 60 else None
            if not final:
                return None, "answer: no extractable final answer"
        target = math_response(solution, final)
    elif source == "synthetic-sft-v1":
        # pre-authored targets, stored directly
        target = answer
        if "\\boxed{" not in target:
            return None, "answer: synthetic target missing boxed final answer"
    else:
        if not answer:
            return None, "answer: empty"
        target = science_response(explanation, answer)

    if not within_budget(target, rec.get("domain", ""), rec.get("subject", "")):
        return None, (f"target: exceeds {budget_class(rec.get('domain', ''), rec.get('subject', ''))} "
                      f"reasoning budget ({len(target)} chars)")
    return target, None


def render_training_text(tokenizer, question: str, target_response: str) -> str:
    """Render one training example through the model's chat template.

    enable_thinking=False matches the declared T3 primary evaluation
    protocol: the assistant turn contains no reasoning block, exactly what
    the model should produce at eval time.
    """
    messages = [
        {"role": "user", "content": question.strip()},
        {"role": "assistant", "content": target_response},
    ]
    return tokenizer.apply_chat_template(
        messages, tokenize=False, enable_thinking=False)