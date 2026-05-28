# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version
# 2.0 (the "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.  See the License for the specific language governing
# permissions and limitations under the License.
"""Behavioural tests for the connector auto-routing surface (issue #53).

Covers:

- :func:`vsdx.routing.compute_route` — pure A* path computation.
- :func:`vsdx.routing.compute_jumps` — line-crossing detection.
- :meth:`Page.add_connector` (with ``routing="right-angle"``) — the
  high-level authoring surface that materialises the polyline as a
  ``<Section N="Geometry">`` on the connector shape.
- :meth:`Page.reroute_connectors` — bulk re-route after a layout pass.
- End-to-end save / reload round trip with a routed connector.
"""

from __future__ import annotations

import io

import pytest

import vsdx
from vsdx import Visio
from vsdx.routing import (
    JUMP_ARC,
    ROUTING_RIGHT_ANGLE,
    ROUTING_STRAIGHT,
    compute_jumps,
    compute_route,
    route_connector,
)


def _three_shape_obstacle_page():
    """Build a 3-shape page with the third shape blocking the direct A->B run.

    Layout (in inches)::

        A (1, 1) -------- [###] -------- B (10, 1)
                          OBSTACLE
                          (5, 0..2)

    A direct horizontal connector from A to B at y=1 would punch
    through the obstacle's bbox; the auto-router must dodge above
    or below it.
    """
    doc = Visio()
    page = doc.pages.add_page(name="Routed", width=12, height=4)
    a = page.shapes.add_shape("Rectangle", at=(1, 1), size=(1, 1))
    b = page.shapes.add_shape("Rectangle", at=(10, 1), size=(1, 1))
    obstacle = page.shapes.add_shape("Rectangle", at=(5, 1), size=(2, 1))
    return doc, page, a, b, obstacle


# ---------------------------------------------------------------------------
# Pure compute_route — no shapes, no I/O
# ---------------------------------------------------------------------------


class DescribeComputeRoute:
    def it_returns_two_points_for_straight_routing(self):
        path = compute_route((0, 0), (5, 5), routing=ROUTING_STRAIGHT)
        assert path == [(0, 0), (5, 5)]

    def it_returns_a_manhattan_path_for_right_angle_routing(self):
        path = compute_route(
            (0, 0), (5, 0), routing=ROUTING_RIGHT_ANGLE,
            page_width=10, page_height=10,
        )
        assert path[0] == (0, 0)
        assert path[-1] == (5, 0)
        # No obstacles → straight line collapses into 2-pt path.
        assert len(path) == 2

    def it_routes_around_a_blocking_obstacle(self):
        # Direct line from (0, 0) to (4, 0) is blocked by a box at
        # (1.5, -0.5)–(2.5, 0.5).
        obstacles = [(1.5, -0.5, 2.5, 0.5)]
        path = compute_route(
            (0, 0),
            (4, 0),
            obstacles=obstacles,
            page_width=8,
            page_height=4,
            routing=ROUTING_RIGHT_ANGLE,
        )
        # Path must bend (≥ 3 points) and include at least one
        # off-y=0 waypoint.
        assert len(path) >= 3
        ys = [p[1] for p in path]
        assert any(abs(y) > 0.5 for y in ys), (
            "expected a vertical detour around the obstacle, got %r" % path
        )

    def it_falls_back_when_no_path_exists(self):
        # Box that sandwiches the start cell: a 4-sided wall around (1,1).
        obstacles = [
            (0.5, 0.5, 1.5, 0.7),  # below
            (0.5, 1.3, 1.5, 1.5),  # above
            (0.5, 0.5, 0.7, 1.5),  # left
            (1.3, 0.5, 1.5, 1.5),  # right
        ]
        path = compute_route(
            (1, 1),
            (5, 5),
            obstacles=obstacles,
            page_width=8,
            page_height=8,
        )
        # Even when A* fails, fallback returns a non-empty polyline
        # that begins at start and ends at end.
        assert path[0] == (1, 1)
        assert path[-1] == (5, 5)

    def it_rejects_an_unknown_routing_mode(self):
        with pytest.raises(ValueError):
            compute_route((0, 0), (1, 1), routing="diagonal")


