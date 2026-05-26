"""Tests for :class:`vsdx.formula.integration.ShapeContext`.

Builds shape oxml fragments and asserts the live resolver returns the
expected values for every cell-reference axis: singletons, section
rows, section cells, multi-axis, and cross-shape (``Sheet.N!`` /
``ShapeName!``).
"""

from __future__ import annotations

import pytest

from vsdx.formula import Context, evaluate, for_shape
from vsdx.formula.errors import FormulaEvaluationError
from vsdx.formula.integration import ShapeContext
from vsdx.oxml import nsdecls, parse_xml, qn


def _shape(extra_xml: str = "", *, shape_id: int = 1, name_u: str = ""):
    """Build a small shape with PinX/PinY/Width/Height + *extra_xml*."""

    name_attr = f' NameU="{name_u}"' if name_u else ""
    xml = (
        '<vsdx:Shape %s ID="%d"%s>'
        '<vsdx:Cell N="PinX" V="5"/>'
        '<vsdx:Cell N="PinY" V="3"/>'
        '<vsdx:Cell N="Width" V="10"/>'
        '<vsdx:Cell N="Height" V="4"/>'
        "%s</vsdx:Shape>" % (nsdecls("vsdx"), shape_id, name_attr, extra_xml)
    ).encode()
    return parse_xml(xml)


def _page_with_two_shapes():
    """Build a ``<PageContents>`` with two sibling shapes for cross-shape tests."""

    xml = (
        '<vsdx:PageContents %s>'
        '<vsdx:Shapes>'
        '<vsdx:Shape ID="1">'
        '<vsdx:Cell N="Width" V="10"/>'
        '</vsdx:Shape>'
        '<vsdx:Shape ID="5" NameU="Other" Name="Other">'
        '<vsdx:Cell N="PinX" V="7.5"/>'
        '</vsdx:Shape>'
        '</vsdx:Shapes>'
        '</vsdx:PageContents>' % nsdecls("vsdx")
    ).encode()
    pc = parse_xml(xml)
    shapes = pc.find(qn("vsdx:Shapes")).findall(qn("vsdx:Shape"))
    return pc, shapes


class DescribeShapeContextSingletons:
    def it_resolves_a_singleton_cell_by_name(self):
        ctx = Context.for_shape(_shape())
        assert evaluate("Width", ctx) == 10.0
        assert evaluate("Height", ctx) == 4.0

    def it_returns_zero_when_a_referenced_singleton_is_absent(self):
        # Visio's "missing cell == zero" rule.
        ctx = Context.for_shape(_shape())
        assert evaluate("LineWeight", ctx) == 0.0

    def it_handles_arithmetic_over_singleton_cells(self):
        ctx = Context.for_shape(_shape())
        assert evaluate("Width * Height", ctx) == 40.0
        assert evaluate("(Width + Height) / 2", ctx) == 7.0

    def it_handles_function_calls_over_singleton_cells(self):
        ctx = Context.for_shape(_shape())
        result = evaluate("SQRT(Width*Width + Height*Height)", ctx)
        assert abs(result - 10.770329614269) < 1e-9


class DescribeShapeContextUserSection:
    def it_resolves_a_named_user_row_with_implicit_Value_cell(self):
        extra = (
            '<vsdx:Section N="User">'
            '<vsdx:Row N="Scale"><vsdx:Cell N="Value" V="2.5"/></vsdx:Row>'
            '<vsdx:Row N="Density"><vsdx:Cell N="Value" V="0.7"/></vsdx:Row>'
            "</vsdx:Section>"
        )
        ctx = Context.for_shape(_shape(extra))
        assert evaluate("User.Scale", ctx) == 2.5
        assert evaluate("User.Density", ctx) == 0.7

    def it_handles_three_axis_user_row_explicit_cell_reference(self):
        extra = (
            '<vsdx:Section N="User">'
            '<vsdx:Row N="Scale"><vsdx:Cell N="Prompt" V="Scale factor"/></vsdx:Row>'
            "</vsdx:Section>"
        )
        ctx = Context.for_shape(_shape(extra))
        assert evaluate("User.Scale.Prompt", ctx) == "Scale factor"

    def it_returns_zero_for_an_unknown_user_row(self):
        extra = (
            '<vsdx:Section N="User">'
            '<vsdx:Row N="Scale"><vsdx:Cell N="Value" V="2"/></vsdx:Row>'
            "</vsdx:Section>"
        )
        ctx = Context.for_shape(_shape(extra))
        assert evaluate("User.Missing", ctx) == 0.0


class DescribeShapeContextGeometrySection:
    def it_resolves_geometry_X_and_Y_cells(self):
        extra = (
            '<vsdx:Section N="Geometry" IX="0">'
            '<vsdx:Row IX="1" T="LineTo">'
            '<vsdx:Cell N="X" V="0.25"/><vsdx:Cell N="Y" V="0.5"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        ctx = Context.for_shape(_shape(extra))
        # ``Geometry1.X1`` is parsed as section=Geometry1, name=X1; the
        # X1-shaped cell name resolves to the first row's X cell.
        result_x = evaluate("Geometry1.X1", ctx)
        result_y = evaluate("Geometry1.Y1", ctx)
        assert result_x == 0.25
        assert result_y == 0.5


class DescribeShapeContextCrossShape:
    def it_resolves_Sheet_N_cross_shape_refs_by_id(self):
        _, shapes = _page_with_two_shapes()
        ctx = Context.for_shape(shapes[0])
        assert evaluate("Sheet.5!PinX", ctx) == 7.5

    def it_resolves_named_shape_cross_refs_by_NameU(self):
        _, shapes = _page_with_two_shapes()
        ctx = Context.for_shape(shapes[0])
        assert evaluate("Other!PinX", ctx) == 7.5

    def it_returns_zero_for_an_unknown_cross_shape_target(self):
        _, shapes = _page_with_two_shapes()
        ctx = Context.for_shape(shapes[0])
        assert evaluate("Sheet.999!PinX", ctx) == 0.0


class DescribeShapeContextErrorBehaviour:
    def it_returns_None_by_default_for_unresolved_references(self):
        ctx = Context.for_shape(_shape())
        # The evaluator coerces None → 0; ShapeContext itself returns None.
        ref = type(
            "FakeRef",
            (),
            {
                "name": "Missing",
                "section": None,
                "row": None,
                "sheet": None,
                "qualified": lambda self: "Missing",
            },
        )()
        assert ctx.resolve(ref) is None

    def it_raises_when_strict_mode_is_set(self):
        ctx = Context.for_shape(_shape(), strict=True)
        with pytest.raises(FormulaEvaluationError):
            evaluate("DoesNotExist", ctx)


class DescribeForShapeEntryPoint:
    def it_returns_a_ShapeContext_for_a_bare_oxml_element(self):
        ctx = for_shape(_shape())
        assert isinstance(ctx, ShapeContext)

    def it_returns_a_ShapeContext_for_a_proxy_with__element(self):
        # Mirror the proxy-API shape: object with ._element pointing at oxml.
        class _ProxyLike:
            def __init__(self, el):
                self._element = el

        ctx = for_shape(_ProxyLike(_shape()))
        assert isinstance(ctx, ShapeContext)

    def it_is_aliased_under_Context_for_shape(self):
        ctx = Context.for_shape(_shape())
        assert isinstance(ctx, ShapeContext)
