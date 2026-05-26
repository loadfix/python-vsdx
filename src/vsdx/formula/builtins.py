"""Built-in ShapeSheet function library.

Roughly 55 functions drawn from the Microsoft Visio Functions Reference
(https://learn.microsoft.com/en-us/office/client-developer/visio/functions-reference).
These are the functions most frequently observed in the stock Visio
masters for the 0.1.0 scope (Rectangle, Ellipse, Triangle, Dynamic
Connector) plus enough coverage that user-supplied formulas for custom
masters work.

Coverage notes:

- **Math / trig**: ``ABS``, ``SIGN``, ``SQRT``, ``SIN``, ``COS``, ``TAN``,
  ``ASIN``, ``ACOS``, ``ATAN``, ``ATAN2``, ``DEGREES``, ``RADIANS``,
  ``EXP``, ``LN``, ``LOG10``, ``POWER``, ``MOD``, ``INT``, ``TRUNC``,
  ``ROUND``, ``CEILING``, ``FLOOR``, ``PI``.
- **Stats / selection**: ``MIN``, ``MAX``, ``SUM``, ``AVG`` / ``AVERAGE``,
  ``COUNT``.
- **Logic**: ``IF``, ``AND``, ``OR``, ``NOT``, ``XOR``, ``ISERR``,
  ``ISERROR``.
- **Lookup / indirection**: ``INDEX``, ``LOOKUP``.
- **String**: ``LEN``, ``LEFT``, ``RIGHT``, ``MID``, ``UPPER``, ``LOWER``,
  ``TRIM``, ``FORMAT``, ``FORMATEX``, ``CONCATENATE``.
- **ShapeSheet-specific**: ``GUARD``, ``SETATREF``, ``SETATREFEVAL``,
  ``SETATREFEXPR``, ``DEPENDSON``, ``THEMEVAL``, ``USE``,
  ``BOUND``, ``MINMAX``, ``FALSE``, ``TRUE``, ``SUMIF``.
- **Geometry passthroughs**: ``HEIGHT``, ``WIDTH``, ``PNT``, ``LOCTOPAR``,
  ``PARTOLOC`` — return their argument as-is (or a tuple for ``PNT``)
  so formulas round-trip losslessly pending a geometry-aware pass.

Functions the evaluator logs a TODO for but does not implement (too
context-sensitive, never encountered in 0.1.0 fixtures): ``RUNADDON``,
``CALLTHIS``, ``DOCMD``, ``HYPERLINK``, ``OPENFILE``, ``PLAYSOUND``,
``RUNMACRO`` (all side-effectful). A future evaluator pass may gain an
``unsafe=True`` flag to attempt them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from vsdx.formula.errors import FormulaEvaluationError, FormulaTypeError

FormulaValue = object  # broadened for built-ins — Any of float/int/bool/str/None


@dataclass(frozen=True)
class BuiltinFunction:
    """Metadata + callable for a ShapeSheet built-in.

    ``min_args`` and ``max_args`` implement Visio's variadic-arity model
    (``MIN(a, b, c, ...)``). ``max_args=-1`` means unbounded.
    """

    name: str
    func: Callable[..., FormulaValue]
    min_args: int
    max_args: int

    def __call__(self, *args: FormulaValue) -> FormulaValue:
        argc = len(args)
        if argc < self.min_args:
            raise FormulaEvaluationError(
                f"{self.name} expects at least {self.min_args} argument(s), got {argc}"
            )
        if self.max_args != -1 and argc > self.max_args:
            raise FormulaEvaluationError(
                f"{self.name} expects at most {self.max_args} argument(s), got {argc}"
            )
        return self.func(*args)


# ----------------------------------------------------------------------- coercions


def _to_number(value: FormulaValue, *, func: str = "", arg_index: int = 0) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise FormulaTypeError(
                f"{func}: argument {arg_index} ({value!r}) is not numeric"
            ) from exc
    raise FormulaTypeError(
        f"{func}: cannot coerce {type(value).__name__} to number"
    )


def _to_bool(value: FormulaValue) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        low = value.strip().lower()
        if low in {"true", "1", "yes"}:
            return True
        if low in {"false", "0", "no", ""}:
            return False
        # Excel/Visio convention: any non-empty non-zero string is true.
        return True
    return bool(value)


def _to_string(value: FormulaValue) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        # Visio prefers integer-looking floats without trailing .0.
        if value.is_integer() and abs(value) < 1e16:
            return str(int(value))
        return repr(value)
    return str(value)


# ----------------------------------------------------------------------- math


def _fn_abs(x: FormulaValue) -> float:
    return abs(_to_number(x, func="ABS"))


def _fn_sign(x: FormulaValue) -> float:
    v = _to_number(x, func="SIGN")
    if v > 0:
        return 1.0
    if v < 0:
        return -1.0
    return 0.0


def _fn_sqrt(x: FormulaValue) -> float:
    v = _to_number(x, func="SQRT")
    if v < 0:
        raise FormulaEvaluationError("SQRT of negative number")
    return math.sqrt(v)


def _fn_sin(x: FormulaValue) -> float:
    return math.sin(_to_number(x, func="SIN"))


def _fn_cos(x: FormulaValue) -> float:
    return math.cos(_to_number(x, func="COS"))


def _fn_tan(x: FormulaValue) -> float:
    return math.tan(_to_number(x, func="TAN"))


def _fn_asin(x: FormulaValue) -> float:
    v = _to_number(x, func="ASIN")
    if not -1.0 <= v <= 1.0:
        raise FormulaEvaluationError("ASIN domain error")
    return math.asin(v)


def _fn_acos(x: FormulaValue) -> float:
    v = _to_number(x, func="ACOS")
    if not -1.0 <= v <= 1.0:
        raise FormulaEvaluationError("ACOS domain error")
    return math.acos(v)


def _fn_atan(x: FormulaValue) -> float:
    return math.atan(_to_number(x, func="ATAN"))


def _fn_atan2(y: FormulaValue, x: FormulaValue) -> float:
    return math.atan2(_to_number(y, func="ATAN2", arg_index=0), _to_number(x, func="ATAN2", arg_index=1))


def _fn_degrees(x: FormulaValue) -> float:
    return math.degrees(_to_number(x, func="DEGREES"))


def _fn_radians(x: FormulaValue) -> float:
    return math.radians(_to_number(x, func="RADIANS"))


def _fn_exp(x: FormulaValue) -> float:
    return math.exp(_to_number(x, func="EXP"))


def _fn_ln(x: FormulaValue) -> float:
    v = _to_number(x, func="LN")
    if v <= 0:
        raise FormulaEvaluationError("LN of non-positive number")
    return math.log(v)


def _fn_log10(x: FormulaValue) -> float:
    v = _to_number(x, func="LOG10")
    if v <= 0:
        raise FormulaEvaluationError("LOG10 of non-positive number")
    return math.log10(v)


def _fn_power(base: FormulaValue, exponent: FormulaValue) -> float:
    return math.pow(_to_number(base, func="POWER", arg_index=0), _to_number(exponent, func="POWER", arg_index=1))


def _fn_mod(a: FormulaValue, b: FormulaValue) -> float:
    bv = _to_number(b, func="MOD", arg_index=1)
    if bv == 0:
        raise FormulaEvaluationError("MOD by zero")
    return math.fmod(_to_number(a, func="MOD", arg_index=0), bv)


def _fn_int(x: FormulaValue) -> float:
    return float(math.floor(_to_number(x, func="INT")))


def _fn_trunc(x: FormulaValue, digits: FormulaValue = 0) -> float:
    v = _to_number(x, func="TRUNC", arg_index=0)
    d = int(_to_number(digits, func="TRUNC", arg_index=1))
    mul = 10 ** d
    return math.trunc(v * mul) / mul


def _fn_round(x: FormulaValue, digits: FormulaValue = 0) -> float:
    v = _to_number(x, func="ROUND", arg_index=0)
    d = int(_to_number(digits, func="ROUND", arg_index=1))
    return round(v, d)


def _fn_ceiling(x: FormulaValue, multiple: FormulaValue = 1.0) -> float:
    v = _to_number(x, func="CEILING", arg_index=0)
    m = _to_number(multiple, func="CEILING", arg_index=1)
    if m == 0:
        raise FormulaEvaluationError("CEILING multiple is zero")
    return math.ceil(v / m) * m


def _fn_floor(x: FormulaValue, multiple: FormulaValue = 1.0) -> float:
    v = _to_number(x, func="FLOOR", arg_index=0)
    m = _to_number(multiple, func="FLOOR", arg_index=1)
    if m == 0:
        raise FormulaEvaluationError("FLOOR multiple is zero")
    return math.floor(v / m) * m


def _fn_pi() -> float:
    return math.pi


# ----------------------------------------------------------------------- stats


def _flatten_numeric(args: tuple[FormulaValue, ...], *, func: str) -> list[float]:
    out: list[float] = []
    for i, a in enumerate(args):
        if a is None:
            continue
        out.append(_to_number(a, func=func, arg_index=i))
    return out


def _fn_min(*args: FormulaValue) -> float:
    nums = _flatten_numeric(args, func="MIN")
    if not nums:
        raise FormulaEvaluationError("MIN requires at least one argument")
    return min(nums)


def _fn_max(*args: FormulaValue) -> float:
    nums = _flatten_numeric(args, func="MAX")
    if not nums:
        raise FormulaEvaluationError("MAX requires at least one argument")
    return max(nums)


def _fn_sum(*args: FormulaValue) -> float:
    return math.fsum(_flatten_numeric(args, func="SUM"))


def _fn_avg(*args: FormulaValue) -> float:
    nums = _flatten_numeric(args, func="AVG")
    if not nums:
        raise FormulaEvaluationError("AVG requires at least one argument")
    return math.fsum(nums) / len(nums)


def _fn_count(*args: FormulaValue) -> float:
    # In Visio, COUNT counts numeric args (non-None, non-string).
    count = 0
    for a in args:
        if a is None:
            continue
        if isinstance(a, (int, float, bool)):
            count += 1
    return float(count)


# ----------------------------------------------------------------------- logic


def _fn_if(cond: FormulaValue, a: FormulaValue, b: FormulaValue = None) -> FormulaValue:
    return a if _to_bool(cond) else b


def _fn_and(*args: FormulaValue) -> bool:
    if not args:
        raise FormulaEvaluationError("AND requires at least one argument")
    return all(_to_bool(a) for a in args)


def _fn_or(*args: FormulaValue) -> bool:
    if not args:
        raise FormulaEvaluationError("OR requires at least one argument")
    return any(_to_bool(a) for a in args)


def _fn_not(x: FormulaValue) -> bool:
    return not _to_bool(x)


def _fn_xor(*args: FormulaValue) -> bool:
    if not args:
        raise FormulaEvaluationError("XOR requires at least one argument")
    count = sum(1 for a in args if _to_bool(a))
    return count % 2 == 1


def _fn_iserr(_x: FormulaValue) -> bool:
    # We don't propagate error values in 0.1.0 — all errors raise. ISERR
    # therefore returns FALSE for any concrete value that made it here.
    return False


# ----------------------------------------------------------------------- strings


def _fn_len(s: FormulaValue) -> float:
    return float(len(_to_string(s)))


def _fn_left(s: FormulaValue, n: FormulaValue) -> str:
    text = _to_string(s)
    k = max(0, int(_to_number(n, func="LEFT", arg_index=1)))
    return text[:k]


def _fn_right(s: FormulaValue, n: FormulaValue) -> str:
    text = _to_string(s)
    k = max(0, int(_to_number(n, func="RIGHT", arg_index=1)))
    return text[-k:] if k else ""


def _fn_mid(s: FormulaValue, start: FormulaValue, length: FormulaValue) -> str:
    text = _to_string(s)
    i = max(1, int(_to_number(start, func="MID", arg_index=1)))
    k = max(0, int(_to_number(length, func="MID", arg_index=2)))
    # Visio uses 1-based indexing.
    return text[i - 1 : i - 1 + k]


def _fn_upper(s: FormulaValue) -> str:
    return _to_string(s).upper()


def _fn_lower(s: FormulaValue) -> str:
    return _to_string(s).lower()


def _fn_trim(s: FormulaValue) -> str:
    return _to_string(s).strip()


def _fn_format(value: FormulaValue, _fmt: FormulaValue = "") -> str:
    # TODO: formula FORMAT — faithful picture-string formatting is a
    # substantial sub-project (Visio's FORMAT grammar differs from both
    # .NET and Excel). 0.1.0 stringifies and ignores the picture.
    return _to_string(value)


def _fn_formatex(value: FormulaValue, _fmt: FormulaValue = "", *_rest: FormulaValue) -> str:
    # TODO: formula FORMATEX — Visio's extended-format sibling to FORMAT.
    return _to_string(value)


def _fn_concatenate(*args: FormulaValue) -> str:
    return "".join(_to_string(a) for a in args)


# ----------------------------------------------------------------------- lookup


def _fn_index(index: FormulaValue, *values: FormulaValue) -> FormulaValue:
    if not values:
        raise FormulaEvaluationError("INDEX requires at least one value argument")
    i = int(_to_number(index, func="INDEX", arg_index=0))
    # Visio's INDEX is 0-based; clamp to range.
    if i < 0:
        return values[0]
    if i >= len(values):
        return values[-1]
    return values[i]


def _fn_lookup(key: FormulaValue, *pairs: FormulaValue) -> FormulaValue:
    # LOOKUP(key, k1, v1, k2, v2, ...) — walk pairs, first key-match wins.
    if len(pairs) % 2 != 0:
        raise FormulaEvaluationError("LOOKUP requires an even number of key/value args")
    for i in range(0, len(pairs), 2):
        if pairs[i] == key:
            return pairs[i + 1]
    return None


# ----------------------------------------------------------------------- shapesheet


def _fn_guard(x: FormulaValue) -> FormulaValue:
    """GUARD(x) — Visio marks the cell as user-protected but the value
    is ``x`` at read time. For our evaluator, it's the identity function.
    """
    return x


def _fn_setatref(x: FormulaValue) -> FormulaValue:
    # SETATREF / SETATREFEVAL / SETATREFEXPR pass the value through;
    # the side effect (mutate the referenced cell) is an authoring-time
    # concern we don't model at eval time.
    return x


def _fn_dependson(*args: FormulaValue) -> FormulaValue:
    # DEPENDSON(a, b, ...) — forces a dependency edge to each arg. The
    # dependency graph pass over the AST picks these up separately
    # (see graph.py). Returns the first arg for composition.
    if not args:
        return 0.0
    return args[0]


def _fn_themeval(_value: FormulaValue = None, fallback: FormulaValue = None) -> FormulaValue:
    # TODO: formula THEMEVAL — theme-color resolution requires a live
    # theme part. 0.1.0 returns the explicit fallback, or 0 / empty.
    if fallback is not None:
        return fallback
    return 0.0


def _fn_use(master: FormulaValue) -> FormulaValue:
    # USE(masterName) — declares master inheritance. Passthrough.
    return master


def _fn_bound(x: FormulaValue, lo: FormulaValue, hi: FormulaValue) -> float:
    v = _to_number(x, func="BOUND")
    low = _to_number(lo, func="BOUND", arg_index=1)
    high = _to_number(hi, func="BOUND", arg_index=2)
    if low > high:
        low, high = high, low
    return max(low, min(high, v))


def _fn_minmax(x: FormulaValue, lo: FormulaValue, hi: FormulaValue) -> float:
    # Historical alias for BOUND (present in some older ShapeSheet variants).
    return _fn_bound(x, lo, hi)


def _fn_true() -> bool:
    return True


def _fn_false() -> bool:
    return False


# ----------------------------------------------------------------------- sumif


def _matches_sumif_condition(value: FormulaValue, condition: FormulaValue) -> bool:
    """Test ``value`` against a SUMIF condition.

    Visio / Excel SUMIF accepts conditions either as a scalar (implicit
    equality) or as a string starting with a comparison operator:
    ``">5"``, ``"<=10"``, ``"<>0"``, ``"=3"``. We mirror that subset —
    enough for the ShapeSheet formulas we've seen in the wild.
    """
    if isinstance(condition, str):
        text = condition.strip()
        for op in ("<=", ">=", "<>", "=", "<", ">"):
            if text.startswith(op):
                rhs_text = text[len(op):].strip()
                try:
                    rhs: FormulaValue = float(rhs_text)
                except ValueError:
                    rhs = rhs_text
                try:
                    lv = _to_number(value, func="SUMIF")
                    rv = _to_number(rhs, func="SUMIF")
                except FormulaTypeError:
                    lv = _to_string(value)
                    rv = _to_string(rhs)
                if op == "=":
                    return lv == rv
                if op == "<>":
                    return lv != rv
                if op == "<":
                    return lv < rv
                if op == "<=":
                    return lv <= rv
                if op == ">":
                    return lv > rv
                if op == ">=":
                    return lv >= rv
        # No operator prefix — treat as literal equality on strings.
        return _to_string(value) == text
    # Non-string condition: scalar equality after numeric coercion.
    try:
        return _to_number(value, func="SUMIF") == _to_number(condition, func="SUMIF")
    except FormulaTypeError:
        return value == condition


def _fn_sumif(
    range_value: FormulaValue,
    condition: FormulaValue,
    sum_value: FormulaValue = None,
) -> float:
    """Simplified SUMIF over a single scalar.

    Full Visio / Excel SUMIF takes a *range* as its first argument, but
    the 0.1.0 evaluator evaluates arguments eagerly to scalars so there
    is no range object to iterate. We support the common scalar case:
    if ``range_value`` matches ``condition``, return the numeric value
    of ``sum_value`` (or ``range_value`` when ``sum_value`` is omitted),
    otherwise ``0.0``. See :func:`_matches_sumif_condition` for the
    condition grammar.
    """
    if _matches_sumif_condition(range_value, condition):
        target = sum_value if sum_value is not None else range_value
        return _to_number(target, func="SUMIF")
    return 0.0


# ----------------------------------------------------------------------- geometry


def _fn_height(x: FormulaValue = None) -> FormulaValue:
    """HEIGHT — passthrough for cache-through round-trip fidelity.

    Native Visio treats ``HEIGHT`` as a cell reference; when it shows up
    in function position (``HEIGHT(expr)``) we return the argument so
    the formula reconstitutes losslessly. With no argument, returns 0.
    """
    return x if x is not None else 0.0


def _fn_width(x: FormulaValue = None) -> FormulaValue:
    """WIDTH — passthrough counterpart to :func:`_fn_height`."""
    return x if x is not None else 0.0


def _fn_pnt(x: FormulaValue, y: FormulaValue) -> Tuple[float, float]:
    """PNT(x, y) — constructs a 2D point.

    Returns a Python tuple so callers can destructure for later geometry
    passes. The evaluator's value union is widened at call sites that
    may observe ``PNT`` output.
    """
    return (_to_number(x, func="PNT", arg_index=0), _to_number(y, func="PNT", arg_index=1))


def _fn_loctopar(x: FormulaValue) -> FormulaValue:
    """LOCTOPAR(x) — local-to-parent coordinate transform, passthrough."""
    return x


def _fn_partoloc(x: FormulaValue) -> FormulaValue:
    """PARTOLOC(x) — parent-to-local coordinate transform, passthrough."""
    return x


# ----------------------------------------------------------------------- registry


BUILTINS: dict[str, BuiltinFunction] = {}


def register_function(
    name: str,
    func: Callable[..., FormulaValue],
    *,
    min_args: int = 0,
    max_args: int = -1,
) -> None:
    """Register a new built-in, overwriting any prior registration.

    Exposed publicly so the ``shapes`` / ``connector`` track can plug in
    geometry-aware functions (``ANGLEALONGPATH``, ``LOCTOLOC``) without
    editing this module.
    """
    BUILTINS[name.upper()] = BuiltinFunction(name.upper(), func, min_args, max_args)


def _register_all() -> None:
    entries: list[tuple[str, Callable[..., FormulaValue], int, int]] = [
        ("ABS", _fn_abs, 1, 1),
        ("SIGN", _fn_sign, 1, 1),
        ("SQRT", _fn_sqrt, 1, 1),
        ("SIN", _fn_sin, 1, 1),
        ("COS", _fn_cos, 1, 1),
        ("TAN", _fn_tan, 1, 1),
        ("ASIN", _fn_asin, 1, 1),
        ("ACOS", _fn_acos, 1, 1),
        ("ATAN", _fn_atan, 1, 1),
        ("ATAN2", _fn_atan2, 2, 2),
        ("DEGREES", _fn_degrees, 1, 1),
        ("RADIANS", _fn_radians, 1, 1),
        ("EXP", _fn_exp, 1, 1),
        ("LN", _fn_ln, 1, 1),
        ("LOG10", _fn_log10, 1, 1),
        ("POWER", _fn_power, 2, 2),
        ("MOD", _fn_mod, 2, 2),
        ("INT", _fn_int, 1, 1),
        ("TRUNC", _fn_trunc, 1, 2),
        ("ROUND", _fn_round, 1, 2),
        ("CEILING", _fn_ceiling, 1, 2),
        ("FLOOR", _fn_floor, 1, 2),
        ("PI", _fn_pi, 0, 0),
        ("MIN", _fn_min, 1, -1),
        ("MAX", _fn_max, 1, -1),
        ("SUM", _fn_sum, 0, -1),
        ("AVG", _fn_avg, 1, -1),
        ("AVERAGE", _fn_avg, 1, -1),
        ("COUNT", _fn_count, 0, -1),
        ("IF", _fn_if, 2, 3),
        ("AND", _fn_and, 1, -1),
        ("OR", _fn_or, 1, -1),
        ("NOT", _fn_not, 1, 1),
        ("XOR", _fn_xor, 1, -1),
        ("ISERR", _fn_iserr, 1, 1),
        ("ISERROR", _fn_iserr, 1, 1),
        ("LEN", _fn_len, 1, 1),
        ("LEFT", _fn_left, 2, 2),
        ("RIGHT", _fn_right, 2, 2),
        ("MID", _fn_mid, 3, 3),
        ("UPPER", _fn_upper, 1, 1),
        ("LOWER", _fn_lower, 1, 1),
        ("TRIM", _fn_trim, 1, 1),
        ("FORMAT", _fn_format, 1, 2),
        ("FORMATEX", _fn_formatex, 1, -1),
        ("CONCATENATE", _fn_concatenate, 1, -1),
        # CONCAT — Visio 2013+ alias for CONCATENATE; same semantics as
        # Excel's CONCAT (no inter-arg separator). Also lets the formula
        # source ``CONCAT(a, b)`` round-trip without rewriting to the
        # older spelling.
        ("CONCAT", _fn_concatenate, 1, -1),
        ("INDEX", _fn_index, 1, -1),
        ("LOOKUP", _fn_lookup, 1, -1),
        ("GUARD", _fn_guard, 1, 1),
        ("SETATREF", _fn_setatref, 1, -1),
        ("SETATREFEVAL", _fn_setatref, 1, -1),
        ("SETATREFEXPR", _fn_setatref, 1, -1),
        ("DEPENDSON", _fn_dependson, 1, -1),
        ("THEMEVAL", _fn_themeval, 0, 2),
        ("USE", _fn_use, 1, 1),
        ("BOUND", _fn_bound, 3, 3),
        ("MINMAX", _fn_minmax, 3, 3),
        ("TRUE", _fn_true, 0, 0),
        ("FALSE", _fn_false, 0, 0),
        ("SUMIF", _fn_sumif, 2, 3),
        ("HEIGHT", _fn_height, 0, 1),
        ("WIDTH", _fn_width, 0, 1),
        ("PNT", _fn_pnt, 2, 2),
        ("LOCTOPAR", _fn_loctopar, 1, 1),
        ("PARTOLOC", _fn_partoloc, 1, 1),
    ]
    for name, func, lo, hi in entries:
        BUILTINS[name] = BuiltinFunction(name, func, lo, hi)


_register_all()


#: Sorted tuple of all registered built-in function names — handy for
#: introspection, documentation, and parser-level error-reporting.
FUNCTION_NAMES: tuple[str, ...] = tuple(sorted(BUILTINS))


def get_builtin(name: str) -> Optional[BuiltinFunction]:
    """Look up a built-in by (case-insensitive) name."""
    return BUILTINS.get(name.upper())
