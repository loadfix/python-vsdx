"""Cell / row / section enumerations for python-vsdx.

These map to the named-string vocabularies documented at
https://learn.microsoft.com/en-us/office/client-developer/visio/typesvisio-xml

They are carried as plain str-enums because Visio emits them as
element attribute values (``<Section N="Geometry">``, ``<Row T="LineTo">``,
``<Cell U="IN">``) with no numeric coding.
"""

from __future__ import annotations

from enum import Enum


class ST_SectionName(str, Enum):
    """Section name values documented by MS Learn.

    Subset that 0.1.0 actually emits. The full enumeration is ~30 values;
    we add more as we need them.
    """

    GEOMETRY = "Geometry"
    CHARACTER = "Character"
    PARAGRAPH = "Paragraph"
    TABS = "Tabs"
    SCRATCH = "Scratch"
    CONNECTION = "Connection"
    CONTROL = "Control"
    LAYER = "Layer"
    ACTIONS = "Actions"
    USER_DEFINED_CELLS = "User-defined Cells"
    USER = "User"
    HYPERLINK = "Hyperlink"

    def __str__(self) -> str:  # pragma: no cover
        return str(self.value)


class ST_RowType(str, Enum):
    """Row-T attribute values for ``<Section N="Geometry">`` rows.

    Each value corresponds to a geometry primitive. 0.1.0 authors only
    use ``MOVE_TO`` / ``LINE_TO`` implicitly via the built-in masters —
    we don't write custom geometry yet — but the vocabulary is here so
    parsers downstream can reason about it.
    """

    MOVE_TO = "MoveTo"
    LINE_TO = "LineTo"
    ARC_TO = "ArcTo"
    ELLIPTICAL_ARC_TO = "EllipticalArcTo"
    ELLIPSE = "Ellipse"
    INFINITE_LINE = "InfiniteLine"
    NURBS_TO = "NURBSTo"
    POLYLINE_TO = "PolylineTo"
    REL_CUBE_BEZ_TO = "RelCubBezTo"
    REL_ELLIPTICAL_ARC_TO = "RelEllipticalArcTo"
    REL_LINE_TO = "RelLineTo"
    REL_MOVE_TO = "RelMoveTo"
    REL_QUAD_BEZ_TO = "RelQuadBezTo"
    SPLINE_KNOT = "SplineKnot"
    SPLINE_START = "SplineStart"

    def __str__(self) -> str:  # pragma: no cover
        return str(self.value)


class ST_Unit(str, Enum):
    """The ``@U`` attribute's allowed values for cell units.

    Practical subset — MS Learn's Types reference lists ~40 unit
    abbreviations (``DA``, ``DP``, ``NM``…) but 99% of Visio files we've
    sampled use only the four below.
    """

    INCHES = "IN"
    MILLIMETRES = "MM"
    CENTIMETRES = "CM"
    POINTS = "PT"
    DEGREES = "DEG"
    RADIANS = "RAD"
    COLORS = "COLORS"
    NO_CAST = "NoCast"

    def __str__(self) -> str:  # pragma: no cover
        return str(self.value)


__all__ = ["ST_RowType", "ST_SectionName", "ST_Unit"]