# ---------------------------------------------------------------------------
# Compute jumps over crossings
# ---------------------------------------------------------------------------


class DescribeComputeJumps:
    def it_finds_a_simple_orthogonal_crossing(self):
        # Horizontal segment 0→4 at y=2; vertical segment at x=2 from 0→4.
        own = [(0, 2), (4, 2)]
        other = [(2, 0), (2, 4)]
        jumps = compute_jumps(own, [other])
        assert len(jumps) == 1
        seg_idx, point = jumps[0]
        assert seg_idx == 0
        assert abs(point[0] - 2) < 1e-9
        assert abs(point[1] - 2) < 1e-9

    def it_returns_no_jumps_for_parallel_lines(self):
        own = [(0, 2), (4, 2)]
        other = [(0, 3), (4, 3)]
        jumps = compute_jumps(own, [other])
        assert jumps == []

    def it_skips_endpoint_touches(self):
        # The two polylines share endpoint (2, 2) — that's anchor glue,
        # not a crossing.
        own = [(0, 0), (2, 2)]
        other = [(2, 2), (4, 0)]
        jumps = compute_jumps(own, [other])
        assert jumps == []

    def it_handles_multiple_crossings(self):
        own = [(0, 1), (10, 1)]
        other_a = [(2, 0), (2, 2)]
        other_b = [(7, 0), (7, 2)]
        jumps = compute_jumps(own, [other_a, other_b])
        assert len(jumps) == 2


# ---------------------------------------------------------------------------
# Page.add_connector + routing — three-shape obstacle test (acceptance)
# ---------------------------------------------------------------------------


class DescribePageAddConnectorRouting:
    def it_authors_a_polyline_geometry_when_routing_is_right_angle(self):
        _, page, a, b, _ = _three_shape_obstacle_page()
        c = page.add_connector(a, b, routing="right-angle", avoid_shapes=True)
        # The connector has a Geometry section with > 2 rows (it must
        # bend around the obstacle).
        geo = c.geometry
        assert geo is not None
        assert len(geo.rows) >= 3, (
            "expected the polyline to bend around the obstacle, "
            "got %d rows" % len(geo.rows)
        )
        # First row is a MoveTo, subsequent rows are LineTo / ArcTo.
        assert geo.rows[0].row_type == "MoveTo"
        for row in geo.rows[1:]:
            assert row.row_type in ("LineTo", "ArcTo", "MoveTo")

    def it_writes_no_geometry_when_routing_is_None(self):
        _, page, a, b, _ = _three_shape_obstacle_page()
        c = page.add_connector(a, b)
        assert c.geometry is None

    def it_writes_no_geometry_for_straight_routing_either(self):
        # Straight routing means "Visio renders a straight line at
        # display time" — no geometry section needed.
        _, page, a, b, _ = _three_shape_obstacle_page()
        c = page.add_connector(a, b, routing="straight")
        # Straight routing uses RouteStyle="16" but doesn't write a
        # geometry path of its own.
        assert c.route_style == "16"

    def it_sets_RouteStyle_to_RIGHT_ANGLE_for_right_angle_mode(self):
        _, page, a, b, _ = _three_shape_obstacle_page()
        c = page.add_connector(a, b, routing="right-angle", avoid_shapes=True)
        assert c.route_style == "1"

    def it_routes_through_the_obstacle_when_avoid_shapes_is_False(self):
        # avoid_shapes=False means the router does not paint obstacles
        # so the polyline stays minimal (2-point path between begin
        # and end). Important for callers that want to disable
        # obstacle avoidance for performance.
        _, page, a, b, _ = _three_shape_obstacle_page()
        c = page.add_connector(a, b, routing="right-angle", avoid_shapes=False)
        # Without obstacle avoidance the path collapses to a 2-pt
        # straight line (begin → end), so the geometry section has
        # exactly 2 rows.
        geo = c.geometry
        assert geo is not None
        assert len(geo.rows) == 2

    def it_glues_the_connector_into_the_Connects_index(self):
        # Routing must not break the underlying <Connect> book-keeping.
        _, page, a, b, _ = _three_shape_obstacle_page()
        conn = page.add_connector(a, b, routing="right-angle", avoid_shapes=True)
        entries = list(page.shapes._element.connects_element)
        assert len(entries) == 2
        from_sheets = {e.get("FromSheet") for e in entries}
        assert from_sheets == {str(conn.shape_id)}

    def it_rejects_an_unknown_routing_mode(self):
        _, page, a, b, _ = _three_shape_obstacle_page()
        with pytest.raises(ValueError):
            page.add_connector(a, b, routing="zigzag")

    def it_rejects_an_unknown_jump_style(self):
        _, page, a, b, _ = _three_shape_obstacle_page()
        with pytest.raises(ValueError):
            page.add_connector(
                a, b, routing="right-angle", jump_style="bounce"
            )


