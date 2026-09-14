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


# --------------------------------------------------------------------------
# T14.2 — compute-necessity taxonomy (deterministic; no second LLM).
# Canonical labels:
#   COMPUTE_REQUIRED          answer materially depends on executing a
#                             deterministic numerical/symbolic tool;
#   COMPUTE_HELPFUL           can reasonably be answered without SciComp
#                             (e.g. T4 unit conversion) but verified
#                             arithmetic could improve reliability;
#   NO_COMPUTE                conceptual / definitional / qualitative /
#                             retrieval-only — do not invoke SciComp;
#   INSUFFICIENT_INFORMATION  required scientific/numerical inputs are
#                             missing or ambiguous — do not invent them.
# Only COMPUTE_REQUIRED automatically routes into SciComp. T12 aliases
# REQUIRED/OPTIONAL/NOT_NEEDED remain as names bound to the new values
# so existing imports keep working; stored labels are the T14 names.
# --------------------------------------------------------------------------
COMPUTE_REQUIRED = "COMPUTE_REQUIRED"
COMPUTE_HELPFUL = "COMPUTE_HELPFUL"
NO_COMPUTE = "NO_COMPUTE"
INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
NECESSITY_REQUIRED = COMPUTE_REQUIRED
NECESSITY_OPTIONAL = COMPUTE_HELPFUL
NECESSITY_NOT_NEEDED = NO_COMPUTE
NECESSITY_INSUFFICIENT_INFORMATION = INSUFFICIENT_INFORMATION

_LEGACY_NECESSITY = {
    COMPUTE_REQUIRED: "REQUIRED",
    COMPUTE_HELPFUL: "OPTIONAL",
    NO_COMPUTE: "NOT_NEEDED",
    INSUFFICIENT_INFORMATION: "NOT_NEEDED",
    "REQUIRED": "REQUIRED",
    "OPTIONAL": "OPTIONAL",
    "NOT_NEEDED": "NOT_NEEDED",
}

# Strong computation verbs (T12 feature, retained as one signal).
_STRONG_COMPUTE: re.Pattern = re.compile(
    r"\b(compute|calculate|evaluate|integrate|differentiate|solve|"
    r"determinant|eigenvalues?|invert|interpolat\w+|extrapolat\w+|"
    r"minimize|minimise|maximize|maximise|fit|regress\w*|sweep|"
    r"confidence interval|p.?value|t.?test|z.?score)\b", re.I)
# Broader computation *request* (T14.3) — nouns and find-forms the T12
# verb list missed ("find the root", "multiply the matrices", "norm of").
_COMPUTE_REQUEST: re.Pattern = re.compile(
    r"\b(compute|calculate|evaluate|integrate|integral of|differentiate|"
    r"derivative of|solve|estimate|simulate|optimize|optimise|"
    r"minimize|minimise|maximize|maximise|interpolat\w+|extrapolat\w+|"
    r"fit|regress\w*|sweep|"
    r"find (the )?(root|zero|zeros|eigenvalues?|determinant|rank|norm|"
    r"mean|median|variance|correlation|minimum|maximum)|"
    r"find x such that|multiply (the )?matrices|invert( the)?( the)?"
    r" matrix|matrix (multiply|product|inverse|rank|norm)|"
    r"how far|how much (charge|energy|distance|work)|"
    r"how long in seconds|how many grams remain|"
    r"what is (the |its )?(euclidean|l2|l1|rank|norm|mean|median|"
    r"determinant|correlation|pearson|speed|energy|current|pressure|"
    r"distance|displacement|orbital speed|velocity)|"
    r"what distance|what energy|what current|net displacement|"
    r"grams remain|charge in coulombs)\b", re.I)
# Question data carriers (T12) plus T14 structured-data forms.
_DATA_CARRIER: re.Pattern = re.compile(
    r"\[[^\]]*\d[^\]]*\]|\bfrom\s+-?\d|\bto\s+-?\d|=\s*-?\d+(\.\d+)?"
    r"(\s*,\s*-?\d+(\.\d+)?){2,}|\bat\s+[xyt]?\s*=\s*-?\d", re.I)
