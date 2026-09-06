"""unit_converter — deterministic unit conversion with a fixed registry.

Units are resolved against a hard-coded registry (SI prefixes + common
science units); unknown units are a deterministic error, never a guess.
Compound units ("km/h", "kg/m^3", "m*s^-2") are parsed with the same
tokenizer discipline as expressions. Temperature uses real offset
conversion (Celsius/Fahrenheit are affine, not multiplicative — converting
25 degC to K by factor alone would produce the wrong 25 K).
"""
from __future__ import annotations

import ast
import math
import re

from sciencemath.tools.base import Tool, ToolError, ToolResult
from sciencemath.tools.safeparse import validate_ast

# dimension vector order: (m, kg, s, A, K, mol, cd)
Dims = tuple

_DIM_M = (1, 0, 0, 0, 0, 0, 0)
_DIM_KG = (0, 1, 0, 0, 0, 0, 0)
_DIM_S = (0, 0, 1, 0, 0, 0, 0)
_DIM_A = (0, 0, 0, 1, 0, 0, 0)
_DIM_K = (0, 0, 0, 0, 1, 0, 0)
_DIM_MOL = (0, 0, 0, 0, 0, 1, 0)
_DIM_CD = (0, 0, 0, 0, 0, 0, 1)
_DIM_NONE = (0, 0, 0, 0, 0, 0, 0)


def _dims_add(a: Dims, b: Dims) -> Dims:
    return tuple(x + y for x, y in zip(a, b))


def _dims_mul(a: Dims, k: int) -> Dims:
    return tuple(x * k for x in a)


def _dims_div(a: Dims, b: Dims) -> Dims:
    return tuple(x - y for x, y in zip(a, b))


def _dims_pow(a: Dims, k: int) -> Dims:
    return tuple(x * k for x in a)


# frequently reused composite dimensions
_D_M_S2 = _dims_add(_dims_add(_DIM_KG, _DIM_M), _dims_mul(_DIM_S, -2))      # kg*m/s^2 (force)
_D_MS2 = _dims_add(_DIM_M, _dims_mul(_DIM_S, -2))                            # m/s^2 (accel)
_D_KG_M2_S2 = _dims_add(_dims_add(_DIM_KG, _dims_mul(_DIM_M, 2)), _dims_mul(_DIM_S, -2))   # energy
_D_KG_M2_S3 = _dims_add(_dims_add(_DIM_KG, _dims_mul(_DIM_M, 2)), _dims_mul(_DIM_S, -3))   # power
_D_PRESSURE = _dims_add(_DIM_KG,
                        _dims_mul(_dims_add(_DIM_M, _dims_mul(_DIM_S, 2)),
                                  -1))  # kg/(m*s^2)
_D_VOLT = _dims_add(_dims_add(_DIM_KG, _dims_mul(_DIM_M, 2)),
                    _dims_add(_dims_mul(_DIM_A, -1), _dims_mul(_DIM_S, -3)))
_D_OHM = _dims_add(_dims_add(_DIM_KG, _dims_mul(_DIM_M, 2)),
                   _dims_add(_dims_mul(_DIM_A, -2), _dims_mul(_DIM_S, -3)))
_D_FARAD = _dims_add(_dims_add(_dims_mul(_DIM_A, 2), _dims_mul(_DIM_S, 4)),
                     _dims_mul(_dims_add(_DIM_KG, _dims_mul(_DIM_M, 2)), -1))

_PREFIXES: dict[str, float] = {
    "Y": 1e24, "Z": 1e21, "E": 1e18, "P": 1e15, "T": 1e12, "G": 1e9,
    "M": 1e6, "k": 1e3, "h": 1e2, "da": 1e1,
    "d": 1e-1, "c": 1e-2, "m": 1e-3, "u": 1e-6, "µ": 1e-6, "μ": 1e-6,
    "n": 1e-9, "p": 1e-12, "f": 1e-15, "a": 1e-18, "z": 1e-21,
    "y": 1e-24,
}