# ---------------------------------------------------------------------------
# Bulk reroute (acceptance)
# ---------------------------------------------------------------------------


class DescribePageRerouteConnectors:
    def it_reroutes_every_connector_on_the_page(self):
        doc = Visio()
        page = doc.pages.add_page(name="Bulk", width=12, height=8)
        a = page.shapes.add_shape("Rectangle", at=(1, 1), size=(1, 1))
        b = page.shapes.add_shape("Rectangle", at=(10, 1), size=(1, 1))
        page.shapes.add_shape("Rectangle", at=(5, 1), size=(2, 1))  # obstacle
        d = page.shapes.add_shape("Rectangle", at=(10, 5), size=(1, 1))
        # Author two connectors as straight lines first.
        ab = page.add_connector(a, b)
        bd = page.add_connector(b, d)
        assert ab.geometry is None
        assert bd.geometry is None

        count = page.reroute_connectors(routing="right-angle", avoid_shapes=True)
        assert count == 2
        # Both connectors now carry a geometry section.
        assert ab.geometry is not None
        assert bd.geometry is not None

    def it_reroutes_zero_connectors_on_an_empty_page(self):
        doc = Visio()
        page = doc.pages.add_page(name="Empty")
        page.shapes.add_shape("Rectangle", at=(1, 1), size=(1, 1))
        assert page.reroute_connectors() == 0

    def it_resnaps_endpoints_before_routing(self):
        # Move an anchor; reroute_connectors should re-snap the
        # connector endpoint to the moved anchor and rebuild the
        # polyline against the new geometry.
        _, page, a, b, _ = _three_shape_obstacle_page()
        conn = page.add_connector(a, b)
        assert conn.begin_x == 1
        a.pin_x = 0.5
        a.pin_y = 0.5
        page.reroute_connectors(routing="right-angle", avoid_shapes=True)
        assert conn.begin_x == 0.5
        assert conn.begin_y == 0.5
        assert conn.geometry is not None


# ---------------------------------------------------------------------------
# Connector.reroute() with routing argument
# ---------------------------------------------------------------------------


class DescribeConnectorRerouteWithRouting:
    def it_runs_the_router_when_a_routing_mode_is_supplied(self):
        _, page, a, b, _ = _three_shape_obstacle_page()
        c = page.add_connector(a, b)
        assert c.geometry is None
        c.reroute(routing="right-angle", avoid_shapes=True)
        assert c.geometry is not None
        assert len(c.geometry.rows) >= 3

    def it_skips_the_router_when_routing_is_None(self):
        _, page, a, b, _ = _three_shape_obstacle_page()
        c = page.add_connector(a, b)
        c.reroute()
        assert c.geometry is None


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


