"""Table-driven tests for :mod:`vsdx.formula.builtins`."""

from __future__ import annotations

import math

import pytest

from vsdx.formula.builtins import BUILTINS, FUNCTION_NAMES, get_builtin, register_function
from vsdx.formula.errors import FormulaEvaluationError, FormulaTypeError


class DescribeBuiltinRegistry:
    def it_exposes_a_sorted_function_name_tuple(self):
        assert FUNCTION_NAMES == tuple(sorted(BUILTINS))

    def it_includes_at_least_fifty_functions(self):
        assert len(FUNCTION_NAMES) >= 50

    @pytest.mark.parametrize(
        "required",
        # Hand-curated sanity list — the core families the scoping doc calls out.
        [
            "ABS", "SQRT", "SIN", "COS", "ATAN2", "POWER", "MOD", "ROUND",
            "TRUNC", "CEILING", "FLOOR", "PI",
            "MIN", "MAX", "SUM", "AVG", "COUNT",
            "IF", "AND", "OR", "NOT", "XOR",
            "LEN", "LEFT", "RIGHT", "MID", "UPPER", "LOWER", "TRIM",
            "INDEX", "LOOKUP",
            "GUARD", "THEMEVAL", "SETATREF", "DEPENDSON", "BOUND",
        ],
    )
    def it_has_each_required_builtin(self, required):
        assert get_builtin(required) is not None

    def it_is_case_insensitive_on_lookup(self):
        assert get_builtin("min") is get_builtin("MIN")


class DescribeArithmetic:
    @pytest.mark.parametrize(
        ("name", "args", "expected"),
        [
            ("ABS", (-5,), 5.0),
            ("SIGN", (-3,), -1.0),
            ("SIGN", (0,), 0.0),
            ("SIGN", (7,), 1.0),
            ("SQRT", (9,), 3.0),
            ("POWER", (2, 10), 1024.0),
            ("MOD", (10, 3), 1.0),
            ("INT", (3.7,), 3.0),
            ("INT", (-3.2,), -4.0),
            ("TRUNC", (3.14159, 2), 3.14),
            ("ROUND", (3.14159, 2), 3.14),
            ("CEILING", (4.3, 1), 5.0),
            ("CEILING", (4.3, 2), 6.0),
            ("FLOOR", (4.9, 2), 4.0),
            ("PI", (), math.pi),
        ],
    )
    def it_computes_expected_value(self, name, args, expected):
        got = BUILTINS[name](*args)
        assert got == pytest.approx(expected)


class DescribeTrig:
    def it_computes_sin_cos_tan(self):
        assert BUILTINS["SIN"](0) == pytest.approx(0.0)
        assert BUILTINS["COS"](0) == pytest.approx(1.0)
        assert BUILTINS["TAN"](0) == pytest.approx(0.0)

    def it_computes_atan2_in_radians(self):
        assert BUILTINS["ATAN2"](1, 1) == pytest.approx(math.pi / 4)

    def it_converts_degrees_and_radians(self):
        assert BUILTINS["DEGREES"](math.pi) == pytest.approx(180.0)
        assert BUILTINS["RADIANS"](180) == pytest.approx(math.pi)

    def it_rejects_asin_domain_error(self):
        with pytest.raises(FormulaEvaluationError):
            BUILTINS["ASIN"](2)


class DescribeStats:
    def it_min_max_sum_avg_count(self):
        assert BUILTINS["MIN"](3, 1, 2) == 1.0
        assert BUILTINS["MAX"](3, 1, 2) == 3.0
        assert BUILTINS["SUM"](1, 2, 3) == 6.0
        assert BUILTINS["AVG"](1, 2, 3, 4) == 2.5
        assert BUILTINS["COUNT"](1, "foo", None, 2, True) == 3.0

    def it_skips_none_in_min(self):
        # None cells (unresolved) are treated as absent.
        assert BUILTINS["MIN"](3, None, 1) == 1.0


