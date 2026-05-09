"""Visio stencil part — root part for a `.vssx` stencil package.

A `.vssx` stencil is structurally identical to a `.vsdx` drawing
except the *root* content-type is ``application/vnd.ms-visio.stencil.main+xml``
and the package typically carries no ``<Pages>`` — only the masters
catalogue. Everything downstream of the stencil root (masters.xml,
master%d.xml, theme, windows) uses the same part classes as
:mod:`vsdx.parts.page` / :mod:`vsdx.parts.master` / etc.

In 0.1.0 stencils are **read-only** — :class:`StencilPart` participates
in round-trip load/save so a user can load a `.vssx` oracle and extract
its masters, but creating a stencil from scratch is deferred to 0.2.0
(scoping doc §7.2).

Relationship: the package root relates to a :class:`StencilPart` via
``RT_VISIO_DOCUMENT`` (same rel-type as a drawing's root — Visio
discriminates by content-type, not by rel-type).

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ooxml_opc.packuri import PackURI

from vsdx.constants import CT_VSDX_STENCIL_MAIN
from vsdx.oxml import parse_xml
from vsdx.parts._templates import DEFAULT_DOCUMENT_XML
from vsdx.parts._verbatim import VerbatimXmlPart

if TYPE_CHECKING:
    from ooxml_opc import OpcPackage


class StencilPart(VerbatimXmlPart):
    """The ``/visio/document.xml`` part of a `.vssx` stencil package.

    Content-type ``application/vnd.ms-visio.stencil.main+xml``.
    Partname is the same ``/visio/document.xml`` a drawing uses —
    Visio's stencil / drawing / template trio discriminate purely by
    the content-type override on that single partname.
    """

    @classmethod
    def new(cls, package: OpcPackage) -> StencilPart:
        """Return a new, empty stencil root part.

        Seeded with the same ``<VisioDocument/>`` root as a drawing
        so both formats share the track 1 ``CT_VisioDocument``
        element-class heritage; the only distinguishing feature at
        the OPC layer is the content-type override.
        """
        element = parse_xml(DEFAULT_DOCUMENT_XML)
        return cls(
            PackURI("/visio/document.xml"),
            CT_VSDX_STENCIL_MAIN,
            package,
            element,
        )
