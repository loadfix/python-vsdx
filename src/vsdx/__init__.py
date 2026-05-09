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

from vsdx.api import Visio
from vsdx.constants import (
    CT_VSDX_DRAWING_MAIN,
    CT_VSDX_MASTER,
    CT_VSDX_MASTERS,
    CT_VSDX_PAGE,
    CT_VSDX_PAGES,
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
from vsdx.document import VisioDocument
from vsdx.enum.shapes import VS_CONNECTOR_STYLE, VS_SHAPE_TYPE
from vsdx.master import Master, Masters
from vsdx.page import Page, Pages
from vsdx.shapes import Connector, Ellipse, Rectangle, Shape, ShapeTree, Triangle
from vsdx.text import Paragraph, Run, TextFrame
from vsdx.util import Cm, Emu, Inches, Length, Mm, Pt

__version__ = "0.1.0.dev0"

__all__ = [
    "CT_VSDX_DRAWING_MAIN",
    "CT_VSDX_MASTER",
    "CT_VSDX_MASTERS",
    "CT_VSDX_PAGE",
    "CT_VSDX_PAGES",
    "CT_VSDX_WINDOWS",
    "Cm",
    "Connector",
    "Ellipse",
    "Emu",
    "Inches",
    "Length",
    "Master",
    "Masters",
    "Mm",
    "NS_R",
    "NS_VSDX_CORE",
    "Page",
    "Pages",
    "Paragraph",
    "Pt",
    "RT_VISIO_DOCUMENT",
    "RT_VISIO_MASTER",
    "RT_VISIO_MASTERS",
    "RT_VISIO_PAGE",
    "RT_VISIO_PAGES",
    "RT_VISIO_WINDOWS",
    "Rectangle",
    "Run",
    "Shape",
    "ShapeTree",
    "TextFrame",
    "Triangle",
    "VS_CONNECTOR_STYLE",
    "VS_SHAPE_TYPE",
    "Visio",
    "VisioDocument",
    "__version__",
]
