"""Shape hierarchy for python-vsdx.

Public classes:

* :class:`ShapeTree` — the ``shapes`` collection on a :class:`~vsdx.page.Page`.
  Mirrors ``pptx.shapes.shapetree.SlideShapes``.
* :class:`Shape` — base shape, wraps a ``<Shape>`` element.
* :class:`Rectangle`, :class:`Ellipse`, :class:`Triangle` — concrete
  autoshape kinds. Each one is a thin subclass that just fixes
  ``master_name_u`` at construction time.
* :class:`Connector` — a dynamic connector wired up via ``<Connects>``.
* :class:`TextShape` — umbrella for any shape that carries text
  (which, for 0.1.0, is all of them). Exposes a ``.text_frame``
  accessor the concrete autoshapes inherit.
"""

from __future__ import annotations

from vsdx.shapes.base import Shape, TextShape
from vsdx.shapes.autoshape import Ellipse, Rectangle, Triangle
from vsdx.shapes.connector import Connector
from vsdx.shapes.group import GroupMembers, GroupShape
from vsdx.shapes.shapetree import ShapeTree

__all__ = [
    "Connector",
    "Ellipse",
    "GroupMembers",
    "GroupShape",
    "Rectangle",
    "Shape",
    "ShapeTree",
    "TextShape",
    "Triangle",
]
