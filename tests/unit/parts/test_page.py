"""Unit tests for `vsdx.parts.page` module."""

from __future__ import annotations

from ooxml_opc import OpcPackage

from vsdx.constants import CT_VSDX_PAGE, CT_VSDX_PAGES, NS_VSDX_CORE
from vsdx.parts.page import PagePart, PagesPart


class DescribePagesPart:
    def it_can_construct_a_default_pages_index_part(self) -> None:
        pages = PagesPart.new(None)  # type: ignore[arg-type]

        assert isinstance(pages, PagesPart)
        assert pages.content_type == CT_VSDX_PAGES
        assert pages.partname == "/visio/pages/pages.xml"

    def it_roots_the_index_in_the_visio_core_namespace(self) -> None:
        pages = PagesPart.new(None)  # type: ignore[arg-type]

        assert pages.element.tag == f"{{{NS_VSDX_CORE}}}Pages"


class DescribePagePart:
    def it_can_construct_a_default_page_part(self) -> None:
        package = OpcPackage()

        page = PagePart.new(package)

        assert isinstance(page, PagePart)
        assert page.content_type == CT_VSDX_PAGE
        assert page.partname == "/visio/pages/page1.xml"
        assert page.element.tag == f"{{{NS_VSDX_CORE}}}PageContents"

    def it_mints_sequential_partnames_within_a_package(self) -> None:
        package = OpcPackage()

        first = PagePart.new(package)
        # -- before `new()` can see an existing page part we must relate it --
        # -- off the package root; otherwise `next_partname` has nothing to --
        # -- count against. Mirrors the real package-save walk.             --
        package.relate_to(first, "pageRel")
        second = PagePart.new(package)

        assert first.partname == "/visio/pages/page1.xml"
        assert second.partname == "/visio/pages/page2.xml"
