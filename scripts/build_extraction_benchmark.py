"""Build extraction negative benchmark suite (T9)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t9" / "extraction-benchmark" / "v1"

CASES = [
    # correct reasoning + wrong boxed answer
    {
        "eval_id": "ext-v1-001",
        "category": "extraction_negative",
        "case_class": "wrong_boxed_answer",
        "question": "What is 2 + 2?",
        "raw_model_output": "The sum is 4. \\boxed{5}",
        "expected_answer": "4",
        "answer_type": "numeric",
        "description": "Correct reasoning but wrong boxed answer",
    },
    # wrong reasoning + correct distractor number
    {
        "eval_id": "ext-v1-002",
        "category": "extraction_negative",
        "case_class": "distractor_number",
        "question": "What is 3 * 7?",
        "raw_model_output": "3 times 7 is 25. No wait, 3 * 7 = 21. \\boxed{21}",
        "expected_answer": "21",
        "answer_type": "numeric",
        "description": "Wrong intermediate, correct final in box",
    },
    # multiple candidate values
    {
        "eval_id": "ext-v1-003",
        "category": "extraction_negative",
        "case_class": "multiple_candidates",
        "question": "Solve x^2 = 16",
        "raw_model_output": "The solutions are x = 4 or x = -4. Therefore x = 4. \\boxed{4}",
        "expected_answer": "4",
        "answer_type": "numeric",
        "description": "Multiple values mentioned, last boxed is correct",
    },
    # unit mismatch
    {
        "eval_id": "ext-v1-004",
        "category": "extraction_negative",
        "case_class": "unit_mismatch",
        "question": "Convert 2 km to meters",
        "raw_model_output": "2 km = 2000 m. \\boxed{2}",
        "expected_answer": "2000",
        "answer_type": "numeric",
        "description": "Correct reasoning but boxed answer missing unit conversion",
    },
    # quoted answer from prompt
    {
        "eval_id": "ext-v1-005",
        "category": "extraction_negative",
        "case_class": "quoted_from_prompt",
        "question": "The previous answer was 42. What is the answer?",
        "raw_model_output": "The answer is 42. \\boxed{42}",
        "expected_answer": "42",
        "answer_type": "numeric",
        "description": "Answer quoted from prompt, correctly boxed",
    },
    # LaTeX distractor
    {
        "eval_id": "ext-v1-006",
        "category": "extraction_negative",
        "case_class": "latex_distractor",
        "question": "What is the derivative of x^2?",
        "raw_model_output": "The derivative is 2x. \\boxed{\\frac{dy}{dx} = 2x}",
        "expected_answer": "2x",
        "answer_type": "numeric",
        "description": "LaTeX in boxed, should extract 2x",
    },
    # markdown bold distractor
    {
        "eval_id": "ext-v1-007",
        "category": "extraction_negative",
        "case_class": "markdown_bold_distractor",
        "question": "What is 10 / 2?",
        "raw_model_output": "The result is **5**. The answer is **5**. \\boxed{5}",
        "expected_answer": "5",
        "answer_type": "numeric",
        "description": "Markdown bold distractor, boxed answer correct",
    },
    # MCQ distractor
    {
        "eval_id": "ext-v1-008",
        "category": "extraction_negative",
        "case_class": "mcq_distractor",
        "question": "Which is the capital of France? A) London B) Paris C) Berlin",
        "raw_model_output": "The capital is Paris. Option B. \\boxed{B}",
        "expected_answer": "B",
        "answer_type": "multiple_choice",
        "choices": ["A", "B", "C"],
        "description": "MCQ with distractor option, correct boxed",
    },
    # corrected value followed by stale old value
    {
        "eval_id": "ext-v1-009",
        "category": "extraction_negative",
        "case_class": "stale_value",
        "question": "What is 15 - 7?",
        "raw_model_output": "15 - 7 = 8. Wait, that's wrong. 15 - 7 = 9. No, 15 - 7 = 8. \\boxed{8}",
        "expected_answer": "8",
        "answer_type": "numeric",
        "description": "Corrected value then stale value, final boxed correct",
    },
    # no boxed answer, fallback to last line
    {
        "eval_id": "ext-v1-010",
        "category": "extraction_negative",
        "case_class": "no_boxed_fallback",
        "question": "What is 9 * 9?",
        "raw_model_output": "9 times 9 equals 81. So the answer is 81.",
        "expected_answer": "81",
        "answer_type": "numeric",
        "description": "No boxed, fallback to last line extraction",
    },
    # multiple boxed, last one wins
    {
        "eval_id": "ext-v1-011",
        "category": "extraction_negative",
        "case_class": "multiple_boxed",
        "question": "What is 5 + 5?",
        "raw_model_output": "First thought: \\boxed{11}. Corrected: \\boxed{10}",
        "expected_answer": "10",
        "answer_type": "numeric",
        "description": "Multiple boxed, last one should win",
    },
    # partial boxed with extra text
    {
        "eval_id": "ext-v1-012",
        "category": "extraction_negative",
        "case_class": "partial_boxed",
        "question": "What is 100 / 4?",
        "raw_model_output": "100 divided by 4 is 25. \\boxed{25} is the answer.",
        "expected_answer": "25",
        "answer_type": "numeric",
        "description": "Boxed with trailing text",
    },
    # answer is pattern
    {
        "eval_id": "ext-v1-013",
        "category": "extraction_negative",
        "case_class": "answer_is_pattern",
        "question": "What is 7 * 8?",
        "raw_model_output": "The answer is 56.",
        "expected_answer": "56",
        "answer_type": "numeric",
        "description": "Answer is pattern without boxed",
    },
    # structured JSON answer
    {
        "eval_id": "ext-v1-014",
        "category": "extraction_negative",
        "case_class": "json_answer",
        "question": "What is 12 * 12?",
        "raw_model_output": '{"final_answer": "144"}',
        "expected_answer": "144",
        "answer_type": "numeric",
        "description": "Structured JSON answer format",
    },
    # hash marker (GSM8K style)
    {
        "eval_id": "ext-v1-015",
        "category": "extraction_negative",
        "case_class": "hash_marker",
        "question": "What is 11 * 11?",
        "raw_model_output": "11 * 11 = 121 #### 121",
        "expected_answer": "121",
        "answer_type": "numeric",
        "description": "GSM8K hash marker format",
    },
    # thinking block not closed
    {
        "eval_id": "ext-v1-016",
        "category": "extraction_negative",
        "case_class": "unclosed_thinking",
        "question": "What is 6 * 6?",
        "raw_model_output": "<think>6 * 6 = 36</think> The answer is 36. \\boxed{36}",
        "expected_answer": "36",
        "answer_type": "numeric",
        "description": "Thinking block properly closed",
    },
    # thinking block never closed
    {
        "eval_id": "ext-v1-017",
        "category": "extraction_negative",
        "case_class": "unclosed_thinking_fail",
        "question": "What is 8 * 8?",
        "raw_model_output": "<think>8 * 8 = 64... The answer is 64.",
        "expected_answer": "64",
        "answer_type": "numeric",
        "description": "Thinking block never closed - should return empty",
    },
    # boxed with units
    {
        "eval_id": "ext-v1-018",
        "category": "extraction_negative",
        "case_class": "boxed_with_units",
        "question": "Convert 1 hour to seconds",
        "raw_model_output": "1 hour = 3600 seconds. \\boxed{3600 s}",
        "expected_answer": "3600",
        "answer_type": "numeric",
        "description": "Boxed answer includes units",
    },
    # fraction in boxed
    {
        "eval_id": "ext-v1-019",
        "category": "extraction_negative",
        "case_class": "fraction_in_boxed",
        "question": "What is 1/2 + 1/3?",
        "raw_model_output": "1/2 + 1/3 = 5/6. \\boxed{\\frac{5}{6}}",
        "expected_answer": "5/6",
        "answer_type": "numeric",
        "description": "Fraction in LaTeX boxed",
    },
    # empty boxed
    {
        "eval_id": "ext-v1-020",
        "category": "extraction_negative",
        "case_class": "empty_boxed",
        "question": "What is 0 * 100?",
        "raw_model_output": "Zero times anything is zero. \\boxed{}",
        "expected_answer": "0",
        "answer_type": "numeric",
        "description": "Empty boxed - extraction should fail",
    },
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=True) for r in CASES]
    payload = ("\n".join(lines) + "\n").encode()
    (OUT / "questions.jsonl").write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    manifest = {
        "name": "mango-extraction-benchmark-v1",
        "frozen": True,
        "questions": len(CASES),
        "case_counts": {
            "wrong_boxed_answer": 1,
            "distractor_number": 1,
            "multiple_candidates": 1,
            "unit_mismatch": 1,
            "quoted_from_prompt": 1,
            "latex_distractor": 1,
            "markdown_bold_distractor": 1,
            "mcq_distractor": 1,
            "stale_value": 1,
            "no_boxed_fallback": 1,
            "multiple_boxed": 1,
            "partial_boxed": 1,
            "answer_is_pattern": 1,
            "json_answer": 1,
            "hash_marker": 1,
            "unclosed_thinking": 1,
            "unclosed_thinking_fail": 1,
            "boxed_with_units": 1,
            "fraction_in_boxed": 1,
            "empty_boxed": 1,
        },
        "sha256": checksum,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (OUT / "checksum.json").write_text(json.dumps({"questions.jsonl": checksum}, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()