# name -> (factor to SI, dims) — temperature entries are placeholders; the
# affine conversion lives in _to_kelvin/_from_kelvin.
_BASE_UNITS: dict[str, tuple[float, Dims]] = {
    # length
    "m": (1.0, _DIM_M), "km": (1e3, _DIM_M), "cm": (1e-2, _DIM_M),
    "mm": (1e-3, _DIM_M), "um": (1e-6, _DIM_M), "µm": (1e-6, _DIM_M),
    "nm": (1e-9, _DIM_M), "mi": (1609.344, _DIM_M),
    "yd": (0.9144, _DIM_M), "ft": (0.3048, _DIM_M), "in": (0.0254, _DIM_M),
    "nmi": (1852.0, _DIM_M), "ly": (9.4607304725808e15, _DIM_M),
    "au": (1.495978707e11, _DIM_M),
    # mass
    "kg": (1.0, _DIM_KG), "g": (1e-3, _DIM_KG), "mg": (1e-6, _DIM_KG),
    "ug": (1e-9, _DIM_KG), "t": (1e3, _DIM_KG), "tonne": (1e3, _DIM_KG),
    "ton": (907.18474, _DIM_KG), "lb": (0.45359237, _DIM_KG),
    "oz": (0.028349523125, _DIM_KG),
    # time
    "s": (1.0, _DIM_S), "ms": (1e-3, _DIM_S), "us": (1e-6, _DIM_S),
    "ns": (1e-9, _DIM_S), "min": (60.0, _DIM_S), "h": (3600.0, _DIM_S),
    "day": (86400.0, _DIM_S), "week": (604800.0, _DIM_S),
    "year": (31557600.0, _DIM_S),          # Julian year
    # dimensionless / angle
    "rad": (1.0, _DIM_NONE), "deg": (math.pi / 180.0, _DIM_NONE),
    "turn": (2 * math.pi, _DIM_NONE),
    "rpm": (2 * math.pi / 60.0, _DIM_NONE),
    "mol": (1.0, _DIM_MOL), "cd": (1.0, _DIM_CD), "A": (1.0, _DIM_A),
    # speed (common standalone spellings)
    "mph": (0.44704, _dims_div(_DIM_M, _DIM_S)),
    "knot": (0.514444444444, _dims_div(_DIM_M, _DIM_S)),
    # force
    "N": (1.0, _D_M_S2),
    "dyne": (1e-5, _D_M_S2),
    # pressure
    "Pa": (1.0, _D_PRESSURE),
    "kPa": (1e3, _D_PRESSURE),
    "MPa": (1e6, _D_PRESSURE),
    "bar": (1e5, _D_PRESSURE),
    "atm": (101325.0, _D_PRESSURE),
    "mmHg": (133.322387415, _D_PRESSURE),
    "torr": (133.322368421, _D_PRESSURE),
    "psi": (6894.757293168, _D_PRESSURE),
    # energy / work / heat
    "J": (1.0, _D_KG_M2_S2),
    "kJ": (1e3, _D_KG_M2_S2),
    "MJ": (1e6, _D_KG_M2_S2),
    "cal": (4.184, _D_KG_M2_S2),
    "kcal": (4184.0, _D_KG_M2_S2),
    "eV": (1.602176634e-19, _D_KG_M2_S2),
    "MeV": (1.602176634e-13, _D_KG_M2_S2),
    "GeV": (1.602176634e-10, _D_KG_M2_S2),
    "Wh": (3600.0, _D_KG_M2_S2),
    "kWh": (3.6e6, _D_KG_M2_S2),
    "BTU": (1055.05585262, _D_KG_M2_S2),
    # power
    "W": (1.0, _D_KG_M2_S3),
    "mW": (1e-3, _D_KG_M2_S3),
    "kW": (1e3, _D_KG_M2_S3),
    "MW": (1e6, _D_KG_M2_S3),
    "hp": (745.699872, _D_KG_M2_S3),
    # frequency
    "Hz": (1.0, _dims_div(_DIM_NONE, _DIM_S)),
    "kHz": (1e3, _dims_div(_DIM_NONE, _DIM_S)), "MHz": (1e6, _dims_div(_DIM_NONE, _DIM_S)),
    "GHz": (1e9, _dims_div(_DIM_NONE, _DIM_S)),
    # charge / potential / resistance / capacitance
    "coulomb": (1.0, _dims_add(_DIM_A, _DIM_S)),
    "V": (1.0, _D_VOLT),
    "mV": (1e-3, _D_VOLT),
    "kV": (1e3, _D_VOLT),
    "ohm": (1.0, _D_OHM),
    "farad": (1.0, _D_FARAD),
    # volume (L^3)
    "L": (1e-3, (3, 0, 0, 0, 0, 0, 0)),
    "mL": (1e-6, (3, 0, 0, 0, 0, 0, 0)),
    "cL": (1e-5, (3, 0, 0, 0, 0, 0, 0)),
    "gal": (0.003785411784, (3, 0, 0, 0, 0, 0, 0)),
    "qt": (0.000946352946, (3, 0, 0, 0, 0, 0, 0)),
    "pint": (0.000473176473, (3, 0, 0, 0, 0, 0, 0)),
    "cup": (0.0002365882365, (3, 0, 0, 0, 0, 0, 0)),
    "fl_oz": (2.95735295625e-5, (3, 0, 0, 0, 0, 0, 0)),
    # area
    "acre": (4046.8564224, (2, 0, 0, 0, 0, 0, 0)),
    "hectare": (1e4, (2, 0, 0, 0, 0, 0, 0)),
    # temperature (dims only; conversion is affine)
    "K": (1.0, _DIM_K), "degC": (1.0, _DIM_K), "degF": (1.0, _DIM_K),
}

