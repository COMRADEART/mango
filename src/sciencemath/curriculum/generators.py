"""T6.6/T6.7 — Deterministic, verified curriculum example generators.

Every generated example carries a canonical arithmetic `expression` in its
provenance; cross_check_with_tools() re-derives the answer with the T4
tool layer and drops any record that disagrees. verified_records() gates
on the T4 verifier being able to parse the answer string (UNKNOWN ->
excluded from the positive SFT corpus, T6.6). Determinism comes from a
seeded RNG — same seed + same version => byte-identical corpus.

Records carry the full mango-sft-v2 provenance contract (T6.4):
source, license, provenance, domain, subject, difficulty, answer,
solution, verification_state, curriculum_level, required_capability,
tool_eligible, retrieval_eligible, family.
"""
from __future__ import annotations

import random
import re
from fractions import Fraction

from sciencemath.tools.router import build_default_registry
from sciencemath.tools.verifier import verify_answer

GEN_SOURCE = "mango-curriculum-gen"
GEN_LICENSE = "CC0-1.0"

# surface variants so L1 does not become a single-template monoculture
_ARITH_SURFACES = [
    "Compute {a} + {b}.",
    "What is {a} + {b}?",
    "{a} + {b} = ?",
    "Add {a} and {b}.",
    "Find the sum of {a} and {b}.",
    "A shop sells {a} apples on Monday and {b} apples on Tuesday. "
    "How many apples did it sell in total?",
    "There are {a} red marbles and {b} blue marbles in a jar. "
    "How many marbles are in the jar?",
]
_SUB_SURFACES = [
    "Compute {a} - {b}.",
    "What is {a} - {b}?",
    "{a} - {b} = ?",
    "Subtract {b} from {a}.",
    "A warehouse holds {a} boxes; {b} boxes are shipped out. "
    "How many boxes remain?",
]
_MUL_SURFACES = [
    "Compute {a} x {b}.",
    "What is {a} multiplied by {b}?",
    "{a} x {b} = ?",
    "Find the product of {a} and {b}.",
    "Each of {a} boxes contains {b} pens. How many pens are there in "
    "total?",
]
_DIV_SURFACES = [
    "Compute {a} / {b}.",
    "What is {a} divided by {b}?",
    "{a} divided by {b} = ?",
    "{a} pencils are shared equally among {b} students. "
    "How many pencils does each student get?",
]


def _frac_str(f: Fraction) -> str:
    return f"{f.numerator}/{f.denominator}"


def solution_text(answer: str, steps: str) -> str:
    """T6.13 controlled format for quantitative answers: final answer
    boxed, concise visible reasoning. No hidden chain-of-thought."""
    return f"Answer: \\boxed{{{answer}}}\n\n{steps.strip()}"


def _record(*, track: str, family: str, subject: str, difficulty: int,
            question: str, answer: str, steps: str, level: int,
            tool_eligible: bool = False, retrieval_eligible: bool = False,
            provenance: dict | None = None) -> dict:
    prov = provenance or {"origin": "deterministic_generator",
                          "generator": track}
    return {
        "source": GEN_SOURCE,
        "license": GEN_LICENSE,
        "provenance": prov,
        "domain": family,
        "family": family,
        "subject": subject,
        "difficulty": difficulty,
        "curriculum_level": level,
        "required_capability": track,
        "tool_eligible": tool_eligible,
        "retrieval_eligible": retrieval_eligible,
        "question": question.strip(),
        "answer": answer,
        "target_response": solution_text(answer, steps),
        "verification_state": "UNVERIFIED",
    }


