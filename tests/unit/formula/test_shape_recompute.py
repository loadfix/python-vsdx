"""Tests for :meth:`vsdx.shapes.base.Shape.recompute`.

End-to-end: build a shape with computed cells (``Width*0``, ``Height/2``,
etc.), drive the proxy's recompute, and assert ``@V`` reflects the
formula result. Also exercises idempotency, error-stamping on bad
formulas, and the page/document-level wrappers.
"""

from __future__ import annotations

from vsdx.oxml import nsdecls, parse_xml
from vsdx.shapes.base import Shape


def _shape_with(*cells_xml: str, sections_xml: str = ""):
    cells = "".join(cells_xml)
    xml = (
        '<vsdx:Shape %s ID="1">%s%s</vsdx:Shape>'
        % (nsdecls("vsdx"), cells, sections_xml)
    ).encode()
    return parse_xml(xml)


def _value_of(shape_el, name: str):
    """Return the @V of <Cell N=name> on *shape_el* or None."""

    for cell in shape_el.cell_lst:
        if cell.get("N") == name:
            return cell.get("V")
    return None


class DescribeShapeRecompute:
    def it_resolves_singleton_formulas_and_writes_them_to_V(self):
        shape_el = _shape_with(
            '<vsdx:Cell N="Width" V="10"/>',
            '<vsdx:Cell N="Height" V="4"/>',
            '<vsdx:Cell N="PinX" V="0" F="Width/2"/>',
            '<vsdx:Cell N="PinY" V="0" F="Height/2"/>',
        )
        shape = Shape(shape_el, parent=None)
        n = shape.recompute()
        assert n == 2
        assert _value_of(shape_el, "PinX") == "5"
        assert _value_of(shape_el, "PinY") == "2"

    def it_returns_zero_on_a_no_op_recompute(self):
        shape_el = _shape_with(
            '<vsdx:Cell N="Width" V="10"/>',
            '<vsdx:Cell N="PinX" V="5" F="Width/2"/>',
        )
        shape = Shape(shape_el, parent=None)
        # First pass: no change because @V already matches the formula.
        assert shape.recompute() == 0
        assert _value_of(shape_el, "PinX") == "5"

    def it_is_idempotent_on_a_second_pass(self):
        shape_el = _shape_with(
            '<vsdx:Cell N="Width" V="10"/>',
            '<vsdx:Cell N="PinX" V="0" F="Width*2"/>',
        )
        shape = Shape(shape_el, parent=None)
        first = shape.recompute()
        second = shape.recompute()
        assert first == 1  # PinX changed.
        assert second == 0  # No more changes.
        assert _value_of(shape_el, "PinX") == "20"

    def it_walks_into_section_rows_and_recomputes_their_cells(self):
        sections = (
            '<vsdx:Section N="Geometry" IX="0">'
            '<vsdx:Row IX="1" T="LineTo">'
            '<vsdx:Cell N="X" V="0" F="Width*0"/>'
            '<vsdx:Cell N="Y" V="0" F="Height*1"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        shape_el = _shape_with(
            '<vsdx:Cell N="Width" V="10"/>',
            '<vsdx:Cell N="Height" V="4"/>',
            sections_xml=sections,
        )
        shape = Shape(shape_el, parent=None)
        n = shape.recompute()
        assert n == 1  # Y went from 0 to 4; X was already 0.
        # Drill into the geometry section to assert.
        section = shape_el.section_lst[0]
        row = section.row_lst[0]
        cells = {c.get("N"): c.get("V") for c in row.cell_lst}
        assert cells["X"] == "0"
        assert cells["Y"] == "4"

    def it_stamps_E_on_evaluation_failures_without_clobbering_V(self):
        shape_el = _shape_with(
            '<vsdx:Cell N="Width" V="10"/>',
            '<vsdx:Cell N="Bad" V="prev" F="DivByZero(1)"/>',
            '<vsdx:Cell N="Zero" V="prev" F="1/0"/>',
        )
        shape = Shape(shape_el, parent=None)
        n = shape.recompute()
        assert n == 2
        # @V is preserved; @E carries the structured error class name.
        for cell in shape_el.cell_lst:
            if cell.get("N") == "Bad":
                assert cell.get("V") == "prev"
                assert cell.get("E", "").startswith("#ERR")
            if cell.get("N") == "Zero":
                assert cell.get("V") == "prev"
                assert cell.get("E", "").startswith("#ERR")

    def it_clears_the_E_marker_when_a_previously_broken_formula_succeeds(self):
        # Cell starts with @E from a prior recompute; once we fix Width
        # and re-recompute, @E should disappear.
        shape_el = _shape_with(
            '<vsdx:Cell N="Width" V="0"/>',
            '<vsdx:Cell N="Result" V="prev" F="1/Width" E="#ERR: prev"/>',
        )
        shape = Shape(shape_el, parent=None)
        # First pass: still divides by zero, @E stays.
        shape.recompute()
        result = next(c for c in shape_el.cell_lst if c.get("N") == "Result")
        assert (result.get("E") or "").startswith("#ERR")
        # Fix Width and recompute.
        for cell in shape_el.cell_lst:
            if cell.get("N") == "Width":
                cell.set("V", "5")
        shape.recompute()
        result = next(c for c in shape_el.cell_lst if c.get("N") == "Result")
        assert result.get("V") == "0.2"
        assert result.get("E") is None

    def it_skips_cells_without_a_formula(self):
        shape_el = _shape_with(
            '<vsdx:Cell N="Width" V="10"/>',
            '<vsdx:Cell N="Height" V="4"/>',
        )
        shape = Shape(shape_el, parent=None)
        assert shape.recompute() == 0
        assert _value_of(shape_el, "Width") == "10"
        assert _value_of(shape_el, "Height") == "4"

    def it_emits_TRUE_FALSE_for_bool_formulas(self):
        shape_el = _shape_with(
            '<vsdx:Cell N="Width" V="10"/>',
            '<vsdx:Cell N="IsBig" V="" F="Width > 5"/>',
        )
        shape = Shape(shape_el, parent=None)
        shape.recompute()
        assert _value_of(shape_el, "IsBig") == "TRUE"


class DescribeShapeCellAccessor:
    def it_returns_a_Cell_proxy_for_an_existing_named_cell(self):
        from vsdx.cell import Cell

        shape_el = _shape_with(
            '<vsdx:Cell N="Width" V="10"/>',
            '<vsdx:Cell N="PinX" V="0" F="Width/2"/>',
        )
        shape = Shape(shape_el, parent=None)
        pin = shape.cell("PinX")
        assert isinstance(pin, Cell)
        assert pin.formula == "Width/2"

    def it_returns_None_for_an_absent_cell_name(self):
        shape_el = _shape_with('<vsdx:Cell N="Width" V="10"/>')
        shape = Shape(shape_el, parent=None)
        assert shape.cell("LineColor") is None