_UNIT_ALIASES: dict[str, str] = {
    "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "kilometer": "km", "kilometers": "km", "kilometre": "km",
    "kilometres": "km", "centimeter": "cm", "centimeters": "cm",
    "millimeter": "mm", "millimeters": "mm", "micrometer": "um",
    "nanometer": "nm", "mile": "mi", "miles": "mi", "yard": "yd",
    "yards": "yd", "foot": "ft", "feet": "ft", "inch": "in", "inches": "in",
    "second": "s", "seconds": "s", "minute": "min", "minutes": "min",
    "hour": "h", "hours": "h", "day": "day", "days": "day",
    "week": "week", "weeks": "week",
    "year": "year", "years": "year", "gram": "g", "grams": "g",
    "kilogram": "kg", "kilograms": "kg", "milligram": "mg",
    "milligrams": "mg", "microgram": "ug", "micrograms": "ug",
    "pound": "lb", "pounds": "lb",
    "ounce": "oz", "ounces": "oz", "newton": "N", "newtons": "N",
    "pascal": "Pa", "pascals": "Pa", "joule": "J", "joules": "J",
    "kilojoule": "kJ", "calorie": "cal", "calories": "cal",
    "kilocalorie": "kcal", "watt": "W", "watts": "W", "kilowatt": "kW",
    "hertz": "Hz", "volt": "V", "volts": "V", "liter": "L",
    "liters": "L", "litre": "L", "litres": "L", "milliliter": "mL",
    "milliliters": "mL", "gallon": "gal", "gallons": "gal",
    "mole": "mol", "moles": "mol", "amp": "A", "ampere": "A",
    "amperes": "A", "kelvin": "K", "degrees": "deg", "degree": "deg",
    "radians": "rad", "lightyear": "ly", "lightyears": "ly",
    "kilometersperhour": "km/h", "meterspersecond": "m/s",
}

_TEMPERATURE_SET = {"K", "degC", "degF", "C", "F", "°C", "°F",
                    "celsius", "fahrenheit", "Kelvin"}


