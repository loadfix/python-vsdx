"""Table-driven tests for :mod:`vsdx.formula.evaluator`."""

from __future__ import annotations

import math

import pytest

from vsdx.formula.context import MappingShapeSheetContext
from vsdx.formula.errors import FormulaEvaluationError
from vsdx.formula.evaluator import Evaluator, evaluate


@pytest.fixture
def ctx():
    return MappingShapeSheetContext(
        {
            "Width": 10.0,
            "Height": 4.0,
            "PinX": 5.0,
            "PinY": 2.0,
            "BeginX": 1.0,
            "EndX": 9.0,
            "User.Scale": 2.0,
            "Geometry1.X1": 0.25,
            "Sheet.5!PinX": 7.5,
        }
    )


class DescribeLiteralEvaluation:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("42", 42.0),
            ("3.14", 3.14),
            ('"hello"', "hello"),
            ("TRUE", True),
            ("FALSE", False),
            ("100%", 1.0),
            (".25", 0.25),
        ],
    )
    def it_returns_literal_values_unchanged(self, source, expected):
        assert evaluate(source) == expected


class DescribeArithmetic:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("1 + 2", 3.0),
            ("10 - 3", 7.0),
            ("4 * 5", 20.0),
            ("15 / 4", 3.75),
            ("2^10", 1024.0),
            ("-5", -5.0),
            ("--7", 7.0),
            ("1 + 2 * 3", 7.0),
            ("(1 + 2) * 3", 9.0),
            ("2^3^2", 512.0),  # right-associative: 2^(3^2).
        ],
    )
    def it_evaluates(self, source, expected):
        assert evaluate(source) == pytest.approx(expected)

    def it_raises_on_division_by_zero(self):
        with pytest.raises(FormulaEvaluationError):
            evaluate("1 / 0")


class DescribeComparison:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("1 = 1", True),
            ("1 <> 2", True),
            ("1 < 2", True),
            ("2 <= 2", True),
            ("3 > 2", True),
            ("2 >= 3", False),
            ('"a" = "a"', True),
            ('"a" < "b"', True),
        ],
    )
    def it_returns_bool(self, source, expected):
        assert evaluate(source) is expected


class DescribeStringConcat:
    def it_concatenates_with_ampersand(self):
        assert evaluate('"foo" & "bar"') == "foobar"

    def it_stringifies_numeric_operands(self):
        assert evaluate('"count=" & 5') == "count=5"


class DescribeFunctionCalls:
    def it_invokes_builtin_functions(self):
        assert evaluate("MAX(1, 2, 3)") == 3.0
        assert evaluate("IF(1 > 0, 10, 20)") == 10.0
        assert evaluate("DEGREES(ATAN2(1, 1))") == pytest.approx(45.0)

    def it_nested_call(self):
        assert evaluate("SQRT(POWER(3, 2) + POWER(4, 2))") == pytest.approx(5.0)

    def it_raises_on_unknown_function(self):
        with pytest.raises(FormulaEvaluationError):
            evaluate("NOPE(1)")


class DescribeCellReferenceEvaluation:
    def it_resolves_singleton_cell(self, ctx):
        assert evaluate("Width", ctx) == 10.0

    def it_resolves_section_cell(self, ctx):
        assert evaluate("User.Scale", ctx) == 2.0

    def it_resolves_geometry_cell(self, ctx):
        assert evaluate("Geometry1.X1", ctx) == 0.25

    def it_resolves_cross_shape_reference(self, ctx):
        assert evaluate("Sheet.5!PinX", ctx) == 7.5

    def it_treats_missing_cell_as_zero(self, ctx):
        # Unknown cell returns 0 in non-strict mode, so arithmetic succeeds.
        assert evaluate("Missing * 2", ctx) == 0.0

    def it_raises_in_strict_mode(self):
        strict = MappingShapeSheetContext({}, strict=True)
        with pytest.raises(FormulaEvaluationError):
            evaluate("Missing", strict)

    def it_raises_without_context(self):
        with pytest.raises(FormulaEvaluationError):
            evaluate("Width")


class DescribeVisioFormulas:
    """End-to-end exercise of formulas pulled from the scoping doc's
    connector / geometry examples."""

    def it_computes_connector_midpoint(self, ctx):
        assert evaluate("(BeginX+EndX)/2", ctx) == 5.0

    def it_computes_connector_angle(self, ctx):
        # ATAN2(EndY-BeginY, EndX-BeginX) style.
        extra = MappingShapeSheetContext(
            {"BeginX": 0, "BeginY": 0, "EndX": 1, "EndY": 1}
        )
        assert evaluate("ATAN2(EndY-BeginY, EndX-BeginX)", extra) == pytest.approx(
            math.pi / 4
        )

    def it_computes_width_scaled_geometry(self, ctx):
        # The classic Geometry row formula — X = Width * 0.5.
        assert evaluate("Width * 0.5", ctx) == 5.0

    def it_guards_user_formula(self, ctx):
        assert evaluate("GUARD(Width)", ctx) == 10.0


