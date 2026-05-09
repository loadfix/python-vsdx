"""Unit tests for the 0.3.0 shape-data (``<Section N="Property">``) proxy.

BDD-style per project conventions. Covers:

* Mapping surface — ``shape.data["name"]`` / iteration / containment /
  length / deletion / ``.get`` / ``.get_field`` / ``.fields`` / ``.names``.
* Typed coercion on ``value`` — String, FixedList, Number, Boolean,
  VariableList, Date, Duration, Currency (round-trips each Visio
  ``@Type`` cell value).
* Authoring — :meth:`ShapeData.add_field` materialises the
  ``<Section N="Property">`` on first use; emits the expected cells;
  rejects duplicate names / empty names.
* Removal — :meth:`ShapeData.remove_field` /
  ``del shape.data["name"]`` delete rows; leave the section element
  in place for round-trip fidelity.
* Metadata surface — `.label` / `.format` / `.prompt` / `.sort_key` /
  `.invisible` / `.type` setters & getters.
* Parse-existing fixtures — round-trip a pre-authored Property
  section.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import pytest

import vsdx
from vsdx.oxml import nsdecls, parse_xml
from vsdx.shape_data import (
    PROPERTY_TYPE_BOOLEAN,
    PROPERTY_TYPE_CURRENCY,
    PROPERTY_TYPE_DATE,
    PROPERTY_TYPE_DURATION,
    PROPERTY_TYPE_FIXED_LIST,
    PROPERTY_TYPE_NUMBER,
    PROPERTY_TYPE_STRING,
    PROPERTY_TYPE_VARIABLE_LIST,
    ShapeData,
    ShapeDataField,
)


def _fresh_shape():
    """Return a ``(doc, page, shape)`` triple with one rectangle on the page."""
    doc = vsdx.Visio()
    page = doc.pages.add_page(name="Page-1")
    shape = page.shapes.add_shape(vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(1, 1))
    return doc, page, shape


def _parse_shape_with_properties(xml_body: str):
    """Parse a ``<Shape>`` element carrying *xml_body* as its children."""
    xml = (
        '<vsdx:Shape %s ID="1" Type="Shape">%s</vsdx:Shape>'
        % (nsdecls("vsdx"), xml_body)
    ).encode()
    return parse_xml(xml)


def _wrap_parsed(shape_el):
    """Wrap a parsed ``CT_Shape`` in a bare :class:`Shape` proxy for tests."""
    from vsdx.shapes.base import Shape

    proxy = Shape.__new__(Shape)
    proxy._element = shape_el  # type: ignore[attr-defined]
    proxy._parent = None  # type: ignore[attr-defined]
    return proxy


# ---------------------------------------------------------------------------
# Describe ShapeData on a fresh shape
# ---------------------------------------------------------------------------


class DescribeShapeData:
    def it_exposes_an_empty_mapping_on_a_fresh_shape(self) -> None:
        _, _, shape = _fresh_shape()
        data = shape.data
        assert isinstance(data, ShapeData)
        assert len(data) == 0
        assert list(data) == []
        assert data.names() == []
        assert data.fields() == []
        assert "anything" not in data

    def it_raises_KeyError_on_missing_lookup(self) -> None:
        _, _, shape = _fresh_shape()
        with pytest.raises(KeyError):
            shape.data["missing"]
        with pytest.raises(KeyError):
            shape.data.field("missing")
        assert shape.data.get("missing") is None
        assert shape.data.get("missing", "default") == "default"
        assert shape.data.get_field("missing") is None

    def it_creates_the_Property_section_on_first_add_field(self) -> None:
        _, _, shape = _fresh_shape()
        # No Property section yet.
        assert not any(
            s.get("N") == "Property" for s in shape._element.section_lst
        )
        shape.data.add_field("Cost", 42.5, type=PROPERTY_TYPE_NUMBER)
        sections = [
            s for s in shape._element.section_lst if s.get("N") == "Property"
        ]
        assert len(sections) == 1

    def it_is_dict_like_after_adding_fields(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field("Cost", 10.0, type=PROPERTY_TYPE_NUMBER)
        shape.data.add_field("Owner", "Alice", type=PROPERTY_TYPE_STRING)
        assert len(shape.data) == 2
        assert "Cost" in shape.data
        assert "Owner" in shape.data
        assert shape.data["Cost"] == 10.0
        assert shape.data["Owner"] == "Alice"
        assert set(shape.data) == {"Cost", "Owner"}


# ---------------------------------------------------------------------------
# Describe add_field authoring
# ---------------------------------------------------------------------------


class DescribeAddField:
    def it_rejects_empty_names(self) -> None:
        _, _, shape = _fresh_shape()
        with pytest.raises(ValueError):
            shape.data.add_field("", "x")

    def it_rejects_duplicate_names(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field("Cost", 10.0, type=PROPERTY_TYPE_NUMBER)
        with pytest.raises(ValueError):
            shape.data.add_field("Cost", 20.0, type=PROPERTY_TYPE_NUMBER)

    def it_defaults_label_to_the_name(self) -> None:
        _, _, shape = _fresh_shape()
        f = shape.data.add_field("Cost", 10.0, type=PROPERTY_TYPE_NUMBER)
        assert f.label == "Cost"

    def it_honours_an_explicit_label(self) -> None:
        _, _, shape = _fresh_shape()
        f = shape.data.add_field(
            "Cost", 10.0, label="Unit Cost ($)", type=PROPERTY_TYPE_NUMBER
        )
        assert f.label == "Unit Cost ($)"

    def it_propagates_format_prompt_sort_key_invisible(self) -> None:
        _, _, shape = _fresh_shape()
        f = shape.data.add_field(
            "Cost",
            10.0,
            type=PROPERTY_TYPE_CURRENCY,
            format="0.00",
            prompt="Enter unit cost",
            sort_key="010",
            invisible=True,
        )
        assert f.format == "0.00"
        assert f.prompt == "Enter unit cost"
        assert f.sort_key == "010"
        assert f.invisible is True

    def it_writes_the_Type_cell_when_non_default(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field("Count", 5.0, type=PROPERTY_TYPE_NUMBER)
        row = shape.data.field("Count").element
        type_cell = next(
            (c for c in row.cell_lst if c.get("N") == "Type"), None
        )
        assert type_cell is not None
        assert type_cell.get("V") == str(PROPERTY_TYPE_NUMBER)

    def it_returns_the_field_proxy_from_add_field(self) -> None:
        _, _, shape = _fresh_shape()
        f = shape.data.add_field("Cost", 10.0, type=PROPERTY_TYPE_NUMBER)
        assert isinstance(f, ShapeDataField)
        assert f.name == "Cost"
        assert f.type == PROPERTY_TYPE_NUMBER
        assert f.value == 10.0


# ---------------------------------------------------------------------------
# Describe typed-coercion round-trips (every Visio type code)
# ---------------------------------------------------------------------------


class DescribeTypedCoercion:
    def it_round_trips_a_String_property(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field(
            "Owner", "Alice", type=PROPERTY_TYPE_STRING
        )
        v = shape.data["Owner"]
        assert isinstance(v, str)
        assert v == "Alice"

    def it_round_trips_a_FixedList_property(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field(
            "Priority", "High", type=PROPERTY_TYPE_FIXED_LIST
        )
        v = shape.data["Priority"]
        assert isinstance(v, str)
        assert v == "High"

    def it_round_trips_a_Number_property(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field("Count", 42.5, type=PROPERTY_TYPE_NUMBER)
        v = shape.data["Count"]
        assert isinstance(v, float)
        assert v == 42.5

    def it_round_trips_a_Boolean_true(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field(
            "IsCritical", True, type=PROPERTY_TYPE_BOOLEAN
        )
        v = shape.data["IsCritical"]
        assert isinstance(v, bool)
        assert v is True
        # Raw @V is "1" — Visio's native encoding.
        assert shape.data.field("IsCritical").raw_value == "1"

    def it_round_trips_a_Boolean_false(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field(
            "IsCritical", False, type=PROPERTY_TYPE_BOOLEAN
        )
        v = shape.data["IsCritical"]
        assert v is False
        assert shape.data.field("IsCritical").raw_value == "0"

    def it_coerces_TRUE_FALSE_tokens_to_bool(self) -> None:
        # Some Visio locales emit TRUE/FALSE instead of 1/0 — read path
        # tolerates that; write path still emits 1/0.
        shape = _parse_shape_with_properties(
            '<vsdx:Section N="Property">'
            '<vsdx:Row N="Flag">'
            '<vsdx:Cell N="Value" V="TRUE"/>'
            '<vsdx:Cell N="Type" V="3"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        proxy = _wrap_parsed(shape)
        assert proxy.data["Flag"] is True

    def it_round_trips_a_VariableList_property(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field(
            "Status", "Open", type=PROPERTY_TYPE_VARIABLE_LIST
        )
        v = shape.data["Status"]
        assert isinstance(v, str)
        assert v == "Open"

    def it_round_trips_a_Date_property_as_string(self) -> None:
        _, _, shape = _fresh_shape()
        # Visio emits a serial-day number; we pass through verbatim.
        shape.data.add_field(
            "DueDate", "42005", type=PROPERTY_TYPE_DATE
        )
        v = shape.data["DueDate"]
        assert isinstance(v, str)
        assert v == "42005"

    def it_round_trips_a_Duration_property_as_string(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field(
            "Lead", "PT1H30M", type=PROPERTY_TYPE_DURATION
        )
        v = shape.data["Lead"]
        assert isinstance(v, str)
        assert v == "PT1H30M"

    def it_round_trips_a_Currency_property(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field(
            "Cost", 99.95, type=PROPERTY_TYPE_CURRENCY, format="0.00"
        )
        v = shape.data["Cost"]
        assert isinstance(v, float)
        assert v == 99.95

    def it_returns_None_for_a_missing_value_cell(self) -> None:
        # Row exists but the Value cell is absent — common pattern for
        # master-defaulted shape-data fields with no instance override.
        shape = _parse_shape_with_properties(
            '<vsdx:Section N="Property">'
            '<vsdx:Row N="Owner">'
            '<vsdx:Cell N="Label" V="Owner"/>'
            '<vsdx:Cell N="Type" V="0"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        proxy = _wrap_parsed(shape)
        assert proxy.data["Owner"] is None

    def it_defaults_type_to_String_when_Type_cell_missing(self) -> None:
        shape = _parse_shape_with_properties(
            '<vsdx:Section N="Property">'
            '<vsdx:Row N="Note">'
            '<vsdx:Cell N="Value" V="Hello"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        proxy = _wrap_parsed(shape)
        assert proxy.data.field("Note").type == PROPERTY_TYPE_STRING
        assert proxy.data["Note"] == "Hello"


# ---------------------------------------------------------------------------
# Describe mutation via __setitem__ / remove
# ---------------------------------------------------------------------------


class DescribeMutation:
    def it_updates_an_existing_value_via_setitem(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field("Cost", 10.0, type=PROPERTY_TYPE_NUMBER)
        shape.data["Cost"] = 25.5
        assert shape.data["Cost"] == 25.5

    def it_rejects_setitem_on_missing_key(self) -> None:
        _, _, shape = _fresh_shape()
        with pytest.raises(KeyError):
            shape.data["Cost"] = 10.0

    def it_removes_a_field(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field("Cost", 10.0, type=PROPERTY_TYPE_NUMBER)
        shape.data.add_field("Owner", "Alice", type=PROPERTY_TYPE_STRING)
        shape.data.remove_field("Cost")
        assert "Cost" not in shape.data
        assert "Owner" in shape.data
        assert len(shape.data) == 1

    def it_removes_a_field_via_del(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field("Cost", 10.0, type=PROPERTY_TYPE_NUMBER)
        del shape.data["Cost"]
        assert "Cost" not in shape.data

    def it_raises_KeyError_on_remove_of_missing_field(self) -> None:
        _, _, shape = _fresh_shape()
        with pytest.raises(KeyError):
            shape.data.remove_field("missing")

    def it_preserves_the_Section_element_when_last_row_removed(self) -> None:
        # Section left in place for round-trip fidelity.
        _, _, shape = _fresh_shape()
        shape.data.add_field("Cost", 10.0, type=PROPERTY_TYPE_NUMBER)
        shape.data.remove_field("Cost")
        sections = [
            s for s in shape._element.section_lst if s.get("N") == "Property"
        ]
        assert len(sections) == 1
        assert len(sections[0].row_lst) == 0

    def it_updates_label_and_format_via_field_proxy(self) -> None:
        _, _, shape = _fresh_shape()
        f = shape.data.add_field("Cost", 10.0, type=PROPERTY_TYPE_NUMBER)
        f.label = "Unit Cost"
        f.format = "0.00"
        assert f.label == "Unit Cost"
        assert f.format == "0.00"

    def it_flips_invisible_flag(self) -> None:
        _, _, shape = _fresh_shape()
        f = shape.data.add_field("Cost", 10.0, type=PROPERTY_TYPE_NUMBER)
        assert f.invisible is False
        f.invisible = True
        assert f.invisible is True


# ---------------------------------------------------------------------------
# Describe parse-existing fixture round-trip
# ---------------------------------------------------------------------------


class DescribeExistingShapeData:
    def it_parses_a_mixed_type_fixture(self) -> None:
        # Mirrors a typical master-instance Property section with
        # String, Number, Boolean, and Currency fields.
        shape = _parse_shape_with_properties(
            '<vsdx:Section N="Property">'
            '<vsdx:Row N="Owner">'
            '<vsdx:Cell N="Value" V="Alice"/>'
            '<vsdx:Cell N="Label" V="Owner"/>'
            '<vsdx:Cell N="Type" V="0"/>'
            '<vsdx:Cell N="SortKey" V="010"/>'
            "</vsdx:Row>"
            '<vsdx:Row N="Cost">'
            '<vsdx:Cell N="Value" V="99.95"/>'
            '<vsdx:Cell N="Label" V="Unit Cost"/>'
            '<vsdx:Cell N="Format" V="0.00"/>'
            '<vsdx:Cell N="Type" V="7"/>'
            '<vsdx:Cell N="SortKey" V="020"/>'
            "</vsdx:Row>"
            '<vsdx:Row N="IsCritical">'
            '<vsdx:Cell N="Value" V="1"/>'
            '<vsdx:Cell N="Label" V="Critical?"/>'
            '<vsdx:Cell N="Type" V="3"/>'
            '<vsdx:Cell N="SortKey" V="030"/>'
            "</vsdx:Row>"
            '<vsdx:Row N="Count">'
            '<vsdx:Cell N="Value" V="42"/>'
            '<vsdx:Cell N="Label" V="Count"/>'
            '<vsdx:Cell N="Type" V="2"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        proxy = _wrap_parsed(shape)
        data = proxy.data

        assert list(data) == ["Owner", "Cost", "IsCritical", "Count"]
        assert data["Owner"] == "Alice"
        assert data["Cost"] == 99.95
        assert data["IsCritical"] is True
        assert data["Count"] == 42.0

        cost = data.field("Cost")
        assert cost.label == "Unit Cost"
        assert cost.format == "0.00"
        assert cost.sort_key == "020"
        assert cost.type == PROPERTY_TYPE_CURRENCY

    def it_round_trips_parse_mutate_read(self) -> None:
        shape = _parse_shape_with_properties(
            '<vsdx:Section N="Property">'
            '<vsdx:Row N="Cost">'
            '<vsdx:Cell N="Value" V="10"/>'
            '<vsdx:Cell N="Type" V="2"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        proxy = _wrap_parsed(shape)
        # Mutate through the Mapping surface.
        proxy.data["Cost"] = 25.75
        proxy.data.add_field(
            "Owner", "Bob", type=PROPERTY_TYPE_STRING
        )
        assert proxy.data["Cost"] == 25.75
        assert proxy.data["Owner"] == "Bob"
        assert len(proxy.data) == 2


# ---------------------------------------------------------------------------
# Describe fields() / names() / field() helpers
# ---------------------------------------------------------------------------


class DescribeFieldHelpers:
    def it_returns_fields_in_document_order(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field("A", "a", type=PROPERTY_TYPE_STRING)
        shape.data.add_field("B", "b", type=PROPERTY_TYPE_STRING)
        shape.data.add_field("C", "c", type=PROPERTY_TYPE_STRING)
        fields = shape.data.fields()
        assert [f.name for f in fields] == ["A", "B", "C"]
        assert shape.data.names() == ["A", "B", "C"]

    def it_repr_includes_the_field_names(self) -> None:
        _, _, shape = _fresh_shape()
        shape.data.add_field("Cost", 10.0, type=PROPERTY_TYPE_NUMBER)
        assert "Cost" in repr(shape.data)

    def it_field_repr_includes_name_type_value(self) -> None:
        _, _, shape = _fresh_shape()
        f = shape.data.add_field(
            "Cost", 10.0, type=PROPERTY_TYPE_NUMBER
        )
        r = repr(f)
        assert "Cost" in r
        assert "10" in r