def _normalize_unit_token(name: str) -> str:
    token = (name or "").strip().strip("_ ")
    token = _UNIT_ALIASES.get(token, token)
    if token in ("C", "°C"):
        return "degC"
    if token in ("F", "°F"):
        return "degF"
    if token == "celsius":
        return "degC"
    if token == "fahrenheit":
        return "degF"
    return token


def _lookup_unit(name: str) -> tuple[float, Dims]:
    """Resolve one unit token against the registry (aliases + SI prefixes)."""
    token = _normalize_unit_token(name)
    if token in _BASE_UNITS:
        return _BASE_UNITS[token]
    for pref in sorted(_PREFIXES, key=len, reverse=True):
        if token.startswith(pref) and len(token) > len(pref):
            stem = _normalize_unit_token(token[len(pref):])
            if stem in _BASE_UNITS and stem not in ("kg", "degC", "degF", "K"):
                factor, dims = _BASE_UNITS[stem]
                return _PREFIXES[pref] * factor, dims
    raise ToolError("UNKNOWN_UNIT", f"unknown unit {name!r}")


def _dims_add(a: Dims, b: Dims) -> Dims:
    return tuple(x + y for x, y in zip(a, b))


def _dims_mul(a: Dims, k: int) -> Dims:
    return tuple(x * k for x in a)


_UNIT_TOKEN_RE = re.compile(r"[a-zA-ZµμΩ°]+\d*|\^-?\d+|[*/]")
_POWER_TOKEN_RE = re.compile(r"\^(-?\d+)")
_UNIT_NAME_DIGITS_RE = re.compile(r"^([a-zA-ZµμΩ°]+)(\d+)$")


def _split_unit_token(tok: str) -> tuple[str, int | None]:
    """Split a bare-digit exponent suffix: 'm2' -> ('m', 2), 'mmHg' ->
    ('mmHg', None). Bare-digit exponents used to be silently dropped
    ('m2' graded equal to 'm')."""
    m = _UNIT_NAME_DIGITS_RE.fullmatch(tok)
    if m:
        return m.group(1), int(m.group(2))
    return tok, None


def parse_unit(unit_str: str) -> tuple[float, Dims, str]:
    """Parse a possibly-compound unit: km/h, kg/m^3, m*s^-2, deg.

    Grammar: unit ('^' int)? (( '*' | '/' ) unit ('^' int)?)*. Only
    registry units are accepted; anything else raises
    ToolError(UNKNOWN_UNIT). Returns (factor_to_si, dims, canonical_name).
    """
    s = (unit_str or "").strip()
    if not s:
        raise ToolError("UNKNOWN_UNIT", "empty unit")
    s = re.sub(r"\bper\b", "/", s)
    tokens = _UNIT_TOKEN_RE.findall(s)
    factor = 1.0
    dims: Dims = _DIM_NONE
    canonical: list[str] = []
    invert_next = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("*", "/"):
            if not canonical or invert_next is None:
                raise ToolError("UNKNOWN_UNIT", f"malformed unit {unit_str!r}")
            if i + 1 >= len(tokens):
                raise ToolError("UNKNOWN_UNIT", f"malformed unit {unit_str!r}")
            invert_next = (tok == "/")
            i += 1
            continue
        if _POWER_TOKEN_RE.fullmatch(tok):
            # stray power not attached to a preceding unit
            raise ToolError("UNKNOWN_UNIT", f"malformed unit {unit_str!r}")
        # unit name; optional following power applies to it
        name, digit_exp = _split_unit_token(tok)
        f, d = _lookup_unit(name)
        tok = name
        exponent = 1
        if digit_exp is not None:
            exponent = digit_exp        # 'm3' == 'm^3'
        if i + 1 < len(tokens) and _POWER_TOKEN_RE.fullmatch(tokens[i + 1]):
            exponent = int(tokens[i + 1][1:])
            i += 1
        if not -6 <= exponent <= 6:
            raise ToolError("UNKNOWN_UNIT", f"unit power out of range: {tok}")
        applied = -exponent if invert_next else exponent
        factor *= f ** applied
        dims = _dims_add(dims, _dims_mul(d, applied))
        if applied == 1:
            canonical.append(tok)
        elif applied == -1:
            canonical.append(f"/{tok}")
        elif applied != 0:
            canonical.append(f"{tok}^{applied}")
        invert_next = False
        i += 1
    if invert_next:
        raise ToolError("UNKNOWN_UNIT", f"malformed unit {unit_str!r}")
    return factor, dims, "*".join(canonical)