_MATRIX_VECTOR: re.Pattern = re.compile(
    r"\[[^\]\[]*\d[^\]\[]*(;|,)[^\]\[]*\d|\(\s*-?\d+(?:\.\d+)?(?:\s*,\s*"
    r"-?\d+(?:\.\d+)?){1,}\s*\)|x\s*=\s*\([^)]*\d|y\s*=\s*\([^)]*\d|"
    r"\bmatrix\b.{0,40}\d", re.I)
_EQUATION: re.Pattern = re.compile(
    r"(?<![A-Za-z])[A-Za-z][A-Za-z0-9]*\s*\(\s*[A-Za-z0-9]+\s*\)\s*=|"
    r"d[A-Za-z0-9]+/dt|d2[A-Za-z]/dt2|"
    r"=\s*-?\d|\*\*|∫|\bf\(x\)\s*=|\bv\(t\)\s*=|\bi\(t\)\s*=", re.I)
_INITIAL_CONDITION: re.Pattern = re.compile(
    r"\b[A-Za-z]\([txy]?0\)\s*=|initial (condition|value)|"
    r"starting from\s+-?\d|from rest|v\(0\)|y\(0\)|P\(0\)|Q\(0\)|"
    r"T\(0\)|N\(0\)|dx/dt\(0\)", re.I)
_LIMITS: re.Pattern = re.compile(
    r"\b(from\s+t?\s*=?\s*-?\d|\bbetween\s+t?\s*=?\s*-?\d|"
    r"in the (first )?(interval|seconds?)|in \[|"
    r"interval \[-?\d|t\s*=\s*-?\d[^\n]{0,24}t\s*=\s*-?\d)", re.I)
_OPTIMIZATION_LANG: re.Pattern = re.compile(
    r"\b(minimize|minimise|maximize|maximise|optimal|argmin|argmax|"
    r"best fit|find the (minimum|maximum))\b", re.I)
_ROOT_REQUEST: re.Pattern = re.compile(
    r"\b(root of|zero of|zeros of|find x such that|find x where|"
    r"crosses (the )?x.?axis|solve .*(for x))\b", re.I)
_ODE_SPAN: re.Pattern = re.compile(
    r"\b(ODE|ordinary differential|d[A-Za-z0-9]{1,3}/dt|"
    r"rate constant .{0,20}per |decays? with rate|grows as )\b", re.I)
_STATS_REQUEST: re.Pattern = re.compile(
    r"\b(mean of|sample mean|median|standard deviation|variance|"
    r"pearson correlation|correlation of|confidence interval|"
    r"p.?value|t.?test|z.?score|percentile|standard normal|"
    r"pdf|cdf|pmf)\b", re.I)
_T4_UNIT_CONVERSION: re.Pattern = re.compile(
    r"\bexpress (it|them|this) in\b|\bconvert\b.{0,40}\b(to|into)\b|"
    r"\bexpress it as a change in\b", re.I)
_T4_ARITHMETIC: re.Pattern = re.compile(
    r"what is\s+-?\d+(?:\.\d+)?\s*[\+\-×*/÷^]\s*-?\d", re.I)
_QUANTITATIVE_ASK: re.Pattern = re.compile(
    r"\b(how far|how much|how long|how many|"
    r"what (power|force|mass|speed|energy|current|pressure|"
    r"distance|displacement|velocity|temperature|momentum|"
    r"optical power)|"
    r"what is (the |its |their )?(average |optical )?(value|speed|"
    r"energy|current|pressure|distance|displacement|rank|norm|mean|"
    r"correlation|determinant|root|temperature|momentum|power|force|"
    r"mass|velocity)|"
    r"what distance|what energy|what current|net displacement|"
    r"grams remain|charge in coulombs|give x and y)\b", re.I)
_QUALITATIVE: re.Pattern = re.compile(
    r"\b(why|explain|define|definition|meaning of|concept of|describe|"
    r"qualitatively|in words|does .*(affect|improve|cause)|difference "
    r"between|compare|advantage|disadvantage|assumptions?\b(?!.*=\s*-?\d))"
    r"\b", re.I)