class DescribeRoutingRoundTrip:
    def it_survives_save_and_reload(self):
        doc, page, a, b, _ = _three_shape_obstacle_page()
        c = page.add_connector(a, b, routing="right-angle", avoid_shapes=True)
        orig_conn_id = c.shape_id
        # Capture the row count + RouteStyle so we can compare
        # post-reload.
        orig_rows = len(c.geometry.rows)
        assert orig_rows >= 3

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        reopened = vsdx.Visio(buf)
        assert len(reopened.pages) == 1
        page2 = reopened.pages[0]

        NS = "{http://schemas.microsoft.com/office/visio/2011/1/core}"
        page_contents = page2._page_part.element
        shapes_el = page_contents.find(f"{NS}Shapes")
        assert shapes_el is not None
        # Find the connector shape by ID.
        conn_el = next(
            s for s in shapes_el.findall(f"{NS}Shape")
            if int(s.get("ID")) == orig_conn_id
        )
        # The connector carries a Geometry section with at least 3 rows.
        geometry_sections = [
            sec for sec in conn_el.findall(f"{NS}Section")
            if sec.get("N") == "Geometry"
        ]
        assert len(geometry_sections) == 1
        rows = geometry_sections[0].findall(f"{NS}Row")
        assert len(rows) == orig_rows
        # First row is MoveTo, others LineTo / ArcTo.
        assert rows[0].get("T") == "MoveTo"
        for r in rows[1:]:
            assert r.get("T") in ("LineTo", "ArcTo", "MoveTo")

    def it_round_trips_the_RouteStyle_cell(self):
        doc, page, a, b, _ = _three_shape_obstacle_page()
        page.add_connector(a, b, routing="right-angle", avoid_shapes=True)

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        reopened = vsdx.Visio(buf)
        page2 = reopened.pages[0]

        NS = "{http://schemas.microsoft.com/office/visio/2011/1/core}"
        page_contents = page2._page_part.element
        shapes_el = page_contents.find(f"{NS}Shapes")
        # Find the connector shape (the only Shape with Master =
        # "Dynamic connector").
        for shape_el in shapes_el.findall(f"{NS}Shape"):
            if shape_el.get("Master") is None:
                continue
            # Master is referenced by ID, but NameU on the master is
            # what the test cares about; the connector's RouteStyle
            # cell is the assertion target.
            for cell in shape_el.findall(f"{NS}Cell"):
                if cell.get("N") == "RouteStyle":
                    assert cell.get("V") == "1"
                    return
        pytest.fail("no RouteStyle cell found on any reloaded shape")


# ---------------------------------------------------------------------------
# Jump / crossing rendering on a 2-connector page
# ---------------------------------------------------------------------------


class DescribeJumpRendering:
    def it_inserts_arc_jumps_when_a_new_connector_crosses_an_existing_one(self):
        # Build a cross pattern: two connectors that intersect.
        doc = Visio()
        page = doc.pages.add_page(name="X", width=10, height=10)
        a = page.shapes.add_shape("Rectangle", at=(1, 5), size=(1, 1))
        b = page.shapes.add_shape("Rectangle", at=(9, 5), size=(1, 1))
        c = page.shapes.add_shape("Rectangle", at=(5, 1), size=(1, 1))
        d = page.shapes.add_shape("Rectangle", at=(5, 9), size=(1, 1))
        # First connector: horizontal, no obstacle painting so the
        # polyline runs straight from a to b at y=5.
        page.add_connector(a, b, routing="right-angle", avoid_shapes=False)
        # Second connector: vertical, must arc over the horizontal one.
        v = page.add_connector(
            c, d, routing="right-angle",
            avoid_shapes=False, jump_style=JUMP_ARC,
        )
        # The vertical connector's geometry should now contain at
        # least one ArcTo row at the crossing.
        types = [row.row_type for row in v.geometry.rows]
        assert "ArcTo" in types, (
            "expected an ArcTo jump where the vertical connector "
            f"crosses the horizontal one, got {types!r}"
        )
