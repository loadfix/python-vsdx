"""Unit tests for the 0.2.0 ``DataGraphic`` / ``DataGraphics`` proxies.

BDD-style per the project's test conventions. Scope is read + preserve
+ shape-side association, matching the 0.2.0 R8-2 deliverable. Full
authoring (``document.add_data_graphic(...)``) ships in 0.3.0.

Each test fabricates a synthetic ``<Section N="DataGraphic">`` tree
inline — the reference corpus doesn't carry a DataGraphic-bearing
fixture yet (tier-4 gating per the scoping doc).

.. versionadded:: 0.2.0
"""

from __future__ import annotations

import pytest

import vsdx
from vsdx.data_graphics import (
    DataGraphic,
    DataGraphicItem,
    DataGraphics,
    _set_shape_data_graphic_id,
    _shape_data_graphic_id,
)
from vsdx.constants import NS_VSDX_CORE
from vsdx.oxml import parse_xml


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _doc_with_graphics(*sections_xml: str):
    """Return a ``VisioDocument`` whose root carries *sections_xml* as
    ``<Section>`` children.

    The helper sidesteps the package layer: we construct a fresh
    :class:`vsdx.Visio` document, then splice synthetic
    ``<Section>`` elements directly onto its ``<VisioDocument>``
    root. This is the lowest-overhead way to populate a data-graphic
    section without a real fixture.
    """
    doc = vsdx.Visio()
    root = doc._element
    for xml in sections_xml:
        element = parse_xml(xml)
        root.append(element)
    return doc


def _basic_graphic_xml(
    ix: int = 0,
    *,
    name: str = "Priority",
    items: tuple = (("TextCallout", "Prop.Priority"),),
    default_position: str = "0",
    default_style: str = "1",
) -> str:
    """Return a ``<Section N="DataGraphic" IX="N">`` XML string.

    *items* is an iterable of ``(kind, column)`` tuples — one row per
    binding.
    """
    item_rows = []
    for idx, (kind, column) in enumerate(items):
        item_rows.append(
            f'<Row IX="{idx}" T="{kind}">'
            f'<Cell N="Column" V="{column}"/>'
            f'<Cell N="DefaultStyle" V="0"/>'
            f"</Row>"
        )
    rows_xml = "".join(item_rows)
    return (
        f'<Section xmlns="{NS_VSDX_CORE}" N="DataGraphic" IX="{ix}" '
        f'NameU="{name}" Name="{name}" '
        f'DefaultPosition="{default_position}" '
        f'DefaultStyle="{default_style}">{rows_xml}</Section>'
    )


# ---------------------------------------------------------------------------
# DataGraphics collection
# ---------------------------------------------------------------------------


class DescribeDataGraphicsCollection:
    def it_exposes_an_empty_collection_on_a_fresh_document(self) -> None:
        doc = vsdx.Visio()
        assert isinstance(doc.data_graphics, DataGraphics)
        assert list(doc.data_graphics) == []
        assert len(doc.data_graphics) == 0

    def it_enumerates_data_graphic_sections_in_document_order(self) -> None:
        doc = _doc_with_graphics(
            _basic_graphic_xml(ix=0, name="Priority"),
            _basic_graphic_xml(ix=1, name="Owner"),
        )
        graphics = list(doc.data_graphics)
        assert [g.id for g in graphics] == [0, 1]
        assert [g.name for g in graphics] == ["Priority", "Owner"]

    def it_supports_getitem_by_index(self) -> None:
        doc = _doc_with_graphics(
            _basic_graphic_xml(ix=0, name="A"),
            _basic_graphic_xml(ix=1, name="B"),
        )
        assert isinstance(doc.data_graphics[0], DataGraphic)
        assert doc.data_graphics[1].name == "B"

    def it_looks_up_graphics_by_id(self) -> None:
        doc = _doc_with_graphics(
            _basic_graphic_xml(ix=7, name="Lucky"),
            _basic_graphic_xml(ix=42, name="Deep"),
        )
        found = doc.data_graphics.get(42)
        assert found is not None
        assert found.name == "Deep"
        assert doc.data_graphics.get(99) is None

    def it_looks_up_graphics_by_name(self) -> None:
        doc = _doc_with_graphics(
            _basic_graphic_xml(ix=0, name="Status"),
            _basic_graphic_xml(ix=1, name="Priority"),
        )
        found = doc.data_graphics.get_by_name("Priority")
        assert found is not None
        assert found.id == 1
        assert doc.data_graphics.get_by_name("Unknown") is None

    def it_ignores_non_datagraphic_sections_at_root(self) -> None:
        # Arbitrary ``<Section N="Hyperlink">`` at root must not pollute
        # the DataGraphic collection.
        doc = _doc_with_graphics(
            _basic_graphic_xml(ix=0, name="G"),
            f'<Section xmlns="{NS_VSDX_CORE}" N="Scratch" IX="0"/>',
        )
        graphics = list(doc.data_graphics)
        assert len(graphics) == 1
        assert graphics[0].name == "G"


