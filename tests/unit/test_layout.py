# Copyright 2026 the python-vsdx authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
"""Unit tests for :mod:`vsdx.layout` and :meth:`Page.layout`.

Four layout kinds, each with a fixture page + position-invariant
assertions. Plus :class:`LayoutReport` introspection coverage.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import io
import math

import pytest

import vsdx
from vsdx.layout import (
    LAYOUT_KIND_FORCE_DIRECTED,
    LAYOUT_KIND_GRID,
    LAYOUT_KIND_HIERARCHY,
    LAYOUT_KIND_RADIAL,
    LAYOUT_KINDS,
    LayoutReport,
    layout as _layout,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _new_page(name: str = "P", width: float = 24.0, height: float = 24.0):
    doc = vsdx.Visio()
    page = doc.pages.add_page(name=name, width=width, height=height)
    return doc, page


def _hierarchy_fixture():
    """A four-node tree: root → {a, b}; b → c.

    Returns ``(doc, page, [root, a, b, c])``.
    """
    doc, page = _new_page("hier")
    root = page.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
    a = page.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
    b = page.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
    c = page.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
    page.connect(root, a)
    page.connect(root, b)
    page.connect(b, c)
    return doc, page, [root, a, b, c]


def _grid_fixture(count: int = 7):
    doc, page = _new_page("grid")
    shapes = [
        page.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
        for _ in range(count)
    ]
    return doc, page, shapes


def _radial_fixture(spokes: int = 5):
    doc, page = _new_page("radial")
    hub = page.shapes.add_shape("Ellipse", at=(0, 0), size=(1.5, 1.5))
    spokes_shapes = []
    for _ in range(spokes):
        s = page.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
        page.connect(hub, s)
        spokes_shapes.append(s)
    return doc, page, hub, spokes_shapes


def _force_fixture():
    """A six-node graph: triangle (0-1-2) + tail (2 → 3 → 4 → 5)."""
    doc, page = _new_page("force")
    shapes = [
        page.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
        for _ in range(6)
    ]
    edges = [(0, 1), (1, 2), (2, 0), (2, 3), (3, 4), (4, 5)]
    for a, b in edges:
        page.connect(shapes[a], shapes[b])
    return doc, page, shapes


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------


class DescribePageLayoutAPI:
    def it_is_callable_via_page_layout(self) -> None:
        _, page, _ = _grid_fixture(4)
        report = page.layout(kind=LAYOUT_KIND_GRID, cols=2, spacing=1.0)
        assert isinstance(report, LayoutReport)
        assert report.layout_kind == LAYOUT_KIND_GRID

    def it_lists_four_kinds(self) -> None:
        assert set(LAYOUT_KINDS) == {
            LAYOUT_KIND_HIERARCHY,
            LAYOUT_KIND_GRID,
            LAYOUT_KIND_RADIAL,
            LAYOUT_KIND_FORCE_DIRECTED,
        }

    def it_rejects_an_unknown_kind(self) -> None:
        _, page, _ = _grid_fixture(2)
        with pytest.raises(ValueError, match="unknown layout kind"):
            page.layout(kind="not-a-kind")

    def it_returns_an_empty_report_for_an_empty_page(self) -> None:
        _, page = _new_page("empty")
        report = page.layout(kind=LAYOUT_KIND_GRID)
        assert report.shapes_moved == 0
        assert report.layout_kind == LAYOUT_KIND_GRID
        assert report.bounding_box == (0.0, 0.0, 0.0, 0.0)
        assert report.iterations == 0

    def it_skips_connector_shapes_when_counting_moved(self) -> None:
        _, page, shapes = _hierarchy_fixture()
        report = page.layout(
            kind=LAYOUT_KIND_HIERARCHY, spacing=1.5
        )
        # Four real shapes; report counts how many actually moved (all
        # were authored at (0, 0) so all four should now have non-zero
        # positions and count as moved).
        assert report.shapes_moved == 4

    def it_exposes_a_bounding_box(self) -> None:
        _, page, _ = _grid_fixture(4)
        report = page.layout(kind=LAYOUT_KIND_GRID, cols=2, spacing=1.0)
        min_x, min_y, max_x, max_y = report.bounding_box
        assert min_x <= max_x and min_y <= max_y


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------


class DescribeHierarchyLayout:
    def it_places_children_below_parents_top_to_bottom(self) -> None:
        _, page, shapes = _hierarchy_fixture()
        root, a, b, c = shapes
        page.layout(kind=LAYOUT_KIND_HIERARCHY, direction="top-to-bottom",
                    spacing=2.0)
        # Top-to-bottom places y = depth * spacing on the Y axis (down).
        assert float(a.pin_y) > float(root.pin_y) - 1e-6
        assert float(b.pin_y) > float(root.pin_y) - 1e-6
        assert float(c.pin_y) > float(b.pin_y) - 1e-6

    def it_places_children_to_the_right_for_left_to_right(self) -> None:
        _, page, shapes = _hierarchy_fixture()
        root, a, b, c = shapes
        page.layout(
            kind=LAYOUT_KIND_HIERARCHY, direction="left-to-right", spacing=1.5
        )
        assert float(a.pin_x) > float(root.pin_x)
        assert float(b.pin_x) > float(root.pin_x)
        assert float(c.pin_x) > float(b.pin_x)

    def it_separates_sibling_subtrees_on_the_cross_axis(self) -> None:
        _, page, shapes = _hierarchy_fixture()
        root, a, b, c = shapes
        page.layout(kind=LAYOUT_KIND_HIERARCHY, direction="top-to-bottom",
                    spacing=1.5)
        # Siblings ``a`` and ``b`` should have distinct cross-axis (X)
        # positions.
        assert abs(float(a.pin_x) - float(b.pin_x)) > 1e-6

    def it_respects_the_spacing_parameter(self) -> None:
        _, page, shapes = _hierarchy_fixture()
        root, a, b, c = shapes
        page.layout(kind=LAYOUT_KIND_HIERARCHY, direction="top-to-bottom",
                    spacing=3.0)
        # With spacing=3, depth-1 children should be 3.0 below root.
        depth_diff = float(b.pin_y) - float(root.pin_y)
        assert abs(depth_diff - 3.0) < 1e-6

    def it_handles_an_isolated_node_with_no_edges(self) -> None:
        doc, page = _new_page("iso")
        s1 = page.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
        s2 = page.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
        # No connector — both are roots.
        report = page.layout(kind=LAYOUT_KIND_HIERARCHY, spacing=1.0)
        # Both should land somewhere distinct; report should reflect 2.
        assert report.shapes_moved == 2 or report.shapes_moved == 1
        assert float(s1.pin_x) != float(s2.pin_x) or float(s1.pin_y) != float(s2.pin_y)

    def it_rejects_an_unknown_direction(self) -> None:
        _, page, _ = _hierarchy_fixture()
        with pytest.raises(ValueError, match="unknown hierarchy direction"):
            page.layout(kind=LAYOUT_KIND_HIERARCHY, direction="diagonal")

    def it_iterations_is_zero_for_analytic_kinds(self) -> None:
        _, page, _ = _hierarchy_fixture()
        report = page.layout(kind=LAYOUT_KIND_HIERARCHY, spacing=1.0)
        assert report.iterations == 0


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------


class DescribeGridLayout:
    def it_lays_out_in_row_major_order(self) -> None:
        _, page, shapes = _grid_fixture(6)
        page.layout(kind=LAYOUT_KIND_GRID, cols=3, spacing=1.0)
        # First three on the same row (same y), next three on the second row.
        assert abs(float(shapes[0].pin_y) - float(shapes[1].pin_y)) < 1e-6
        assert abs(float(shapes[1].pin_y) - float(shapes[2].pin_y)) < 1e-6
        assert float(shapes[3].pin_y) > float(shapes[0].pin_y)

    def it_keeps_cell_spacing_equal(self) -> None:
        _, page, shapes = _grid_fixture(6)
        page.layout(kind=LAYOUT_KIND_GRID, cols=3, spacing=1.0)
        dx = float(shapes[1].pin_x) - float(shapes[0].pin_x)
        dx2 = float(shapes[2].pin_x) - float(shapes[1].pin_x)
        assert abs(dx - dx2) < 1e-6

    def it_defaults_cols_to_square_root_of_n(self) -> None:
        _, page, shapes = _grid_fixture(9)
        page.layout(kind=LAYOUT_KIND_GRID, spacing=1.0)
        # 9 shapes, default cols=3 → row-2 starts at index 3.
        assert float(shapes[3].pin_y) > float(shapes[2].pin_y)
        # First three on the same row.
        assert abs(float(shapes[0].pin_y) - float(shapes[2].pin_y)) < 1e-6

    def it_handles_n_smaller_than_cols(self) -> None:
        _, page, shapes = _grid_fixture(2)
        page.layout(kind=LAYOUT_KIND_GRID, cols=4, spacing=1.0)
        assert abs(float(shapes[0].pin_y) - float(shapes[1].pin_y)) < 1e-6

    def it_marks_every_shape_moved_when_starting_at_origin(self) -> None:
        _, page, shapes = _grid_fixture(5)
        report = page.layout(kind=LAYOUT_KIND_GRID, cols=3, spacing=1.0)
        # 4 of 5 shapes will have moved (the first lands at origin (1,1),
        # which differs from (0,0) — so all 5 move).
        assert report.shapes_moved == 5


# ---------------------------------------------------------------------------
# Radial
# ---------------------------------------------------------------------------


class DescribeRadialLayout:
    def it_places_the_centre_shape_at_origin(self) -> None:
        _, page, hub, _ = _radial_fixture(spokes=4)
        page.layout(kind=LAYOUT_KIND_RADIAL, center_shape=hub, spacing=2.0,
                    origin=(5.0, 5.0))
        assert abs(float(hub.pin_x) - 5.0) < 1e-6
        assert abs(float(hub.pin_y) - 5.0) < 1e-6

    def it_places_spokes_on_a_ring_at_radius_spacing(self) -> None:
        _, page, hub, spokes = _radial_fixture(spokes=4)
        page.layout(kind=LAYOUT_KIND_RADIAL, center_shape=hub, spacing=3.0,
                    origin=(0.0, 0.0))
        for s in spokes:
            d = math.hypot(float(s.pin_x), float(s.pin_y))
            assert abs(d - 3.0) < 1e-6

    def it_distributes_spokes_evenly_around_the_circle(self) -> None:
        _, page, hub, spokes = _radial_fixture(spokes=6)
        page.layout(kind=LAYOUT_KIND_RADIAL, center_shape=hub, spacing=2.0,
                    origin=(0.0, 0.0))
        # Sum of the unit-vectors for evenly-distributed points is zero.
        sum_x = sum(float(s.pin_x) for s in spokes)
        sum_y = sum(float(s.pin_y) for s in spokes)
        assert abs(sum_x) < 1e-6
        assert abs(sum_y) < 1e-6

    def it_falls_back_to_highest_degree_node_when_centre_omitted(self) -> None:
        _, page, hub, spokes = _radial_fixture(spokes=4)
        # No center_shape — the hub has degree 4, every spoke has degree 1.
        page.layout(kind=LAYOUT_KIND_RADIAL, spacing=1.0, origin=(0.0, 0.0))
        assert abs(float(hub.pin_x)) < 1e-6
        assert abs(float(hub.pin_y)) < 1e-6

    def it_rejects_a_centre_shape_not_on_the_page(self) -> None:
        _, page, hub, _ = _radial_fixture(spokes=2)
        # Build an unrelated shape on a different page.
        doc2 = vsdx.Visio()
        page2 = doc2.pages.add_page("other")
        stranger = page2.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
        with pytest.raises(ValueError, match="not on this page"):
            page.layout(kind=LAYOUT_KIND_RADIAL, center_shape=stranger)

    def it_handles_unreachable_nodes_in_an_outer_ring(self) -> None:
        _, page, hub, spokes = _radial_fixture(spokes=2)
        # Add an isolated extra shape — should land on the catch-all ring.
        extra = page.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
        page.layout(kind=LAYOUT_KIND_RADIAL, center_shape=hub, spacing=1.0,
                    origin=(0.0, 0.0))
        # Extra is on ring index 2 (one beyond the spokes' ring 1).
        d = math.hypot(float(extra.pin_x), float(extra.pin_y))
        assert d > 1.5


# ---------------------------------------------------------------------------
# Force-directed
# ---------------------------------------------------------------------------


class DescribeForceDirectedLayout:
    def it_runs_the_requested_iterations(self) -> None:
        _, page, _ = _force_fixture()
        report = page.layout(
            kind=LAYOUT_KIND_FORCE_DIRECTED, iterations=50,
            repulsion=1000.0, spacing=2.0,
        )
        assert report.iterations == 50

    def it_is_deterministic_for_the_same_input(self) -> None:
        # Two independent fixture runs should converge to the same
        # positions because the spiral seed depends only on shape order.
        _, page1, shapes1 = _force_fixture()
        page1.layout(
            kind=LAYOUT_KIND_FORCE_DIRECTED, iterations=30, spacing=2.0
        )
        positions1 = [(float(s.pin_x), float(s.pin_y)) for s in shapes1]

        _, page2, shapes2 = _force_fixture()
        page2.layout(
            kind=LAYOUT_KIND_FORCE_DIRECTED, iterations=30, spacing=2.0
        )
        positions2 = [(float(s.pin_x), float(s.pin_y)) for s in shapes2]

        for (x1, y1), (x2, y2) in zip(positions1, positions2):
            assert abs(x1 - x2) < 1e-6
            assert abs(y1 - y2) < 1e-6

    def it_separates_connected_nodes_from_zero_overlap(self) -> None:
        _, page, shapes = _force_fixture()
        page.layout(
            kind=LAYOUT_KIND_FORCE_DIRECTED, iterations=50, spacing=2.0
        )
        # No two shapes should be coincident after annealing.
        for i, s in enumerate(shapes):
            for j, t in enumerate(shapes):
                if i >= j:
                    continue
                d = math.hypot(
                    float(s.pin_x) - float(t.pin_x),
                    float(s.pin_y) - float(t.pin_y),
                )
                assert d > 0.01

    def it_converges_to_a_stable_layout(self) -> None:
        # Run 100 iterations — final positions should not change much
        # vs running 80 iterations more (i.e. layout is converged).
        _, page1, shapes1 = _force_fixture()
        page1.layout(
            kind=LAYOUT_KIND_FORCE_DIRECTED, iterations=100, spacing=2.0
        )
        pos_100 = [(float(s.pin_x), float(s.pin_y)) for s in shapes1]

        _, page2, shapes2 = _force_fixture()
        page2.layout(
            kind=LAYOUT_KIND_FORCE_DIRECTED, iterations=180, spacing=2.0
        )
        pos_180 = [(float(s.pin_x), float(s.pin_y)) for s in shapes2]

        # Final-frame difference should be small relative to the frame
        # size. Frame is roughly 2*sqrt(6) ~= 4.9 inches; 1.5" wiggle
        # room is generous but catches the obvious "not converging at
        # all" regression.
        for (x1, y1), (x2, y2) in zip(pos_100, pos_180):
            assert math.hypot(x1 - x2, y1 - y2) < 1.5

    def it_handles_a_zero_iteration_request(self) -> None:
        _, page, shapes = _force_fixture()
        report = page.layout(
            kind=LAYOUT_KIND_FORCE_DIRECTED, iterations=0, spacing=2.0
        )
        assert report.iterations == 0
        # Shapes should still have moved off (0, 0) onto the spiral seed.
        assert any(
            float(s.pin_x) != 0.0 or float(s.pin_y) != 0.0 for s in shapes
        )

    def it_handles_a_one_node_page(self) -> None:
        doc, page = _new_page("one")
        s = page.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
        report = page.layout(
            kind=LAYOUT_KIND_FORCE_DIRECTED, iterations=10, origin=(2.0, 3.0)
        )
        assert report.iterations == 0
        assert abs(float(s.pin_x) - 2.0) < 1e-6
        assert abs(float(s.pin_y) - 3.0) < 1e-6


# ---------------------------------------------------------------------------
# Round-trip safety
# ---------------------------------------------------------------------------


class DescribeRoundTripSafety:
    def it_persists_grid_positions_through_save_and_reload(self) -> None:
        doc, page, shapes = _grid_fixture(4)
        page.layout(kind=LAYOUT_KIND_GRID, cols=2, spacing=1.5)
        positions = [(float(s.pin_x), float(s.pin_y)) for s in shapes]

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        reopened = vsdx.Visio(buf)
        reopened_page = reopened.pages[0]
        # Filter out connectors when comparing.
        reopened_shapes = [
            s for s in reopened_page.shapes
            if not isinstance(s, vsdx.Connector)
        ]
        for (x, y), shape in zip(positions, reopened_shapes):
            assert abs(float(shape.pin_x) - x) < 1e-6
            assert abs(float(shape.pin_y) - y) < 1e-6

    def it_persists_hierarchy_positions_through_save_and_reload(self) -> None:
        doc, page, shapes = _hierarchy_fixture()
        page.layout(kind=LAYOUT_KIND_HIERARCHY, direction="top-to-bottom",
                    spacing=1.5)
        positions = [(float(s.pin_x), float(s.pin_y)) for s in shapes]

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        reopened = vsdx.Visio(buf)
        reopened_shapes = [
            s for s in reopened.pages[0].shapes
            if not isinstance(s, vsdx.Connector)
        ]
        for (x, y), shape in zip(positions, reopened_shapes):
            assert abs(float(shape.pin_x) - x) < 1e-6
            assert abs(float(shape.pin_y) - y) < 1e-6


# ---------------------------------------------------------------------------
# LayoutReport
# ---------------------------------------------------------------------------


class DescribeLayoutReport:
    def it_is_a_frozen_dataclass(self) -> None:
        report = LayoutReport(
            shapes_moved=3, layout_kind="grid",
            bounding_box=(0.0, 0.0, 1.0, 1.0), iterations=0,
        )
        with pytest.raises((AttributeError, Exception)):
            report.shapes_moved = 5  # type: ignore[misc]

    def it_carries_kind_and_box(self) -> None:
        _, page, _ = _grid_fixture(4)
        report = page.layout(kind=LAYOUT_KIND_GRID, cols=2, spacing=1.0)
        assert report.layout_kind == LAYOUT_KIND_GRID
        assert len(report.bounding_box) == 4


# ---------------------------------------------------------------------------
# Direct-call shape (skip the Page sugar)
# ---------------------------------------------------------------------------


class DescribeDirectLayoutFunction:
    def it_can_be_called_as_a_module_function(self) -> None:
        _, page, _ = _grid_fixture(4)
        report = _layout(page, kind=LAYOUT_KIND_GRID, cols=2, spacing=1.0)
        assert isinstance(report, LayoutReport)
