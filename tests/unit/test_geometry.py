"""Unit tests for the 0.3.0 custom-geometry proxy.

BDD-style per project conventions. Covers:

* Builder API — :meth:`Geometry.move_to` / ``.line_to`` / ``.arc_to``
  / ``.elliptical_arc_to`` / ``.nurbs_to`` / ``.rel_*`` variants —
  each returns a typed row proxy whose ``@IX`` is monotonic.
* Row-type dispatch — every known ``@T`` value resolves to its
  dedicated subclass (``MoveTo`` / ``LineTo`` / …); unknown ``@T``
  falls back to :class:`UnknownGeometryRow` so parse never drops
  rows.
* Section-level flag cells (``NoFill`` / ``NoLine`` / ``NoShow`` /
  ``NoSnap`` / ``NoQuickDrag``) round-trip via the property surface.
* Shapes may carry multiple Geometry sections (compound paths) and
  :class:`Geometries` iterates them in ``@IX`` order.
* Parse → mutate → re-serialise round-trip on a shape built
  programmatically.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

from lxml import etree

import vsdx
from vsdx.geometry import (
    ArcTo,
    EllipticalArcTo,
    Geometry,
    LineTo,
    MoveTo,
    NURBSTo,
    PolylineTo,
    RelCubBezTo,
    RelEllipticalArcTo,
    RelLineTo,
    RelMoveTo,
    RelQuadBezTo,
    SplineKnot,
    SplineStart,
    UnknownGeometryRow,
)
from vsdx.oxml import nsdecls, parse_xml


def _fresh_shape():
    """Return a ``(doc, page, shape)`` triple with one rectangle on the page."""
    doc = vsdx.Visio()
    page = doc.pages.add_page(name="Page-1")
    shape = page.shapes.add_shape(vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(1, 1))
    return doc, page, shape


def _parse_shape_with_geometry(xml_body: str):
    """Parse a ``<Shape>`` element carrying *xml_body* as its children."""
    xml = (
        '<vsdx:Shape %s ID="1" Type="Shape">%s</vsdx:Shape>'
        % (nsdecls("vsdx"), xml_body)
    ).encode()
    return parse_xml(xml)


# ---------------------------------------------------------------------------
# Describe geometry collection on Shape
# ---------------------------------------------------------------------------


class DescribeShapeGeometry:
    def it_exposes_no_geometry_on_a_fresh_shape(self) -> None:
        _, _, shape = _fresh_shape()
        assert shape.geometry is None
        assert len(shape.geometries) == 0
        assert list(shape.geometries) == []

    def it_materialises_a_geometry_section_on_add(self) -> None:
        _, _, shape = _fresh_shape()
        geometry = shape.add_geometry()
        assert isinstance(geometry, Geometry)
        assert geometry.index == 0
        assert len(shape.geometries) == 1
        assert shape.geometry is not None
        # Section written with N="Geometry" IX="0".
        assert geometry.section.get("N") == "Geometry"
        assert geometry.section.get("IX") == "0"

    def it_returns_first_section_from_shape_dot_geometry(self) -> None:
        _, _, shape = _fresh_shape()
        shape.add_geometry()
        shape.add_geometry()
        assert shape.geometry.index == 0
        assert shape.geometries[1].index == 1

    def it_supports_multiple_geometry_sections(self) -> None:
        _, _, shape = _fresh_shape()
        first = shape.add_geometry()
        second = shape.add_geometry()
        third = shape.add_geometry()
        assert [g.index for g in shape.geometries] == [0, 1, 2]
        assert first.index == 0 and second.index == 1 and third.index == 2


# ---------------------------------------------------------------------------
# Describe builder API — square, arc, NURBS
# ---------------------------------------------------------------------------


class DescribeGeometryBuilders:
    def it_builds_a_square_with_move_and_three_lines(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        m = geo.move_to(0, 0)
        l1 = geo.line_to(1, 0)
        l2 = geo.line_to(1, 1)
        l3 = geo.line_to(0, 1)
        l4 = geo.line_to(0, 0)
        assert isinstance(m, MoveTo)
        assert all(isinstance(r, LineTo) for r in (l1, l2, l3, l4))
        # IX starts at 1 and grows monotonically.
        assert [r.ix for r in geo.rows] == [1, 2, 3, 4, 5]
        # Coordinates round-trip through the proxy getters.
        coords = [(r.x, r.y) for r in geo.rows]
        assert coords == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]

    def it_builds_an_arc(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        geo.move_to(0, 0)
        arc = geo.arc_to(1.0, 0.0, 0.25)
        assert isinstance(arc, ArcTo)
        assert arc.x == 1.0
        assert arc.y == 0.0
        assert arc.bow == 0.25  # ``bow`` is the ArcTo alias for ``a``.
        assert arc.a == 0.25

    def it_builds_an_elliptical_arc(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        geo.move_to(0, 0)
        ea = geo.elliptical_arc_to(1.0, 0.0, 0.5, 0.25, 0.0, 1.5)
        assert isinstance(ea, EllipticalArcTo)
        assert (ea.x, ea.y, ea.a, ea.b, ea.c, ea.d) == (
            1.0, 0.0, 0.5, 0.25, 0.0, 1.5
        )

    def it_builds_a_NURBS_curve(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        geo.move_to(0, 0)
        n = geo.nurbs_to(2.0, 2.0, 1.0, 1.0, 0.0, 3.0)
        assert isinstance(n, NURBSTo)
        assert (n.x, n.y, n.a, n.b, n.c, n.d) == (
            2.0, 2.0, 1.0, 1.0, 0.0, 3.0
        )
        assert n.e is None  # E cell omitted when not supplied.

    def it_builds_a_NURBS_curve_with_E_cell(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        geo.nurbs_to(2.0, 2.0, 1.0, 1.0, 0.0, 3.0, e=4.0)
        n = geo.rows[0]
        assert n.e == 4.0

    def it_builds_a_spline(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        geo.move_to(0, 0)
        start = geo.spline_start(0.5, 0.5, 0.1, 0.0, 1.0, 3.0)
        knot = geo.spline_knot(1.0, 1.0, 0.5)
        assert isinstance(start, SplineStart)
        assert isinstance(knot, SplineKnot)
        assert start.d == 3.0  # degree
        assert knot.a == 0.5

    def it_builds_a_polyline(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        geo.move_to(0, 0)
        p = geo.polyline_to(1.0, 1.0, 0.0)
        assert isinstance(p, PolylineTo)
        assert (p.x, p.y, p.a) == (1.0, 1.0, 0.0)

    def it_builds_relative_rows(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        rm = geo.rel_move_to(0, 0)
        rl = geo.rel_line_to(0.5, 0.5)
        rc = geo.rel_cub_bez_to(1.0, 1.0, 0.25, 0.0, 0.75, 1.0)
        rq = geo.rel_quad_bez_to(1.0, 0.5, 0.5, 0.25)
        re = geo.rel_elliptical_arc_to(1.0, 0.0, 0.5, 0.25, 0.0, 1.5)
        assert isinstance(rm, RelMoveTo)
        assert isinstance(rl, RelLineTo)
        assert isinstance(rc, RelCubBezTo)
        assert isinstance(rq, RelQuadBezTo)
        assert isinstance(re, RelEllipticalArcTo)


# ---------------------------------------------------------------------------
# Describe row-type discriminator dispatch (parse path)
# ---------------------------------------------------------------------------


class DescribeRowTypeDispatch:
    def it_dispatches_LineTo_rows_to_LineTo(self) -> None:
        shape = _parse_shape_with_geometry(
            '<vsdx:Section N="Geometry" IX="0">'
            '<vsdx:Row IX="1" T="LineTo">'
            '<vsdx:Cell N="X" V="1" U="IN"/><vsdx:Cell N="Y" V="2" U="IN"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        # Wrap the parsed shape in a Shape proxy manually for the test.
        # We don't need the ShapeTree — the Geometry proxy only needs
        # the element.
        from vsdx.shapes.base import Shape

        proxy = Shape.__new__(Shape)
        proxy._element = shape  # type: ignore[attr-defined]
        proxy._parent = None  # type: ignore[attr-defined]
        geo = proxy.geometry
        assert geo is not None
        row = geo.rows[0]
        assert isinstance(row, LineTo)
        assert row.row_type == "LineTo"
        assert row.x == 1.0
        assert row.y == 2.0

    def it_dispatches_unknown_row_types_to_UnknownGeometryRow(self) -> None:
        shape = _parse_shape_with_geometry(
            '<vsdx:Section N="Geometry" IX="0">'
            '<vsdx:Row IX="1" T="MadeUpCurveTo">'
            '<vsdx:Cell N="X" V="3"/><vsdx:Cell N="Y" V="4"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        from vsdx.shapes.base import Shape

        proxy = Shape.__new__(Shape)
        proxy._element = shape  # type: ignore[attr-defined]
        proxy._parent = None  # type: ignore[attr-defined]
        row = proxy.geometry.rows[0]
        assert isinstance(row, UnknownGeometryRow)
        assert row.row_type == "MadeUpCurveTo"
        # Raw coords still reachable via the base-class X/Y accessors.
        assert row.x == 3.0 and row.y == 4.0

    def it_discriminates_every_known_row_type(self) -> None:
        types = [
            ("MoveTo", MoveTo),
            ("LineTo", LineTo),
            ("ArcTo", ArcTo),
            ("EllipticalArcTo", EllipticalArcTo),
            ("NURBSTo", NURBSTo),
            ("PolylineTo", PolylineTo),
            ("SplineStart", SplineStart),
            ("SplineKnot", SplineKnot),
            ("RelMoveTo", RelMoveTo),
            ("RelLineTo", RelLineTo),
            ("RelCubBezTo", RelCubBezTo),
            ("RelQuadBezTo", RelQuadBezTo),
            ("RelEllipticalArcTo", RelEllipticalArcTo),
        ]
        rows_xml = "".join(
            f'<vsdx:Row IX="{i + 1}" T="{t}">'
            f'<vsdx:Cell N="X" V="0"/><vsdx:Cell N="Y" V="0"/>'
            "</vsdx:Row>"
            for i, (t, _) in enumerate(types)
        )
        shape = _parse_shape_with_geometry(
            f'<vsdx:Section N="Geometry" IX="0">{rows_xml}</vsdx:Section>'
        )
        from vsdx.shapes.base import Shape

        proxy = Shape.__new__(Shape)
        proxy._element = shape  # type: ignore[attr-defined]
        proxy._parent = None  # type: ignore[attr-defined]
        rows = proxy.geometry.rows
        for row, (_, expected_cls) in zip(rows, types):
            assert isinstance(row, expected_cls), (
                f"{row.row_type} dispatched to {type(row).__name__}, "
                f"expected {expected_cls.__name__}"
            )


# ---------------------------------------------------------------------------
# Describe flag-cell round-trip on Section
# ---------------------------------------------------------------------------


class DescribeGeometryFlagCells:
    def it_defaults_flags_to_false(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        assert geo.no_fill is False
        assert geo.no_line is False
        assert geo.no_show is False
        assert geo.no_snap is False
        assert geo.no_quick_drag is False

    def it_round_trips_no_fill_flag(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry(no_fill=True)
        assert geo.no_fill is True
        # Mutate through the setter too.
        geo.no_fill = False
        assert geo.no_fill is False

    def it_round_trips_every_flag(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        for attr in ("no_fill", "no_line", "no_show", "no_snap", "no_quick_drag"):
            setattr(geo, attr, True)
            assert getattr(geo, attr) is True


# ---------------------------------------------------------------------------
# Describe setter round-trips on row coordinate cells
# ---------------------------------------------------------------------------


class DescribeGeometryRowSetters:
    def it_round_trips_X_and_Y_via_setters(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        row = geo.line_to(1.0, 2.0)
        row.x = 3.5
        row.y = 4.25
        assert row.x == 3.5 and row.y == 4.25

    def it_round_trips_A_and_B_on_XYAB_rows(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        row = geo.infinite_line(0, 0, 1, 1)
        row.a = 2.0
        row.b = 3.0
        assert row.a == 2.0 and row.b == 3.0

    def it_accepts_formula_overrides_via_set_formula(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        row = geo.line_to(0, 0)
        row.set_formula("X", "Width*1")
        row.set_formula("Y", "Height*0")
        assert row.get_formula("X") == "Width*1"
        assert row.get_formula("Y") == "Height*0"

    def it_clears_a_formula_when_passed_None(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        row = geo.line_to(0, 0)
        row.set_formula("X", "Width*1")
        row.set_formula("X", None)
        assert row.get_formula("X") is None


# ---------------------------------------------------------------------------
# Describe parse-existing + round-trip
# ---------------------------------------------------------------------------


class DescribeExistingShapeGeometry:
    def it_parses_a_fixture_like_square_geometry(self) -> None:
        # Mirrors the rectangle master fixture verbatim (trimmed to the
        # geometry section).
        shape = _parse_shape_with_geometry(
            '<vsdx:Section N="Geometry" IX="0">'
            '<vsdx:Cell N="NoFill" V="0"/>'
            '<vsdx:Cell N="NoLine" V="0"/>'
            '<vsdx:Cell N="NoShow" V="0"/>'
            '<vsdx:Row T="MoveTo" IX="1">'
            '<vsdx:Cell N="X" V="0" U="IN" F="Width*0"/>'
            '<vsdx:Cell N="Y" V="0" U="IN" F="Height*0"/>'
            "</vsdx:Row>"
            '<vsdx:Row T="LineTo" IX="2">'
            '<vsdx:Cell N="X" V="1.5" U="IN" F="Width*1"/>'
            '<vsdx:Cell N="Y" V="0" U="IN" F="Height*0"/>'
            "</vsdx:Row>"
            '<vsdx:Row T="LineTo" IX="3">'
            '<vsdx:Cell N="X" V="1.5" U="IN" F="Width*1"/>'
            '<vsdx:Cell N="Y" V="1" U="IN" F="Height*1"/>'
            "</vsdx:Row>"
            '<vsdx:Row T="LineTo" IX="4">'
            '<vsdx:Cell N="X" V="0" U="IN" F="Width*0"/>'
            '<vsdx:Cell N="Y" V="1" U="IN" F="Height*1"/>'
            "</vsdx:Row>"
            '<vsdx:Row T="LineTo" IX="5">'
            '<vsdx:Cell N="X" V="0" U="IN" F="Geometry1.X1"/>'
            '<vsdx:Cell N="Y" V="0" U="IN" F="Geometry1.Y1"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
        )
        from vsdx.shapes.base import Shape

        proxy = Shape.__new__(Shape)
        proxy._element = shape  # type: ignore[attr-defined]
        proxy._parent = None  # type: ignore[attr-defined]
        geo = proxy.geometry
        assert geo is not None
        rows = geo.rows
        assert len(rows) == 5
        assert isinstance(rows[0], MoveTo)
        assert all(isinstance(r, LineTo) for r in rows[1:])
        # Close-the-path formulas preserved.
        assert rows[4].get_formula("X") == "Geometry1.X1"
        assert rows[4].get_formula("Y") == "Geometry1.Y1"

    def it_round_trips_build_then_serialise(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        geo.move_to(0, 0)
        geo.line_to(1, 0)
        geo.line_to(1, 1)
        geo.line_to(0, 1)
        geo.line_to(0, 0)
        # Serialise to XML and re-parse; assert every row survives.
        xml = etree.tostring(shape._element)
        reparsed = parse_xml(xml)
        from vsdx.shapes.base import Shape

        proxy = Shape.__new__(Shape)
        proxy._element = reparsed  # type: ignore[attr-defined]
        proxy._parent = None  # type: ignore[attr-defined]
        reparsed_geo = proxy.geometry
        assert reparsed_geo is not None
        assert len(reparsed_geo.rows) == 5
        coords = [(r.x, r.y) for r in reparsed_geo.rows]
        assert coords == [
            (0.0, 0.0),
            (1.0, 0.0),
            (1.0, 1.0),
            (0.0, 1.0),
            (0.0, 0.0),
        ]


# ---------------------------------------------------------------------------
# Describe row removal
# ---------------------------------------------------------------------------


class DescribeGeometryMutation:
    def it_removes_a_row_without_renumbering_IX(self) -> None:
        _, _, shape = _fresh_shape()
        geo = shape.add_geometry()
        geo.move_to(0, 0)
        second = geo.line_to(1, 0)
        geo.line_to(1, 1)
        geo.remove_row(second)
        assert len(geo.rows) == 2
        # IX values on surviving rows are NOT renumbered — Visio
        # tolerates gaps in geometry-row indices (rows are ordered by
        # document order, not by @IX).
        assert [r.ix for r in geo.rows] == [1, 3]

    def it_removes_a_whole_geometry_section(self) -> None:
        _, _, shape = _fresh_shape()
        first = shape.add_geometry()
        second = shape.add_geometry()
        shape.geometries.remove(first)
        assert len(shape.geometries) == 1
        assert shape.geometries[0] is not second  # fresh proxy each access
        assert shape.geometries[0].index == second.index
