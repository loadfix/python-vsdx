"""Tests for the enum vocabularies."""

from __future__ import annotations

from vsdx.enum.cells import ST_RowType, ST_SectionName, ST_Unit
from vsdx.enum.shapes import VS_CONNECTOR_STYLE, VS_SHAPE_TYPE


class DescribeVsShapeType:
    def it_exposes_the_builtin_master_names(self):
        assert VS_SHAPE_TYPE.RECTANGLE == "Rectangle"
        assert VS_SHAPE_TYPE.ELLIPSE == "Ellipse"
        assert VS_SHAPE_TYPE.TRIANGLE == "Triangle"
        assert VS_SHAPE_TYPE.DYNAMIC_CONNECTOR == "Dynamic connector"

    def its_members_are_strings(self):
        assert isinstance(VS_SHAPE_TYPE.RECTANGLE.value, str)


class DescribeConnectorStyle:
    def it_exposes_the_common_styles(self):
        assert VS_CONNECTOR_STYLE.RIGHT_ANGLE.value == "1"
        assert VS_CONNECTOR_STYLE.STRAIGHT.value == "2"


class DescribeSectionName:
    def it_has_the_expected_members(self):
        assert ST_SectionName.GEOMETRY == "Geometry"
        assert ST_SectionName.CHARACTER == "Character"
        assert ST_SectionName.PARAGRAPH == "Paragraph"


class DescribeRowType:
    def it_has_MoveTo_and_LineTo(self):
        assert ST_RowType.MOVE_TO == "MoveTo"
        assert ST_RowType.LINE_TO == "LineTo"


class DescribeSTUnit:
    def it_carries_inch_unit_value(self):
        assert ST_Unit.INCHES == "IN"
        assert ST_Unit.POINTS == "PT"
        assert ST_Unit.DEGREES == "DEG"