class DescribeEvaluatorInstance:
    def it_can_be_reused_across_asts(self, ctx):
        ev = Evaluator(ctx)
        from vsdx.formula.parser import parse as _parse

        a = _parse("Width + 1")
        b = _parse("Height - 1")
        assert ev.eval_ast(a) == 11.0
        assert ev.eval_ast(b) == 3.0


# ---------------------------------------------------------------- R11-4 builtins


class DescribeGuardAndSetAtRefFamily:
    """GUARD / SETATREF / SETATREFEXPR / SETATREFEVAL are identity-return
    passthroughs (the authoring-time side effect is not modelled at eval
    time — we just need the round-trip value to survive)."""

    def it_guard_returns_its_argument_unchanged(self):
        assert evaluate("GUARD(42)") == 42.0
        assert evaluate('GUARD("x")') == "x"

    def it_setatref_variants_are_identity(self):
        assert evaluate("SETATREF(99)") == 99.0
        assert evaluate("SETATREFEXPR(12)") == 12.0
        assert evaluate("SETATREFEVAL(7)") == 7.0


class DescribeDependsOn:
    def it_returns_a_value_and_accepts_many_args(self):
        # Preserves existing semantics (see test_formula_builtins.py): the
        # dependency graph walk owns the side effect; the evaluator just
        # needs the call to succeed.
        assert evaluate("DEPENDSON(1, 2, 3)") == 1.0

    def it_accepts_a_single_arg(self):
        assert evaluate("DEPENDSON(42)") == 42.0


class DescribeSumIf:
    def it_sums_when_scalar_matches_a_literal(self):
        # SUMIF(range, condition, [sum_range]) — simplified scalar form.
        # With condition 5 and value 5, the "range" qualifies, so we sum
        # the sum_range (10).
        assert evaluate("SUMIF(5, 5, 10)") == 10.0
        assert evaluate("SUMIF(5, 6, 10)") == 0.0

    def it_parses_comparison_operator_conditions(self):
        assert evaluate('SUMIF(7, ">5", 3)') == 3.0
        assert evaluate('SUMIF(2, ">5", 3)') == 0.0
        assert evaluate('SUMIF(10, "<=10", 1)') == 1.0

    def it_defaults_sum_value_to_range_value(self):
        assert evaluate("SUMIF(4, 4)") == 4.0
        assert evaluate("SUMIF(4, 5)") == 0.0


class DescribeUseFunction:
    def it_looks_up_a_named_cell_when_context_has_one(self):
        from vsdx.formula.context import MappingShapeSheetContext

        ctx_ = MappingShapeSheetContext({"MyMaster": 123.0})
        assert evaluate('USE("MyMaster")', ctx_) == 123.0

    def it_falls_back_to_passthrough_when_name_unknown(self):
        from vsdx.formula.context import MappingShapeSheetContext

        ctx_ = MappingShapeSheetContext({})
        assert evaluate('USE("Unknown")', ctx_) == "Unknown"

    def it_passes_through_when_no_context_attached(self):
        assert evaluate('USE("MasterName")') == "MasterName"


class DescribeGeometryBuiltins:
    def it_height_and_width_are_passthroughs(self):
        assert evaluate("HEIGHT(4.5)") == 4.5
        assert evaluate("WIDTH(10)") == 10.0

    def it_height_and_width_default_to_zero(self):
        assert evaluate("HEIGHT()") == 0.0
        assert evaluate("WIDTH()") == 0.0

    def it_pnt_returns_a_tuple(self):
        assert evaluate("PNT(1, 2)") == (1.0, 2.0)
        assert evaluate("PNT(-3, 4.5)") == (-3.0, 4.5)

    def it_loctopar_partoloc_are_passthroughs(self):
        assert evaluate("LOCTOPAR(7)") == 7.0
        assert evaluate("PARTOLOC(7)") == 7.0
        assert evaluate("LOCTOPAR(-2.5)") == -2.5


class DescribeIfShortCircuit:
    def it_does_not_evaluate_false_branch_when_true(self):
        # 1/0 would raise if evaluated — short-circuit must skip it.
        assert evaluate("IF(1 > 0, 42, 1/0)") == 42.0

    def it_does_not_evaluate_true_branch_when_false(self):
        assert evaluate("IF(1 < 0, 1/0, 99)") == 99.0

    def it_returns_false_when_no_else_branch_given(self):
        # Two-arg IF is uncommon but the parser accepts it; the short-
        # circuit path must still yield a concrete value.
        assert evaluate("IF(1 > 0, 5)") == 5.0
        assert evaluate("IF(1 < 0, 5)") is False


class DescribeLogicalShortCircuit:
    def it_and_short_circuits_on_first_false(self):
        # If AND were eager, 1/0 would raise; short-circuit must skip it.
        assert evaluate("AND(FALSE, 1/0)") is False
        assert evaluate("AND(TRUE, TRUE, TRUE)") is True

    def it_or_short_circuits_on_first_true(self):
        assert evaluate("OR(TRUE, 1/0)") is True
        assert evaluate("OR(FALSE, FALSE, FALSE)") is False

    def it_not_inverts_truthiness(self):
        assert evaluate("NOT(FALSE)") is True
        assert evaluate("NOT(TRUE)") is False
        assert evaluate("NOT(0)") is True
