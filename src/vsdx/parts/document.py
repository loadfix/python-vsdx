"""Visio document part — root XML part of a ``.vsdx`` package.

Corresponds to ``/visio/document.xml``. Referenced from the package
root via the ``RT_VISIO_DOCUMENT`` relationship. Holds the top-level
``<VisioDocument>`` element plus its ``DocumentSettings``, ``Colors``,
``FaceNames``, ``StyleSheets``, ``DocumentSheet`` children (track 1
oxml classes).

Also carries relationships to the inner parts of the Visio sub-tree:
``pages.xml`` (via ``RT_VISIO_PAGES``), ``masters.xml`` (via
``RT_VISIO_MASTERS``), ``windows.xml`` (via ``RT_VISIO_WINDOWS``), and
the theme part (via the shared ``RT.THEME``).

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ooxml_opc import XmlPart
from ooxml_opc.packuri import PackURI

from vsdx.constants import CT_VSDX_DRAWING_MAIN
from vsdx.oxml import parse_xml
from vsdx.parts._templates import DEFAULT_DOCUMENT_XML

if TYPE_CHECKING:
    from ooxml_opc import OpcPackage


class VisioDocumentPart(XmlPart):
    """The ``/visio/document.xml`` part.

    Content-type ``application/vnd.ms-visio.drawing.main+xml``.
    Partname is fixed at ``/visio/document.xml`` — unlike
    ``.pptx``'s per-slide-part numbering, the Visio document part is
    a singleton.
    """

    @classmethod
    def new(cls, package: OpcPackage) -> VisioDocumentPart:
        """Return a new, empty document part seeded with a bare
        ``<VisioDocument/>`` root.

        Used when constructing a package from scratch. Track 1's
        ``CT_VisioDocument.new_default()`` will replace this default
        blob in a follow-up; for 0.1.0 the oxml layer is expected to
        hydrate children on first write.
        """
        element = parse_xml(DEFAULT_DOCUMENT_XML)
        return cls(
            PackURI("/visio/document.xml"),
            CT_VSDX_DRAWING_MAIN,
            package,
            element,
        )