# ---------------------------------------------------------------------------
# DataGraphic instance
# ---------------------------------------------------------------------------


class DescribeDataGraphic:
    def it_surfaces_id_and_name(self) -> None:
        doc = _doc_with_graphics(_basic_graphic_xml(ix=3, name="Priority"))
        g = doc.data_graphics[0]
        assert g.id == 3
        assert g.name == "Priority"
        assert g.name_universal == "Priority"

    def it_surfaces_default_position_and_style(self) -> None:
        doc = _doc_with_graphics(
            _basic_graphic_xml(
                ix=0, default_position="2", default_style="5"
            )
        )
        g = doc.data_graphics[0]
        assert g.default_position == "2"
        assert g.default_style == "5"

    def it_enumerates_items_in_ix_order(self) -> None:
        doc = _doc_with_graphics(
            _basic_graphic_xml(
                ix=0,
                items=(
                    ("TextCallout", "Prop.Owner"),
                    ("IconSet", "Prop.Priority"),
                    ("ColorByValue", "Prop.Status"),
                ),
            )
        )
        items = doc.data_graphics[0].items
        assert len(items) == 3
        assert [i.index for i in items] == [0, 1, 2]
        assert [i.kind for i in items] == [
            "TextCallout", "IconSet", "ColorByValue",
        ]

    def it_sorts_items_by_ix_even_when_document_order_is_shuffled(self) -> None:
        # Row IX values out of order — the proxy must sort by @IX
        # rather than document order.
        xml = (
            f'<Section xmlns="{NS_VSDX_CORE}" N="DataGraphic" IX="0">'
            '<Row IX="2" T="ColorByValue"><Cell N="Column" V="Prop.C"/></Row>'
            '<Row IX="0" T="TextCallout"><Cell N="Column" V="Prop.A"/></Row>'
            '<Row IX="1" T="IconSet"><Cell N="Column" V="Prop.B"/></Row>'
            "</Section>"
        )
        doc = _doc_with_graphics(xml)
        items = doc.data_graphics[0].items
        assert [i.index for i in items] == [0, 1, 2]
        assert [i.column for i in items] == ["Prop.A", "Prop.B", "Prop.C"]

    def it_is_iterable(self) -> None:
        doc = _doc_with_graphics(
            _basic_graphic_xml(
                ix=0,
                items=(
                    ("TextCallout", "Prop.X"),
                    ("IconSet", "Prop.Y"),
                ),
            )
        )
        g = doc.data_graphics[0]
        assert len(g) == 2
        kinds = [item.kind for item in g]
        assert kinds == ["TextCallout", "IconSet"]


# ---------------------------------------------------------------------------
# DataGraphicItem
# ---------------------------------------------------------------------------


class DescribeDataGraphicItem:
    def it_exposes_kind_and_column(self) -> None:
        doc = _doc_with_graphics(
            _basic_graphic_xml(
                ix=0, items=(("IconSet", "Prop.Severity"),)
            )
        )
        item = doc.data_graphics[0].items[0]
        assert isinstance(item, DataGraphicItem)
        assert item.kind == "IconSet"
        assert item.column == "Prop.Severity"

    def it_reports_default_style_cell(self) -> None:
        doc = _doc_with_graphics(_basic_graphic_xml())
        item = doc.data_graphics[0].items[0]
        assert item.default_style == "0"

    def it_reads_arbitrary_cells_via_the_cells_mapping(self) -> None:
        xml = (
            f'<Section xmlns="{NS_VSDX_CORE}" N="DataGraphic" IX="0">'
            '<Row IX="0" T="DataBar">'
            '<Cell N="Column" V="Prop.Count"/>'
            '<Cell N="LowValue" V="0"/>'
            '<Cell N="HighValue" V="100"/>'
            '<Cell N="BarStyle" V="3"/>'
            "</Row></Section>"
        )
        doc = _doc_with_graphics(xml)
        item = doc.data_graphics[0].items[0]
        assert item.cells == {
            "Column": "Prop.Count",
            "LowValue": "0",
            "HighValue": "100",
            "BarStyle": "3",
        }

    def it_exposes_the_underlying_row_element(self) -> None:
        doc = _doc_with_graphics(_basic_graphic_xml())
        item = doc.data_graphics[0].items[0]
        assert item.element.get("T") == "TextCallout"