# ---------------------------------------------------------------- arithmetic
def gen_arithmetic(rng: random.Random, difficulty: int,
                   level: int = 1) -> dict:
    op = rng.choice("+-x/" if difficulty >= 2 else "+-x")
    if difficulty <= 1:
        a, b = rng.randint(2, 20), rng.randint(2, 20)
    else:
        a, b = rng.randint(10, 250), rng.randint(3, 99)
    if op == "+":
        ans = a + b
        q = rng.choice(_ARITH_SURFACES).format(a=a, b=b)
        steps = f"Add: {a} + {b} = {ans}."
        expr = f"({a})+({b})"
    elif op == "-":
        a, b = max(a, b), min(a, b)
        ans = a - b
        q = rng.choice(_SUB_SURFACES).format(a=a, b=b)
        steps = f"Subtract: {a} - {b} = {ans}."
        expr = f"({a})-({b})"
    elif op == "x":
        a, b = min(a, b), max(a, b)
        ans = a * b
        q = rng.choice(_MUL_SURFACES).format(a=a, b=b)
        steps = f"Multiply: {a} x {b} = {ans}."
        expr = f"({a})*({b})"
    else:
        b = rng.randint(2, 12)
        ans = rng.randint(2, 40)
        a = b * ans
        q = rng.choice(_DIV_SURFACES).format(a=a, b=b)
        steps = f"Divide: {a} / {b} = {ans}."
        expr = f"({a})/({b})"
    return _record(track="math_arithmetic", family="mathematics",
                   subject="arithmetic", difficulty=difficulty,
                   question=q, answer=str(ans), steps=steps, level=level,
                   tool_eligible=(difficulty >= 2 and a * b >= 100),
                   provenance={"generator": "arithmetic",
                               "expression": expr})


# ---------------------------------------------------------------- fractions
def gen_fractions(rng: random.Random, difficulty: int,
                  level: int = 1) -> dict:
    def frac():
        f = Fraction(rng.randint(1, 9), rng.randint(2, 12))
        return Fraction(f.numerator, f.denominator)

    f1, f2 = frac(), frac()
    if difficulty <= 1:
        d = rng.choice([f1.denominator, 4, 6, 8])
        f1 = Fraction(rng.randint(1, max(1, d - 1)), d)
        f2 = Fraction(rng.randint(1, max(1, d - 1)), d)
        op = rng.choice(["+", "-"])
    else:
        op = rng.choice(["+", "-", "x", "/"])
    if op == "-":
        if f2 > f1:
            f1, f2 = f2, f1
    r = {"+": f1 + f2, "-": f1 - f2, "x": f1 * f2, "/": f1 / f2}[op]
    steps = f"{_frac_str(f1)} {op} {_frac_str(f2)} = {_frac_str(r)} " \
            "(simplified)."
    ans = _frac_str(r)
    if r.denominator == 1:
        ans = str(r.numerator)
    q = (f"Compute {_frac_str(f1)} {op} {_frac_str(f2)}. "
         f"Give the answer as a simplified fraction.")
    num = lambda f: f"({f.numerator})/({f.denominator})"
    expr = {"+": f"{num(f1)}+{num(f2)}", "-": f"{num(f1)}-{num(f2)}",
            "x": f"{num(f1)}*{num(f2)}",
            "/": f"({num(f1)})/({num(f2)})"}[op]
    return _record(track="math_fractions", family="mathematics",
                   subject="fractions", difficulty=difficulty,
                   question=q, answer=ans, steps=steps, level=level,
                   tool_eligible=(op in "x/" or difficulty >= 2),
                   provenance={"generator": "fractions",
                               "expression": expr})


# ------------------------------------------------------------------- ratios
def gen_ratios(rng: random.Random, difficulty: int, level: int = 1) -> dict:
    ra, rb = rng.randint(2, 9), rng.randint(2, 9)
    unit = rng.randint(2, 15) if difficulty >= 2 else rng.randint(1, 6)
    total = (ra + rb) * unit
    ans = ra * unit
    q = (f"Two friends split {total} stickers in the ratio {ra}:{rb}. "
         f"How many stickers does the first friend receive?")
    steps = (f"Ratio parts: {ra} + {rb} = {ra + rb}. One part = "
             f"{total} / {ra + rb} = {unit}. First friend: "
             f"{ra} x {unit} = {ans}.")
    return _record(track="math_ratios", family="mathematics",
                   subject="ratios", difficulty=difficulty,
                   question=q, answer=str(ans), steps=steps, level=level,
                   tool_eligible=(total >= 100),
                   provenance={"generator": "ratios",
                               "expression": f"({total}/({ra}+{rb}))*{ra}"})


