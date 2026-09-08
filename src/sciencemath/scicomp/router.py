"""scicomp router — deterministic compute-eligibility routing (T11.13).

Decides whether a question needs scientific computation and which
category of operation applies, BEFORE any LLM tool-call generation. The
router is rule-based (keyword/regex patterns over question text) and
NEVER executes anything — it recommends a route:

    LINEAR_ALGEBRA, NUMERICAL_INTEGRATION, DERIVATIVE, ROOT_FINDING,
    ODE, OPTIMIZATION, STATISTICS, INTERPOLATION, PARAMETER_SWEEP,
    NO_COMPUTE

No second LLM is involved. Precision/recall/wrong-tool/unnecessary-compute
of the router are measured against eval labels (T11.13, T11.20); route
conflicts with the T4 math router are counted at integration time
(T11.34).
"""
from __future__ import annotations

import re

ROUTE_NO_COMPUTE = "NO_COMPUTE"

# Conceptual-question guard: interrogative/definitional forms that mention
# math vocabulary but ask for an explanation, not a computation. Checked
# BEFORE the category rules (first match wins ordering still applies to
# compute routing). Kept narrow so computational forms ("What is the rank
# of the matrix", "Compute the mean of ...") are never suppressed.
_CONCEPTUAL_GUARD: re.Pattern = re.compile(
    r"^\s*(is it |is the |is an |is a |is every |is interpolation|"
    r"state the |does |can |why |should |explain |give one reason|"
    r"what does |what is the difference|what is a |what is overfitting|"
    r"what is the definition|what assumptions|what information|"
    r"what parameter |if a |if an )", re.I)

# Ordered rules: first match wins. Each rule is (category, pattern).
# Patterns target the *computation request*, not the science topic:
# "eigenvalues of", "integrate ... from .. to", "solve the ODE".
_RULES: list[tuple[str, re.Pattern]] = [
    # --- linear algebra ---
    (r"LINEAR_ALGEBRA", re.compile(
        r"\b(eigenvalues?|eigenvectors?|determinant|matrix (multiply|"
        r"inverse|rank|norm)|inverse of (the |a )?matrix|invert( the)?"
        r" (the )?matrix|multiply (the )?matrices|matrix (product|"
        r"multiplication)|(l2|l1|linf|infinity|euclidean|frobenius) norm|"
        r"norm of (the )?(vector|matrix)|rank of (the |a )?matrix|"
        r"solve the (matrix |system of )?(linear )?(equations?|system)|"
        r"least.?squares|condition number|linear system)\b", re.I)),
    # --- ODE before integration (ODEs mention both) ---
    (r"ODE", re.compile(
        r"\b(ODE|ordinary differential equation|initial value problem|"
        r"d[iy]ffeq?|solve the differential equation|differential "
        r"equation .*(initial condition|t\s*=\s*0))\b|"
        r"\bd[a-z0-9]{1,2}/dt\b", re.I)),
    # --- integration ---
    (r"NUMERICAL_INTEGRATION", re.compile(
        r"\b(integrate|integral of|definite integral|area under|"
        r"∫)\b|\b[vip]\(t\)\s*=|\bhow far\b|\bhow much (charge|energy)"
        r"\b|\bhow many (liters|coulombs)\b", re.I)),
    # --- derivative ---
    (r"DERIVATIVE", re.compile(
        r"\b(derivative of|differentiate|d/dx|slope of the (curve|"
        r"tangent)|rate of change (of|at))\b", re.I)),
    # --- root finding ---
    (r"ROOT_FINDING", re.compile(
        r"\b(root of|zero of|zeros of|find x where|find x such that|"
        r"solve .*(for x)|nonlinear (equation|root)|crosses (the )?"
        r"x.?axis)\b", re.I)),
    # --- optimization ---
    (r"OPTIMIZATION", re.compile(
        r"\b(minimize|minimise|maximize|maximise|optimal value|"
        r"optim[au]m|best fit parameters?|argmin|argmax|find the "
        r"(minimum|maximum))\b", re.I)),
    # --- statistics ---
    (r"STATISTICS", re.compile(
        r"\b(mean of|mean value|sample mean|median|standard deviation|"
        r"variance|confidence interval|correlation|regress(ion)?|"
        r"linear fit|p.?value|statistically significant|t.?test|"
        r"t.?statistic|z.?score|percentile|quartile|skew|"
        r"normal distribution|binomial distribution|poisson|"
        r"P\s*\(\s*[A-Za-z]\s*[<=])", re.I)),
    # --- interpolation / fitting ---
    (r"INTERPOLATION", re.compile(
        r"\b(interpolat\w+|extrapolat\w+|curve fit|fit (a|the) (curve|"
        r"line|model|polynomial)|\d-parameter model|unique polynomial|"
        r"through the points|polynomial through)\b", re.I)),
    # --- parameter sweep ---
    (r"PARAMETER_SWEEP", re.compile(
        r"\b(sweep|parameter (scan|grid|study)|sensitivity (table|"
        r"analysis)|for (all|each) (values?|combinations?)|grid of "
        r"values)\b", re.I)),
]


def route(question: str) -> dict:
    """Deterministic routing decision for one question.

    Returns {"route": <category|NO_COMPUTE>, "matched_term": str|None,
    "confidence": "pattern"} — pure function, no execution.
    """
    if not isinstance(question, str) or not question.strip():
        return {"route": ROUTE_NO_COMPUTE, "matched_term": None,
                "confidence": "empty_input"}
    if _CONCEPTUAL_GUARD.match(question):
        return {"route": ROUTE_NO_COMPUTE, "matched_term": None,
                "confidence": "conceptual_form"}
    for category, pattern in _RULES:
        m = pattern.search(question)
        if m:
            return {"route": category, "matched_term": m.group(0),
                    "confidence": "pattern"}
    return {"route": ROUTE_NO_COMPUTE, "matched_term": None,
            "confidence": "no_pattern"}


def route_metrics(decisions: list[tuple[str, str]]) -> dict:
    """Precision/recall/wrong-tool/unnecessary-compute for a set of
    routing decisions (T11.13).

    decisions: list of (predicted_route, gold_label) pairs where
    gold_label is a route category or NO_COMPUTE.
    """
    compute_routes = {c for c, _ in _RULES}
    tp = fp = fn = tn = wrong_tool = unnecessary = 0
    for predicted, gold in decisions:
        pred_compute = predicted in compute_routes
        gold_compute = gold in compute_routes
        if pred_compute and gold_compute:
            if predicted == gold:
                tp += 1
            else:
                wrong_tool += 1      # compute needed, wrong category
        elif pred_compute and not gold_compute:
            fp += 1
            unnecessary += 1
        elif not pred_compute and gold_compute:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp + wrong_tool) if (tp + fp + wrong_tool) else None
    recall = tp / (tp + fn + wrong_tool) if (tp + fn + wrong_tool) else None
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "wrong_tool": wrong_tool,
        "unnecessary_compute": unnecessary,
        "precision": precision,
        "recall": recall,
    }