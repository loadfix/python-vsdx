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
"""Connector auto-routing — Manhattan / right-angle pathfinding.

This module implements the opt-in :func:`compute_route` engine used by
the connector-authoring surface (:meth:`Page.add_connector` /
:meth:`Page.reroute_connectors`) when the caller asks for
``routing="right-angle"`` and obstacle avoidance.

Algorithm
---------

A standard A* search on a discretised page grid:

1. The page bounds (``page.width`` × ``page.height``, plus a fixed
   margin) are quantised at :data:`GRID_RESOLUTION` inches per cell.
2. Every shape on the page that isn't itself the connector or one of
   its two anchor shapes paints the cells under its bounding box as
   obstacles.
3. A* searches from the source-anchor cell to the target-anchor cell
   with a Manhattan-distance heuristic and four-direction movement.
   A small **turn penalty** is added on direction changes so the
   resulting path prefers long straight runs over staircases — the
   right-angle look users expect from Visio's native routing.
4. The cell sequence is collapsed to its corner waypoints, then
   prefixed and suffixed with the exact float-precision endpoint
   coordinates so the polyline meets the source / target shapes
   without on-grid quantisation artefacts.

When no obstacle-free path exists (rare — only when the source and
target are walled off by other shapes touching the page bounds), the
engine falls back to a direct three-segment Manhattan path
(start → midpoint-x → end) so the connector still renders. The
fallback never raises.

The implementation is **pure Python with no third-party dependencies**
— grids are stored as tuples of ints, the open set is a binary heap,
and no NumPy is required. Performance is dominated by grid resolution;
the default of 0.25 inch per cell yields a ~34 × 44 grid for an 8.5 ×
11 page, which an A* with turn-penalty completes in well under 50 ms
for realistic shape counts (≤ 50 obstacles).

Jump computation
----------------

When ``jump_style != "none"`` and the new connector's polyline crosses
a previously-routed connector's polyline, :func:`compute_jumps` walks
the segment list and emits a small visual hop (an :class:`ArcTo` for
``"arc"`` style, a stroke gap for ``"gap"``) at each crossing. Jumps
are inserted into the polyline by :func:`apply_route_to_connector`
before the geometry section is materialised.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import heapq
import math
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, Union

if TYPE_CHECKING:
    from vsdx.page import Page
    from vsdx.shapes.base import Shape
    from vsdx.shapes.connector import Connector


# ---------------------------------------------------------------------------
# Tunables — top-level constants so callers / tests can patch them.
# ---------------------------------------------------------------------------

#: Grid resolution in page-inches per A*-cell. 0.25" yields a 34×44
#: grid for an 8.5×11 page — small enough to bend around shapes, large
#: enough that the search completes in single-digit milliseconds.
GRID_RESOLUTION: float = 0.25

#: Margin (in inches) added around shape bounding boxes when painting
#: obstacles. Keeps connector polylines visually clear of shape
#: outlines instead of grazing them.
OBSTACLE_PADDING: float = 0.125

#: Penalty (in grid units) applied to a turn during A* expansion. A
#: nonzero penalty makes long straight runs cheaper than staircases;
#: 1.5 reproduces the "Visio prefers two right-angle bends" look.
TURN_PENALTY: float = 1.5

#: Visual hop height (inches) for ``jump_style="arc"`` crossings.
JUMP_ARC_HEIGHT: float = 0.0625

#: Half-width (inches) of the gap excised from the polyline when
#: ``jump_style="gap"`` — total gap length is twice this value.
JUMP_GAP_HALFWIDTH: float = 0.0625


# Type alias for an inch-space (x, y) coordinate.
Point = Tuple[float, float]


# Routing-mode literals. Plain strings rather than an Enum to keep the
# call site (``routing="right-angle"``) ergonomic — Enum membership
# would require an import at every author site.
ROUTING_RIGHT_ANGLE: str = "right-angle"
ROUTING_STRAIGHT: str = "straight"
ROUTING_CURVED: str = "curved"

VALID_ROUTING_MODES = frozenset(
    {ROUTING_RIGHT_ANGLE, ROUTING_STRAIGHT, ROUTING_CURVED}
)


# Jump-style literals.
JUMP_NONE: str = "none"
JUMP_ARC: str = "arc"
JUMP_GAP: str = "gap"

VALID_JUMP_STYLES = frozenset({JUMP_NONE, JUMP_ARC, JUMP_GAP})


# ---------------------------------------------------------------------------
# Bounding boxes
# ---------------------------------------------------------------------------


def _shape_bbox(shape: "Shape") -> Tuple[float, float, float, float]:
    """Return ``(left, bottom, right, top)`` of *shape* in page-inches.

    Mirrors :func:`vsdx.shapes.connector._shape_bbox` — kept here as a
    small private helper so this module doesn't reach into a sibling
    module's underscore-prefixed API.

    Falls back to a zero-size rect at the shape's pin when width /
    height aren't materialised — a degenerate shape that an author has
    half-built. Routing tolerates that without raising.
    """
    try:
        pin_x = float(shape.pin_x)
        pin_y = float(shape.pin_y)
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0, 0.0)
    w_attr = shape.width
    h_attr = shape.height
    try:
        w = float(w_attr) if w_attr is not None else 0.0
    except (TypeError, ValueError):
        w = 0.0
    try:
        h = float(h_attr) if h_attr is not None else 0.0
    except (TypeError, ValueError):
        h = 0.0
    return (pin_x - w / 2.0, pin_y - h / 2.0, pin_x + w / 2.0, pin_y + h / 2.0)


def _collect_obstacles(
    page: "Page",
    exclude: Sequence["Shape"],
) -> List[Tuple[float, float, float, float]]:
    """Collect bounding boxes of every shape on *page* not in *exclude*.

    Connector shapes (master == ``"Dynamic connector"``) are skipped
    even when not in *exclude* — connectors are routed *around*
    rectangles and ellipses, not other connectors.

    Shape identity is matched by ``shape_id`` rather than ``id()``
    because iterating ``page.shapes`` mints a fresh proxy per shape
    on every call — the proxy returned for shape ID 1 is not the
    same Python object as the proxy held by an earlier call.
    """
    from vsdx.shapes.connector import Connector

    excluded_ids: set[int] = set()
    for s in exclude:
        try:
            sid = int(s.shape_id) if s.shape_id is not None else None
        except (AttributeError, TypeError, ValueError):
            sid = None
        if sid is not None:
            excluded_ids.add(sid)
    boxes: List[Tuple[float, float, float, float]] = []
    for shape in page.shapes:
        try:
            sid = int(shape.shape_id) if shape.shape_id is not None else None
        except (AttributeError, TypeError, ValueError):
            sid = None
        if sid is not None and sid in excluded_ids:
            continue
        if isinstance(shape, Connector):
            continue
        bbox = _shape_bbox(shape)
        # Skip degenerate / zero-size obstacles — they paint nothing.
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        boxes.append(bbox)
    return boxes


# ---------------------------------------------------------------------------
# Grid construction + A* search
# ---------------------------------------------------------------------------


class _Grid:
    """Discretised page grid for A* obstacle avoidance.

    Coordinates flow inch-space → grid-space via :meth:`to_cell`;
    grid-cell → inch-space via :meth:`to_xy` (returns the cell's
    centre). Out-of-bounds coordinates are clamped.
    """

    __slots__ = (
        "cols",
        "obstacles",
        "origin_x",
        "origin_y",
        "resolution",
        "rows",
    )

    def __init__(
        self,
        origin_x: float,
        origin_y: float,
        width: float,
        height: float,
        resolution: float,
    ) -> None:
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.resolution = resolution
        # +1 so the right / top edges are reachable even when width is
        # an exact multiple of resolution.
        self.cols = max(1, int(math.ceil(width / resolution)) + 1)
        self.rows = max(1, int(math.ceil(height / resolution)) + 1)
        # Bitset would save memory but a plain set keeps the code
        # boring and is plenty fast at 30×40 = 1200 cells.
        self.obstacles: set[Tuple[int, int]] = set()

    def paint_obstacle(
        self, bbox: Tuple[float, float, float, float], padding: float = 0.0
    ) -> None:
        """Paint cells under *bbox* (with *padding* added) as obstacles."""
        left = bbox[0] - padding
        bottom = bbox[1] - padding
        right = bbox[2] + padding
        top = bbox[3] + padding
        cx0, cy0 = self._raw_cell(left, bottom)
        cx1, cy1 = self._raw_cell(right, top)
        cx0 = max(0, min(self.cols - 1, cx0))
        cy0 = max(0, min(self.rows - 1, cy0))
        cx1 = max(0, min(self.cols - 1, cx1))
        cy1 = max(0, min(self.rows - 1, cy1))
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                self.obstacles.add((cx, cy))

    def clear_cell(self, cx: int, cy: int) -> None:
        """Remove (cx, cy) from the obstacle set if present."""
        self.obstacles.discard((cx, cy))

    def _raw_cell(self, x: float, y: float) -> Tuple[int, int]:
        return (
            int(math.floor((x - self.origin_x) / self.resolution)),
            int(math.floor((y - self.origin_y) / self.resolution)),
        )

    def to_cell(self, x: float, y: float) -> Tuple[int, int]:
        """Return the grid cell containing inch-space ``(x, y)``."""
        cx, cy = self._raw_cell(x, y)
        cx = max(0, min(self.cols - 1, cx))
        cy = max(0, min(self.rows - 1, cy))
        return (cx, cy)

    def to_xy(self, cx: int, cy: int) -> Point:
        """Return the inch-space centre of cell ``(cx, cy)``."""
        return (
            self.origin_x + (cx + 0.5) * self.resolution,
            self.origin_y + (cy + 0.5) * self.resolution,
        )

    def is_blocked(self, cx: int, cy: int) -> bool:
        return (cx, cy) in self.obstacles

    def in_bounds(self, cx: int, cy: int) -> bool:
        return 0 <= cx < self.cols and 0 <= cy < self.rows


def _astar(
    grid: _Grid,
    start: Tuple[int, int],
    goal: Tuple[int, int],
    *,
    turn_penalty: float = TURN_PENALTY,
) -> Optional[List[Tuple[int, int]]]:
    """Return a cell path from *start* to *goal* on *grid*, or ``None``.

    Four-direction movement; Manhattan-distance heuristic; per-move
    cost of 1 plus *turn_penalty* on direction changes. Returns the
    cell sequence inclusive of both endpoints, or ``None`` when no
    obstacle-free path exists.
    """
    if start == goal:
        return [start]
    # Each frontier entry is (f_score, counter, cell, came_from_dir).
    # The counter breaks ties stably so heap ordering is deterministic.
    counter = 0
    open_heap: list[Tuple[float, int, Tuple[int, int], Optional[Tuple[int, int]]]] = []
    h0 = abs(start[0] - goal[0]) + abs(start[1] - goal[1])
    heapq.heappush(open_heap, (h0, counter, start, None))
    counter += 1

    came_from: dict[Tuple[int, int], Tuple[Tuple[int, int], Optional[Tuple[int, int]]]] = {}
    g_score: dict[Tuple[int, int], float] = {start: 0.0}
    closed: set[Tuple[int, int]] = set()

    deltas = ((1, 0), (-1, 0), (0, 1), (0, -1))

    while open_heap:
        _, _, current, prev_dir = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current == goal:
            return _reconstruct(came_from, start, goal)
        closed.add(current)
        cx, cy = current
        for dx, dy in deltas:
            nx, ny = cx + dx, cy + dy
            if not grid.in_bounds(nx, ny):
                continue
            if grid.is_blocked(nx, ny):
                continue
            step_cost = 1.0
            if prev_dir is not None and (dx, dy) != prev_dir:
                step_cost += turn_penalty
            tentative = g_score[current] + step_cost
            if tentative < g_score.get((nx, ny), math.inf):
                g_score[(nx, ny)] = tentative
                came_from[(nx, ny)] = (current, (dx, dy))
                h = abs(nx - goal[0]) + abs(ny - goal[1])
                heapq.heappush(
                    open_heap, (tentative + h, counter, (nx, ny), (dx, dy))
                )
                counter += 1
    return None


def _reconstruct(
    came_from: dict, start: Tuple[int, int], goal: Tuple[int, int]
) -> List[Tuple[int, int]]:
    cells = [goal]
    current = goal
    while current != start:
        prev_entry = came_from.get(current)
        if prev_entry is None:
            break
        prev, _direction = prev_entry
        cells.append(prev)
        current = prev
    cells.reverse()
    return cells


def _collapse_to_corners(cells: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Collapse a cell-by-cell path to corner cells only.

    A* yields one cell per grid step; only the cells where direction
    changes (the "corners") matter for a Manhattan polyline. Keep the
    first and last cells unconditionally so the returned sequence
    always represents the full path's endpoints.
    """
    if len(cells) <= 2:
        return list(cells)
    corners: List[Tuple[int, int]] = [cells[0]]
    for i in range(1, len(cells) - 1):
        prev = cells[i - 1]
        curr = cells[i]
        nxt = cells[i + 1]
        d1 = (curr[0] - prev[0], curr[1] - prev[1])
        d2 = (nxt[0] - curr[0], nxt[1] - curr[1])
        if d1 != d2:
            corners.append(curr)
    corners.append(cells[-1])
    return corners


