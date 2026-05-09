"""``ShapeTree`` — the ``shapes`` collection on a :class:`~vsdx.page.Page`.

Mirrors ``pptx.shapes.shapetree.SlideShapes`` in shape and spirit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, Optional, Union

from vsdx.enum.shapes import VS_SHAPE_TYPE
from vsdx.shapes.autoshape import (
    AUTOSHAPE_REGISTRY,
    Ellipse,
    Rectangle,
    Triangle,
    _BuiltInAutoShape,
    autoshape_cls_for,
)
from vsdx.shapes.base import Shape, TextShape
from vsdx.shapes.connector import Connector
from vsdx.shared import ParentedElementProxy

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_PageContents, CT_Shape  # TODO(vsdx/track-1)
    from vsdx.page import Page


# Coordinate-tuple type for ``at=`` / ``size=`` keyword arguments.
PointLike = Union[tuple[float, float], tuple[int, int]]


class ShapeTree(ParentedElementProxy):
    """Collection of shapes on a page.

    Iteration yields :class:`Shape` proxies in document order. Add
    shapes via :meth:`add_shape` / :meth:`add_connector` /
    :meth:`add_shape_from_master`.
    """

    _element: "CT_PageContents"

    def __init__(self, page_contents: "CT_PageContents", parent: "Page") -> None:
        super().__init__(page_contents, parent)

    # -- container ------------------------------------------------------

    def __iter__(self) -> Iterator[Shape]:
        for el in self._element.shapes_element.shape_lst:
            yield self._proxy_for(el)

    def __len__(self) -> int:
        return len(self._element.shapes_element.shape_lst)

    def __getitem__(self, idx: int) -> Shape:
        return self._proxy_for(self._element.shapes_element.shape_lst[idx])

    # -- authoring ------------------------------------------------------

    def add_shape(
        self,
        shape_type: Union[VS_SHAPE_TYPE, str],
        at: PointLike = (0.0, 0.0),
        size: PointLike = (1.0, 1.0),
        text: Optional[str] = None,
    ) -> _BuiltInAutoShape:
        """Add a built-in autoshape and return its proxy.

        :param shape_type: Either a :class:`VS_SHAPE_TYPE` member or the
            raw NameU string of a built-in master (``"Rectangle"``,
            ``"Ellipse"``, ``"Triangle"``).
        :param at: ``(pin_x, pin_y)`` tuple in inches — the shape's
            centre-pin position.
        :param size: ``(width, height)`` tuple in inches.
        :param text: optional initial text content.
        """
        name_u = shape_type.value if isinstance(shape_type, VS_SHAPE_TYPE) else str(shape_type)
        shape_el = self._element.shapes_element.add_shape(master_name_u=name_u)

        # Allocate a shape ID via the owning page.
        page = self._parent
        shape_el.shape_id = page.next_shape_id()

        cls = autoshape_cls_for(name_u)
        proxy: _BuiltInAutoShape = cls(shape_el, self)
        pin_x, pin_y = float(at[0]), float(at[1])
        w, h = float(size[0]), float(size[1])
        proxy.set_geometry(pin_x, pin_y, w, h)
        if text is not None:
            proxy.text = text
        return proxy

    def add_shape_from_master(
        self,
        master_name_u: str,
        at: PointLike = (0.0, 0.0),
        size: Optional[PointLike] = None,
    ) -> Shape:
        """Add a shape that references an arbitrary master by NameU.

        The master must already exist in the document's masters
        collection — use ``doc.masters.add_master(name_u)`` first if
        it's not one of the built-ins.
        """
        shape_el = self._element.shapes_element.add_shape(master_name_u=master_name_u)
        page = self._parent
        shape_el.shape_id = page.next_shape_id()

        proxy = TextShape(shape_el, self)
        pin_x, pin_y = float(at[0]), float(at[1])
        proxy.pin_x = pin_x
        proxy.pin_y = pin_y
        if size is not None:
            proxy.width = float(size[0])
            proxy.height = float(size[1])
        return proxy

    def add_connector(
        self,
        from_shape: Shape,
        to_shape: Shape,
    ) -> Connector:
        """Add a dynamic connector between *from_shape* and *to_shape*.

        Creates the connector ``<Shape>`` on the page, sets its
        ``BeginX`` / ``EndX`` / ``BeginY`` / ``EndY`` cells to the two
        anchor-shape pins, and adds two ``<Connect>`` entries to the
        page's ``<Connects>`` element.
        """
        shape_el = self._element.shapes_element.add_shape(
            master_name_u=VS_SHAPE_TYPE.DYNAMIC_CONNECTOR.value
        )
        page = self._parent
        shape_el.shape_id = page.next_shape_id()

        conn = Connector(shape_el, self)
        conn._anchor_to(from_shape, to_shape)

        connects = self._element.connects_element
        connects.add_connect(
            from_sheet=str(conn.shape_id),
            to_sheet=str(from_shape.shape_id),
            from_cell="BeginX",
            to_cell="PinX",
        )
        connects.add_connect(
            from_sheet=str(conn.shape_id),
            to_sheet=str(to_shape.shape_id),
            from_cell="EndX",
            to_cell="PinX",
        )
        return conn

    # -- helpers --------------------------------------------------------

    def _proxy_for(self, shape_el: "CT_Shape") -> Shape:
        """Return the best-fit :class:`Shape` proxy subclass for *shape_el*."""
        name_u = shape_el.get("Master") or ""
        if name_u == VS_SHAPE_TYPE.DYNAMIC_CONNECTOR.value:
            return Connector(shape_el, self)
        if name_u in AUTOSHAPE_REGISTRY:
            return AUTOSHAPE_REGISTRY[name_u](shape_el, self)
        return TextShape(shape_el, self)


__all__ = ["ShapeTree"]