def _format_dims(dims: Dims) -> str:
    names = ["m", "kg", "s", "A", "K", "mol", "cd"]
    num, den = [], []
    for name, exp in zip(names, dims):
        if exp > 0:
            num.append(name if exp == 1 else f"{name}^{exp}")
        elif exp < 0:
            den.append(name if exp == -1 else f"{name}^{abs(exp)}")
    if not num and not den:
        return "dimensionless"
    out = "*".join(num) if num else "1"
    if den:
        out += "/" + "*".join(den)
    return out


def _format_si(dims: Dims) -> str:
    if dims == _DIM_NONE:
        return "1"
    return _format_dims(dims)


# ---------------------------------------------------------------------------
# Temperature affine conversion
# ---------------------------------------------------------------------------

def is_temperature_unit(unit: str) -> bool:
    return _normalize_unit_token(unit) in _TEMPERATURE_SET


def to_kelvin(value: float, unit: str) -> float:
    token = _normalize_unit_token(unit)
    if token == "K":
        return value
    if token == "degC":
        return value + 273.15
    if token == "degF":
        return (value - 32.0) * 5.0 / 9.0 + 273.15
    raise ToolError("UNKNOWN_UNIT", f"not a temperature unit: {unit!r}")


def from_kelvin(value: float, unit: str) -> float:
    token = _normalize_unit_token(unit)
    if token == "K":
        return value
    if token == "degC":
        return value - 273.15
    if token == "degF":
        return (value - 273.15) * 9.0 / 5.0 + 32.0
    raise ToolError("UNKNOWN_UNIT", f"not a temperature unit: {unit!r}")


# ---------------------------------------------------------------------------
# Quantity parsing: "5 km", "3.2e4 kg/m^3", "98.6 °F", "15%"
# ---------------------------------------------------------------------------

_QUANTITY_RE = re.compile(
    r"^\s*(?P<value>[-+]?[0-9][0-9eE+\-.,*/()\s]*)\s*"
    r"(?P<unit>[a-zA-ZµμΩ°%^-].*?)\s*$")

_PHRASE_UNITS = [
    (r"(?i)\bdegrees?\s+celsius\b", "degC"),
    (r"(?i)\bdegrees?\s+fahrenheit\b", "degF"),
    (r"(?i)\bmeters?\s+per\s+second\b", "m/s"),
    (r"(?i)\bkilometers?\s+per\s+hour\b", "km/h"),
    (r"(?i)\bmiles?\s+per\s+hour\b", "mph"),
    (r"(?i)\brevolutions\s+per\s+minute\b", "rpm"),
    (r"(?i)\bdegrees?\b", "deg"),
]


def parse_quantity(text: str) -> tuple[float, str] | None:
    """Split '5 km' / '3.2e4 kg/m^3' / '25%' / '98.6 degF' into
    (value, unit). Returns None when the text is not quantity-like.
    '%' is kept as the literal unit — callers decide its meaning."""
    if not isinstance(text, str):
        return None
    s = text.strip().strip("$").strip()
    for pattern, repl in _PHRASE_UNITS:
        s = re.sub(pattern, repl, s)
    m = _QUANTITY_RE.match(s)
    if not m:
        return None
    value_s = m.group("value").strip().replace(",", "").rstrip(".")
    unit = m.group("unit").strip()
    if not unit:
        return None
    try:
        val = _eval_value(value_s)
    except ToolError:
        return None
    return val, unit