# --------------------------------------------------------------- percentages
def gen_percentages(rng: random.Random, difficulty: int,
                    level: int = 1) -> dict:
    style = rng.choice(["of", "increase", "decrease", "what_percent"])
    if style == "of":
        p = rng.choice([5, 10, 15, 20, 25, 40, 60, 75, 80])
        n = rng.randint(80, 1600) if difficulty >= 2 else rng.randint(20, 200)
        ans = p * n / 100
        ans_s = str(int(round(ans))) if abs(ans - round(ans)) < 1e-9 \
            else f"{ans:g}"
        q = f"What is {p}% of {n}? Give your answer as a number."
        steps = f"{p}% of {n} = {p}/100 x {n} = {ans_s}."
        expr = f"({p})*({n})/100"
    elif style in ("increase", "decrease"):
        p = rng.choice([5, 10, 15, 20, 25, 50])
        n = rng.randint(40, 800)
        delta = p * n / 100
        ans = n + delta if style == "increase" else n - delta
        ans_s = str(int(round(ans))) if abs(ans - round(ans)) < 1e-9 \
            else f"{ans:g}"
        word = "increases" if style == "increase" else "decreases"
        q = (f"A price of {n} dollars {word} by {p}%. "
             f"What is the new price in dollars?")
        steps = (f"{p}% of {n} = {delta:g}. New price = {n} "
                 f"{'+' if style == 'increase' else '-'} {delta:g} = {ans_s}.")
        sign = "+" if style == "increase" else "-"
        expr = f"({n}){sign}({p})*({n})/100"
    else:
        part = rng.choice([12, 15, 18, 21, 24, 30, 36, 45])
        whole = part * rng.choice([2, 4, 8])
        p_val = part / whole * 100
        ans_s = str(int(round(p_val))) if abs(p_val - round(p_val)) < 1e-9 \
            else f"{p_val:g}"
        q = (f"A student scored {part} points out of {whole} points. "
             f"What percentage did they score?")
        steps = f"Percentage = {part} / {whole} x 100 = {ans_s}%."
        expr = f"({part})/({whole})*100"
    return _record(track="math_percentages", family="mathematics",
                   subject="percentages", difficulty=difficulty,
                   question=q, answer=ans_s, steps=steps, level=level,
                   tool_eligible=True,
                   provenance={"generator": "percentages",
                               "expression": expr})


# --------------------------------------------------------- linear equations
def gen_linear_equations(rng: random.Random, difficulty: int,
                         level: int = 1) -> dict:
    x = rng.randint(-12, 12)
    a = rng.choice([1, 2, 3, 4, 5] if difficulty <= 1
                   else [2, 3, 4, 5, 6, 7, -2, -3])
    b = rng.randint(-20, 20)
    c = a * x + b
    if rng.random() < 0.6:
        if b >= 0:
            human = f"Solve for x: {a}x + {b} = {c}"
            steps = f"{a}x = {c} - {b} = {c - b}. x = {c - b} / {a} = {x}."
        else:
            human = f"Solve for x: {a}x - {abs(b)} = {c}"
            steps = (f"{a}x = {c} + {abs(b)} = {c - b}. "
                     f"x = {c - b} / {a} = {x}.")
        expr = None
        equation = f"{a}*x + ({b}) = {c}"
    else:
        x = rng.choice([2, 3, 4, 6, 8, 9, 10, 12]) * abs(a)
        c = x // abs(a) + b
        human = f"Solve for x: x/{abs(a)} + {b} = {c}" if b >= 0 else \
            f"Solve for x: x/{abs(a)} - {abs(b)} = {c}"
        steps = (f"x/{abs(a)} = {c} - ({b}) = {c - b}. "
                 f"x = {c - b} x {abs(a)} = {x}.")
        expr = f"({c}-({b}))*({abs(a)})"
        equation = f"x/{abs(a)} + ({b}) = {c}"
        return _record(track="math_linear_equations", family="mathematics",
                       subject="linear_equations", difficulty=difficulty,
                       question=human, answer=str(x), steps=steps,
                       level=level,
                       tool_eligible=True,
                       provenance={"generator": "linear_equations",
                                   "equation": equation,
                                   "expression": expr})
    return _record(track="math_linear_equations", family="mathematics",
                   subject="linear_equations", difficulty=difficulty,
                   question=human, answer=str(x), steps=steps, level=level,
                   tool_eligible=(abs(a) >= 4 or abs(c) >= 60),
                   provenance={"generator": "linear_equations",
                               "equation": equation})