# ---------------------------------------------------------------------------
# Public route computation
# ---------------------------------------------------------------------------


def compute_route(
    start: Point,
    end: Point,
    *,
    obstacles: Sequence[Tuple[float, float, float, float]] = (),
    page_width: float = 8.5,
    page_height: float = 11.0,
    routing: str = ROUTING_RIGHT_ANGLE,
    resolution: float = GRID_RESOLUTION,
) -> List[Point]:
    """Compute a polyline from *start* to *end* with the given *routing*.

    ``routing="right-angle"`` runs A* on a grid covering the page
    bounds (with a 1-inch margin on each side so the engine can route
    *around* shapes that hug the page edge); ``"straight"`` returns a
    two-point list; ``"curved"`` returns the same waypoint sequence
    as right-angle but with the corner-cells acting as control hints
    for the connector consumer to render an arc — the polyline shape
    itself is the same Manhattan path.

    Returns a list of inch-space ``(x, y)`` waypoints inclusive of
    *start* and *end*. Never raises — falls back to a three-segment
    Manhattan path when no obstacle-free route is found.

    .. versionadded:: 0.3.0
    """
    if routing not in VALID_ROUTING_MODES:
        raise ValueError(
            "routing must be one of %s, got %r"
            % (sorted(VALID_ROUTING_MODES), routing)
        )

    if routing == ROUTING_STRAIGHT:
        return [start, end]

    # Right-angle / curved paths need the obstacle grid. Pad the page
    # bounds by 1 inch so the grid wraps shapes that touch the edges.
    margin = 1.0
    origin_x = -margin
    origin_y = -margin
    width = page_width + 2 * margin
    height = page_height + 2 * margin
    grid = _Grid(origin_x, origin_y, width, height, resolution)
    for bbox in obstacles:
        grid.paint_obstacle(bbox, padding=OBSTACLE_PADDING)

    start_cell = grid.to_cell(*start)
    end_cell = grid.to_cell(*end)
    # Endpoint cells must be walkable even if they happen to land
    # inside an anchor-shape's padded obstacle (which can happen when
    # the connector glues to a centre-pin sitting inside a shape).
    grid.clear_cell(*start_cell)
    grid.clear_cell(*end_cell)

    cells = _astar(grid, start_cell, end_cell)
    if cells is None:
        return _fallback_manhattan(start, end)

    corners = _collapse_to_corners(cells)
    waypoints: List[Point] = [start]
    # Skip the first/last cell-centres — they would introduce a
    # quantisation jog at the endpoints. Use the float-precision
    # *start* / *end* directly.
    for cx, cy in corners[1:-1]:
        waypoints.append(grid.to_xy(cx, cy))
    waypoints.append(end)
    return _smooth_collinear(waypoints)