_DECORATIVE_NUMBER: re.Pattern = re.compile(
    r"\b(\d+|two|three|four|five)\s+(examples?|reasons?|laws?|types?|"
    r"kinds?|ways|sentences?)\b|"
    r"\b(first|second|third)\s+(law|example|reason)\b", re.I)
_NUMBER: re.Pattern = re.compile(
    r"(?<![A-Za-z])[-+]?(?:\d+\.\d+|\d+)(?:[eE][-+]?\d+)?")
_SCIENCE_FACT_NAME: re.Pattern = re.compile(
    r"\b(speed of light|planck|avogadro|earth-moon|ideal gas|"
    r"stefan.?boltzmann|rydberg|boltzmann constant)\b", re.I)
_RETRIEVAL_ONLY: re.Pattern = re.compile(
    r"\b(who discovered|what is the chemical symbol|atomic number of|"
    r"which element|named after|in what year)\b", re.I)
_UNIT_TARGET: re.Pattern = re.compile(
    r"\bin (kelvin|diopters?|meters?|metres?|joules?|newtons?|"
    r"watts?|seconds?|amperes?|kg|m/s|km/h|pascals?|pa)\b", re.I)


def extract_routing_features(question: str) -> dict:
    """Deterministic routing features (T14.3). Pure; no execution."""
    if not isinstance(question, str) or not question.strip():
        return {"empty": True}
    numbers = _NUMBER.findall(question)
    decorative = bool(_DECORATIVE_NUMBER.search(question))
    numeric_inputs = bool(numbers) and not (
        decorative and len(numbers) <= 2 and not _EQUATION.search(question)
        and not _MATRIX_VECTOR.search(question))
    scicomp_route = route(question)["route"]
    features = {
        "empty": False,
        "conceptual_guard": bool(_CONCEPTUAL_GUARD.match(question)),
        "qualitative_intent": bool(_QUALITATIVE.search(question)),
        "strong_compute_verb": bool(_STRONG_COMPUTE.search(question)),
        "compute_request": bool(_COMPUTE_REQUEST.search(question)),
        "data_carrier": bool(_DATA_CARRIER.search(question)),
        "has_equation": bool(_EQUATION.search(question)),
        "has_matrix_or_vector": bool(_MATRIX_VECTOR.search(question)),
        "has_initial_conditions": bool(_INITIAL_CONDITION.search(question)),
        "has_integration_limits": bool(_LIMITS.search(question)),
        "has_optimization_language": bool(_OPTIMIZATION_LANG.search(question)),
        "has_root_solving": bool(_ROOT_REQUEST.search(question)),
        "has_ode_state_or_span": bool(_ODE_SPAN.search(question)),
        "has_statistics_request": bool(_STATS_REQUEST.search(question)),
        "explicit_numeric_inputs": numeric_inputs,
        "numeric_token_count": len(numbers),
        "quantitative_ask": bool(_QUANTITATIVE_ASK.search(question)),
        "t4_unit_conversion": bool(_T4_UNIT_CONVERSION.search(question)),
        "t4_arithmetic": bool(_T4_ARITHMETIC.search(question)),
        "retrieval_named_constant": bool(_SCIENCE_FACT_NAME.search(question)),
        "retrieval_only_cue": bool(_RETRIEVAL_ONLY.search(question)),
        "unit_target": bool(_UNIT_TARGET.search(question)),
        "scicomp_route": scicomp_route,
        "conceptual_form": bool(_CONCEPTUAL_GUARD.match(question)),
    }
    if re.search(r"\b(without|no|missing|unspecified)\s+initial\b",
                 question, re.I):
        features["has_initial_conditions"] = False
    unspecified_fx = bool(re.search(r"\bf\(x\)\s*=\s*0\b", question, re.I)) \
        and not bool(re.search(
            r"f\(x\)\s*=\s*.*(\*\*|sin|cos|exp|log|[+\-*/]x)", question, re.I))
    features["unspecified_function"] = unspecified_fx
    features["structured_operands"] = bool(
        features["data_carrier"] or features["has_matrix_or_vector"]
        or features["has_equation"] or features["has_initial_conditions"]
        or features["has_integration_limits"]
        or (features["explicit_numeric_inputs"]
            and features["numeric_token_count"] >= 2)
        or (features["quantitative_ask"]
            and features["explicit_numeric_inputs"]
            and features["unit_target"]))
    if unspecified_fx:
        features["structured_operands"] = False
    features["t4_sufficient"] = (
        (features["t4_unit_conversion"] or features["t4_arithmetic"])
        and not features["has_ode_state_or_span"]
        and not features["has_root_solving"]
        and not features["has_optimization_language"])
    native = False
    rt = scicomp_route
    if rt == "LINEAR_ALGEBRA" and features["structured_operands"]:
        native = True
    elif rt == "ODE" and features["has_ode_state_or_span"] \
            and features["explicit_numeric_inputs"] \
            and (features["has_equation"]
                 or features["has_initial_conditions"]):
        native = True
    elif rt == "ROOT_FINDING" and features["has_root_solving"] \
            and not unspecified_fx and features["structured_operands"]:
        native = True
    elif rt == "NUMERICAL_INTEGRATION" and (
            re.search(r"\b(integrate|integral|definite integral)\b",
                      question, re.I)
            or re.search(r"\b[vip]\(t\)\s*=", question, re.I)):
        native = True
    elif rt in ("DERIVATIVE", "OPTIMIZATION", "INTERPOLATION",
                "PARAMETER_SWEEP") and features["structured_operands"]:
        native = True
    elif rt == "STATISTICS" and features["has_statistics_request"] \
            and features["structured_operands"]:
        native = True
    features["native_scicomp_task"] = native
    return features