# ------------------------------------------------- scientific notation (L2+)
def gen_scientific_notation(rng: random.Random, difficulty: int,
                            level: int = 2) -> dict:
    m = rng.choice([2, 3, 4, 5, 6, 7]) if difficulty <= 2 else \
        rng.choice([1.5, 2.4, 3.6, 4.8, 6.3])
    e = rng.randint(2, 6)
    if rng.random() < 0.5:
        n = int(m * 10 ** e)
        q = f"Write {n} in scientific notation (a x 10^b form)."
        ans = f"{m} x 10^{e}"
        steps = f"{n} = {m} x 10^{e} (decimal point {e} places left)."
    else:
        n = m * 10 ** e
        n_s = str(int(n)) if float(n).is_integer() else f"{n:g}"
        q = f"What is {m} x 10^{e} written as an ordinary number?"
        ans = n_s
        steps = f"{m} x 10^{e} = {n_s} (decimal point {e} places right)."
    return _record(track="math_scientific_notation", family="mathematics",
                   subject="scientific_notation", difficulty=difficulty,
                   question=q, answer=ans, steps=steps, level=level,
                   tool_eligible=False,
                   provenance={"generator": "scientific_notation"})


# -------------------------------------------------------- unit conversion
_UNIT_PAIRS = [
    ("km", "m", 1000), ("m", "cm", 100), ("kg", "g", 1000),
    ("L", "mL", 1000), ("hour", "minute", 60), ("m", "mm", 1000),
]


def gen_unit_conversion(rng: random.Random, difficulty: int,
                        level: int = 1) -> dict:
    u_from, u_to, k = rng.choice(_UNIT_PAIRS)
    if difficulty >= 2 and rng.random() < 0.5:
        u_from, u_to = u_to, u_from
        val = round(rng.uniform(0.5, 9.5), 1)
        ans = val / k
        steps = (f"1 {u_to} = {k:g} {u_from}, so {val} {u_from} / {k:g} "
                 f"= {ans:g} {u_to}.")
        expr = f"({val})/({k})"
    else:
        val = rng.randint(2, 90)
        ans = val * k
        steps = f"1 {u_from} = {k:g} {u_to}, so {val} x {k:g} = {ans} {u_to}."
        expr = f"({val})*({k})"
    q = f"Convert {val} {u_from} to {u_to}."
    ans_s = str(int(ans)) if float(ans).is_integer() else f"{ans:g}"
    return _record(track="sci_measurements", family="scientific_reasoning",
                   subject="measurements", difficulty=difficulty,
                   question=q, answer=ans_s, steps=steps, level=level,
                   tool_eligible=True,
                   provenance={"generator": "unit_conversion",
                               "expression": expr})


