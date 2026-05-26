"""Tests for the :class:`vsdx.formula.Context` namespace facade.

The facade is a thin convenience over the underlying constructors so
user-facing code can write ``Context.for_shape(s)`` /
``Context.for_mapping(...)`` without importing extra symbols.
"""

from __future__ import annotations

from vsdx.formula import Context, MappingShapeSheetContext, evaluate
from vsdx.formula.integration import ShapeContext
from vsdx.oxml import nsdecls, parse_xml


def _shape():
    xml = (
        '<vsdx:Shape %s ID="1">'
        '<vsdx:Cell N="Width" V="10"/>'
        '<vsdx:Cell N="Height" V="4"/>'
        "</vsdx:Shape>" % nsdecls("vsdx")
    ).encode()
    return parse_xml(xml)


class DescribeContextNamespace:
    def it_for_shape_builds_a_ShapeContext(self):
        ctx = Context.for_shape(_shape())
        assert isinstance(ctx, ShapeContext)

    def it_for_mapping_builds_a_MappingShapeSheetContext(self):
        ctx = Context.for_mapping({"Width": 10.0})
        assert isinstance(ctx, MappingShapeSheetContext)

    def it_for_mapping_resolves_explicit_keys(self):
        ctx = Context.for_mapping({"Width": 10.0, "Height": 4.0})
        assert evaluate("Width * Height", ctx) == 40.0

    def it_for_mapping_supports_strict_mode(self):
        import pytest

        from vsdx.formula.errors import FormulaEvaluationError

        ctx = Context.for_mapping({"Width": 10.0}, strict=True)
        with pytest.raises(FormulaEvaluationError):
            evaluate("DoesNotExist", ctx)

    def it_for_shape_supports_strict_mode(self):
        import pytest

        from vsdx.formula.errors import FormulaEvaluationError

        ctx = Context.for_shape(_shape(), strict=True)
        with pytest.raises(FormulaEvaluationError):
            evaluate("DoesNotExist", ctx)
