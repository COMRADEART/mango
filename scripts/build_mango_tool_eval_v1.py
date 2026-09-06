"""Build mango-tool-eval-v1 (T4.5) — ADDITIVE tool-evaluation suite.

Composition (150 questions):
  * reused math/science questions from the frozen sciencemath-eval-v1
    (original eval_ids kept, `source_suite` recorded) so the no-tool arm can
    reuse existing base predictions;
  * 30 new synthetic tool-specific questions (units / equations / symbolic)
    whose answers are computed by INDEPENDENT arithmetic in this script
    (plain `math`/`fractions`, never via the T4 tool modules themselves —
    self-verification would bias the suite);
  * every question carries a `correct_tools` annotation (the deterministic
    tool set that should be invoked, [] for pure science prose) used to
    score router invocation precision/recall.

The frozen evaluations/suite/v1 is NOT touched: this suite lives in
evaluations/tool-suite/v1 and only READS from suite/v1.
"""
from __future__ import annotations

import hashlib
import json
import random
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "evaluations" / "suite" / "v1" / "questions.jsonl"
OUT = ROOT / "evaluations" / "tool-suite" / "v1"
VERSION = "mango-tool-eval-v1"
SEED = 42

# category -> correct_tools (router ground-truth annotation)
# two tiers:
#   strict    - the annotation is unambiguous (new synthetic units /
#               equations / symbolic questions, science distractors where
#               NO tool should fire); router P/R are computed on these
#   plausible - reused competition-math questions are heterogeneous (word
#               problems, number theory, min/max), so several tools are
#               legitimately useful; these only contribute a
#               math-routing-coverage rate, never strict P/R
CATEGORY_TOOLS = {
    "arithmetic": ["calculator", "equation_solver", "symbolic_math",
                   "numerical_math"],
    "algebra": ["calculator", "equation_solver", "symbolic_math",
                "numerical_math"],
    "trigonometry_precalculus": ["calculator", "equation_solver",
                                 "symbolic_math"],
    "probability_statistics": ["calculator", "numerical_math"],
    "geometry": ["calculator", "equation_solver", "symbolic_math"],
    "general_science": [],                   # pure prose/MCQ: no tools
    "uncertainty_calibration": [],
    "instruction_following": [],
    "units": ["unit_converter"],
    "equations": ["equation_solver"],
    "symbolic": ["symbolic_math"],
}

STRICT_CATEGORIES = {"units", "equations", "symbolic", "general_science",
                     "uncertainty_calibration", "instruction_following"}

MATH_CATEGORIES = ["arithmetic", "algebra", "probability_statistics",
                   "trigonometry_precalculus"]
REUSE_SCIENCE = 20        # general_science MCQs as routing distractors
N_UNITS = 10
N_EQUATIONS = 10
N_SYMBOLIC = 10


def mev_id(question: str) -> str:
    h = hashlib.sha256(f"{VERSION}|{question}".encode()).hexdigest()[:12]
    return f"mev1-{h}"