def _smooth_collinear(points: Sequence[Point]) -> List[Point]:
    """Drop interior points colinear with both neighbours.

    Cell-centre quantisation occasionally produces three collinear
    waypoints (start → first-corner → second-corner-on-same-axis).
    Strip those interior points so the emitted polyline is minimal.
    """
    if len(points) <= 2:
        return list(points)
    out: List[Point] = [points[0]]
    for i in range(1, len(points) - 1):
        prev = out[-1]
        curr = points[i]
        nxt = points[i + 1]
        # Vector cross-product zero → colinear.  Use a small tolerance
        # so float jitter from the grid centre maths doesn't keep
        # near-collinear points.
        cross = (curr[0] - prev[0]) * (nxt[1] - prev[1]) - (
            curr[1] - prev[1]
        ) * (nxt[0] - prev[0])
        if abs(cross) > 1e-9:
            out.append(curr)
    out.append(points[-1])
    return out


def _fallback_manhattan(start: Point, end: Point) -> List[Point]:
    """Return a deterministic three-segment Manhattan path.

    Used when A* fails to find an obstacle-free path — preserves the
    "right-angle" look without leaving the connector with no geometry.
    """
    sx, sy = start
    ex, ey = end
    if abs(ex - sx) < 1e-9 or abs(ey - sy) < 1e-9:
        return [start, end]
    mid_x = (sx + ex) / 2.0
    return [start, (mid_x, sy), (mid_x, ey), end]


