"""Unit tests for the 0.3.0 connection-points (``<Section N="Connection">``) proxy.

BDD-style per project conventions. Covers:

* Sequence surface — ``shape.connection_points[i]`` / iteration /
  ``len`` / empty-mapping on a fresh shape.
* Authoring — :meth:`ConnectionPoints.add` materialises the
  ``<Section N="Connection">`` on first use; emits X/Y/DirX/DirY/Type
  cells; static vs dynamic cases; auto-gen flag.
* Removal — :meth:`ConnectionPoints.remove` deletes a row; leaves the
  section element in place for round-trip fidelity.
* Typed accessors — `.x` / `.y` / `.dir_x` / `.dir_y` / `.type` /
  `.auto_gen` getters & setters.
* Parse-existing fixtures — round-trip a pre-authored Connection
  section (inward, outward, inward-outward types).

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import pytest

import vsdx
from vsdx.connection_points import (
    CONNECTION_TYPE,
    ConnectionPoint,
    ConnectionPoints,
)
from vsdx.oxml import nsdecls, parse_xml


def _fresh_shape():
    """Return a ``(doc, page, shape)`` triple with one rectangle on the page."""
    doc = vsdx.Visio()
    page = doc.pages.add_page(name="Page-1")
    shape = page.shapes.add_shape(vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(1, 1))
    return doc, page, shape


def _parse_shape_with_connections(xml_body: str):
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
# Describe ConnectionPoints on a fresh shape
# ---------------------------------------------------------------------------


class DescribeConnectionPoints:
    def it_exposes_an_empty_sequence_on_a_fresh_shape(self) -> None:
        _, _, shape = _fresh_shape()
        points = shape.connection_points
        assert isinstance(points, ConnectionPoints)
        assert len(points) == 0
        assert list(points) == []

    def it_raises_IndexError_on_out_of_range_lookup(self) -> None:
        _, _, shape = _fresh_shape()
        with pytest.raises(IndexError):
            shape.connection_points[0]

    def it_creates_the_Connection_section_on_first_add(self) -> None:
        _, _, shape = _fresh_shape()
        assert not any(
            s.get("N") == "Connection" for s in shape._element.section_lst
        )
        shape.connection_points.add(0.5, 0.5)
        sections = [
            s
            for s in shape._element.section_lst
            if s.get("N") == "Connection"
        ]
        assert len(sections) == 1

    def it_is_list_like_after_adding_points(self) -> None:
        _, _, shape = _fresh_shape()
        shape.connection_points.add(0.0, 0.5)
        shape.connection_points.add(1.0, 0.5)
        points = shape.connection_points
        assert len(points) == 2
        assert points[0].x == 0.0
        assert points[1].x == 1.0
        # Iterable.
        xs = [p.x for p in points]
        assert xs == [0.0, 1.0]

    def it_repr_includes_the_point_count(self) -> None:
        _, _, shape = _fresh_shape()
        shape.connection_points.add(0.5, 0.5)
        assert "1" in repr(shape.connection_points)


# ---------------------------------------------------------------------------
# Describe add() authoring
# ---------------------------------------------------------------------------


class DescribeAdd:
    def it_returns_the_point_proxy(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(0.5, 0.75)
        assert isinstance(p, ConnectionPoint)
        assert p.x == 0.5
        assert p.y == 0.75

    def it_defaults_to_a_static_inward_point(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(0.5, 0.5)
        assert p.dir_x == 0.0
        assert p.dir_y == 0.0
        assert p.type == CONNECTION_TYPE.INWARD
        assert p.auto_gen is False

    def it_emits_a_Type_cell_with_the_inward_value(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(0.5, 0.5)
        type_cell = next(
            (c for c in p.element.cell_lst if c.get("N") == "Type"), None
        )
        assert type_cell is not None
        assert type_cell.get("V") == "0"

    def it_authors_a_dynamic_outward_point(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(
            1.0,
            0.5,
            dir_x=1.0,
            dir_y=0.0,
            type=CONNECTION_TYPE.OUTWARD,
        )
        assert p.dir_x == 1.0
        assert p.dir_y == 0.0
        assert p.type == CONNECTION_TYPE.OUTWARD

    def it_authors_an_inward_outward_point(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(
            0.5, 1.0, type=CONNECTION_TYPE.INWARD_OUTWARD
        )
        assert p.type == CONNECTION_TYPE.INWARD_OUTWARD

    def it_accepts_an_integer_type_code(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(0.5, 0.5, type=1)
        assert p.type == CONNECTION_TYPE.OUTWARD

    def it_accepts_a_raw_string_type_code(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(0.5, 0.5, type="2")
        assert p.type == CONNECTION_TYPE.INWARD_OUTWARD

    def it_rejects_an_unknown_type_code(self) -> None:
        _, _, shape = _fresh_shape()
        with pytest.raises(ValueError):
            shape.connection_points.add(0.5, 0.5, type=99)

    def it_sets_the_auto_gen_flag(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(0.5, 0.5, auto_gen=True)
        assert p.auto_gen is True
        auto_gen_cell = next(
            (
                c
                for c in p.element.cell_lst
                if c.get("N") == "AutoGen"
            ),
            None,
        )
        assert auto_gen_cell is not None
        assert auto_gen_cell.get("V") == "1"

    def it_assigns_monotonic_ix_starting_at_1(self) -> None:
        _, _, shape = _fresh_shape()
        p1 = shape.connection_points.add(0.0, 0.0)
        p2 = shape.connection_points.add(1.0, 0.0)
        p3 = shape.connection_points.add(0.5, 1.0)
        assert p1.index == 1
        assert p2.index == 2
        assert p3.index == 3

    def it_emits_the_IN_unit_on_coordinate_cells(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(0.5, 0.75)
        x_cell = next(
            c for c in p.element.cell_lst if c.get("N") == "X"
        )
        y_cell = next(
            c for c in p.element.cell_lst if c.get("N") == "Y"
        )
        assert x_cell.get("U") == "IN"
        assert y_cell.get("U") == "IN"


# ---------------------------------------------------------------------------
# Describe typed accessors / mutation
# ---------------------------------------------------------------------------


class DescribeConnectionPointAccessors:
    def it_updates_coordinates(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(0.0, 0.0)
        p.x = 0.25
        p.y = 0.75
        assert shape.connection_points[0].x == 0.25
        assert shape.connection_points[0].y == 0.75

    def it_updates_direction(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(0.5, 0.5)
        p.dir_x = 0.707
        p.dir_y = 0.707
        assert p.dir_x == 0.707
        assert p.dir_y == 0.707

    def it_flips_the_auto_gen_flag(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(0.5, 0.5)
        assert p.auto_gen is False
        p.auto_gen = True
        assert p.auto_gen is True
        p.auto_gen = False
        assert p.auto_gen is False

    def it_updates_type_via_enum(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(0.5, 0.5)
        p.type = CONNECTION_TYPE.OUTWARD
        assert p.type == CONNECTION_TYPE.OUTWARD

    def it_updates_type_via_int(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(0.5, 0.5)
        p.type = 2
        assert p.type == CONNECTION_TYPE.INWARD_OUTWARD

    def it_rejects_an_invalid_type_assignment(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(0.5, 0.5)
        with pytest.raises(ValueError):
            p.type = 99

    def it_repr_is_useful(self) -> None:
        _, _, shape = _fresh_shape()
        p = shape.connection_points.add(0.5, 0.75)
        r = repr(p)
        assert "ConnectionPoint" in r
        assert "INWARD" in r


# ---------------------------------------------------------------------------
# Describe removal
# ---------------------------------------------------------------------------


class DescribeRemove:
    def it_removes_the_point_at_index(self) -> None:
        _, _, shape = _fresh_shape()
        shape.connection_points.add(0.0, 0.0)
        shape.connection_points.add(1.0, 0.0)
        shape.connection_points.add(0.5, 1.0)
        shape.connection_points.remove(1)
        xs = [p.x for p in shape.connection_points]
        assert xs == [0.0, 0.5]

    def it_raises_IndexError_on_out_of_range_remove(self) -> None:
        _, _, shape = _fresh_shape()
        with pytest.raises(IndexError):
            shape.connection_points.remove(0)

    def it_preserves_the_section_when_the_last_row_is_removed(self) -> None:
        _, _, shape = _fresh_shape()
        shape.connection_points.add(0.5, 0.5)
        shape.connection_points.remove(0)
        sections = [
            s
            for s in shape._element.section_lst
            if s.get("N") == "Connection"
        ]
        assert len(sections) == 1
        assert len(sections[0].row_lst) == 0
        assert len(shape.connection_points) == 0


# ---------------------------------------------------------------------------
# Describe parse-existing fixture round-trip
# ---------------------------------------------------------------------------


class DescribeExistingConnectionPoints:
    def it_parses_a_mixed_type_fixture(self) -> None:
        # Mirrors a typical master-instance Connection section with
        # inward, outward, and inward-outward points.
        shape = _parse_shape_with_connections(
            '<vsdx:Section N="Connection">'
            '<vsdx:Row IX="1">'
            '<vsdx:Cell N="X" V="0" U="IN"/>'
            '<vsdx:Cell N="Y" V="0.5" U="IN"/>'
            '<vsdx:Cell N="DirX" V="0"/>'
            '<vsdx:Cell N="DirY" V="0"/>'
            '<vsdx:Cell N="Type" V="0"/>'
            "</vsdx:Row>"
            '<vsdx:Row IX="2">'
            '<vsdx:Cell N="X" V="1" U="IN"/>'
            '<vsdx:Cell N="Y" V="0.5" U="IN"/>'
            '<vsdx:Cell N="DirX" V="1"/>'
            '<vsdx:Cell N="DirY" V="0"/>'
            '<vsdx:Cell N="Type" V="1"/>'
            '<vsdx:Cell N="AutoGen" V="1"/>'
            "</vsdx:Row>"
            '<vsdx:Row IX="3">'
            '<vsdx:Cell N="X" V="0.5" U="IN"/>'
            '<vsdx:Cell N="Y" V="1" U="IN"/>'
            '<vsdx:Cell N="Type" V="2"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        proxy = _wrap_parsed(shape)
        points = proxy.connection_points
        assert len(points) == 3

        # Static inward.
        assert points[0].x == 0.0
        assert points[0].y == 0.5
        assert points[0].type == CONNECTION_TYPE.INWARD
        assert points[0].auto_gen is False

        # Dynamic outward with auto-gen.
        assert points[1].x == 1.0
        assert points[1].dir_x == 1.0
        assert points[1].type == CONNECTION_TYPE.OUTWARD
        assert points[1].auto_gen is True

        # Inward-outward, no DirX/DirY cells.
        assert points[2].type == CONNECTION_TYPE.INWARD_OUTWARD
        assert points[2].dir_x == 0.0
        assert points[2].dir_y == 0.0

    def it_round_trips_parse_mutate_read(self) -> None:
        shape = _parse_shape_with_connections(
            '<vsdx:Section N="Connection">'
            '<vsdx:Row IX="1">'
            '<vsdx:Cell N="X" V="0.25" U="IN"/>'
            '<vsdx:Cell N="Y" V="0.25" U="IN"/>'
            '<vsdx:Cell N="Type" V="0"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        proxy = _wrap_parsed(shape)
        # Mutate the parsed point.
        proxy.connection_points[0].x = 0.5
        # Add a brand-new point.
        proxy.connection_points.add(
            0.75, 0.75, type=CONNECTION_TYPE.OUTWARD
        )
        assert len(proxy.connection_points) == 2
        assert proxy.connection_points[0].x == 0.5
        assert proxy.connection_points[1].x == 0.75
        assert (
            proxy.connection_points[1].type == CONNECTION_TYPE.OUTWARD
        )

    def it_defaults_type_to_inward_when_cell_missing(self) -> None:
        shape = _parse_shape_with_connections(
            '<vsdx:Section N="Connection">'
            '<vsdx:Row IX="1">'
            '<vsdx:Cell N="X" V="0.5" U="IN"/>'
            '<vsdx:Cell N="Y" V="0.5" U="IN"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        proxy = _wrap_parsed(shape)
        assert proxy.connection_points[0].type == CONNECTION_TYPE.INWARD

    def it_tolerates_an_unknown_type_code(self) -> None:
        # Load-preserve-save invariant — unknown codes fall back to
        # INWARD rather than raising on parse.
        shape = _parse_shape_with_connections(
            '<vsdx:Section N="Connection">'
            '<vsdx:Row IX="1">'
            '<vsdx:Cell N="X" V="0.5" U="IN"/>'
            '<vsdx:Cell N="Y" V="0.5" U="IN"/>'
            '<vsdx:Cell N="Type" V="99"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        proxy = _wrap_parsed(shape)
        assert proxy.connection_points[0].type == CONNECTION_TYPE.INWARD
