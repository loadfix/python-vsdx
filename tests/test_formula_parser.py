"""Table-driven tests for :mod:`vsdx.formula.parser`."""

from __future__ import annotations

import pytest

from vsdx.formula.errors import FormulaParseError
from vsdx.formula.nodes import (
    BinaryOp,
    BoolLiteral,
    CellRef,
    FunctionCall,
    NumberLiteral,
    StringLiteral,
    UnaryOp,
)
from vsdx.formula.parser import parse


class DescribeParser:
    def it_parses_number_literals(self):
        assert parse("42") == NumberLiteral(42.0)
        assert parse("3.14") == NumberLiteral(3.14)
        assert parse("100%") == NumberLiteral(1.0)

    def it_parses_string_literals(self):
        assert parse('"hello"') == StringLiteral("hello")

    def it_parses_boolean_literals(self):
        assert parse("TRUE") == BoolLiteral(True)
        assert parse("false") == BoolLiteral(False)

    def it_strips_leading_equals(self):
        assert parse("=42") == NumberLiteral(42.0)
        assert parse("= Width") == CellRef(name="Width", source="Width")

    @pytest.mark.parametrize(
        ("source", "op"),
        [("1+2", "+"), ("1-2", "-"), ("1*2", "*"), ("1/2", "/"), ("1^2", "^")],
    )
    def it_parses_arithmetic(self, source, op):
        node = parse(source)
        assert isinstance(node, BinaryOp) and node.op == op

    def it_respects_precedence_of_mul_over_add(self):
        node = parse("1 + 2 * 3")
        assert isinstance(node, BinaryOp) and node.op == "+"
        assert isinstance(node.right, BinaryOp) and node.right.op == "*"

    def it_right_associates_exponent(self):
        node = parse("2^3^4")
        assert isinstance(node, BinaryOp) and node.op == "^"
        assert isinstance(node.right, BinaryOp) and node.right.op == "^"

    def it_parses_unary_minus(self):
        node = parse("-5")
        assert isinstance(node, UnaryOp) and node.op == "-"

    @pytest.mark.parametrize(
        ("source", "op"),
        [("a=b", "="), ("a<>b", "<>"), ("a<b", "<"), ("a<=b", "<="), ("a>b", ">"), ("a>=b", ">=")],
    )
    def it_parses_comparison_operators(self, source, op):
        node = parse(source)
        assert isinstance(node, BinaryOp) and node.op == op

    def it_parses_string_concat(self):
        node = parse('"a" & "b"')
        assert isinstance(node, BinaryOp) and node.op == "&"

    def it_parses_parenthesised_expressions(self):
        node = parse("(1 + 2) * 3")
        assert isinstance(node, BinaryOp) and node.op == "*"
        assert isinstance(node.left, BinaryOp) and node.left.op == "+"

    def it_parses_function_call_no_args(self):
        assert parse("PI()") == FunctionCall("PI", ())

    def it_parses_function_call_with_args(self):
        node = parse("MIN(1, 2, 3)")
        assert node.name == "MIN"
        assert len(node.args) == 3

    def it_uppercases_function_names(self):
        assert parse("if(1,2,3)").name == "IF"

    def it_parses_singleton_cell_reference(self):
        assert parse("Width") == CellRef(name="Width", source="Width")

    def it_parses_section_cell_reference(self):
        node = parse("User.Scale")
        assert isinstance(node, CellRef)
        assert node.section == "User"
        assert node.name == "Scale"

    def it_parses_geometry_cell_reference(self):
        node = parse("Geometry1.X1")
        assert isinstance(node, CellRef)
        assert node.section == "Geometry1"
        assert node.name == "X1"

    def it_parses_three_part_cell_reference(self):
        node = parse("Prop.Foo.Prompt")
        assert isinstance(node, CellRef)
        assert node.section == "Prop"
        assert node.row == "Foo"
        assert node.name == "Prompt"

    def it_parses_sheet_N_cross_shape_reference(self):
        node = parse("Sheet.5!PinX")
        assert isinstance(node, CellRef)
        assert node.sheet == "Sheet.5"
        assert node.name == "PinX"

    def it_parses_named_shape_cross_reference(self):
        node = parse("TheShape!Width")
        assert isinstance(node, CellRef)
        assert node.sheet == "TheShape"
        assert node.name == "Width"

    def it_parses_connector_midpoint_formula(self):
        # Classic Dynamic Connector formula.
        node = parse("(BeginX+EndX)/2")
        assert isinstance(node, BinaryOp) and node.op == "/"

    def it_parses_nested_function_calls(self):
        node = parse("IF(AND(A, B), SUM(1,2,3), 0)")
        assert node.name == "IF"
        assert node.args[0].name == "AND"  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        "bad",
        ["1 +", "(1 + 2", "*5", "MIN(1,,2)", "MIN 1", "Sheet.5 + 2"],
    )
    def it_rejects_malformed_expressions(self, bad):
        with pytest.raises(FormulaParseError):
            parse(bad)

    def it_rejects_non_string_source(self):
        with pytest.raises(FormulaParseError):
            parse(42)  # type: ignore[arg-type]
