"""Unit tests for `vsdx.parts.document` module."""

from __future__ import annotations

from lxml import etree
from ooxml_opc import RELATIONSHIP_TYPE as RT
from ooxml_opc import OpcPackage

from vsdx.constants import CT_VSDX_DRAWING_MAIN, NS_VSDX_CORE
from vsdx.parts.document import VisioDocumentPart
from vsdx.parts.theme import ThemePart

_STUB_THEME = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    b'<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/>'
)


class DescribeVisioDocumentPart:
    def it_can_construct_a_default_document_part(self) -> None:
        doc = VisioDocumentPart.new(None)  # type: ignore[arg-type]

        assert isinstance(doc, VisioDocumentPart)
        assert doc.content_type == CT_VSDX_DRAWING_MAIN
        assert doc.partname == "/visio/document.xml"

    def it_roots_the_document_in_the_visio_core_namespace(self) -> None:
        doc = VisioDocumentPart.new(None)  # type: ignore[arg-type]

        root = doc.element
        # -- lxml reports the qualified name in Clark form on the root's tag --
        assert root.tag == f"{{{NS_VSDX_CORE}}}VisioDocument"

    def it_re_serialises_the_default_part_without_loss(self) -> None:
        doc = VisioDocumentPart.new(None)  # type: ignore[arg-type]

        # -- blob goes through lxml's serialiser; re-parsing must round-trip --
        reloaded = etree.fromstring(doc.blob)
        assert reloaded.tag == f"{{{NS_VSDX_CORE}}}VisioDocument"


class DescribeVisioDocumentPartThemeAccess:
    def it_returns_none_when_no_theme_rel_is_present(self) -> None:
        package = OpcPackage()
        doc = VisioDocumentPart.new(package)

        assert doc.theme_part is None

    def it_returns_the_theme_part_when_related(self) -> None:
        package = OpcPackage()
        doc = VisioDocumentPart.new(package)
        theme = ThemePart.new(package, _STUB_THEME)
        doc.relate_to(theme, RT.THEME)

        resolved = doc.theme_part

        assert resolved is theme
