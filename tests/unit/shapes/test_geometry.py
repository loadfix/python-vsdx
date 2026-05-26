"""Behavioural tests for the proxy-layer custom-geometry authoring API.

Sister suite to ``tests/unit/test_geometry.py`` (which covers the
core :class:`~vsdx.geometry.Geometry` proxy in isolation). This file
exercises the integration points the 0.3.0 Tier-1 maturity blocker
needs:

* :meth:`Shapes.add_custom_shape` — drops a master-less Shape with an
  empty Geometry section pre-installed.
* :attr:`Shape.geometry` — the chainable single-section accessor.
* The new :meth:`Geometry.curve_to` cubic-Bezier helper (NURBSTo
  encoding under the hood).
* :meth:`Geometry.arc_to` accepting ``sweep`` as a keyword alias for
  ``bow``.
* :meth:`Geometry.close` — appends a ``LineTo`` back to the most
  recent :class:`MoveTo`.
* End-to-end round-trip: build a path, serialise the
  :class:`~vsdx.package.Package` to a ``BytesIO``, reload it, assert
  every row survived intact.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import io

from lxml import etree

import vsdx
from vsdx.geometry import (
    ArcTo,
    Geometry,
    LineTo,
    MoveTo,
    NURBSTo,
)


def _fresh_custom_shape(at=(1.0, 1.0), size=(3.0, 2.0)):
    """Helper — make a doc + page + custom shape ready for path-building."""
    doc = vsdx.Visio()
    page = doc.pages.add_page(name="Custom")
    shape = page.shapes.add_custom_shape(at=at, size=size)
    return doc, page, shape


# ---------------------------------------------------------------------------
# DescribeShapes.add_custom_shape
# ---------------------------------------------------------------------------


class DescribeShapes:
    def it_adds_a_custom_shape(self):
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        shape = page.shapes.add_custom_shape(at=(1, 1), size=(3, 2))
        assert shape is not None
        assert float(shape.pin_x) == 1.0
        assert float(shape.pin_y) == 1.0
        assert float(shape.width) == 3.0
        assert float(shape.height) == 2.0

    def it_adds_a_custom_shape_without_a_master_reference(self):
        _, _, shape = _fresh_custom_shape()
        # Master-less shape — Visio treats it as user-authored, not an
        # autoshape instance.
        assert shape.master_name_u is None
        assert shape._element.get("Master") is None

    def it_pre_installs_an_empty_Geometry_section_on_a_custom_shape(self):
        _, _, shape = _fresh_custom_shape()
        # A custom shape arrives with one empty Geometry section so
        # callers can chain shape.geometry.move_to(...) directly.
        assert shape.geometry is not None
        assert isinstance(shape.geometry, Geometry)
        assert len(shape.geometry.rows) == 0
        assert shape.geometry.index == 0

    def it_assigns_a_unique_shape_id_to_each_custom_shape(self):
        doc = vsdx.Visio()
        page = doc.pages.add_page()
        a = page.shapes.add_custom_shape(at=(0, 0), size=(1, 1))
        b = page.shapes.add_custom_shape(at=(2, 2), size=(1, 1))
        c = page.shapes.add_custom_shape(at=(4, 4), size=(1, 1))
        assert len({a.shape_id, b.shape_id, c.shape_id}) == 3

    def it_accepts_an_optional_master_for_inherited_styling(self):
        # When a master NameU is supplied, the shape DOES carry a
        # @Master attr — the custom geometry overrides the master's
        # outline but the master still contributes fill / line / text
        # defaults.
        doc = vsdx.Visio()
        page = doc.pages.add_page()
        shape = page.shapes.add_custom_shape(
            at=(0, 0), size=(1, 1), master="Rectangle"
        )
        assert shape.master_name_u == "Rectangle"
        # Geometry still pre-installed.
        assert shape.geometry is not None


# ---------------------------------------------------------------------------
# DescribeGeometry — append-row primitives
# ---------------------------------------------------------------------------


class DescribeGeometry:
    def it_appends_a_move_to(self):
        _, _, shape = _fresh_custom_shape()
        m = shape.geometry.move_to(0.5, 1.0)
        assert isinstance(m, MoveTo)
        assert m.row_type == "MoveTo"
        assert m.x == 0.5
        assert m.y == 1.0
        assert m.ix == 1  # IX starts at 1 in Visio

    def it_appends_a_line_to(self):
        _, _, shape = _fresh_custom_shape()
        shape.geometry.move_to(0, 0)
        line = shape.geometry.line_to(1.5, 2.0)
        assert isinstance(line, LineTo)
        assert line.row_type == "LineTo"
        assert line.x == 1.5
        assert line.y == 2.0
        assert line.ix == 2

    def it_appends_an_arc_to_with_a_positional_bow(self):
        _, _, shape = _fresh_custom_shape()
        shape.geometry.move_to(0, 0)
        arc = shape.geometry.arc_to(1.0, 0.0, 0.25)
        assert isinstance(arc, ArcTo)
        assert arc.x == 1.0
        assert arc.bow == 0.25
        assert arc.a == 0.25

    def it_appends_an_arc_to_with_a_sweep_keyword(self):
        _, _, shape = _fresh_custom_shape()
        shape.geometry.move_to(0, 0)
        arc = shape.geometry.arc_to(0, 1, sweep=0.5)
        assert isinstance(arc, ArcTo)
        assert arc.bow == 0.5  # sweep is an alias for bow
        assert arc.a == 0.5

    def it_rejects_arc_to_with_both_bow_and_sweep(self):
        import pytest

        _, _, shape = _fresh_custom_shape()
        shape.geometry.move_to(0, 0)
        with pytest.raises(TypeError):
            shape.geometry.arc_to(1, 1, bow=0.25, sweep=0.5)

    def it_defaults_arc_to_bow_to_zero_when_omitted(self):
        _, _, shape = _fresh_custom_shape()
        shape.geometry.move_to(0, 0)
        arc = shape.geometry.arc_to(1, 1)
        assert arc.a == 0.0

    def it_appends_a_curve_to_as_a_NURBS_row(self):
        _, _, shape = _fresh_custom_shape()
        shape.geometry.move_to(0, 0)
        curve = shape.geometry.curve_to(0.5, 0.5, 1.0, 0.5, 1.0, 1.0)
        # curve_to lowers to a NURBSTo row (Visio's canonical cubic
        # Bezier encoding).
        assert isinstance(curve, NURBSTo)
        assert curve.row_type == "NURBSTo"
        # Endpoint cells are absolute inches.
        assert curve.x == 1.0
        assert curve.y == 1.0
        # Degree=3 (cubic).
        assert curve.d == 3.0
        # Weights both 1 (cubic Bezier rationality).
        assert curve.a == 1.0
        assert curve.b == 1.0

    def it_carries_curve_to_control_points_in_the_C_cell_formula(self):
        _, _, shape = _fresh_custom_shape()
        shape.geometry.move_to(0, 0)
        curve = shape.geometry.curve_to(0.5, 0.5, 1.0, 0.5, 1.0, 1.0)
        formula = curve.get_formula("C")
        assert formula is not None
        # Both control-point coordinates must appear in the formula.
        assert "0.5" in formula
        assert "1" in formula
        assert formula.startswith("NURBS(")

    def it_appends_a_close(self):
        _, _, shape = _fresh_custom_shape()
        shape.geometry.move_to(0.5, 1.0)
        shape.geometry.line_to(1.5, 1.0)
        shape.geometry.line_to(1.5, 2.0)
        closing = shape.geometry.close()
        assert isinstance(closing, LineTo)
        # Closing row's coords match the most recent MoveTo.
        assert closing.x == 0.5
        assert closing.y == 1.0

    def it_returns_None_from_close_on_an_empty_path(self):
        _, _, shape = _fresh_custom_shape()
        # No MoveTo yet — close() is a no-op.
        assert shape.geometry.close() is None
        assert len(shape.geometry.rows) == 0

    def it_closes_back_to_the_most_recent_move_to(self):
        _, _, shape = _fresh_custom_shape()
        shape.geometry.move_to(0, 0)
        shape.geometry.line_to(1, 0)
        shape.geometry.move_to(2, 2)  # second subpath
        shape.geometry.line_to(3, 2)
        closing = shape.geometry.close()
        # Closes to the most recent MoveTo (2, 2), not the first.
        assert closing is not None
        assert closing.x == 2.0
        assert closing.y == 2.0

    def it_grows_IX_monotonically_as_rows_are_appended(self):
        _, _, shape = _fresh_custom_shape()
        shape.geometry.move_to(0, 0)
        shape.geometry.line_to(1, 0)
        shape.geometry.curve_to(0.5, 0.5, 1.0, 0.5, 1.0, 1.0)
        shape.geometry.arc_to(0, 1, sweep=0.5)
        shape.geometry.close()
        ixs = [r.ix for r in shape.geometry.rows]
        assert ixs == [1, 2, 3, 4, 5]

    def it_iterates_rows_in_document_order(self):
        _, _, shape = _fresh_custom_shape()
        shape.geometry.move_to(0, 0)
        shape.geometry.line_to(1, 0)
        shape.geometry.line_to(1, 1)
        types = [r.row_type for r in shape.geometry]
        assert types == ["MoveTo", "LineTo", "LineTo"]

    def it_supports_len_on_a_geometry(self):
        _, _, shape = _fresh_custom_shape()
        assert len(shape.geometry) == 0
        shape.geometry.move_to(0, 0)
        assert len(shape.geometry) == 1
        shape.geometry.line_to(1, 0)
        shape.geometry.line_to(1, 1)
        assert len(shape.geometry) == 3

    def it_supports_indexed_access_on_a_geometry(self):
        _, _, shape = _fresh_custom_shape()
        m = shape.geometry.move_to(0, 0)
        line = shape.geometry.line_to(1, 0)
        assert shape.geometry[0].row_type == m.row_type
        assert shape.geometry[1].row_type == line.row_type


# ---------------------------------------------------------------------------
# DescribeGeometry — round-trip
# ---------------------------------------------------------------------------


class DescribeGeometryRoundTrip:
    def it_round_trips_a_path(self):
        _, _, shape = _fresh_custom_shape()
        geo = shape.geometry
        geo.move_to(0, 0)
        geo.line_to(1, 0)
        geo.curve_to(0.5, 0.5, 1.0, 0.5, 1.0, 1.0)
        geo.arc_to(0, 1, sweep=0.5)
        closing = geo.close()
        assert closing is not None  # close() returned the LineTo

        # XML-level round-trip — serialise the Shape element and re-parse.
        from vsdx.oxml import parse_xml
        from vsdx.shapes.base import Shape as ShapeProxy

        xml = etree.tostring(shape._element)
        reparsed = parse_xml(xml)
        proxy = ShapeProxy.__new__(ShapeProxy)
        proxy._element = reparsed  # type: ignore[attr-defined]
        proxy._parent = None  # type: ignore[attr-defined]
        rebuilt = proxy.geometry
        assert rebuilt is not None
        rows = rebuilt.rows
        # Five rows: MoveTo, LineTo, NURBSTo (curve), ArcTo, LineTo (close).
        assert [r.row_type for r in rows] == [
            "MoveTo",
            "LineTo",
            "NURBSTo",
            "ArcTo",
            "LineTo",
        ]
        # Endpoint coordinates survive verbatim.
        assert rows[0].x == 0.0 and rows[0].y == 0.0
        assert rows[1].x == 1.0 and rows[1].y == 0.0
        assert rows[2].x == 1.0 and rows[2].y == 1.0  # curve endpoint
        assert rows[3].x == 0.0 and rows[3].y == 1.0  # arc endpoint
        assert rows[4].x == 0.0 and rows[4].y == 0.0  # closed back to MoveTo
        # The cubic Bezier's control-point formula survives intact.
        nurbs_row = rows[2]
        assert nurbs_row.get_formula("C") is not None
        assert nurbs_row.get_formula("C").startswith("NURBS(")

    def it_round_trips_a_path_through_a_full_package_save_load(self):
        # Full-package round-trip — the load-bearing test. Build a
        # shape with a custom path, save the package to a BytesIO,
        # reload it, assert every geometry row survived.
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Custom")
        shape = page.shapes.add_custom_shape(at=(2, 2), size=(3, 3))
        geo = shape.geometry
        geo.move_to(0, 0)
        geo.line_to(1, 0)
        geo.line_to(1, 1)
        geo.line_to(0, 1)
        geo.close()

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        reopened = vsdx.Visio(buf)
        rpage = reopened.pages[0]
        # The custom shape is the last shape on the page (the page may
        # carry a default rectangle template — find ours by looking
        # for the master-less one).
        target = None
        for sh in rpage.shapes:
            if sh.master_name_u is None:
                target = sh
                break
        assert target is not None, "custom shape lost on round-trip"
        rebuilt = target.geometry
        assert rebuilt is not None
        coords = [(r.x, r.y) for r in rebuilt.rows]
        assert coords == [
            (0.0, 0.0),
            (1.0, 0.0),
            (1.0, 1.0),
            (0.0, 1.0),
            (0.0, 0.0),
        ]


# ---------------------------------------------------------------------------
# DescribeGeometry — multi-section
# ---------------------------------------------------------------------------


class DescribeGeometryIndex:
    def it_distinguishes_geometry_index(self):
        _, _, shape = _fresh_custom_shape()
        # The custom shape arrives with Geometry IX=0 already.
        first = shape.geometry
        assert first is not None
        assert first.index == 0
        # Add a second compound path.
        second = shape.add_geometry()
        assert second.index == 1
        # Each path takes its own row sequence.
        first.move_to(0, 0)
        first.line_to(1, 0)
        second.move_to(0, 1)
        second.line_to(1, 1)
        assert [r.row_type for r in first] == ["MoveTo", "LineTo"]
        assert [r.row_type for r in second] == ["MoveTo", "LineTo"]
        # Iteration order on shape.geometries matches IX order.
        all_paths = list(shape.geometries)
        assert [p.index for p in all_paths] == [0, 1]

    def it_appends_a_third_geometry_section_with_next_unused_IX(self):
        _, _, shape = _fresh_custom_shape()
        shape.add_geometry()
        third = shape.add_geometry()
        assert [g.index for g in shape.geometries] == [0, 1, 2]
        assert third.index == 2

    def it_keeps_per_section_rows_isolated_when_multiple_sections_present(self):
        _, _, shape = _fresh_custom_shape()
        first = shape.geometry
        first.move_to(0, 0)
        first.line_to(1, 0)
        second = shape.add_geometry()
        second.move_to(5, 5)
        # First section's rows are unaffected by edits to the second.
        assert len(first.rows) == 2
        assert len(second.rows) == 1
        assert first.rows[0].x == 0.0
        assert second.rows[0].x == 5.0


# ---------------------------------------------------------------------------
# DescribeGeometry — chainable shape.geometry on a custom shape
# ---------------------------------------------------------------------------


class DescribeChainableShapeGeometry:
    def it_lets_callers_chain_path_builders_off_shape_dot_geometry(self):
        # The 0.3.0 ergonomics target — the spec's motivating example.
        _, _, shape = _fresh_custom_shape()
        shape.geometry.move_to(0, 0)
        shape.geometry.line_to(1, 0)
        shape.geometry.curve_to(0.5, 0.5, 1.0, 0.5, 1.0, 1.0)
        shape.geometry.arc_to(0, 1, sweep=0.5)
        shape.geometry.close()
        # Five rows survived all five method calls — no surprise
        # mid-build proxy resets.
        assert len(shape.geometry.rows) == 5

    def it_preserves_section_identity_across_geometry_attribute_accesses(self):
        # ``shape.geometry`` returns a fresh Geometry proxy on each
        # access (it doesn't cache), but every proxy refers to the
        # SAME underlying ``<Section>`` element — so rows appended via
        # one access show up on the next.
        _, _, shape = _fresh_custom_shape()
        shape.geometry.move_to(0, 0)
        shape.geometry.line_to(1, 0)
        # Every shape.geometry access reads the same section element.
        assert shape.geometry._section is shape.geometries[0]._section
        assert len(shape.geometry.rows) == 2
