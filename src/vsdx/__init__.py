"""Microsoft Visio (`.vsdx`) authoring library for the loadfix OOXML family.

A fourth parent library anchored on top of the existing shared-package
stack (`python-ooxml-opc`, `python-ooxml-xmlchemy`). Unlike docx / pptx /
xlsx, Visio's schema is not ECMA-standardised — the authoritative source
is Microsoft Learn's
``http://schemas.microsoft.com/office/visio/2011/1/core`` namespace.

The 0.1.0 public surface covers the **oxml layer** (track 1 of the
0.1.0 fan-out):

- :mod:`vsdx.constants` — namespace / content-type / relationship-type
  constants.
- :mod:`vsdx.oxml` — hardened parser, namespace registry, and
  ``CT_*`` element-class registration.
- :mod:`vsdx.oxml.cell`, :mod:`vsdx.oxml.row`,
  :mod:`vsdx.oxml.section`, :mod:`vsdx.oxml.shape`,
  :mod:`vsdx.oxml.shapes`, :mod:`vsdx.oxml.page`,
  :mod:`vsdx.oxml.pages`, :mod:`vsdx.oxml.master`,
  :mod:`vsdx.oxml.masters`, :mod:`vsdx.oxml.document`,
  :mod:`vsdx.oxml.connects`, :mod:`vsdx.oxml.window` — per-module
  ``CT_*`` classes for Visio's element vocabulary.

The proxy layer (``vsdx.document``, ``vsdx.page``, ``vsdx.shapes``,
``vsdx.api``), parts layer (``vsdx.parts``), and formula-passthrough
layer (``vsdx.formula``) are populated by other 0.1.0 tracks.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

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

__version__ = "0.1.0.dev0"

__all__ = [
    "CT_VSDX_DRAWING_MAIN",
    "CT_VSDX_MASTER",
    "CT_VSDX_MASTERS",
    "CT_VSDX_PAGE",
    "CT_VSDX_PAGES",
    "CT_VSDX_WINDOWS",
    "NS_R",
    "NS_VSDX_CORE",
    "RT_VISIO_DOCUMENT",
    "RT_VISIO_MASTER",
    "RT_VISIO_MASTERS",
    "RT_VISIO_PAGE",
    "RT_VISIO_PAGES",
    "RT_VISIO_WINDOWS",
    "__version__",
]
