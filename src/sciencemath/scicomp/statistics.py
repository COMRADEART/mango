"""scicomp statistics — descriptive statistics and explicit-assumption
tests (T11.2, T11.28).

Every inferential result carries its sample size and its assumptions
(independence, normality, equal variance) as structured diagnostics, so
Mango can never state "statistically significant" without the actual
test result AND the assumptions it rests on (T11.28). Distribution
parameters are validated (invalid parameters are INVALID_INPUT, not NaN).
Stochastic methods are NOT included — T11 v1 is deterministic (T11.26).
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats as sci_stats

from sciencemath.scicomp import diagnostics
from sciencemath.scicomp.schemas import (Limits, finite_list,
                                         finite_number, invalid_input)

MAX_SAMPLE = 10_000


def _sample(inputs: dict, key: str, limits: Limits) -> np.ndarray:
    values = finite_list(inputs.get(key), key, limits.max_stats_points)
    if len(values) < 2:
        raise invalid_input(f"'{key}' needs at least 2 values")
    return np.asarray(values)


# --- descriptive statistics -------------------------------------------------

def describe(inputs: dict, options: dict, limits: Limits) -> dict:
    values = _sample(inputs, "values", limits)
    n = values.size
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1)) if n > 1 else None
    result = {
        "n": int(n),
        "mean": mean,
        "median": float(np.median(values)),
        "std_dev": std,
        "variance": std * std if std is not None else None,
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "quartile_25": float(np.percentile(values, 25)),
        "quartile_75": float(np.percentile(values, 75)),
        "skewness": float(sci_stats.skew(values)) if n >= 3 else None,
        "kurtosis": float(sci_stats.kurtosis(values)) if n >= 4 else None,
    }
    return {
        "result": result,
        "diagnostics": diagnostics.stats(
            int(n), ["descriptive statistics only — no inferential claim",
                     "sample std uses ddof=1 (unbiased estimator)"]),
        "provenance": {"engine": "scipy", "method": "describe"},
    }


# --- confidence interval for the mean ------------------------------------------

def confidence_interval_mean(inputs: dict, options: dict, limits: Limits) -> dict:
    values = _sample(inputs, "values", limits)
    n = values.size
    confidence = inputs.get("confidence", 0.95)
    confidence = finite_number(confidence, "confidence")
    if not 0.0 < confidence < 1.0:
        raise invalid_input("'confidence' must be in (0, 1)")
    method = inputs.get("method", "t")
    if method not in ("t", "normal"):
        raise invalid_input("'method' must be 't' or 'normal'")
    mean = float(np.mean(values))
    se = float(np.std(values, ddof=1) / math.sqrt(n))
    if method == "t":
        crit = float(sci_stats.t.ppf((1 + confidence) / 2, df=n - 1))
        note = "t distribution, df = n-1; assumes independent samples and " \
               "approximately normal population"
    else:
        crit = float(sci_stats.norm.ppf((1 + confidence) / 2))
        note = "normal approximation; assumes independent samples, " \
               "approximately normal population, and large n"
    half = crit * se
    warnings = []
    if n < 30 and method == "normal":
        warnings.append("normal approximation with n < 30: interval may "
                        "be inaccurate")
    return {
        "result": {
            "mean": mean,
            "ci_low": mean - half,
            "ci_high": mean + half,
            "confidence": confidence,
        },
        "diagnostics": {**diagnostics.stats(int(n), [note]),
                        "critical_value": crit,
                        "standard_error": se},
        "warnings": warnings,
        "status": "NUMERICAL_WARNING" if warnings else "PASS",
        "provenance": {"engine": "scipy", "method":
                       f"ci-mean-{method}"},
    }


# --- correlation -----------------------------------------------------------------

def correlation(inputs: dict, options: dict, limits: Limits) -> dict:
    x = _sample(inputs, "x", limits)
    y = _sample(inputs, "y", limits)
    if x.size != y.size:
        raise invalid_input("'x' and 'y' must have equal length")
    method = inputs.get("method", "pearson")
    if method not in ("pearson", "spearman"):
        raise invalid_input("'method' must be 'pearson' or 'spearman'")
    if method == "pearson":
        stat, p = sci_stats.pearsonr(x, y)
        assumptions = ["independence of pairs", "linearity of relation",
                       "pearson r measures LINEAR association only"]
    else:
        stat, p = sci_stats.spearmanr(x, y)
        assumptions = ["independence of pairs",
                       "spearman rho measures monotonic association"]
    return {
        "result": {"correlation": float(stat), "p_value": float(p),
                   "method": method},
        "diagnostics": diagnostics.stats(int(x.size), assumptions),
        "provenance": {"engine": "scipy", "method":
                       f"correlation-{method}"},
    }


# --- simple linear regression -----------------------------------------------------

def linear_regression(inputs: dict, options: dict, limits: Limits) -> dict:
    x = _sample(inputs, "x", limits)
    y = _sample(inputs, "y", limits)
    if x.size != y.size:
        raise invalid_input("'x' and 'y' must have equal length")
    fit = sci_stats.linregress(x, y)
    assumptions = ["independence of residuals", "linearity",
                   "constant residual variance (homoscedasticity)",
                   "approximately normal residuals (for p-values)"]
    return {
        "result": {
            "slope": float(fit.slope),
            "intercept": float(fit.intercept),
            "r_value": float(fit.rvalue),
            "r_squared": float(fit.rvalue ** 2),
            "p_value": float(fit.pvalue),
            "slope_std_error": float(fit.stderr),
            "intercept_std_error": float(fit.intercept_stderr),
        },
        "diagnostics": diagnostics.stats(int(x.size), assumptions),
        "provenance": {"engine": "scipy", "method": "linregress"},
    }


# --- hypothesis tests (explicit assumptions, T11.28) -------------------------------

def hypothesis_test(inputs: dict, options: dict, limits: Limits) -> dict:
    test = inputs.get("test")
    if test not in ("ttest_1samp", "ttest_ind"):
        raise invalid_input("'test' must be 'ttest_1samp' or 'ttest_ind'")
    null_mean = inputs.get("null_value", 0.0)
    null_mean = finite_number(null_mean, "null_value")
    assumptions = ["independent samples",
                   "approximately normal population (or large n)"]
    if test == "ttest_1samp":
        a = _sample(inputs, "values", limits)
        stat, p = sci_stats.ttest_1samp(a, null_mean)
        result = {"t_statistic": float(stat), "p_value": float(p),
                  "test": test, "null_value": null_mean,
                  "alternative": "two-sided"}
        n = int(a.size)
    else:
        a = _sample(inputs, "values", limits)
        b = _sample(inputs, "values2", limits)
        equal_var = inputs.get("equal_var")
        if equal_var is None:
            raise invalid_input(
                "'equal_var' must be declared explicitly (true for "
                "Student's t, false for Welch's t)")
        if not isinstance(equal_var, bool):
            raise invalid_input("'equal_var' must be a boolean")
        stat, p = sci_stats.ttest_ind(a, b, equal_var=equal_var)
        assumptions.append(
            "equal population variance assumed" if equal_var
            else "Welch's t: does NOT assume equal variance")
        result = {"t_statistic": float(stat), "p_value": float(p),
                  "test": test, "null_value": null_mean,
                  "equal_var": equal_var, "alternative": "two-sided"}
        n = int(a.size + b.size)
    result["interpretation_note"] = (
        "p < alpha indicates the data are inconsistent with the null "
        "hypothesis under these assumptions; it does not prove causation "
        "or correctness of assumptions")
    return {
        "result": result,
        "diagnostics": diagnostics.stats(n, assumptions),
        "provenance": {"engine": "scipy", "method": test},
    }


# --- distribution evaluation -------------------------------------------------------

_DISTRIBUTIONS = {
    # name -> (scipy dist, caller-facing parameter names, validation,
    #          translation to scipy kwargs where names differ)
    "normal": (sci_stats.norm, ("mu", "sigma"),
               {"mu": None, "sigma": (0, "exclusive")},
               {"mu": "loc", "sigma": "scale"}),
    "exponential": (sci_stats.expon, ("scale",),
                    {"scale": (0, "exclusive")}, {}),
    "uniform": (sci_stats.uniform, ("loc", "scale"),
                {"scale": (0, "exclusive")}, {}),
    "poisson": (sci_stats.poisson, ("mu",),
                {"mu": (0, "exclusive")}, {}),
    "binomial": (sci_stats.binom, ("n", "p"),
                 {"n": (0, "inclusive"), "p": None}, {}),
}


def distribution_value(inputs: dict, options: dict, limits: Limits) -> dict:
    name = inputs.get("distribution")
    if name not in _DISTRIBUTIONS:
        raise invalid_input(
            f"'distribution' must be one of {sorted(_DISTRIBUTIONS)}")
    dist_cls, param_names, checks, translate = _DISTRIBUTIONS[name]
    params = inputs.get("parameters") or {}
    if not isinstance(params, dict):
        raise invalid_input("'parameters' must be an object")
    missing = [p for p in param_names if p not in params]
    if missing:
        raise invalid_input(
            f"missing distribution parameters: {', '.join(missing)}")
    values = {}
    caller_values = {}
    for p in param_names:
        v = finite_number(params.get(p), f"parameters.{p}")
        spec = checks.get(p)
        if spec and spec[1] == "exclusive" and v <= 0:
            raise invalid_input(
                f"parameter '{p}' must be > 0 for the {name} distribution")
        if p == "p" and not 0.0 <= v <= 1.0:
            raise invalid_input("probability parameter 'p' must be in "
                                "[0, 1]")
        values[translate.get(p, p)] = v
        caller_values[p] = v
    x = finite_number(inputs.get("at"), "at")
    kind = inputs.get("quantity", "pdf")
    if kind not in ("pdf", "cdf", "logpdf", "pmf"):
        raise invalid_input("'quantity' must be pdf, cdf, logpdf, or pmf")
    dist = dist_cls(**values)
    if kind in ("pdf", "logpdf") and name in ("poisson", "binomial"):
        # discrete distributions have pmf, not pdf
        kind = "pmf" if kind == "pdf" else kind
    try:
        value = float(getattr(dist, kind)(x))
    except (ValueError, FloatingPointError) as e:
        raise invalid_input(f"distribution evaluation failed: {e}")
    if value != value or abs(value) == float("inf") and kind != "logpdf":
        raise invalid_input(
            "distribution value undefined at this point")
    warnings = []
    if kind == "logpdf" and (value != value or abs(value) == float("inf")):
        warnings.append("log-density is -inf: density is zero at this "
                        "point")
    return {
        "result": {"value": value, "distribution": name,
                   "quantity": kind, "at": x, "parameters": caller_values},
        "diagnostics": {"assumptions": [
            f"parameterization is scipy.stats.{name}"], },
        "warnings": warnings,
        "status": "NUMERICAL_WARNING" if warnings else "PASS",
        "provenance": {"engine": "scipy", "method": f"{name}-{kind}"},
    }