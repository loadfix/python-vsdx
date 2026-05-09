"""Shape-related enumerations for python-vsdx.

These are lightweight string-valued enums — Visio stores shape
categorisation at the attribute level (``<Shape Type="Shape">``),
not as coded numeric ST_* values the way PresentationML does, so
we don't inherit from the docx/pptx ``BaseXmlEnum`` machinery. A
plain ``str`` subclass gives us singleton identity, equality to
literal strings, and no runtime typing overhead.
"""

from __future__ import annotations

from enum import Enum


class VS_SHAPE_TYPE(str, Enum):
    """Enumeration of built-in Visio shape kinds that vsdx 0.1.0 supports.

    Members carry the master ``NameU`` string used by the bundled master
    stencils. Comparing with ``shape.master_name_u == VS_SHAPE_TYPE.RECTANGLE``
    is intentionally legal because every member is also a plain ``str``.
    """

    RECTANGLE = "Rectangle"
    ELLIPSE = "Ellipse"
    TRIANGLE = "Triangle"
    DYNAMIC_CONNECTOR = "Dynamic connector"
    GROUP = "Group"
    FOREIGN = "Foreign"
    GUIDE = "Guide"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


class VS_CONNECTOR_STYLE(str, Enum):
    """Visio route-style choices for a ``<Cell N="RouteStyle">`` value.

    Values mirror the integer constants in Visio's ``visRouteStyle`` enum
    but are carried as strings so they survive attribute round-trip. See
    https://learn.microsoft.com/en-us/office/vba/api/visio.visroutestyle
    for the authoritative mapping.
    """

    RIGHT_ANGLE = "1"
    STRAIGHT = "2"
    CENTER_TO_CENTER = "3"
    NETWORK = "4"
    ORGANIZATION_CHART = "5"
    FLOWCHART_NORTH_SOUTH = "6"
    SIMPLE = "16"

    def __str__(self) -> str:  # pragma: no cover
        return str(self.value)


__all__ = ["VS_CONNECTOR_STYLE", "VS_SHAPE_TYPE"]
