"""Unit tests for Visio-specific ``ST_*`` simple types."""

from __future__ import annotations

import pytest

from vsdx.oxml.simpletypes import (
    ST_BaseID,
    ST_Boolean,
    ST_FormulaString,
    ST_LineStyle,
    ST_RowType,
    ST_SectionName,
    ST_ShapeType,
    ST_UniqueID,
    ST_UnitString,
    ST_WindowType,
)


class Describe_ST_Boolean:
    def it_converts_0_to_False(self) -> None:
        assert ST_Boolean.convert_from_xml("0") is False

    def it_converts_1_to_True(self) -> None:
        assert ST_Boolean.convert_from_xml("1") is True

    def it_also_accepts_word_spellings_on_read(self) -> None:
        assert ST_Boolean.convert_from_xml("false") is False
        assert ST_Boolean.convert_from_xml("true") is True

    def it_writes_the_numeric_form(self) -> None:
        assert ST_Boolean.convert_to_xml(True) == "1"
        assert ST_Boolean.convert_to_xml(False) == "0"

    def but_it_rejects_garbage_strings(self) -> None:
        with pytest.raises(ValueError):
            ST_Boolean.convert_from_xml("maybe")

    def it_validates_that_value_is_bool(self) -> None:
        ST_Boolean.validate(True)
        with pytest.raises(TypeError):
            ST_Boolean.validate(1)  # type: ignore[arg-type]


class Describe_ST_ShapeType:
    def it_accepts_each_documented_value(self) -> None:
        for value in ("Shape", "Group", "Foreign", "Guide", "Page"):
            ST_ShapeType.validate(value)

    def but_it_rejects_undocumented_values(self) -> None:
        with pytest.raises(Exception):
            ST_ShapeType.validate("Connector")


class Describe_ST_LineStyle:
    def it_accepts_each_documented_value(self) -> None:
        for value in (
            "Normal",
            "None",
            "Visio 10",
            "Visio 20",
            "Visio 40",
        ):
            ST_LineStyle.validate(value)


class Describe_ST_RowType:
    def it_accepts_each_geometry_row_type(self) -> None:
        for value in (
            "MoveTo",
            "LineTo",
            "ArcTo",
            "EllipticalArcTo",
            "InfiniteLine",
            "Ellipse",
            "PolylineTo",
            "NURBSTo",
        ):
            ST_RowType.validate(value)


class Describe_ST_SectionName:
    def it_accepts_geometry_and_char_and_para_and_user(self) -> None:
        for value in ("Geometry", "Character", "Paragraph", "User"):
            ST_SectionName.validate(value)

    def it_accepts_connection_and_controls(self) -> None:
        ST_SectionName.validate("Connection")
        ST_SectionName.validate("ConnectionABCD")
        ST_SectionName.validate("Controls")


class Describe_ST_WindowType:
    def it_accepts_the_four_documented_kinds(self) -> None:
        for value in ("Drawing", "Stencil", "Sheet", "Icon"):
            ST_WindowType.validate(value)


class Describe_ST_UnitString:
    def it_accepts_IN_and_MM_and_points(self) -> None:
        ST_UnitString.validate("IN")
        ST_UnitString.validate("MM")
        ST_UnitString.validate("PT")

    def but_it_rejects_NUL_bytes(self) -> None:
        with pytest.raises(ValueError):
            ST_UnitString.validate("IN\x00")


class Describe_ST_FormulaString:
    def it_accepts_simple_formulas(self) -> None:
        ST_FormulaString.validate("Width*0")
        ST_FormulaString.validate("(BeginX+EndX)/2")
        ST_FormulaString.validate("ATAN2(EndY-BeginY,EndX-BeginX)")

    def it_accepts_cross_shape_references(self) -> None:
        ST_FormulaString.validate("Sheet.2!Width*0.5")

    def but_it_rejects_NUL_bytes(self) -> None:
        with pytest.raises(ValueError):
            ST_FormulaString.validate("Width\x00*0")

    def and_it_rejects_overlong_payloads(self) -> None:
        with pytest.raises(ValueError):
            ST_FormulaString.validate("x" * (16 * 1024 + 1))


class Describe_ST_BaseID:
    def it_accepts_a_curly_braced_GUID(self) -> None:
        ST_BaseID.validate("{91A5A9A0-1234-5678-ABCD-1234567890AB}")

    def but_it_rejects_bare_GUIDs(self) -> None:
        with pytest.raises(ValueError):
            ST_BaseID.validate("91A5A9A0-1234-5678-ABCD-1234567890AB")

    def and_it_rejects_malformed_GUIDs(self) -> None:
        with pytest.raises(ValueError):
            ST_BaseID.validate("{not-a-guid}")


class Describe_ST_UniqueID:
    def it_accepts_a_curly_braced_GUID(self) -> None:
        ST_UniqueID.validate("{DEADBEEF-0000-0000-0000-000000000000}")

    def but_it_rejects_the_empty_string(self) -> None:
        with pytest.raises(ValueError):
            ST_UniqueID.validate("")