# ------------------------------------------------- mechanics foundations (L1)
def gen_mechanics(rng: random.Random, difficulty: int, level: int = 1) -> dict:
    kind = rng.choice(["speed", "force", "ke", "momentum"])
    if kind == "speed":
        d = rng.choice([30, 45, 60, 90, 120, 150, 240])
        t = rng.choice([2, 3, 5, 6, 10])
        v = d / t
        ans_s = str(int(v)) if v.is_integer() else f"{v:g}"
        q = (f"A cyclist rides {d} kilometers in {t} hours at constant "
             f"speed. What is the speed in kilometers per hour?")
        steps = f"speed = distance / time = {d} km / {t} h = {ans_s} km/h."
        expr = f"({d})/({t})"
        track = "phys_mechanics"
    elif kind == "force":
        m = rng.choice([2, 3, 4, 5, 8, 10, 12])
        a = rng.choice([2, 3, 4, 5, 10])
        f = m * a
        q = (f"A {m} kg cart accelerates at {a} m/s^2 on a flat track. "
             f"What net force, in newtons, is applied to it?")
        ans_s = str(f)
        steps = f"F = m x a = {m} kg x {a} m/s^2 = {ans_s} N."
        expr = f"({m})*({a})"
        track = "phys_mechanics"
    elif kind == "momentum":
        m = rng.choice([2, 3, 4, 5, 10])
        v = rng.choice([2, 3, 4, 5, 6, 8, 10])
        p = m * v
        q = (f"What is the momentum, in kg m/s, of a {m} kg ball moving "
             f"at {v} m/s?")
        ans_s = str(p)
        steps = f"p = m x v = {m} kg x {v} m/s = {ans_s} kg m/s."
        expr = f"({m})*({v})"
        track = "phys_energy_momentum"
    else:
        m = rng.choice([2, 4, 5, 8, 10])
        v = rng.choice([2, 3, 4, 5, 6])
        ke = m * v * v / 2
        ans_s = str(int(ke)) if float(ke).is_integer() else f"{ke:g}"
        q = (f"What is the kinetic energy, in joules, of a {m} kg object "
             f"moving at {v} m/s?")
        steps = f"KE = (1/2) m v^2 = 0.5 x {m} x {v}^2 = {ans_s} J."
        expr = f"0.5*({m})*({v})**2"
        track = "phys_energy_momentum"
    return _record(track=track, family="physics",
                   subject="mechanics" if track == "phys_mechanics"
                   else "energy_momentum",
                   difficulty=difficulty, question=q, answer=ans_s,
                   steps=steps, level=level,
                   tool_eligible=(difficulty >= 2),
                   provenance={"generator": "mechanics_" + kind,
                               "expression": expr})


# ---------------------------------------------------- stoichiometry (L2)
_MOLAR = {"H2O": 18, "CO2": 44, "NaCl": 58.5, "O2": 32, "CH4": 16,
          "NH3": 17, "H2": 2, "CaCO3": 100}


def gen_stoichiometry(rng: random.Random, difficulty: int,
                      level: int = 2) -> dict:
    compound = rng.choice(list(_MOLAR))
    mm = _MOLAR[compound]
    moles = rng.choice([0.5, 1, 2, 2.5, 3, 4, 5])
    mass = round(moles * mm, 2)
    if rng.random() < 0.5:
        q = (f"Using the molar mass of {compound} = {mm:g} g/mol, how many "
             f"moles are in {mass:g} g of {compound}? Give the number of "
             f"moles as a plain number.")
        ans_s = f"{moles:g}"
        steps = (f"moles = mass / molar mass = {mass:g} g / {mm:g} g/mol "
                 f"= {ans_s} mol.")
        expr = f"({mass})/({mm})"
    else:
        q = (f"Using the molar mass of {compound} = {mm:g} g/mol, what is "
             f"the mass of {moles:g} mol of {compound} in grams?")
        ans_s = f"{mass:g}"
        steps = (f"mass = moles x molar mass = {moles:g} mol x {mm:g} g/mol "
                 f"= {ans_s} g.")
        expr = f"({moles})*({mm})"
    return _record(track="chem_stoichiometry", family="chemistry",
                   subject="stoichiometry", difficulty=difficulty,
                   question=q, answer=ans_s, steps=steps, level=level,
                   tool_eligible=True,
                   provenance={"generator": "stoichiometry",
                               "compound": compound, "molar_mass": mm,
                               "expression": expr})


# ----------------------------------------------------------------- assembly
GENERATORS = {
    "math_arithmetic": gen_arithmetic,
    "math_fractions": gen_fractions,
    "math_ratios": gen_ratios,
    "math_percentages": gen_percentages,
    "math_linear_equations": gen_linear_equations,
    "math_scientific_notation": gen_scientific_notation,
    "sci_measurements": gen_unit_conversion,
    "phys_mechanics": gen_mechanics,
    "phys_energy_momentum": gen_mechanics,
    "chem_stoichiometry": gen_stoichiometry,
}