# ---------------------------------------------------------------------------
# Shape <-> DataGraphic association
# ---------------------------------------------------------------------------


def _fresh_page_with_shape_and_graphic():
    doc = _doc_with_graphics(_basic_graphic_xml(ix=5, name="Priority"))
    page = doc.pages.add_page(name="Page-1")
    page.shapes.add_shape(vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(1, 1))
    return doc, page


class DescribeShapeDataGraphicAssociation:
    def it_reports_no_data_graphic_by_default(self) -> None:
        _, page = _fresh_page_with_shape_and_graphic()
        shape = page.shapes[0]
        assert shape.data_graphic is None

    def it_resolves_the_graphic_through_the_shape_cell(self) -> None:
        doc, page = _fresh_page_with_shape_and_graphic()
        shape = page.shapes[0]
        target = doc.data_graphics.get(5)
        shape.data_graphic = target
        assert shape.data_graphic is not None
        assert shape.data_graphic.id == 5

    def it_writes_the_datagraphic_cell_on_assignment(self) -> None:
        doc, page = _fresh_page_with_shape_and_graphic()
        shape = page.shapes[0]
        target = doc.data_graphics.get(5)
        shape.data_graphic = target
        assert _shape_data_graphic_id(shape._element) == 5

    def it_clears_the_cell_when_assigned_none(self) -> None:
        doc, page = _fresh_page_with_shape_and_graphic()
        shape = page.shapes[0]
        target = doc.data_graphics.get(5)
        shape.data_graphic = target
        shape.data_graphic = None
        assert _shape_data_graphic_id(shape._element) is None
        assert shape.data_graphic is None

    def it_rejects_non_datagraphic_assignments(self) -> None:
        _, page = _fresh_page_with_shape_and_graphic()
        shape = page.shapes[0]
        with pytest.raises(TypeError):
            shape.data_graphic = 42  # not a DataGraphic proxy

    def it_returns_none_when_the_cell_points_at_an_unknown_id(self) -> None:
        # Orphaned reference — cell present, but no DataGraphic with
        # that id. Defensive guard for hand-edited packages.
        doc, page = _fresh_page_with_shape_and_graphic()
        shape = page.shapes[0]
        _set_shape_data_graphic_id(shape._element, 999)
        assert shape.data_graphic is None


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class DescribeDataGraphicRoundTrip:
    def it_preserves_the_section_on_parse_reserialise(self) -> None:
        # Ensure the new ``section`` descriptor on CT_VisioDocument
        # round-trips DataGraphic sections through lxml's serialiser.
        from lxml import etree

        doc = _doc_with_graphics(
            _basic_graphic_xml(
                ix=3,
                name="Priority",
                items=(
                    ("TextCallout", "Prop.Owner"),
                    ("IconSet", "Prop.Priority"),
                ),
            )
        )
        xml_bytes = etree.tostring(doc._element)
        reparsed = parse_xml(xml_bytes)
        sections = [
            s for s in reparsed.section_lst if s.get("N") == "DataGraphic"
        ]
        assert len(sections) == 1
        assert sections[0].get("IX") == "3"
        assert sections[0].get("Name") == "Priority"
        assert len(sections[0].row_lst) == 2
        assert sections[0].row_lst[0].get("T") == "TextCallout"

    def it_round_trips_the_shape_datagraphic_cell(self) -> None:
        from lxml import etree

        doc, page = _fresh_page_with_shape_and_graphic()
        shape = page.shapes[0]
        shape.data_graphic = doc.data_graphics.get(5)
        xml_bytes = etree.tostring(shape._element)
        assert b'N="DataGraphic"' in xml_bytes
        assert b'V="5"' in xml_bytes


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------


class DescribePublicSurface:
    def it_exports_the_three_classes_on_the_vsdx_namespace(self) -> None:
        assert vsdx.DataGraphic is DataGraphic
        assert vsdx.DataGraphicItem is DataGraphicItem
        assert vsdx.DataGraphics is DataGraphics