class DescribeLogic:
    @pytest.mark.parametrize(
        ("cond", "expected"),
        [(True, "a"), (False, "b"), (1, "a"), (0, "b"), ("non-empty", "a"), ("", "b")],
    )
    def it_if_selects_based_on_truthiness(self, cond, expected):
        assert BUILTINS["IF"](cond, "a", "b") == expected

    def it_and_or_not(self):
        assert BUILTINS["AND"](True, 1, "x") is True
        assert BUILTINS["AND"](True, 0) is False
        assert BUILTINS["OR"](False, 0, 1) is True
        assert BUILTINS["NOT"](0) is True
        assert BUILTINS["NOT"](1) is False

    def it_xor_parity(self):
        assert BUILTINS["XOR"](True, False) is True
        assert BUILTINS["XOR"](True, True) is False
        assert BUILTINS["XOR"](True, True, True) is True


class DescribeStrings:
    def it_len_left_right_mid(self):
        assert BUILTINS["LEN"]("hello") == 5.0
        assert BUILTINS["LEFT"]("hello", 2) == "he"
        assert BUILTINS["RIGHT"]("hello", 2) == "lo"
        assert BUILTINS["MID"]("hello", 2, 3) == "ell"  # 1-based.

    def it_upper_lower_trim(self):
        assert BUILTINS["UPPER"]("abc") == "ABC"
        assert BUILTINS["LOWER"]("ABC") == "abc"
        assert BUILTINS["TRIM"]("  hi  ") == "hi"

    def it_concatenate(self):
        assert BUILTINS["CONCATENATE"]("a", 1, "b") == "a1b"


class DescribeLookup:
    def it_index_is_zero_based_and_clamps(self):
        assert BUILTINS["INDEX"](0, "a", "b", "c") == "a"
        assert BUILTINS["INDEX"](1, "a", "b", "c") == "b"
        assert BUILTINS["INDEX"](99, "a", "b", "c") == "c"
        assert BUILTINS["INDEX"](-1, "a", "b", "c") == "a"

    def it_lookup_walks_key_value_pairs(self):
        assert BUILTINS["LOOKUP"]("b", "a", 1, "b", 2, "c", 3) == 2
        assert BUILTINS["LOOKUP"]("missing", "a", 1) is None

    def it_lookup_rejects_odd_pair_count(self):
        with pytest.raises(FormulaEvaluationError):
            BUILTINS["LOOKUP"]("a", "b", "c", "d")


class DescribeShapeSheetFunctions:
    def it_guard_is_identity(self):
        assert BUILTINS["GUARD"](42) == 42

    def it_setatref_passes_through(self):
        assert BUILTINS["SETATREF"](99) == 99

    def it_themeval_returns_fallback(self):
        assert BUILTINS["THEMEVAL"]("color", 7) == 7

    def it_bound_clamps_to_range(self):
        assert BUILTINS["BOUND"](15, 0, 10) == 10.0
        assert BUILTINS["BOUND"](-5, 0, 10) == 0.0
        assert BUILTINS["BOUND"](5, 0, 10) == 5.0

    def it_bound_swaps_inverted_bounds(self):
        assert BUILTINS["BOUND"](5, 10, 0) == 5.0

    def it_dependson_returns_first(self):
        assert BUILTINS["DEPENDSON"](10, 20, 30) == 10


class DescribeArity:
    def it_rejects_too_few_args(self):
        with pytest.raises(FormulaEvaluationError):
            BUILTINS["POWER"](2)  # needs 2 args

    def it_rejects_too_many_args(self):
        with pytest.raises(FormulaEvaluationError):
            BUILTINS["ABS"](1, 2)  # needs exactly 1


class DescribeRegisterFunction:
    def it_allows_plugin_registration(self):
        def double(x):
            return float(x) * 2.0

        try:
            register_function("DOUBLE", double, min_args=1, max_args=1)
            assert BUILTINS["DOUBLE"](3) == 6.0
        finally:
            BUILTINS.pop("DOUBLE", None)

    def it_rejects_type_mismatches(self):
        with pytest.raises(FormulaTypeError):
            BUILTINS["ABS"]("not-a-number")
