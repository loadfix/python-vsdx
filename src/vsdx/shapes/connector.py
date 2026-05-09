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

from typing import TYPE_CHECKING, ClassVar, Optional

from vsdx.enum.shapes import VS_CONNECTOR_STYLE, VS_SHAPE_TYPE
from vsdx.shapes.base import TextShape

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_Shape
    from vsdx.shapes.base import Shape
    from vsdx.shapes.shapetree import ShapeTree


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


__all__ = ["Connector"]
