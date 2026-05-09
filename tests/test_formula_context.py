"""Tests for :mod:`vsdx.formula.context`."""

from __future__ import annotations

import pytest

from vsdx.formula.context import (
    MappingShapeSheetContext,
    cell_ref_to_string,
    parse_cell_ref,
)
from vsdx.formula.errors import FormulaEvaluationError
from vsdx.formula.nodes import CellRef


class DescribeParseCellRef:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Width", CellRef(name="Width", source="Width")),
            ("User.Scale", CellRef(name="Scale", section="User", source="User.Scale")),
            (
                "Prop.Foo.Value",
                CellRef(
                    name="Value", section="Prop", row="Foo", source="Prop.Foo.Value"
                ),
            ),
            (
                "Sheet.5!PinX",
                CellRef(name="PinX", sheet="Sheet.5", source="PinX"),
            ),
        ],
    )
    def it_parses_representative_references(self, text, expected):
        got = parse_cell_ref(text)
        assert got.name == expected.name
        assert got.section == expected.section
        assert got.row == expected.row
        assert got.sheet == expected.sheet

    def it_rejects_empty_reference(self):
        with pytest.raises(FormulaEvaluationError):
            parse_cell_ref("")


class DescribeCellRefToString:
    @pytest.mark.parametrize(
        ("ref", "expected"),
        [
            (CellRef(name="Width"), "Width"),
            (CellRef(name="Scale", section="User"), "User.Scale"),
            (
                CellRef(name="Value", section="Prop", row="Foo"),
                "Prop.Foo.Value",
            ),
            (CellRef(name="PinX", sheet="Sheet.5"), "Sheet.5!PinX"),
        ],
    )
    def it_serialises_canonical_form(self, ref, expected):
        assert cell_ref_to_string(ref) == expected


class DescribeMappingShapeSheetContext:
    def it_returns_stored_values(self):
        ctx = MappingShapeSheetContext({"Width": 3.0})
        assert ctx.resolve(CellRef(name="Width")) == 3.0

    def it_returns_none_for_missing_cells_in_non_strict_mode(self):
        ctx = MappingShapeSheetContext({})
        assert ctx.resolve(CellRef(name="Missing")) is None

    def it_raises_for_missing_cells_in_strict_mode(self):
        ctx = MappingShapeSheetContext({}, strict=True)
        with pytest.raises(FormulaEvaluationError):
            ctx.resolve(CellRef(name="Missing"))

    def it_falls_back_to_unscoped_when_sheet_is_set(self):
        # ``Sheet.N!Width`` falls back to ``Width`` if not explicitly registered.
        ctx = MappingShapeSheetContext({"Width": 7.0})
        assert ctx.resolve(CellRef(name="Width", sheet="Sheet.5")) == 7.0

    def it_supports_set_then_get(self):
        ctx = MappingShapeSheetContext()
        ctx.set("Width", 9.0)
        assert ctx.get("Width") == 9.0