def _determined_compute(features: dict) -> bool:
    """True iff a numeric/symbolic answer is determined by given inputs.

    Numbers or a scientific keyword alone are not enough (T14.3).
    """
    if features.get("empty") or features.get("conceptual_guard"):
        return False
    request = (
        features["compute_request"] or features["strong_compute_verb"]
        or features["has_root_solving"] or features["has_statistics_request"]
        or features["has_optimization_language"]
        or features["quantitative_ask"]
        or (features["scicomp_route"] != ROUTE_NO_COMPUTE
            and features["structured_operands"]))
    if not request:
        return False
    return bool(features["structured_operands"])


def compute_necessity(question: str) -> dict:
    """T14 necessity label for one question.

    Pure function; no model, no execution. ONLY COMPUTE_REQUIRED
    automatically routes into SciComp. COMPUTE_HELPFUL stays
    conservative. NO_COMPUTE and INSUFFICIENT_INFORMATION never invoke
    SciComp and never invent missing parameters.
    """
    if not isinstance(question, str) or not question.strip():
        features = {"empty": True}
        return {
            "necessity": INSUFFICIENT_INFORMATION,
            "legacy_necessity": "NOT_NEEDED",
            "features": features,
            "preferred_skill": "NO_TOOL",
            "reason": "empty_input",
        }
    features = extract_routing_features(question)
    t4_tools = __import__(
        "sciencemath.tools.router", fromlist=["route_question"]
    ).route_question(question)

    if features["conceptual_guard"] and not (
            _determined_compute(features)
            and features["scicomp_route"] != ROUTE_NO_COMPUTE
            and not features["qualitative_intent"]):
        label, reason = NO_COMPUTE, "conceptual_form"
    elif features["retrieval_only_cue"] and not _determined_compute(features):
        label, reason = NO_COMPUTE, "retrieval_only"
    elif (features["qualitative_intent"] and not _determined_compute(features)
          and not features["t4_sufficient"]):
        label, reason = NO_COMPUTE, "qualitative_intent"
    elif _determined_compute(features) and features.get("t4_sufficient"):
        label, reason = COMPUTE_HELPFUL, "t4_sufficient"
    elif _determined_compute(features) and not features.get(
            "native_scicomp_task"):
        label, reason = COMPUTE_HELPFUL, "determined_but_t4_level"
    elif _determined_compute(features):
        label, reason = COMPUTE_REQUIRED, "determined_numeric_or_symbolic_task"
    elif ((features["compute_request"] or features["has_root_solving"]
           or features["has_optimization_language"]
           or features["has_statistics_request"])
          and not features["structured_operands"]
          and not features["qualitative_intent"]):
        label, reason = INSUFFICIENT_INFORMATION, "compute_request_without_inputs"
    elif features["t4_sufficient"]:
        label, reason = COMPUTE_HELPFUL, "t4_sufficient"
    else:
        label, reason = NO_COMPUTE, "no_compute_task"

    preferred = _preferred_skill(label, features, t4_tools)
    return {
        "necessity": label,
        "legacy_necessity": _LEGACY_NECESSITY[label],
        "features": features,
        "preferred_skill": preferred,
        "reason": reason,
    }


