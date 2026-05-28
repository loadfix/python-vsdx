"""Dynamic connector — instantiated from the built-in Dynamic-connector master.

A connector authoring call is three distinct pieces of XML:

1. A ``<Shape Master="Dynamic connector">`` on the page, with its own
   ``<Cell N="BeginX">`` / ``<Cell N="EndX">`` / ``<Cell N="BeginY">`` /
   ``<Cell N="EndY">`` geometry cells.
2. A ``<Connect>`` entry inside ``<Connects>`` wiring the connector's
   ``BeginX`` cell to the *from* shape's ``PinX``.
3. A second ``<Connect>`` entry wiring the connector's ``EndX`` cell to
   the *to* shape's ``PinX``.

All three happen inside
:meth:`vsdx.shapes.shapetree.ShapeTree.add_connector`. The
:class:`Connector` proxy class itself is just the ``<Shape>`` piece;
the ``<Connect>`` entries are stored on the page's ``<Connects>``
element and accessed via ``connector.connects``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar, Optional

from vsdx.enum.shapes import VS_CONNECTOR_STYLE, VS_SHAPE_TYPE
from vsdx.shapes.base import TextShape

if TYPE_CHECKING:
    from vsdx.connection_points import ConnectionPoint
    from vsdx.oxml._stubs import CT_Shape
    from vsdx.shapes.base import Shape
    from vsdx.shapes.shapetree import ShapeTree


# ``Connections.X<n>`` / ``Connections.Y<n>`` — the cell-name Visio writes
# on a ``<Connect>``'s ``@ToCell`` when a connector endpoint is glued to a
# specific connection point on the anchor shape. Value ``PinX`` means
# centre-pin glue instead of a numbered connection point.
_CONNECTIONS_CELL_RE = re.compile(r"^Connections\.[XY](\d+)$")


class Connector(TextShape):
    """A dynamic connector between two shapes.

    Use :meth:`ShapeTree.add_connector` to create one — direct
    instantiation is possible for tests but not the idiomatic path
    because the ``<Connect>`` entries also have to land in the page's
    ``<Connects>`` element.
    """

    NAME_U: ClassVar[str] = VS_SHAPE_TYPE.DYNAMIC_CONNECTOR.value

    def __init__(self, shape_element: "CT_Shape", parent: "ShapeTree") -> None:
        super().__init__(shape_element, parent)

    # -- endpoint coords ---------------------------------------------------

    @property
    def begin_x(self) -> Optional[float]:
        return _cell_float(self._element, "BeginX")

    @begin_x.setter
    def begin_x(self, v: float) -> None:
        _set_cell_float(self._element, "BeginX", float(v), "IN")

    @property
    def begin_y(self) -> Optional[float]:
        return _cell_float(self._element, "BeginY")

    @begin_y.setter
    def begin_y(self, v: float) -> None:
        _set_cell_float(self._element, "BeginY", float(v), "IN")

    @property
    def end_x(self) -> Optional[float]:
        return _cell_float(self._element, "EndX")

    @end_x.setter
    def end_x(self, v: float) -> None:
        _set_cell_float(self._element, "EndX", float(v), "IN")

    @property
    def end_y(self) -> Optional[float]:
        return _cell_float(self._element, "EndY")

    @end_y.setter
    def end_y(self, v: float) -> None:
        _set_cell_float(self._element, "EndY", float(v), "IN")

    @property
    def route_style(self) -> Optional[str]:
        cell = self._get_cell("RouteStyle")
        return cell.get("V") if cell is not None else None

    @route_style.setter
    def route_style(self, value: VS_CONNECTOR_STYLE | str) -> None:
        cell = self._element.get_or_add_cell("RouteStyle")
        cell.set("V", str(value))

    # -- endpoint anchoring -------------------------------------------------

    def _anchor_to(
        self,
        from_shape: "Shape",
        to_shape: "Shape",
    ) -> None:
        """Populate begin / end cells to match the two anchor shapes' pins."""
        self.begin_x = float(from_shape.pin_x)
        self.begin_y = float(from_shape.pin_y)
        self.end_x = float(to_shape.pin_x)
        self.end_y = float(to_shape.pin_y)

    # -- typed endpoint proxies --------------------------------------------

    def _find_glue_entry(self, from_cell: str):
        """Return the ``<Connect>`` entry gluing this connector's *from_cell*.

        Walks the owning page's ``<Connects>`` container and returns the
        first entry whose ``@FromSheet`` matches this connector's shape
        ID and whose ``@FromCell`` equals *from_cell* (``"BeginX"`` for
        the source endpoint, ``"EndX"`` for the target).  Returns
        ``None`` when no matching entry exists (the connector was
        authored without glue — a degenerate but legal state).
        """
        tree = self._parent
        page_contents = getattr(tree, "_element", None)
        if page_contents is None:
            return None
        connects = getattr(page_contents, "connects", None)
        if connects is None:
            return None
        my_id = str(self.shape_id)
        for entry in connects.connect_lst:
            if entry.get("FromSheet") == my_id and entry.get("FromCell") == from_cell:
                return entry
        return None

    def _resolve_glue_shape(self, from_cell: str) -> Optional["Shape"]:
        """Resolve the shape this connector's *from_cell* is glued to."""
        entry = self._find_glue_entry(from_cell)
        if entry is None:
            return None
        to_sheet = entry.get("ToSheet")
        if to_sheet is None:
            return None
        try:
            target_id = int(to_sheet)
        except ValueError:
            return None
        tree = self._parent
        # Avoid the connector proxy matching itself on some pathological
        # self-glue — the common case is a distinct anchor shape.
        for el in tree._element.shapes_element.shape_lst:
            if int(el.shape_id or 0) == target_id:
                return tree._proxy_for(el)
        return None

    def _resolve_glue_point(self, from_cell: str) -> Optional["ConnectionPoint"]:
        """Resolve the :class:`ConnectionPoint` this endpoint targets, if any.

        Returns ``None`` when the endpoint glues to the anchor shape's
        centre-pin (``ToCell="PinX"``) instead of a numbered connection
        point, or when the glue entry references a connection-point
        index that does not exist on the resolved anchor shape.
        """
        entry = self._find_glue_entry(from_cell)
        if entry is None:
            return None
        to_cell = entry.get("ToCell") or ""
        match = _CONNECTIONS_CELL_RE.match(to_cell)
        if match is None:
            return None
        # ``Connections.X<n>`` — ``<n>`` is 1-based in Visio.
        ordinal = int(match.group(1))
        shape = self._resolve_glue_shape(from_cell)
        if shape is None:
            return None
        for point in shape.connection_points:
            if point.index == ordinal:
                return point
        return None

    @property
    def source_shape(self) -> Optional["Shape"]:
        """The shape this connector's ``BeginX`` endpoint is glued to.

        Returns ``None`` for a degenerate connector authored without
        begin-side glue.

        .. versionadded:: 0.3.0
        """
        return self._resolve_glue_shape("BeginX")

    @property
    def target_shape(self) -> Optional["Shape"]:
        """The shape this connector's ``EndX`` endpoint is glued to.

        Returns ``None`` for a connector authored without end-side glue.

        .. versionadded:: 0.3.0
        """
        return self._resolve_glue_shape("EndX")

    @property
    def source_point(self) -> Optional["ConnectionPoint"]:
        """The :class:`ConnectionPoint` this connector's source is glued to, or ``None``.

        Returns ``None`` when the endpoint glues to the source shape's
        centre-pin (``ToCell="PinX"``) instead of a numbered connection
        point.

        .. versionadded:: 0.3.0
        """
        return self._resolve_glue_point("BeginX")

    @property
    def target_point(self) -> Optional["ConnectionPoint"]:
        """The :class:`ConnectionPoint` this connector's target is glued to, or ``None``.

        .. versionadded:: 0.3.0
        """
        return self._resolve_glue_point("EndX")

    # -- route recomputation ------------------------------------------------

    def reroute(
        self,
        routing: Optional[str] = None,
        avoid_shapes: bool = False,
        jump_style: str = "none",
    ) -> None:
        """Recompute the connector's endpoint coordinates from current glue.

        For the dynamic-connector default (``RouteStyle`` absent or
        ``RIGHT_ANGLE``), Visio recomputes the waypoint polyline at
        render time from the endpoint coordinates plus the target-shape
        bounding boxes — the authoring file only needs to carry the
        ``BeginX`` / ``BeginY`` / ``EndX`` / ``EndY`` cells. This method
        re-pulls those four cells from the currently-resolved source /
        target shapes (or their specific connection points, when glued
        that way).  Callers who have moved an anchor shape via
        :meth:`Shape.set_geometry` can call :meth:`reroute` to snap the
        connector to the new positions without rebuilding the
        ``<Connect>`` entries.

        Passing ``routing`` (one of ``"right-angle"``, ``"straight"``,
        ``"curved"``) additionally runs the auto-router from
        :mod:`vsdx.routing`, materialising the connector's polyline as
        a ``<Section N="Geometry">`` path. *avoid_shapes* paints other
        shapes on the page as obstacles; *jump_style* (``"arc"`` /
        ``"gap"`` / ``"none"``) controls how the new route renders
        crossings of pre-existing connector polylines.

        No-op when either endpoint is unglued.

        .. versionadded:: 0.3.0
        """
        src = self.source_shape
        tgt = self.target_shape
        src_point = self.source_point
        tgt_point = self.target_point

        if src is not None:
            if src_point is not None:
                wx, wy = _connection_point_world_xy(src, src_point)
            else:
                wx, wy = float(src.pin_x), float(src.pin_y)
            self.begin_x = wx
            self.begin_y = wy
        if tgt is not None:
            if tgt_point is not None:
                wx, wy = _connection_point_world_xy(tgt, tgt_point)
            else:
                wx, wy = float(tgt.pin_x), float(tgt.pin_y)
            self.end_x = wx
            self.end_y = wy

        if routing is not None:
            from vsdx.page import Page
            from vsdx.routing import route_connector

            tree = self._parent
            page = getattr(tree, "_parent", None)
            if isinstance(page, Page):
                route_connector(
                    self,
                    page,
                    routing=routing,
                    avoid_shapes=avoid_shapes,
                    jump_style=jump_style,
                )


