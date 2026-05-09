"""Unit tests for `vsdx.parts.stencil` module."""

from __future__ import annotations

from vsdx.constants import CT_VSDX_STENCIL_MAIN, NS_VSDX_CORE
from vsdx.parts.stencil import StencilPart


class DescribeStencilPart:
    def it_can_construct_a_default_stencil_root_part(self) -> None:
        stencil = StencilPart.new(None)  # type: ignore[arg-type]

        assert isinstance(stencil, StencilPart)
        # -- stencil uses the `.vssx` content-type, NOT the drawing main  --
        # -- content-type — Visio discriminates stencil/drawing/template  --
        # -- purely by content-type over the shared `/visio/document.xml` --
        # -- partname. Track 2 registers ``VisioDocumentPart`` as the     --
        # -- part-class for drawing+template and ``StencilPart`` for the  --
        # -- stencil content-type (see VISIO_PART_TYPE_MAP).              --
        assert stencil.content_type == CT_VSDX_STENCIL_MAIN
        assert stencil.partname == "/visio/document.xml"
        assert stencil.element.tag == f"{{{NS_VSDX_CORE}}}VisioDocument"
