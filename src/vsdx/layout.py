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
"""Auto-layout algorithms for :class:`vsdx.page.Page`.

Four pure-Python layout kinds are exposed via
:meth:`vsdx.page.Page.layout`:

* ``"hierarchy"`` — Reingold-Tilford-style tidy tree layout. Roots are
  the shapes with no incoming connector edge; descendants are placed
  level-by-level along *direction*, with siblings spaced by *spacing*
  on the cross axis. Multiple disjoint trees are stacked side by side
  on the cross axis with one *spacing* gap between forests.
* ``"grid"`` — equal-cell grid in row-major order. *cols* selects the
  column count (default ``ceil(sqrt(n))``) and *spacing* the inter-cell
  gap. The cell size is the maximum shape extent on each axis.
* ``"radial"`` — concentric rings around *center_shape*. Distance from
  the centre is graph distance (BFS over the connector edges, treated
  as undirected). Ring ``k`` carries every shape at distance ``k`` and
  is laid out evenly around a circle of radius ``k * spacing``.
* ``"force-directed"`` — Fruchterman-Reingold spring embedder. Repulsion
  scales with *repulsion*; attraction acts along connector edges. After
  *iterations* steps the temperature decays linearly to zero so the
  final positions stabilise rather than oscillating.

After every kind the shapes' ``PinX`` / ``PinY`` cells are mutated in
place; connector endpoints are *not* rewritten directly because the
existing :meth:`vsdx.shapes.connector.Connector.reroute` call (invoked
by ``page.recompute()`` or by Visio desktop on open) re-pulls them from
the anchor shapes' new pins. For agents authoring a clean ``.vsdx``,
calling :meth:`Connector.reroute` after layout keeps the saved
``Begin* / End*`` cells consistent with the laid-out positions.

Decision tree
-------------

::

    Are shapes already connected by connectors?
    ├── No  → "grid"      (no edges; pure visual organisation)
    └── Yes
        ├── One root, tree-shaped (no cycles, every node ≤ 1 parent)?
        │       → "hierarchy"
        ├── One central hub with everything else attached to it?
        │       → "radial" (pass center_shape=hub)
        └── Otherwise (general graph, possibly cyclic / disconnected)
                → "force-directed"

Layouts are deterministic for a fixed input — the force-directed kind
seeds its position grid from shape order, not :mod:`random`, so two
agents calling ``page.layout("force-directed")`` on the same page see
the same result.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
)

if TYPE_CHECKING:
    from vsdx.page import Page
    from vsdx.shapes.base import Shape
    from vsdx.shapes.connector import Connector


# Layout-kind identifiers — keep in sync with the dispatch table at the
# bottom of this module and the ``LAYOUT_KINDS`` re-export.
LAYOUT_KIND_HIERARCHY = "hierarchy"
LAYOUT_KIND_GRID = "grid"
LAYOUT_KIND_RADIAL = "radial"
LAYOUT_KIND_FORCE_DIRECTED = "force-directed"

LAYOUT_KINDS: Tuple[str, ...] = (
    LAYOUT_KIND_HIERARCHY,
    LAYOUT_KIND_GRID,
    LAYOUT_KIND_RADIAL,
    LAYOUT_KIND_FORCE_DIRECTED,
)

# Hierarchy direction tokens. ``Page.layout(direction=...)`` accepts any
# of these spellings; the renderer converts them into per-axis sign /
# axis-mapping internally.
_HIERARCHY_DIRECTIONS: Tuple[str, ...] = (
    "top-to-bottom",
    "bottom-to-top",
    "left-to-right",
    "right-to-left",
)


@dataclass(frozen=True)
class LayoutReport:
    """Introspection record returned by :meth:`vsdx.page.Page.layout`.

    Attributes:

    * ``shapes_moved`` — number of non-connector shapes whose ``PinX``
      or ``PinY`` actually changed (delta > 1e-6 in either axis).
    * ``layout_kind`` — the *kind* string the layout call dispatched on.
    * ``bounding_box`` — ``(min_x, min_y, max_x, max_y)`` of the post-
      layout positions, computed over the centre-pins of every laid-
      out shape. ``(0.0, 0.0, 0.0, 0.0)`` when the page had no shapes.
    * ``iterations`` — for ``"force-directed"``, the actual iteration
      count run; ``0`` for the analytic kinds (hierarchy / grid /
      radial). Useful for tests asserting convergence.

    .. versionadded:: 0.4.0
    """

    shapes_moved: int
    layout_kind: str
    bounding_box: Tuple[float, float, float, float]
    iterations: int = 0


# ---------------------------------------------------------------------------
# Public driver
# ---------------------------------------------------------------------------


def layout(
    page: "Page",
    kind: str,
    *,
    direction: str = "top-to-bottom",
    spacing: float = 1.0,
    cols: Optional[int] = None,
    center_shape: "Optional[Shape]" = None,
    iterations: int = 100,
    repulsion: float = 1000.0,
    origin: Tuple[float, float] = (1.0, 1.0),
) -> LayoutReport:
    """Run an auto-layout pass over the non-connector shapes on *page*.

    See the module docstring for the *kind* decision tree. Connector
    shapes (``Master="Dynamic connector"``) are skipped — their
    endpoints follow the anchor shapes via the existing glue.

    .. versionadded:: 0.4.0
    """
    if kind not in LAYOUT_KINDS:
        raise ValueError(
            "unknown layout kind %r (expected one of %s)"
            % (kind, ", ".join(LAYOUT_KINDS))
        )

    nodes = _node_shapes(page)
    if not nodes:
        return LayoutReport(
            shapes_moved=0,
            layout_kind=kind,
            bounding_box=(0.0, 0.0, 0.0, 0.0),
            iterations=0,
        )

    # Snapshot incoming positions so we can compute ``shapes_moved`` and
    # — for kinds that no-op on a single-node page — return early without
    # mutating attribute state.
    before: Dict[int, Tuple[float, float]] = {
        id(s): (float(s.pin_x), float(s.pin_y)) for s in nodes
    }

    iters_run = 0
    if kind == LAYOUT_KIND_HIERARCHY:
        _layout_hierarchy(
            nodes,
            page=page,
            direction=direction,
            spacing=float(spacing),
            origin=origin,
        )
    elif kind == LAYOUT_KIND_GRID:
        _layout_grid(
            nodes,
            cols=cols,
            spacing=float(spacing),
            origin=origin,
        )
    elif kind == LAYOUT_KIND_RADIAL:
        _layout_radial(
            nodes,
            page=page,
            center_shape=center_shape,
            spacing=float(spacing),
            origin=origin,
        )
    else:  # force-directed
        iters_run = _layout_force_directed(
            nodes,
            page=page,
            iterations=int(iterations),
            repulsion=float(repulsion),
            spacing=float(spacing),
            origin=origin,
        )

    moved = 0
    min_x = math.inf
    min_y = math.inf
    max_x = -math.inf
    max_y = -math.inf
    for s in nodes:
        px, py = float(s.pin_x), float(s.pin_y)
        bx, by = before[id(s)]
        if abs(px - bx) > 1e-6 or abs(py - by) > 1e-6:
            moved += 1
        if px < min_x:
            min_x = px
        if py < min_y:
            min_y = py
        if px > max_x:
            max_x = px
        if py > max_y:
            max_y = py
    bbox = (min_x, min_y, max_x, max_y)

    return LayoutReport(
        shapes_moved=moved,
        layout_kind=kind,
        bounding_box=bbox,
        iterations=iters_run,
    )


# ---------------------------------------------------------------------------
# Shape / edge enumeration
# ---------------------------------------------------------------------------


def _node_shapes(page: "Page") -> "List[Shape]":
    """Top-level non-connector shapes on *page*, in document order."""
    from vsdx.shapes.connector import Connector

    out: "List[Shape]" = []
    for shape in page.shapes:
        if isinstance(shape, Connector):
            continue
        out.append(shape)
    return out


def _connector_shapes(page: "Page") -> "List[Connector]":
    from vsdx.shapes.connector import Connector

    return [s for s in page.shapes if isinstance(s, Connector)]


def _edge_pairs(
    page: "Page", nodes: "Sequence[Shape]"
) -> List[Tuple[int, int]]:
    """Return ``(source_idx, target_idx)`` pairs for every glued connector.

    Indices are positions in *nodes*; connectors whose source / target
    shape is missing from *nodes* (e.g. glued to a connector or to a
    nested-group child) are silently skipped.
    """
    by_id: Dict[int, int] = {
        s.shape_id: i for i, s in enumerate(nodes) if s.shape_id is not None
    }
    edges: List[Tuple[int, int]] = []
    for conn in _connector_shapes(page):
        src = conn.source_shape
        tgt = conn.target_shape
        if src is None or tgt is None:
            continue
        si = by_id.get(src.shape_id)
        ti = by_id.get(tgt.shape_id)
        if si is None or ti is None or si == ti:
            continue
        edges.append((si, ti))
    return edges


# ---------------------------------------------------------------------------
# Hierarchy (Reingold-Tilford-lite)
# ---------------------------------------------------------------------------


def _hierarchy_visit(
    node: int,
    depth: int,
    children: List[List[int]],
    visited: set,
    slots: List[Tuple[int, int, int]],
    cross_counter: List[int],
) -> int:
    """Place *node* (and its subtree) into *slots*, returning its cross-coord.

    Helper for :func:`_layout_hierarchy`. Lifted out of an enclosing
    function so the closure does not capture the per-tree ``slots`` /
    ``cross_counter`` from a loop variable (a common ruff B023 trap).
    """
    if node in visited:
        # Cycle — emit nothing for this branch.
        return cross_counter[0]
    visited.add(node)
    kids = [c for c in children[node] if c not in visited]
    if not kids:
        col = cross_counter[0]
        cross_counter[0] += 1
        slots.append((node, depth, col))
        return col
    child_cols = [
        _hierarchy_visit(c, depth + 1, children, visited, slots, cross_counter)
        for c in kids
    ]
    # Centre this node above its children.
    col = (child_cols[0] + child_cols[-1]) // 2
    slots.append((node, depth, col))
    return col


def _layout_hierarchy(
    nodes: "Sequence[Shape]",
    *,
    page: "Page",
    direction: str,
    spacing: float,
    origin: Tuple[float, float],
) -> None:
    """Tidy-tree layout based on connector parent / child edges.

    Roots are nodes with no incoming edge (or — when the graph is a
    pure cycle — the first node in document order). Multiple disjoint
    trees are stacked side-by-side on the cross axis; nodes that are
    not reachable from any root are appended after the last tree as a
    single column so they still receive a position.
    """
    if direction not in _HIERARCHY_DIRECTIONS:
        raise ValueError(
            "unknown hierarchy direction %r (expected one of %s)"
            % (direction, ", ".join(_HIERARCHY_DIRECTIONS))
        )
    edges = _edge_pairs(page, nodes)
    n = len(nodes)
    children: List[List[int]] = [[] for _ in range(n)]
    indegree = [0] * n
    seen_edges: set = set()
    for s, t in edges:
        if (s, t) in seen_edges:
            continue
        seen_edges.add((s, t))
        children[s].append(t)
        indegree[t] += 1

    # Roots: indegree == 0. If every node has indegree >= 1 (pure cycle),
    # break the cycle by promoting node 0.
    roots = [i for i, d in enumerate(indegree) if d == 0]
    if not roots:
        roots = [0]

    # ``visited`` tracks already-placed nodes so we can detect /
    # truncate cycles when descending. A child seen on a deeper recursion
    # is dropped silently rather than spinning forever.
    visited: set = set()

    # Per-tree layout: for each root, compute (depth, cross-coordinate)
    # for every reachable descendant. ``cross`` slots are integer ranks
    # within the tree; we stretch by *spacing* later.
    tree_assignments: List[List[Tuple[int, int, int]]] = []  # [(idx, depth, cross)]
    next_cross_total = 0
    for root in roots:
        if root in visited:
            continue
        slots: List[Tuple[int, int, int]] = []
        cross_counter = [next_cross_total]
        _hierarchy_visit(
            root, 0, children, visited, slots, cross_counter
        )
        tree_assignments.append(slots)
        # Add a one-slot gap between forests on the cross axis.
        next_cross_total = cross_counter[0] + 1

    # Sweep up any nodes that weren't reachable from a root (e.g. nodes
    # only appearing as targets of every edge they touch in a cycle).
    leftover_depth = 0
    for i in range(n):
        if i not in visited:
            tree_assignments.append([(i, leftover_depth, next_cross_total)])
            visited.add(i)
            leftover_depth += 1
            # Keep all leftovers on the same cross slot; they stack on
            # the depth axis — better than overlapping in one cell.

    # Resolve direction → per-axis layout.
    ox, oy = origin
    for slots in tree_assignments:
        for idx, depth, cross in slots:
            if direction == "top-to-bottom":
                px = ox + cross * spacing
                py = oy + depth * spacing
            elif direction == "bottom-to-top":
                px = ox + cross * spacing
                py = oy - depth * spacing
            elif direction == "left-to-right":
                px = ox + depth * spacing
                py = oy + cross * spacing
            else:  # right-to-left
                px = ox - depth * spacing
                py = oy + cross * spacing
            shape = nodes[idx]
            shape.pin_x = px
            shape.pin_y = py


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------


def _layout_grid(
    nodes: "Sequence[Shape]",
    *,
    cols: Optional[int],
    spacing: float,
    origin: Tuple[float, float],
) -> None:
    """Equal-cell grid in row-major order over *nodes*.

    ``cols`` defaults to ``ceil(sqrt(n))`` so the resulting grid is as
    square as the count allows. The cell size is the maximum shape
    extent on each axis plus *spacing* on both axes — this keeps cells
    proportional to the largest shape rather than collapsing tiny
    shapes into a tight cluster while letting big shapes overlap.
    """
    n = len(nodes)
    if cols is None or cols <= 0:
        cols_resolved = max(1, math.ceil(math.sqrt(n)))
    else:
        cols_resolved = int(cols)

    # Cell size scales with the widest / tallest shape on the page.
    cell_w = 0.0
    cell_h = 0.0
    for s in nodes:
        w = float(s.width) or 0.0
        h = float(s.height) or 0.0
        if w > cell_w:
            cell_w = w
        if h > cell_h:
            cell_h = h
    # If every shape was zero-sized, fall back to the spacing alone.
    cell_w = (cell_w if cell_w > 0 else 1.0) + spacing
    cell_h = (cell_h if cell_h > 0 else 1.0) + spacing

    ox, oy = origin
    for i, shape in enumerate(nodes):
        row, col = divmod(i, cols_resolved)
        shape.pin_x = ox + col * cell_w
        shape.pin_y = oy + row * cell_h


# ---------------------------------------------------------------------------
# Radial
# ---------------------------------------------------------------------------


def _layout_radial(
    nodes: "Sequence[Shape]",
    *,
    page: "Page",
    center_shape: "Optional[Shape]",
    spacing: float,
    origin: Tuple[float, float],
) -> None:
    """Concentric-ring layout around *center_shape*.

    BFS distance over the undirected connector graph determines the
    ring index; ring ``k`` is at radius ``k * spacing`` from the centre.
    Nodes unreachable from the centre form an outermost catch-all ring
    so every shape still gets a position.
    """
    n = len(nodes)
    if n == 0:
        return

    # Resolve centre — first explicit, otherwise the highest-degree node,
    # otherwise document-order node 0.  Match by element identity so a
    # shape that happens to share a ``shape_id`` with one on a different
    # page is correctly rejected.
    if center_shape is not None:
        center_idx = -1
        target_el = getattr(center_shape, "_element", None)
        for i, s in enumerate(nodes):
            if getattr(s, "_element", None) is target_el:
                center_idx = i
                break
        if center_idx == -1:
            raise ValueError(
                "center_shape is not on this page (shape_id=%r)"
                % getattr(center_shape, "shape_id", None)
            )
    else:
        edges = _edge_pairs(page, nodes)
        degree = [0] * n
        for s, t in edges:
            degree[s] += 1
            degree[t] += 1
        if any(d > 0 for d in degree):
            center_idx = max(range(n), key=lambda i: degree[i])
        else:
            center_idx = 0

    edges = _edge_pairs(page, nodes)
    adj: List[List[int]] = [[] for _ in range(n)]
    for s, t in edges:
        adj[s].append(t)
        adj[t].append(s)

    # BFS distances from the centre. ``-1`` for unreachable.
    dist = [-1] * n
    dist[center_idx] = 0
    frontier = [center_idx]
    while frontier:
        next_frontier: List[int] = []
        for u in frontier:
            for v in adj[u]:
                if dist[v] == -1:
                    dist[v] = dist[u] + 1
                    next_frontier.append(v)
        frontier = next_frontier

    # Group nodes per ring (preserving document order within a ring).
    rings: Dict[int, List[int]] = {}
    unreachable: List[int] = []
    for i in range(n):
        if dist[i] == -1:
            unreachable.append(i)
        else:
            rings.setdefault(dist[i], []).append(i)
    max_known = max(rings) if rings else 0
    if unreachable:
        rings[max_known + 1] = unreachable

    cx, cy = origin
    # The centre node sits exactly on (cx, cy).
    ring_keys = sorted(rings)
    for ring_idx in ring_keys:
        members = rings[ring_idx]
        if ring_idx == 0:
            # Centre node — single member, by construction.
            for i in members:
                nodes[i].pin_x = cx
                nodes[i].pin_y = cy
            continue
        radius = ring_idx * spacing
        count = len(members)
        for k, i in enumerate(members):
            theta = 2.0 * math.pi * k / count
            nodes[i].pin_x = cx + radius * math.cos(theta)
            nodes[i].pin_y = cy + radius * math.sin(theta)


# ---------------------------------------------------------------------------
# Force-directed (Fruchterman-Reingold)
# ---------------------------------------------------------------------------


def _layout_force_directed(
    nodes: "Sequence[Shape]",
    *,
    page: "Page",
    iterations: int,
    repulsion: float,
    spacing: float,
    origin: Tuple[float, float],
) -> int:
    """Fruchterman-Reingold spring embedder.

    The frame is a square of side ``L = spacing * sqrt(n)``; the
    optimal edge length ``k`` derives from ``sqrt(area / n)`` scaled by
    *spacing* so callers passing ``spacing=2`` get edges roughly twice
    as long. Repulsion is the standard ``k**2 / d`` decay multiplied by
    *repulsion* / 1000 so a caller can boost or dampen the spread
    without rewriting the formula.

    Initial positions are deterministic — node ``i`` starts on a
    Fibonacci-spiral grid scaled to the frame so two runs over the
    same shape order converge to the same final layout. Returns the
    iteration count actually run (capped at *iterations*).
    """
    n = len(nodes)
    if n == 0:
        return 0
    if n == 1:
        nodes[0].pin_x = origin[0]
        nodes[0].pin_y = origin[1]
        return 0

    edges = _edge_pairs(page, nodes)
    # De-duplicate undirected edges so a bidirectional pair only counts
    # once when computing spring forces.
    undirected: set = set()
    for s, t in edges:
        a, b = (s, t) if s < t else (t, s)
        undirected.add((a, b))

    L = max(1.0, float(spacing) * math.sqrt(n))
    area = L * L
    k = math.sqrt(area / n)
    repulsion_scale = float(repulsion) / 1000.0

    # Deterministic initial placement: Fibonacci-spiral within the frame.
    # Pure ``random.random()`` would also work but would require a seed
    # spec for repeatability; the spiral is simpler and equally effective
    # at avoiding the degenerate "everything on one row" start.
    golden = math.pi * (3.0 - math.sqrt(5.0))
    pos: List[List[float]] = []
    for i in range(n):
        # Spread points on a unit disk, then scale to half-frame.
        r = math.sqrt((i + 0.5) / n)
        theta = i * golden
        pos.append([0.5 * L * r * math.cos(theta), 0.5 * L * r * math.sin(theta)])

    iterations_run = 0
    if iterations <= 0:
        # Caller asked for zero iterations — still snap to the spiral so
        # ``shapes_moved`` reflects a deliberate placement.
        ox, oy = origin
        for i in range(n):
            nodes[i].pin_x = ox + pos[i][0]
            nodes[i].pin_y = oy + pos[i][1]
        return 0

    # Initial temperature: 10% of the frame side. Cools linearly to ~0
    # by the last iteration so late perturbations are sub-pixel.
    t0 = L / 10.0

    for step in range(iterations):
        iterations_run += 1
        disp = [[0.0, 0.0] for _ in range(n)]

        # Repulsive forces — every pair.
        for i in range(n):
            for j in range(i + 1, n):
                dx = pos[i][0] - pos[j][0]
                dy = pos[i][1] - pos[j][1]
                d2 = dx * dx + dy * dy
                if d2 < 1e-9:
                    # Coincident points — nudge apart deterministically.
                    dx = (i - j) * 1e-3
                    dy = (j - i) * 1e-3
                    d2 = dx * dx + dy * dy
                d = math.sqrt(d2)
                force = repulsion_scale * (k * k) / d
                fx = (dx / d) * force
                fy = (dy / d) * force
                disp[i][0] += fx
                disp[i][1] += fy
                disp[j][0] -= fx
                disp[j][1] -= fy

        # Attractive forces — edges only.
        for s, target in undirected:
            dx = pos[s][0] - pos[target][0]
            dy = pos[s][1] - pos[target][1]
            d = math.sqrt(dx * dx + dy * dy)
            if d < 1e-9:
                continue
            force = (d * d) / k
            fx = (dx / d) * force
            fy = (dy / d) * force
            disp[s][0] -= fx
            disp[s][1] -= fy
            disp[target][0] += fx
            disp[target][1] += fy

        # Cool: linear decay from t0 to ~0.
        temp = t0 * (1.0 - step / max(1, iterations))

        for i in range(n):
            dx, dy = disp[i]
            d = math.sqrt(dx * dx + dy * dy)
            if d < 1e-9:
                continue
            scale = min(d, temp) / d
            pos[i][0] += dx * scale
            pos[i][1] += dy * scale
            # Clamp to frame so a single high-energy node can't bolt
            # off-page mid-anneal.
            half = L
            if pos[i][0] < -half:
                pos[i][0] = -half
            elif pos[i][0] > half:
                pos[i][0] = half
            if pos[i][1] < -half:
                pos[i][1] = -half
            elif pos[i][1] > half:
                pos[i][1] = half

    ox, oy = origin
    # Translate so the bounding box sits with its min-corner at *origin*.
    min_x = min(p[0] for p in pos)
    min_y = min(p[1] for p in pos)
    for i in range(n):
        nodes[i].pin_x = ox + pos[i][0] - min_x
        nodes[i].pin_y = oy + pos[i][1] - min_y

    return iterations_run


__all__ = [
    "LAYOUT_KIND_FORCE_DIRECTED",
    "LAYOUT_KIND_GRID",
    "LAYOUT_KIND_HIERARCHY",
    "LAYOUT_KIND_RADIAL",
    "LAYOUT_KINDS",
    "LayoutReport",
    "layout",
]