# ---------------------------------------------------------------------------
# Jump computation
# ---------------------------------------------------------------------------


def _segments_for(points: Sequence[Point]) -> List[Tuple[Point, Point]]:
    """Yield consecutive (p, q) pairs from *points* as a segment list."""
    return [(points[i], points[i + 1]) for i in range(len(points) - 1)]


def _segment_intersection(
    a: Point, b: Point, c: Point, d: Point
) -> Optional[Point]:
    """Return the intersection point of segment ``ab`` × ``cd`` or ``None``.

    Specialised for axis-aligned segments — we only call it from
    :func:`compute_jumps` where every input segment is horizontal or
    vertical. The general-case math works for any pair.
    """
    # Solve a + t·(b - a) = c + u·(d - c), 0 ≤ t, u ≤ 1.
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    rxs = r[0] * s[1] - r[1] * s[0]
    if abs(rxs) < 1e-12:
        return None  # parallel
    qp = (c[0] - a[0], c[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / rxs
    u = (qp[0] * r[1] - qp[1] * r[0]) / rxs
    eps = 1e-9
    if t < -eps or t > 1 + eps or u < -eps or u > 1 + eps:
        return None
    return (a[0] + t * r[0], a[1] + t * r[1])


def compute_jumps(
    waypoints: Sequence[Point],
    other_polylines: Sequence[Sequence[Point]],
) -> List[Tuple[int, Point]]:
    """Find every place *waypoints* crosses any of *other_polylines*.

    Returns a list of ``(segment_index, intersection_point)`` tuples
    — *segment_index* is the index of the segment in ``waypoints``
    where the crossing lies (so callers can splice a jump into the
    polyline at the right place).

    Crossings at exact polyline endpoints are ignored — they
    represent shared anchor glue, not a true line-over-line cross.

    .. versionadded:: 0.3.0
    """
    out: List[Tuple[int, Point]] = []
    own_endpoints = {waypoints[0], waypoints[-1]}
    own_segments = _segments_for(waypoints)
    for seg_idx, (a, b) in enumerate(own_segments):
        for other in other_polylines:
            for c, d in _segments_for(other):
                point = _segment_intersection(a, b, c, d)
                if point is None:
                    continue
                # Skip touches at our own endpoints — those are
                # source / target glue, not a crossing.
                if any(
                    abs(point[0] - p[0]) < 1e-6 and abs(point[1] - p[1]) < 1e-6
                    for p in own_endpoints
                ):
                    continue
                out.append((seg_idx, point))
    return out


def insert_jumps(
    waypoints: Sequence[Point],
    jumps: Sequence[Tuple[int, Point]],
    style: str,
) -> List[Tuple[Point, Optional[float]]]:
    """Splice *jumps* into *waypoints*, returning ``(point, bow)`` tuples.

    A ``bow`` of ``None`` indicates a straight :class:`LineTo` segment;
    a non-None value indicates an :class:`ArcTo` row whose ``A`` cell
    carries the supplied bow height (positive ⇒ arc curves above the
    direction of travel). For ``style="gap"`` two adjacent waypoints
    flanking the crossing are emitted with no arc and the consumer
    breaks the geometry section into two paths via a fresh Geometry
    section — see :func:`apply_route_to_connector`.

    For ``style="none"`` *jumps* is ignored and the input polyline
    survives verbatim.

    .. versionadded:: 0.3.0
    """
    if style == JUMP_NONE or not jumps:
        return [(p, None) for p in waypoints]

    # Group jumps by segment for in-order insertion.
    by_segment: dict[int, List[Point]] = {}
    for seg_idx, point in jumps:
        by_segment.setdefault(seg_idx, []).append(point)

    out: List[Tuple[Point, Optional[float]]] = [(waypoints[0], None)]
    for seg_idx in range(len(waypoints) - 1):
        a = waypoints[seg_idx]
        b = waypoints[seg_idx + 1]
        crossings = sorted(
            by_segment.get(seg_idx, []),
            key=lambda p: (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2,
        )
        for crossing in crossings:
            if style == JUMP_ARC:
                # Insert an ArcTo bowing towards the upper / right
                # side of the segment — sign is determined by the
                # segment direction so the bow always sits "above"
                # the line of travel.
                dx = b[0] - a[0]
                dy = b[1] - a[1]
                # Unit normal (90° CCW from direction).
                length = math.hypot(dx, dy) or 1.0
                nx = -dy / length
                ny = dx / length
                bow_pt = (
                    crossing[0] + nx * JUMP_ARC_HEIGHT,
                    crossing[1] + ny * JUMP_ARC_HEIGHT,
                )
                out.append((bow_pt, JUMP_ARC_HEIGHT))
            else:
                # gap — emit two collinear points flanking the
                # crossing; the writer materialises them as separate
                # LineTo rows with no MoveTo between, but the visual
                # effect of "gap" requires the consumer's geometry
                # writer to insert a fresh MoveTo at the second point
                # (handled in apply_route_to_connector).
                dx = b[0] - a[0]
                dy = b[1] - a[1]
                length = math.hypot(dx, dy) or 1.0
                ux = dx / length
                uy = dy / length
                gap_lo = (
                    crossing[0] - ux * JUMP_GAP_HALFWIDTH,
                    crossing[1] - uy * JUMP_GAP_HALFWIDTH,
                )
                gap_hi = (
                    crossing[0] + ux * JUMP_GAP_HALFWIDTH,
                    crossing[1] + uy * JUMP_GAP_HALFWIDTH,
                )
                # Encode "gap" via a sentinel bow of -0.0 — callers
                # check for this signal and break the geometry path.
                out.append((gap_lo, None))
                out.append((gap_hi, -0.0))
        out.append((b, None))
    return out


# ---------------------------------------------------------------------------
# Geometry section materialisation on the connector shape
# ---------------------------------------------------------------------------


def apply_route_to_connector(
    connector: "Connector",
    waypoints: Sequence[Point],
    *,
    routing: str = ROUTING_RIGHT_ANGLE,
    jumps: Sequence[Tuple[int, Point]] = (),
    jump_style: str = JUMP_NONE,
) -> None:
    """Materialise *waypoints* as a Geometry section on *connector*.

    The connector's ``BeginX`` / ``EndX`` cells are also updated to the
    first / last waypoint so the connector's bounding box matches the
    rendered polyline. Removes any pre-existing Geometry sections so
    repeated reroute calls don't accumulate stale paths.

    Coordinates are written **shape-local** — Visio geometry rows are
    relative to the shape's pin frame, not page space, so we subtract
    ``(pin_x - width/2, pin_y - height/2)`` from every waypoint before
    emitting it. The connector's pin / size are sized to wrap the
    polyline's bounding box so the local coordinates stay within
    ``[0, width] × [0, height]``.

    .. versionadded:: 0.3.0
    """
    if jump_style not in VALID_JUMP_STYLES:
        raise ValueError(
            "jump_style must be one of %s, got %r"
            % (sorted(VALID_JUMP_STYLES), jump_style)
        )
    if routing not in VALID_ROUTING_MODES:
        raise ValueError(
            "routing must be one of %s, got %r"
            % (sorted(VALID_ROUTING_MODES), routing)
        )
    if len(waypoints) < 2:
        return

    # Drop existing Geometry sections so repeated reroutes don't
    # accumulate stale paths.
    shape_el = connector._element
    for section in list(shape_el.section_lst):
        if section.get("N") == "Geometry":
            shape_el.remove(section)

    # Update endpoint cells to the polyline's start / end.
    sx, sy = waypoints[0]
    ex, ey = waypoints[-1]
    connector.begin_x = sx
    connector.begin_y = sy
    connector.end_x = ex
    connector.end_y = ey

    # Set RouteStyle to match the requested routing mode so a Visio
    # reopen recognises the connector's intent.
    if routing == ROUTING_RIGHT_ANGLE:
        connector.route_style = "1"  # visRouteStyleRightAngle
    elif routing == ROUTING_STRAIGHT:
        connector.route_style = "16"  # visRouteStyleSimple (straight)
    elif routing == ROUTING_CURVED:
        connector.route_style = "1"  # right-angle baseline; arcs add curve

    # Compute the bounding box of the polyline + pin / size so local
    # coordinates stay non-negative.
    xs = [p[0] for p in waypoints]
    ys = [p[1] for p in waypoints]
    min_x = min(xs)
    min_y = min(ys)
    max_x = max(xs)
    max_y = max(ys)
    width = max(max_x - min_x, 1e-6)
    height = max(max_y - min_y, 1e-6)
    pin_x = min_x + width / 2.0
    pin_y = min_y + height / 2.0

    # Set the shape's pin and dimensions to wrap the polyline.
    from vsdx.shapes.base import _set_cell_float

    _set_cell_float(shape_el, "PinX", pin_x, "IN")
    _set_cell_float(shape_el, "PinY", pin_y, "IN")
    _set_cell_float(shape_el, "Width", width, "IN")
    _set_cell_float(shape_el, "Height", height, "IN")
    _set_cell_float(shape_el, "LocPinX", width / 2.0, "IN")
    _set_cell_float(shape_el, "LocPinY", height / 2.0, "IN")

    # Splice jumps into the polyline.
    spliced = insert_jumps(waypoints, jumps, jump_style)

    # Materialise a fresh Geometry section.
    geometry = connector.add_geometry(no_fill=True)
    # MoveTo origin — first point in shape-local coords.
    first_pt, _first_bow = spliced[0]
    fx = first_pt[0] - min_x
    fy = first_pt[1] - min_y
    geometry.move_to(fx, fy)
    prev_was_gap = False
    for point, bow in spliced[1:]:
        lx = point[0] - min_x
        ly = point[1] - min_y
        if bow is not None and bow > 0:
            # Arc-style jump.
            geometry.arc_to(lx, ly, bow=bow)
        elif bow is not None and bow == -0.0:
            # Gap-style jump second point — start a new subpath.
            geometry.move_to(lx, ly)
            prev_was_gap = True
        else:
            if prev_was_gap:
                geometry.line_to(lx, ly)
                prev_was_gap = False
            else:
                geometry.line_to(lx, ly)


# ---------------------------------------------------------------------------
# High-level page-scope route + apply
# ---------------------------------------------------------------------------


def route_connector(
    connector: "Connector",
    page: "Page",
    *,
    routing: str = ROUTING_RIGHT_ANGLE,
    avoid_shapes: bool = True,
    jump_style: str = JUMP_NONE,
    other_connectors: "Optional[Sequence[Connector]]" = None,
) -> List[Point]:
    """Compute and apply a route for *connector* on *page*.

    Returns the inch-space waypoint list as a convenience for tests
    and callers that want to introspect the path. Endpoint coordinates
    are pulled from the connector's current ``BeginX`` / ``EndX`` /
    ``BeginY`` / ``EndY`` cells — :meth:`Connector.reroute` should be
    called first when the source / target shape pins have changed.

    *avoid_shapes* controls whether other shapes' bounding boxes are
    painted as A* obstacles; passing ``False`` reduces A* to a pure
    Manhattan two-corner path between the endpoints.

    *other_connectors* carries the list of pre-existing connectors
    whose polylines should be considered for jump computation. Pass
    ``None`` (default) to scan every connector on *page* except this
    one. Pass an empty list to skip jump computation entirely (also
    happens when ``jump_style="none"``).

    .. versionadded:: 0.3.0
    """
    if connector.begin_x is None or connector.end_x is None:
        return []
    if connector.begin_y is None or connector.end_y is None:
        return []

    start = (float(connector.begin_x), float(connector.begin_y))
    end = (float(connector.end_x), float(connector.end_y))

    obstacles: List[Tuple[float, float, float, float]] = []
    if avoid_shapes and routing != ROUTING_STRAIGHT:
        anchors: List["Shape"] = []
        src = connector.source_shape
        tgt = connector.target_shape
        if src is not None:
            anchors.append(src)
        if tgt is not None:
            anchors.append(tgt)
        # Always exclude the connector itself.
        anchors.append(connector)
        obstacles = _collect_obstacles(page, anchors)

    waypoints = compute_route(
        start,
        end,
        obstacles=obstacles,
        page_width=float(page.width),
        page_height=float(page.height),
        routing=routing,
    )

    # Jump computation: only run when style is non-none and we have
    # other connectors to test against.
    jumps: List[Tuple[int, Point]] = []
    if jump_style != JUMP_NONE and routing != ROUTING_STRAIGHT:
        from vsdx.shapes.connector import Connector

        if other_connectors is None:
            others_iter: List[Connector] = []
            for shape in page.shapes:
                if isinstance(shape, Connector) and shape is not connector:
                    others_iter.append(shape)
        else:
            others_iter = list(other_connectors)
        other_polylines: List[List[Point]] = []
        for other in others_iter:
            poly = _connector_polyline(other)
            if poly is not None and len(poly) >= 2:
                other_polylines.append(poly)
        jumps = compute_jumps(waypoints, other_polylines)

    apply_route_to_connector(
        connector,
        waypoints,
        routing=routing,
        jumps=jumps,
        jump_style=jump_style,
    )
    return waypoints


def _connector_polyline(connector: "Connector") -> Optional[List[Point]]:
    """Recover the page-space polyline of *connector* from its geometry.

    Reads the connector's first :class:`Geometry` section, translating
    each ``MoveTo`` / ``LineTo`` / ``ArcTo`` row's local coordinates
    back into page-space using the connector's pin / size cells.
    Returns ``None`` when the connector has no geometry (a freshly-
    authored straight connector that hasn't been routed yet); callers
    fall back to the begin / end straight-line approximation.
    """
    geo = connector.geometry
    if geo is None:
        return None
    rows = geo.rows
    if not rows:
        return None
    # Recover the local-to-page offset. ``pin_x`` / ``pin_y`` come
    # back as :class:`Length` (a non-Optional float subclass with a
    # zero-default), so we don't need a None-guard.
    pin_x = float(connector.pin_x)
    pin_y = float(connector.pin_y)
    width = float(connector.width or 0.0)
    height = float(connector.height or 0.0)
    origin_x = pin_x - width / 2.0
    origin_y = pin_y - height / 2.0

    points: List[Point] = []
    for row in rows:
        x = row.x
        y = row.y
        if x is None or y is None:
            continue
        points.append((origin_x + float(x), origin_y + float(y)))
    return points if points else None


__all__ = [
    "GRID_RESOLUTION",
    "JUMP_ARC",
    "JUMP_GAP",
    "JUMP_NONE",
    "OBSTACLE_PADDING",
    "ROUTING_CURVED",
    "ROUTING_RIGHT_ANGLE",
    "ROUTING_STRAIGHT",
    "TURN_PENALTY",
    "VALID_JUMP_STYLES",
    "VALID_ROUTING_MODES",
    "apply_route_to_connector",
    "compute_jumps",
    "compute_route",
    "insert_jumps",
    "route_connector",
]