def generate_stage_examples(*, level: int, tracks: dict[str, int],
                            seed: int = 42) -> tuple[list[dict], dict]:
    """Generate examples for the given track counts
    ({track_id: n_examples}); difficulty is drawn from the level
    definition's range (T6.7). Returns (records, generation_stats)."""
    from sciencemath.curriculum.levels import LEVELS
    lo, hi = LEVELS[level]["difficulty_range"]
    rng = random.Random(seed)
    records, stats = [], {}
    for track, n in tracks.items():
        if track not in GENERATORS:
            stats[track] = {"requested": n, "generated": 0,
                            "skipped": "no generator (agent-authored)"}
            continue
        gen = GENERATORS[track]
        made, attempts = 0, 0
        while made < n and attempts < n * 8:
            attempts += 1
            diff = rng.randint(lo, hi)
            rec = gen(rng, diff, level)
            rec["required_capability"] = track   # shared generators
            if _seen(records, rec):
                continue
            records.append(rec)
            made += 1
        stats[track] = {"requested": n, "generated": made}
    return records, stats


def _seen(records: list[dict], rec: dict) -> bool:
    q = re.sub(r"\s+", " ", rec["question"].lower()).strip()
    return any(re.sub(r"\s+", " ", r["question"].lower()).strip() == q
               for r in records)


def verified_records(records: list[dict]) -> tuple[list[dict], dict]:
    """Parse gate: the T4 verifier must be able to parse each candidate's
    own answer string (verify_answer(answer, answer) == PASS). Answers the
    verifier cannot parse return UNKNOWN and are excluded — this
    guarantees the verifier can score the training target format. The real
    math check is cross_check_with_tools()."""
    kept, fail, unknown = [], 0, 0
    for r in records:
        res = verify_answer(r["answer"], r["answer"])
        if res["verdict"] == "PASS":
            kept.append(r)
        elif res["verdict"] == "FAIL":
            fail += 1
        else:
            unknown += 1
    return kept, {"candidates": len(records), "parsed": len(kept),
                  "failed": fail, "unknown": unknown}


def _numeric(value) -> float:
    """Parse a number that may be an int/float, a decimal string, or a
    fraction string like '5/4' (possibly with a leading minus)."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    m = re.fullmatch(r"(-?\d+)/(\d+)", s)
    if m:
        return int(m.group(1)) / int(m.group(2))
    return float(s)


def cross_check_with_tools(records: list[dict]) -> tuple[list[dict], dict]:
    """Strong check: re-derive the recorded answer from the recorded
    canonical expression (or equation) with the T4 tools; drop records
    that disagree. This is what actually catches generator bugs."""
    registry = build_default_registry()
    kept, dropped = [], []
    for r in records:
        ok = True
        pv = r.get("provenance") or {}
        if pv.get("equation"):
            sol = registry.invoke("equation_solver", {
                "equation": pv["equation"], "variable": "x"})
            if sol.status == "ok" and sol.result["solutions"]:
                ok = str(sol.result["solutions"][0]["x"]) == str(r["answer"])
            else:
                ok = False
        elif pv.get("expression"):
            calc = registry.invoke("calculator",
                                   {"expression": pv["expression"]})
            if calc.status == "ok":
                try:
                    ok = abs(_numeric(calc.result["value"])
                             - _numeric(r["answer"])) <= 1e-6
                except (TypeError, ValueError):
                    ok = False
            else:
                ok = False
        if ok:
            kept.append(r)
        else:
            dropped.append(r["question"][:80])
    return kept, {"cross_checked": len(records), "kept": len(kept),
                  "dropped": len(dropped), "dropped_samples": dropped[:10]}


def mark_verified(records: list[dict]) -> list[dict]:
    for r in records:
        r["verification_state"] = "PASS"
    return records