# -- local copies of the base module helpers (private to this file) ---------
# Re-importing from vsdx.shapes.base would make connector look heavier in
# isolation than it is.


def _cell_float(shape_el, name):  # type: ignore[no-untyped-def]
    for cell in shape_el.cell_lst:
        if cell.get("N") == name:
            v = cell.get("V")
            if v is None or v == "":
                return None
            try:
                return float(v)
            except ValueError:
                return None
    return None


def _set_cell_float(shape_el, name, value, unit="IN"):  # type: ignore[no-untyped-def]
    cell = shape_el.get_or_add_cell(name)
    s = str(int(value)) if value == int(value) else ("%f" % value).rstrip("0").rstrip(".")
    cell.set("V", s)
    cell.set("U", unit)


def _connection_point_world_xy(
    shape: "Shape", point: "ConnectionPoint"
) -> tuple[float, float]:
    """Return the page-space (x, y) of *point* on *shape*, in inches.

    Connection-point coordinates are stored in the shape's local frame.
    This helper maps them to page coordinates using the simple Visio
    default: the shape's pin is its local centre (``LocPinX = Width/2``
    / ``LocPinY = Height/2``) and shape rotation is zero.  R14 does not
    honour non-centre ``LocPinX/Y`` or non-zero ``Angle``; those are a
    follow-up when rotation lands on the authoring surface.
    """
    lx = point.x or 0.0
    ly = point.y or 0.0
    w = float(shape.width) or 0.0
    h = float(shape.height) or 0.0
    origin_x = float(shape.pin_x) - w / 2.0
    origin_y = float(shape.pin_y) - h / 2.0
    return origin_x + lx, origin_y + ly


def _shape_bbox(shape: "Shape") -> tuple[float, float, float, float]:
    """Return *(left, bottom, right, top)* of *shape* in page-inches.

    Approximation matches :func:`_connection_point_world_xy` — the pin
    is assumed centred and rotation zero.  Used by :meth:`Page.connect`
    to score candidate connection points for nearest-edge selection.
    """
    pin_x = float(shape.pin_x)
    pin_y = float(shape.pin_y)
    w = float(shape.width) or 0.0
    h = float(shape.height) or 0.0
    return pin_x - w / 2.0, pin_y - h / 2.0, pin_x + w / 2.0, pin_y + h / 2.0


__all__ = ["Connector"]
