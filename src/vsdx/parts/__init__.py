"""Package-part classes for the `python-vsdx` OPC layer.

Each module exports an ``XmlPart`` (or ``Part``) subclass that binds a
Visio-specific content-type to a well-known partname pattern inside a
`.vsdx` package. The parts layer sits between:

- ``ooxml_opc`` below (generic OPC runtime, zip writer, rel graph);
- ``vsdx.oxml`` beside it (``CT_*`` element classes, track 1);
- ``vsdx.package.VisioPackage`` above (``OpcPackage`` subclass that
  assembles the whole ``.vsdx``).

The Visio OPC layout is (per scoping doc §2.2, cross-verified against
dave-howard/vsdx and MS Learn):

.. code-block:: text

    /[Content_Types].xml                    [OPC]
    /_rels/.rels                            [OPC]
    /docProps/{core,app,custom}.xml         [ooxml-docprops]
    /visio/document.xml                     VisioDocumentPart
    /visio/_rels/document.xml.rels
    /visio/windows.xml                      WindowsPart
    /visio/theme/theme%d.xml                ThemePart
    /visio/pages/pages.xml                  PagesPart
    /visio/pages/page%d.xml                 PagePart
    /visio/masters/masters.xml              MastersPart
    /visio/masters/master%d.xml             MasterPart

Stencil (``.vssx``) packages reuse the same masters machinery but swap
``VisioDocumentPart`` for :class:`StencilPart` at the root.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from vsdx.parts.document import VisioDocumentPart
from vsdx.parts.master import MasterPart, MastersPart
from vsdx.parts.page import PagePart, PagesPart
from vsdx.parts.stencil import StencilPart
from vsdx.parts.theme import ThemePart
from vsdx.parts.windows import WindowsPart

__all__ = [
    "MasterPart",
    "MastersPart",
    "PagePart",
    "PagesPart",
    "StencilPart",
    "ThemePart",
    "VisioDocumentPart",
    "WindowsPart",
]