def _preferred_skill(label: str, features: dict, t4_tools: dict) -> str:
    if label == INSUFFICIENT_INFORMATION:
        return "NO_TOOL"
    if label == NO_COMPUTE:
        if features.get("retrieval_only_cue") or features.get(
                "retrieval_named_constant"):
            return "SCIENCE_RAG"
        return "GENERAL"
    if features.get("t4_sufficient") and t4_tools.get("primary"):
        return "MATH_T4"
    if label == COMPUTE_REQUIRED and features.get("scicomp_route") != ROUTE_NO_COMPUTE:
        if features.get("retrieval_named_constant") and not features.get(
                "explicit_numeric_inputs"):
            return "SCIENCE_RAG"
        if features.get("retrieval_named_constant"):
            return "SCICOMP"  # mixed handled by precedence
        return "SCICOMP"
    if t4_tools.get("primary"):
        return "MATH_T4"
    if label == COMPUTE_HELPFUL:
        return "MATH_T4" if t4_tools.get("primary") else "GENERAL"
    return "GENERAL"


def legacy_necessity(necessity: str) -> str:
    """Map T14 taxonomy → T12 REQUIRED/OPTIONAL/NOT_NEEDED labels."""
    return _LEGACY_NECESSITY.get(necessity, "NOT_NEEDED")


def blocks_scicomp_invocation(necessity: str) -> bool:
    """True iff the routing guard must refuse a SciComp call."""
    return necessity in (NO_COMPUTE, INSUFFICIENT_INFORMATION, "NOT_NEEDED")


def auto_routes_scicomp(necessity: str) -> bool:
    """Only COMPUTE_REQUIRED automatically routes into SciComp."""
    return necessity in (COMPUTE_REQUIRED, "REQUIRED")


# T14.4 — deterministic route precedence (compute-side). Full multi-skill
# orchestration lives in the executive router; this function only orders
# the T4 / SciComp / RAG / none decision.
PRECEDENCE = (
    "INSUFFICIENT_INPUT",
    "MATH_T4",
    "SCICOMP",
    "SCIENCE_RAG",
    "MIXED_RAG_SCICOMP",
    "NO_TOOL",
)


def route_precedence(question: str) -> dict:
    """Return the first applicable compute-side skill under T14.4 order."""
    nec = compute_necessity(question)
    feat = nec["features"]
    t4 = __import__("sciencemath.tools.router",
                    fromlist=["route_question"]).route_question(question)
    if nec["necessity"] == INSUFFICIENT_INFORMATION or feat.get("empty"):
        primary = "INSUFFICIENT_INPUT"
    elif feat.get("t4_sufficient") and t4.get("primary"):
        primary = "MATH_T4"
    elif nec["necessity"] == COMPUTE_REQUIRED and feat.get(
            "retrieval_named_constant"):
        primary = "MIXED_RAG_SCICOMP"
    elif nec["necessity"] == COMPUTE_REQUIRED:
        primary = "SCICOMP"
    elif feat.get("retrieval_only_cue") or (
            nec["preferred_skill"] == "SCIENCE_RAG"):
        primary = "SCIENCE_RAG"
    elif t4.get("primary") and nec["necessity"] == COMPUTE_HELPFUL:
        primary = "MATH_T4"
    else:
        primary = "NO_TOOL"
    return {
        "primary": primary,
        "necessity": nec["necessity"],
        "t4_tools": t4.get("tools") or [],
        "scicomp_route": feat.get("scicomp_route"),
        "reason": nec["reason"],
    }