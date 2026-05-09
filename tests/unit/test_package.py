"""Unit tests for `vsdx.package` module — the ``VisioPackage`` class."""

from __future__ import annotations

import io

from ooxml_opc import CONTENT_TYPE as CT
from ooxml_opc import OpcPackage, PartFactory

from vsdx.constants import (
    CT_VSDX_DRAWING_MAIN,
    CT_VSDX_MASTERS,
    CT_VSDX_PAGES,
    CT_VSDX_STENCIL_MAIN,
    CT_VSDX_WINDOWS,
    RT_VISIO_DOCUMENT,
    RT_VISIO_MASTERS,
    RT_VISIO_PAGES,
    RT_VISIO_WINDOWS,
)
from vsdx.package import VISIO_PART_TYPE_MAP, VisioPackage, register_visio_parts
from vsdx.parts.document import VisioDocumentPart
from vsdx.parts.master import MasterPart, MastersPart
from vsdx.parts.page import PagePart, PagesPart
from vsdx.parts.stencil import StencilPart
from vsdx.parts.theme import ThemePart
from vsdx.parts.windows import WindowsPart


class DescribeVisioPackage:
    """Behaviour of :class:`VisioPackage.new` — the default-package factory."""

    def it_is_a_subclass_of_the_shared_opc_package(self) -> None:
        assert issubclass(VisioPackage, OpcPackage)

    def it_seeds_a_visio_document_part_at_the_canonical_partname(self) -> None:
        package = VisioPackage.new()

        doc = package.document_part
        assert isinstance(doc, VisioDocumentPart)
        assert doc.partname == "/visio/document.xml"
        assert doc.content_type == CT_VSDX_DRAWING_MAIN

    def it_relates_the_document_part_from_the_package_root(self) -> None:
        package = VisioPackage.new()

        # -- the ``main_document_part`` alias resolves via RT.OFFICE_DOCUMENT --
        # -- on pptx/docx/xlsx; vsdx uses ``RT_VISIO_DOCUMENT`` instead (see  --
        # -- the scoping doc §2.4). Exercise the Visio-specific rel path.     --
        doc = package.part_related_by(RT_VISIO_DOCUMENT)
        assert isinstance(doc, VisioDocumentPart)

    def it_seeds_empty_pages_masters_and_windows_parts(self) -> None:
        package = VisioPackage.new()

        pages = package.pages_part
        masters = package.masters_part
        windows = package.windows_part

        assert isinstance(pages, PagesPart)
        assert pages.content_type == CT_VSDX_PAGES
        assert isinstance(masters, MastersPart)
        assert masters.content_type == CT_VSDX_MASTERS
        assert isinstance(windows, WindowsPart)
        assert windows.content_type == CT_VSDX_WINDOWS

    def it_wires_the_three_inner_rels_off_the_document_part(self) -> None:
        package = VisioPackage.new()
        doc = package.document_part

        assert doc.part_related_by(RT_VISIO_PAGES) is package.pages_part
        assert doc.part_related_by(RT_VISIO_MASTERS) is package.masters_part
        assert doc.part_related_by(RT_VISIO_WINDOWS) is package.windows_part

    def it_does_not_seed_a_theme_part_at_new(self) -> None:
        # -- theme is the track 4 templates layer's responsibility; keeping --
        # -- the parts factory independent of the template bundle.         --
        package = VisioPackage.new()

        partnames = {p.partname for p in package.iter_parts()}
        theme_partnames = {p for p in partnames if "/visio/theme/" in p}
        assert not theme_partnames

    def it_exposes_empty_page_and_master_iterators_before_content_is_added(
        self,
    ) -> None:
        package = VisioPackage.new()

        assert package.iter_page_parts() == []
        assert package.iter_master_parts() == []

    def it_yields_each_added_page_via_iter_page_parts(self) -> None:
        package = VisioPackage.new()

        page1 = PagePart.new(package)
        package.pages_part.relate_to(page1, "http://example/page")
        page2 = PagePart.new(package)
        package.pages_part.relate_to(page2, "http://example/page")

        assert package.iter_page_parts() == [page1, page2]

    def it_yields_each_added_master_via_iter_master_parts(self) -> None:
        package = VisioPackage.new()

        master = MasterPart.new(package)
        package.masters_part.relate_to(master, "http://example/master")

        assert package.iter_master_parts() == [master]

    def it_round_trips_a_default_package_through_save_and_reopen(
        self,
    ) -> None:
        # -- full end-to-end: build in memory, serialise to bytes via the --
        # -- shared zip writer, reopen via ``ooxml_opc`` and confirm the  --
        # -- part graph survived. Locks in zip-writer + content-types     --
        # -- compatibility with the shared stack.                         --
        package = VisioPackage.new()

        buf = io.BytesIO()
        package.save(buf)

        buf.seek(0)
        reloaded = VisioPackage.open(buf)

        assert isinstance(reloaded.document_part, VisioDocumentPart)
        assert isinstance(reloaded.pages_part, PagesPart)
        assert isinstance(reloaded.masters_part, MastersPart)
        assert isinstance(reloaded.windows_part, WindowsPart)


class DescribeVisioPartTypeRegistration:
    """Behaviour of :func:`register_visio_parts` and the shared registry."""

    def it_registers_the_drawing_main_content_type(self) -> None:
        # -- import-time side effect: ``import vsdx.package`` should have  --
        # -- already registered the Visio content-types with the shared    --
        # -- ``PartFactory``.                                               --
        assert (
            PartFactory.part_type_for.get(CT_VSDX_DRAWING_MAIN)
            is VisioDocumentPart
        )

    def it_registers_the_stencil_main_content_type(self) -> None:
        assert (
            PartFactory.part_type_for.get(CT_VSDX_STENCIL_MAIN) is StencilPart
        )

    def it_registers_the_theme_content_type(self) -> None:
        # -- shared OFC_THEME — vsdx reuses the standard DrawingML theme --
        # -- content-type rather than minting a Visio-specific one.      --
        assert PartFactory.part_type_for.get(CT.OFC_THEME) is ThemePart

    def it_is_idempotent(self) -> None:
        # -- calling ``register_visio_parts`` twice must not fail and must --
        # -- not clobber existing registrations.                           --
        before = dict(PartFactory.part_type_for)
        register_visio_parts()

        assert PartFactory.part_type_for == before

    def it_covers_every_visio_content_type_in_the_scoping_doc(self) -> None:
        # -- guard against silent drift in VISIO_PART_TYPE_MAP by spot- --
        # -- checking every key is a recognised family. 0.2.0 added the --
        # -- vbaProject binary for macro-enabled variants (.vsdm /      --
        # -- .vssm / .vstm), which lives under ``vnd.ms-office.``.      --
        for ct in VISIO_PART_TYPE_MAP:
            assert (
                ct.startswith("application/vnd.ms-visio.")
                or ct == CT.OFC_THEME
                or ct == "application/vnd.ms-office.vbaProject"
            ), f"unexpected CT in map: {ct}"
