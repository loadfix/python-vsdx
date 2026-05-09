"""Concrete autoshape classes — Rectangle, Ellipse, Triangle.

Each class is a thin subclass of :class:`~vsdx.shapes.base.TextShape`
that fixes the ``Master`` attribute on construction and exposes a
polymorphic ``NAME_U`` class attribute the ShapeTree uses for
``add_shape`` dispatch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from vsdx.enum.shapes import VS_SHAPE_TYPE
from vsdx.shapes.base import TextShape

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_Shape
    from vsdx.shapes.shapetree import ShapeTree


class _BuiltInAutoShape(TextShape):
    """Common super for built-in masters instantiated via ShapeTree.add_shape."""

    #: The ``NameU`` stored in the ``@Master`` attribute. Overridden by
    #: each concrete subclass to point at the bundled master.
    NAME_U: ClassVar[str] = ""

    def __init__(self, shape_element: "CT_Shape", parent: "ShapeTree") -> None:
        super().__init__(shape_element, parent)


class Rectangle(_BuiltInAutoShape):
    """The built-in Rectangle autoshape."""

    NAME_U: ClassVar[str] = VS_SHAPE_TYPE.RECTANGLE.value


class Ellipse(_BuiltInAutoShape):
    """The built-in Ellipse / Circle autoshape."""

    NAME_U: ClassVar[str] = VS_SHAPE_TYPE.ELLIPSE.value


class Triangle(_BuiltInAutoShape):
    """The built-in Triangle autoshape."""

    NAME_U: ClassVar[str] = VS_SHAPE_TYPE.TRIANGLE.value


#: Registry — mapping name-u ↔ class. ShapeTree.add_shape uses it for
#: dispatch so callers can pass either a :class:`VS_SHAPE_TYPE` member
#: (``VS_SHAPE_TYPE.RECTANGLE``) or its raw string
#: (``"Rectangle"``) and end up with the right proxy class.
AUTOSHAPE_REGISTRY: dict[str, type[_BuiltInAutoShape]] = {
    Rectangle.NAME_U: Rectangle,
    Ellipse.NAME_U: Ellipse,
    Triangle.NAME_U: Triangle,
}


def autoshape_cls_for(name_u: str) -> type[_BuiltInAutoShape]:
    """Return the autoshape subclass for *name_u*, falling back to Rectangle.

    Unknown master names still get a :class:`Rectangle` so opening an
    existing ``.vsdx`` that references a master we haven't explicitly
    modelled doesn't crash — the user gets a plain Shape-API surface.
    """
    return AUTOSHAPE_REGISTRY.get(name_u, Rectangle)


__all__ = [
    "AUTOSHAPE_REGISTRY",
    "Ellipse",
    "Rectangle",
    "Triangle",
    "autoshape_cls_for",
]
