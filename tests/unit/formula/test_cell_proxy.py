"""Tests for the :class:`vsdx.cell.Cell` proxy.

Exercises the typed accessors (``name``/``value``/``formula``/``unit``),
``evaluate`` against live + mapping contexts, and ``recompute`` writing
back to ``@V``.
"""

from __future__ import annotations

import pytest

from vsdx.cell import Cell
from vsdx.formula import Context, MappingShapeSheetContext
from vsdx.formula.errors import FormulaEvaluationError
from vsdx.oxml import nsdecls, parse_xml


def _cell(xml_attrs: str):
    """Parse a single ``<vsdx:Cell>`` element with the given attribute string."""

    xml = ('<vsdx:Cell %s %s/>' % (nsdecls("vsdx"), xml_attrs)).encode()
    return parse_xml(xml)


def _shape_with_formula_cell(name: str, value: str, formula: str):
    """Build a shape carrying a single named cell with the given V/F."""

    xml = (
        '<vsdx:Shape %s ID="1">'
        '<vsdx:Cell N="Width" V="10"/>'
        '<vsdx:Cell N="Height" V="4"/>'
        '<vsdx:Cell N="%s" V="%s" F="%s"/>'
        "</vsdx:Shape>" % (nsdecls("vsdx"), name, value, formula)
    ).encode()
    return parse_xml(xml)


class DescribeCellAccessors:
    def it_exposes_the_name_value_formula_unit_attributes(self):
        cell_el = _cell('N="PinX" V="2" F="Width/2" U="IN"')
        cell = Cell(cell_el)
        assert cell.name == "PinX"
        assert cell.value == "2"
        assert cell.formula == "Width/2"
        assert cell.unit == "IN"

    def it_returns_None_for_absent_attributes(self):
        cell_el = _cell('N="PinX"')
        cell = Cell(cell_el)
        assert cell.value is None
        assert cell.formula is None
        assert cell.unit is None

    def it_writes_value_through_to_the_underlying_element(self):
        cell_el = _cell('N="PinX" V="2"')
        cell = Cell(cell_el)
        cell.value = "5"
        assert cell_el.get("V") == "5"

    def it_clears_value_on_None_assignment(self):
        cell_el = _cell('N="PinX" V="2"')
        cell = Cell(cell_el)
        cell.value = None
        assert cell_el.get("V") is None

    def it_writes_formula_through_to_the_underlying_element(self):
        cell_el = _cell('N="PinX" V="0"')
        cell = Cell(cell_el)
        cell.formula = "Width*2"
        assert cell_el.get("F") == "Width*2"

    def it_clears_formula_on_None_assignment(self):
        cell_el = _cell('N="PinX" V="0" F="Width*2"')
        cell = Cell(cell_el)
        cell.formula = None
        assert cell_el.get("F") is None


class DescribeCellEvaluate:
    def it_evaluates_a_literal_formula_without_a_context(self):
        cell_el = _cell('N="PinX" V="0" F="2 + 3"')
        cell = Cell(cell_el)
        assert cell.evaluate() == 5.0

    def it_evaluates_a_formula_against_a_mapping_context(self):
        cell_el = _cell('N="PinX" V="0" F="Width/2"')
        cell = Cell(cell_el)
        ctx = MappingShapeSheetContext({"Width": 10.0})
        assert cell.evaluate(ctx) == 5.0

    def it_evaluates_a_formula_against_a_live_shape_context(self):
        shape_el = _shape_with_formula_cell("PinX", "0", "Width/2")
        # Last cell on the shape is PinX.
        pin_cell = Cell(shape_el.cell_lst[-1])
        ctx = Context.for_shape(shape_el)
        assert pin_cell.evaluate(ctx) == 5.0

    def it_returns_the_coerced_value_when_no_formula_is_present(self):
        cell_el = _cell('N="Width" V="10"')
        cell = Cell(cell_el)
        assert cell.evaluate() == 10.0

    def it_returns_None_for_an_empty_value_cell_with_no_formula(self):
        cell_el = _cell('N="LineColor" V=""')
        cell = Cell(cell_el)
        assert cell.evaluate() is None

    def it_coerces_TRUE_FALSE_value_strings_to_bools(self):
        true_cell = Cell(_cell('N="Foo" V="TRUE"'))
        false_cell = Cell(_cell('N="Foo" V="FALSE"'))
        assert true_cell.evaluate() is True
        assert false_cell.evaluate() is False

    def it_falls_back_to_the_raw_string_when_value_is_not_numeric(self):
        cell_el = _cell('N="LineColor" V="Themed"')
        cell = Cell(cell_el)
        assert cell.evaluate() == "Themed"

    def it_raises_on_unknown_function_names(self):
        cell_el = _cell('N="Foo" V="0" F="NoSuchFunc(1)"')
        cell = Cell(cell_el)
        with pytest.raises(FormulaEvaluationError):
            cell.evaluate()


class DescribeCellRecompute:
    def it_writes_the_evaluated_value_back_to_V_and_returns_True(self):
        shape_el = _shape_with_formula_cell("PinX", "0", "Width/2")
        cell = Cell(shape_el.cell_lst[-1])
        ctx = Context.for_shape(shape_el)
        assert cell.recompute(ctx) is True
        assert cell.value == "5"

    def it_returns_False_when_the_recomputed_value_matches_existing_V(self):
        shape_el = _shape_with_formula_cell("PinX", "5", "Width/2")
        cell = Cell(shape_el.cell_lst[-1])
        ctx = Context.for_shape(shape_el)
        assert cell.recompute(ctx) is False
        assert cell.value == "5"

    def it_returns_False_for_a_cell_without_a_formula(self):
        cell_el = _cell('N="Width" V="10"')
        cell = Cell(cell_el)
        assert cell.recompute() is False
        assert cell.value == "10"

    def it_emits_TRUE_FALSE_for_bool_results(self):
        cell_el = _cell('N="Vis" V="" F="Width > 5"')
        # Evaluate against a literal context where Width=10
        ctx = MappingShapeSheetContext({"Width": 10.0})
        cell = Cell(cell_el)
        assert cell.recompute(ctx) is True
        assert cell.value == "TRUE"

    def it_trims_trailing_zeros_in_float_results(self):
        cell_el = _cell('N="Pi3" V="" F="3.14159"')
        cell = Cell(cell_el)
        assert cell.recompute() is True
        # Visio strips trailing zeros / decimal point on integer-valued
        # floats; this number is not integer-valued so it round-trips.
        assert "0000" not in (cell.value or "")