def rec(qid: str, **kw) -> dict:
    base = {
        "eval_id": qid,
        "source_suite": kw.pop("source_suite", VERSION),
        "license": kw.pop("license", "MIT"),
        "synthetic": kw.pop("synthetic", True),
        "answer_type": kw.pop("answer_type", "numeric"),
        "correct_tools": kw.pop("correct_tools", []),
        "annotation_kind": "strict"
        if kw.get("category") in STRICT_CATEGORIES else "plausible",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# new synthetic questions — independent answer computation
# ---------------------------------------------------------------------------

def synth_units(rng: random.Random) -> list[dict]:
    """Unit conversions; factors are a tiny independent table."""
    items = []
    table = [
        ("kilometers", "meters", 1000.0), ("centimeters", "meters", 0.01),
        ("milligrams", "grams", 0.001), ("hours", "minutes", 60.0),
        ("days", "hours", 24.0), ("feet", "inches", 12.0),
        ("kilograms", "grams", 1000.0), ("liters", "milliliters", 1000.0),
        ("miles", "feet", 5280.0), ("weeks", "days", 7.0),
    ]
    for i, (src, dst, f) in enumerate(table):
        v = rng.choice([2, 3, 4, 5, 7, 7.5, 12, 0.5, 1.25])
        q = f"Convert {v} {src} to {dst}."
        ans = v * f
        items.append(rec(mev_id(q), question=q,
                         expected_answer=str(ans).rstrip("0").rstrip(".")
                         if isinstance(ans, float) and ans == int(ans)
                         else str(ans),
                         category="units", correct_tools=["unit_converter"]))
    return items


def synth_equations(rng: random.Random) -> list[dict]:
    """Linear/quadratic equations; roots computed independently."""
    items = []
    for i in range(10):
        if i < 6:                                   # ax + b = c
            a = rng.randint(2, 9)
            x = rng.randint(-9, 12)
            b = rng.randint(-9, 9)
            c = a * x + b
            q = f"Solve for x: {a}x + {b} = {c}." if b >= 0 else \
                f"Solve for x: {a}x - {abs(b)} = {c}."
            items.append(rec(mev_id(q), question=q, expected_answer=str(x),
                             category="equations",
                             correct_tools=["equation_solver"]))
        else:                                       # (x - r1)(x - r2)
            r1, r2 = rng.randint(-6, 6), rng.randint(-6, 6)
            b, c = -(r1 + r2), r1 * r2
            sign_b = f"+ {b}" if b >= 0 else f"- {abs(b)}"
            sign_c = f"+ {c}" if c >= 0 else f"- {abs(c)}"
            q = f"Find the roots of x^2 {sign_b}x {sign_c} = 0."
            sols = sorted({r1, r2})
            items.append(rec(mev_id(q), question=q,
                             expected_answer=", ".join(str(s) for s in sols),
                             category="equations",
                             correct_tools=["equation_solver"]))
    return items


def synth_symbolic(rng: random.Random) -> list[dict]:
    """Derivatives/integrals of polynomials with hand-checkable answers."""
    # (term coefficients low -> easy closed forms)
    specs = [
        ("Find the derivative of x**3.", "3*x**2"),
        ("Find the derivative of 2*x**2 + 3*x.", "4*x + 3"),
        ("Find the derivative of x**4.", "4*x**3"),
        ("Find the derivative of sin(x).", "cos(x)"),
        ("Find the derivative of cos(x).", "-sin(x)"),
        ("Find the derivative of exp(x).", "exp(x)"),
        ("Find the derivative of 5*x.", "5"),
        ("Find the derivative of x**2 + x.", "2*x + 1"),
        ("Integrate 2*x with respect to x.", "x**2"),          # + C family
        ("Integrate 3*x**2 with respect to x.", "x**3"),
    ]
    items = []
    for q, ans in specs:
        items.append(rec(mev_id(q), question=q, expected_answer=ans,
                         category="symbolic",
                         answer_type="expression",
                         correct_tools=["symbolic_math"]))
    return items


# ---------------------------------------------------------------------------
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    rows = [json.loads(l) for l in
            SRC.read_text(encoding="utf-8").splitlines() if l.strip()]

    reused, distractors = [], []
    for r in rows:
        cat = r.get("category")
        if cat in MATH_CATEGORIES:
            r2 = dict(r)
            r2["source_suite"] = "sciencemath-eval-v1"
            r2["correct_tools"] = list(CATEGORY_TOOLS[cat])
            r2["annotation_kind"] = \
                "strict" if cat in STRICT_CATEGORIES else "plausible"
            reused.append(r2)
        elif cat == "general_science" and r.get("answer_type") \
                == "multiple_choice" and len(distractors) < REUSE_SCIENCE:
            r2 = dict(r)
            r2["source_suite"] = "sciencemath-eval-v1"
            r2["correct_tools"] = []
            r2["annotation_kind"] = "strict"
            distractors.append(r2)
    distractors.sort(key=lambda r: r["eval_id"])

    new = synth_units(rng) + synth_equations(rng) + synth_symbolic(rng)

    out_rows = reused + distractors + new
    n_by_cat: dict[str, int] = {}
    for r in out_rows:
        n_by_cat[r["category"]] = n_by_cat.get(r["category"], 0) + 1

    with open(OUT / "questions.jsonl", "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    manifest = {
        "version": VERSION,
        "frozen_at": None,           # stamped by the checksum step below
        "seed": SEED,
        "n_questions": len(out_rows),
        "composition": {
            "reused_math_from_sciencemath_eval_v1": len(reused),
            "reused_science_distractors_from_sciencemath_eval_v1":
                len(distractors),
            "new_synthetic_tool_questions": len(new),
        },
        "categories": dict(sorted(n_by_cat.items())),
        "additivity":
            "frozen sciencemath-eval-v1 untouched; this suite only reads it",
        "metrics": [
            "no_tool_vs_tool_enabled_accuracy",
            "router_invocation_precision_recall",
            "verifier_correctness",
            "false_pass_rate (critical, target ~0)",
            "unknown_rate",
        ],
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    (OUT / "category_manifest.json").write_text(
        json.dumps({c: {"n": n, "correct_tools": CATEGORY_TOOLS.get(c, [])}
                    for c, n in sorted(n_by_cat.items())}, indent=2) + "\n",
        encoding="utf-8")

    checksum = {
        json.loads(l)["eval_id"]:
            hashlib.sha256(l.encode()).hexdigest()
        for l in (OUT / "questions.jsonl")
        .read_text(encoding="utf-8").splitlines() if l.strip()
    }
    (OUT / "checksum.json").write_text(
        json.dumps(checksum, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {len(out_rows)} questions to {OUT}")
    print("categories:", dict(sorted(n_by_cat.items())))


if __name__ == "__main__":
    main()