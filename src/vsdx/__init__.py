"""python-vsdx — create and update Microsoft Visio (.vsdx) files.

A fourth parent library in the loadfix OOXML family, anchored on the
existing shared-package stack (`python-ooxml-opc`,
`python-ooxml-xmlchemy`). Unlike docx / pptx / xlsx, Visio's schema is
not ECMA-standardised — the authoritative source is Microsoft Learn's
``http://schemas.microsoft.com/office/visio/2011/1/core`` namespace.

Public entry point is :func:`Visio`. Document / page / shape / master
/ text proxy classes are exposed via their submodules. The ``oxml``
layer (``CT_*`` element classes) is re-exported via :mod:`vsdx.oxml`
and the ``constants`` module exposes the content-type / relationship-
type / namespace identifiers the packaging layer needs.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from vsdx.api import Stencil, Template, Visio, VisioPackageOpener
from vsdx.connection_points import (
    CONNECTION_TYPE,
    ConnectionPoint,
    ConnectionPoints,
)
from vsdx.data_graphics import DataGraphic, DataGraphicItem, DataGraphics
from vsdx.data_recordsets import (
    DataBinding,
    DataColumn,
    DataRecordset,
    DataRecordsets,
    DataRow,
)
from vsdx.constants import (
    CT_VSDX_DRAWING_MAIN,
    CT_VSDX_MACRO_DRAWING_MAIN,
    CT_VSDX_MACRO_STENCIL_MAIN,
    CT_VSDX_MACRO_TEMPLATE_MAIN,
    CT_VSDX_MASTER,
    CT_VSDX_MASTERS,
    CT_VSDX_PAGE,
    CT_VSDX_PAGES,
    CT_VSDX_STENCIL_MAIN,
    CT_VSDX_TEMPLATE_MAIN,
    CT_VSDX_WINDOWS,
    NS_R,
    NS_VSDX_CORE,
    RT_VISIO_DOCUMENT,
    RT_VISIO_MASTER,
    RT_VISIO_MASTERS,
    RT_VISIO_PAGE,
    RT_VISIO_PAGES,
    RT_VISIO_WINDOWS,
)
from vsdx.document import EncryptedPackageError, VisioDocument
from vsdx.enum.shapes import VS_CONNECTOR_STYLE, VS_SHAPE_TYPE
from vsdx.hyperlinks import Hyperlink, HyperlinkCollection
from vsdx.ink import InkStroke
from vsdx.geometry import (
    ArcTo,
    EllipticalArcTo,
    Geometries,
    Geometry,
    GeometryRow,
    InfiniteLine,
    LineTo,
    MoveTo,
    NURBSTo,
    PolylineTo,
    RelCubBezTo,
    RelEllipticalArcTo,
    RelLineTo,
    RelMoveTo,
    RelQuadBezTo,
    SplineKnot,
    SplineStart,
    UnknownGeometryRow,
)
from vsdx.layers import Layer, Layers
from vsdx.master import Master, Masters
from vsdx.page import Page, Pages
from vsdx.print_setup import PRINT_ORIENTATION, PrintSetup
from vsdx.shape_data import (
    PROPERTY_TYPE_BOOLEAN,
    PROPERTY_TYPE_CURRENCY,
    PROPERTY_TYPE_DATE,
    PROPERTY_TYPE_DURATION,
    PROPERTY_TYPE_FIXED_LIST,
    PROPERTY_TYPE_NUMBER,
    PROPERTY_TYPE_STRING,
    PROPERTY_TYPE_VARIABLE_LIST,
    ShapeData,
    ShapeDataField,
)
from vsdx.shapes import (
    Connector,
    Ellipse,
    GroupShape,
    Rectangle,
    Shape,
    ShapeTree,
    Triangle,
)
from vsdx.text import Paragraph, Run, TextFrame
from vsdx.theme import ColorScheme, FontScheme, Theme
from vsdx.util import Cm, Emu, Inches, Length, Mm, Pt

__version__ = "0.2.0.dev0"

__all__ = [
    "CT_VSDX_DRAWING_MAIN",
    "CT_VSDX_MACRO_DRAWING_MAIN",
    "CT_VSDX_MACRO_STENCIL_MAIN",
    "CT_VSDX_MACRO_TEMPLATE_MAIN",
    "CT_VSDX_MASTER",
    "CT_VSDX_MASTERS",
    "CT_VSDX_PAGE",
    "CT_VSDX_PAGES",
    "CT_VSDX_STENCIL_MAIN",
    "CT_VSDX_TEMPLATE_MAIN",
    "CT_VSDX_WINDOWS",
    "ArcTo",
    "CONNECTION_TYPE",
    "Cm",
    "ColorScheme",
    "ConnectionPoint",
    "ConnectionPoints",
    "Connector",
    "DataBinding",
    "DataColumn",
    "DataGraphic",
    "DataGraphicItem",
    "DataGraphics",
    "DataRecordset",
    "DataRecordsets",
    "DataRow",
    "Ellipse",
    "EllipticalArcTo",
    "Emu",
    "EncryptedPackageError",
    "FontScheme",
    "Geometries",
    "Geometry",
    "GeometryRow",
    "GroupShape",
    "Hyperlink",
    "HyperlinkCollection",
    "InfiniteLine",
    "Inches",
    "InkStroke",
    "Layer",
    "Layers",
    "Length",
    "LineTo",
    "Master",
    "Masters",
    "Mm",
    "MoveTo",
    "NURBSTo",
    "NS_R",
    "NS_VSDX_CORE",
    "PRINT_ORIENTATION",
    "PROPERTY_TYPE_BOOLEAN",
    "PROPERTY_TYPE_CURRENCY",
    "PROPERTY_TYPE_DATE",
    "PROPERTY_TYPE_DURATION",
    "PROPERTY_TYPE_FIXED_LIST",
    "PROPERTY_TYPE_NUMBER",
    "PROPERTY_TYPE_STRING",
    "PROPERTY_TYPE_VARIABLE_LIST",
    "Page",
    "Pages",
    "Paragraph",
    "PolylineTo",
    "PrintSetup",
    "Pt",
    "RelCubBezTo",
    "RelEllipticalArcTo",
    "RelLineTo",
    "RelMoveTo",
    "RelQuadBezTo",
    "RT_VISIO_DOCUMENT",
    "RT_VISIO_MASTER",
    "RT_VISIO_MASTERS",
    "RT_VISIO_PAGE",
    "RT_VISIO_PAGES",
    "RT_VISIO_WINDOWS",
    "Rectangle",
    "Run",
    "Shape",
    "ShapeData",
    "ShapeDataField",
    "ShapeTree",
    "SplineKnot",
    "SplineStart",
    "Stencil",
    "Template",
    "TextFrame",
    "Theme",
    "Triangle",
    "UnknownGeometryRow",
    "VS_CONNECTOR_STYLE",
    "VS_SHAPE_TYPE",
    "Visio",
    "VisioDocument",
    "VisioPackageOpener",
    "__version__",
]