def _eval_value(expr: str) -> float:
    """Evaluate a value-only arithmetic string via the AST gate; no eval."""
    try:
        float(expr)
        return float(expr)
    except ValueError:
        pass
    tree = validate_ast(expr, allow_calls=False)
    return _eval_node(tree.body)


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.UnaryOp):
        v = _eval_node(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ToolError("DIVISION_BY_ZERO", "division by zero")
            return left / right
        if isinstance(node.op, ast.Pow):
            return left ** right
    raise ToolError("PARSE_ERROR", "unsupported value expression")


def _round_clean(x: float) -> float:
    """Trim float noise (0.30000000000000004 -> 0.3) without losing range."""
    return round(x, 12) + 0.0


class UnitConverterTool(Tool):
    name = "unit_converter"
    description = (
        "Convert a quantity between units from the fixed registry (SI "
        "prefixes; length, mass, time, force, pressure, energy, power, "
        "frequency, volume, area, speed, angle, temperature). Usage: "
        "value + from_unit (+ optional to_unit; default converts to SI). "
        "Unknown units are deterministic errors, never guesses. "
        "Temperature conversion applies the correct affine offsets."
    )
    input_schema = {"type": "object",
                    "required": ["value", "from_unit"],
                    "properties": {
                        "value": {"type": "number"},
                        "from_unit": {"type": "string"},
                        "to_unit": {"type": "string"}}}
    output_schema = {"type": "object",
                     "properties": {
                         "converted_value": {"type": "number"},
                         "to_unit": {"type": "string"},
                         "si_value": {"type": "number"},
                         "si_unit": {"type": "string"},
                         "dimension": {"type": "string"}}}

    def _checked_run(self, arguments: dict) -> ToolResult:
        value = self._require_number(arguments, "value")
        from_unit = self._require_str(arguments, "from_unit")
        to_unit = arguments.get("to_unit")

        # temperature vs everything else must not mix
        if is_temperature_unit(from_unit):
            if not to_unit:
                raise ToolError("INVALID_INPUT",
                                "temperature conversion requires 'to_unit'")
            if not is_temperature_unit(to_unit):
                raise ToolError("INCOMPATIBLE_UNITS",
                                "cannot convert temperature to non-temperature")
            kelvin = to_kelvin(value, from_unit)
            converted = from_kelvin(kelvin, to_unit)
            return ToolResult(tool=self.name, status="ok", result={
                "converted_value": _round_clean(converted),
                "to_unit": _normalize_unit_token(to_unit),
                "si_value": _round_clean(kelvin), "si_unit": "K",
                "dimension": "temperature"})

        f_from, d_from, _name_from = parse_unit(from_unit)
        si_value = value * f_from
        si_unit = _format_si(d_from)

        if to_unit:
            if not isinstance(to_unit, str):
                raise ToolError("INVALID_INPUT", "'to_unit' must be a string")
            if is_temperature_unit(to_unit):
                raise ToolError("INCOMPATIBLE_UNITS",
                                "cannot convert non-temperature to temperature")
            f_to, d_to, _name_to = parse_unit(to_unit)
            if d_from != d_to:
                raise ToolError(
                    "INCOMPATIBLE_UNITS",
                    f"{_format_dims(d_from)} cannot convert to "
                    f"{_format_dims(d_to)}")
            converted = value * f_from / f_to
            out_unit = to_unit.strip()
        else:
            converted = si_value
            out_unit = si_unit

        return ToolResult(tool=self.name, status="ok", result={
            "converted_value": _round_clean(converted),
            "to_unit": out_unit,
            "si_value": _round_clean(si_value),
            "si_unit": si_unit,
            "dimension": _format_dims(d_from)})